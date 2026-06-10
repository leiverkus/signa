from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _

from app.plugins.views import TaskView, GetTaskResult
from app.plugins.worker import run_function_async
from worker.tasks import TestSafeAsyncResult

from .gcp_detect import detect_gcps


class FindGCPException(Exception):
    pass


class TaskFindGCPDetect(TaskView):
    """Kick off ArUco GCP detection for a task's images in a background worker."""

    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)

        coords_file = request.FILES.get('coords')
        if coords_file is None:
            return Response({'error': _('No GCP coordinate file uploaded.')},
                            status=status.HTTP_200_OK)
        try:
            coords_text = coords_file.read().decode('utf-8', errors='replace')
        except Exception:
            return Response({'error': _('Cannot read the coordinate file.')},
                            status=status.HTTP_200_OK)

        try:
            epsg = int(request.data.get('epsg'))
        except (TypeError, ValueError):
            return Response({'error': _('A valid EPSG code is required.')},
                            status=status.HTTP_200_OK)

        try:
            dict_id = int(request.data.get('dict', 1))
            minrate = float(request.data.get('minrate', 0.01))
            ignore = float(request.data.get('ignore', 0.33))
        except (TypeError, ValueError):
            return Response({'error': _('Invalid detection parameters.')},
                            status=status.HTTP_200_OK)

        adjust = str(request.data.get('adjust', 'true')).lower() in ('1', 'true', 'on', 'yes')

        # Resolve the task's input images on disk
        image_paths = [task.get_image_path(i) for i in task.scan_images()]
        if not image_paths:
            return Response({'error': _('This task has no images.')},
                            status=status.HTTP_200_OK)

        celery_task_id = run_function_async(
            detect_gcps, image_paths, coords_text, epsg,
            dict_id, minrate, ignore, adjust, task.name).task_id

        return Response({'celery_task_id': celery_task_id}, status=status.HTTP_200_OK)


class TaskFindGCPCheck(APIView):
    """Poll detection status; on completion returns the run summary."""
    permission_classes = (permissions.AllowAny,)

    def get(self, request, celery_task_id=None, **kwargs):
        res = TestSafeAsyncResult(celery_task_id)
        if not res.ready():
            out = {'ready': False}
            if res.state == 'PROGRESS' and res.info is not None:
                for k in res.info:
                    out[k] = res.info[k]
            return Response(out, status=status.HTTP_200_OK)

        result = res.get()
        if result.get('error') is not None:
            return Response({'ready': True, 'error': result['error']})

        return Response({'ready': True, 'summary': result.get('output')})


class TaskFindGCPDownload(GetTaskResult):
    """Stream the generated gcp_list.txt (inherits GetTaskResult file handling)."""
    pass
