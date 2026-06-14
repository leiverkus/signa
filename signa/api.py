from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _

from app.models import Task
from app.plugins import UserDataStore
from app.plugins.views import TaskView
from app.plugins.worker import run_function_async
from app.api.common import check_project_perms
from worker.tasks import TestSafeAsyncResult

from .gcp_detect import detect_gcps
from .params import validate_params

# Datastore namespace. Must equal the plugin directory name (what
# PluginBase.get_name() / get_user_data_store() use), so detect (write) and
# check (read) address the same per-user store.
PLUGIN_NAMESPACE = "signa"


def _run_key(celery_task_id):
    return "run:{}".format(celery_task_id)


def _last_key(task_id):
    return "last:{}".format(task_id)


# Per-user detection defaults (settable on the Signa Settings page). Stored in
# the same per-user datastore as the run bindings (distinct "default_*" keys).
DEFAULTS = {'epsg': 28191, 'dict': 1, 'minrate': 0.01, 'ignore': 0.33, 'adjust': True}


def read_user_defaults(store):
    return {
        'epsg': store.get_int('default_epsg', DEFAULTS['epsg']),
        'dict': store.get_int('default_dict', DEFAULTS['dict']),
        'minrate': store.get_float('default_minrate', DEFAULTS['minrate']),
        'ignore': store.get_float('default_ignore', DEFAULTS['ignore']),
        'adjust': store.get_bool('default_adjust', DEFAULTS['adjust']),
    }


class TaskFindGCPDetect(TaskView):
    """Start ArUco GCP detection for a task's images in a background worker.

    Tightened beyond WebODM's default TaskNestedView (AllowAny + public-task
    bypass): authentication is required and change_project permission is
    enforced even for public tasks, since detection is an expensive operation.
    """
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        # Enforce object-level permission even when the task/project is public.
        check_project_perms(request, task.project, ('change_project',))

        coords_file = request.FILES.get('coords')
        if coords_file is None:
            return Response({'error': _('No GCP coordinate file uploaded.')},
                            status=status.HTTP_200_OK)
        if coords_file.size > 5 * 1024 * 1024:
            return Response({'error': _('Coordinate file too large (max 5 MB).')},
                            status=status.HTTP_200_OK)
        try:
            coords_text = coords_file.read().decode('utf-8', errors='replace')
        except Exception:
            return Response({'error': _('Cannot read the coordinate file.')},
                            status=status.HTTP_200_OK)

        params, error = validate_params(request.data)
        if error is not None:
            # params.py is Django-free and returns plain English strings; the
            # runtime gettext lookup translates them (msgids are in our .po).
            return Response({'error': _(error)}, status=status.HTTP_200_OK)

        image_paths = [task.get_image_path(i) for i in task.scan_images()]
        if not image_paths:
            return Response({'error': _('This task has no images.')},
                            status=status.HTTP_200_OK)

        celery_task_id = run_function_async(
            detect_gcps, image_paths, coords_text, params['epsg'],
            params['dict_id'], params['minrate'], params['ignore'],
            params['adjust'], task.name).task_id

        # Bind this run to the requesting user (per-user datastore) and to the
        # task. Keep one ownership record per (user, task): drop the previous
        # run's record so entries don't accumulate, but DO NOT delete on read,
        # so a completed result stays retrievable (until the celery result
        # itself expires) instead of being one-shot.
        store = UserDataStore(PLUGIN_NAMESPACE, request.user)
        prev = store.get_string(_last_key(task.id), "")
        if prev:
            store.del_key(_run_key(prev))
        store.set_string(_run_key(celery_task_id), str(task.id))
        store.set_string(_last_key(task.id), celery_task_id)

        return Response({'celery_task_id': celery_task_id}, status=status.HTTP_200_OK)


class TaskFindGCPCheck(APIView):
    """Poll detection status; on completion returns the summary and gcp_list text.

    Results are bound to the user who started the run (via the plugin's per-user
    datastore) and to the task: the run's celery id must be recorded in the
    requesting user's store with a matching task pk. Worker exceptions are turned
    into a terminal error response (not an HTTP 500) and clean up the ownership
    record. Successful results are left in place so they can be re-fetched.
    """
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk=None, celery_task_id=None, **kwargs):
        # Re-check the CURRENT project permission, not just the original run
        # binding: if the user's change_project access was revoked after starting
        # the run, deny now. All denials return a terminal error (HTTP 200) so the
        # client stops polling instead of looping on a 404.
        try:
            task = Task.objects.only('id', 'project').get(pk=pk)
        except (ObjectDoesNotExist, ValidationError, ValueError):
            return Response({'ready': True, 'error': _('Result not found.')},
                            status=status.HTTP_200_OK)
        if not request.user.has_perm('change_project', task.project):
            return Response({'ready': True, 'error': _('Result not found.')},
                            status=status.HTTP_200_OK)

        store = UserDataStore(PLUGIN_NAMESPACE, request.user)
        key = _run_key(celery_task_id)
        owned_task = store.get_string(key, "")
        if not owned_task or owned_task != str(pk):
            # Not started by this user (or not for this task).
            return Response({'ready': True, 'error': _('Result not found.')},
                            status=status.HTTP_200_OK)

        res = TestSafeAsyncResult(celery_task_id)
        if not res.ready():
            out = {'ready': False}
            if res.state == 'PROGRESS' and res.info is not None:
                for k in res.info:
                    out[k] = res.info[k]
            return Response(out, status=status.HTTP_200_OK)

        # Terminal. get(propagate=False) returns the worker's return value on
        # success, or the raised exception instance on failure — never re-raises.
        try:
            result = res.get(propagate=False)
        except Exception as e:  # backend/deserialization failure
            store.del_key(key)
            return Response({'ready': True,
                             'error': _('Detection failed in the worker: %(err)s')
                             % {'err': str(e)[:300]}})

        if not isinstance(result, dict):
            # The worker function raised (e.g. cv2 missing, OOM, OpenCV error).
            store.del_key(key)
            return Response({'ready': True,
                             'error': _('Detection failed in the worker: %(err)s')
                             % {'err': str(result)[:300]}})

        if result.get('error') is not None:
            return Response({'ready': True, 'error': result['error']})

        return Response({'ready': True, 'summary': result.get('output')})


class FindGCPSettings(APIView):
    """Return the requesting user's saved detection defaults (used by the
    dashboard dialog to pre-fill its fields)."""
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, **kwargs):
        store = UserDataStore(PLUGIN_NAMESPACE, request.user)
        return Response(read_user_defaults(store))
