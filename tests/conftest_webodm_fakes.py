"""Minimal fakes for the WebODM / DRF / Django surface that findgcp/api.py imports.

Lets the API view logic (auth gating, change_project enforcement, run-binding,
permission re-check, celery error handling) be unit-tested in CI without a
running WebODM — the same technique used to mock cv2 for detect_gcps.

`install()` registers the fakes in sys.modules and returns a `Registry` used to
configure per-test state (tasks, celery results, the datastore). It must be
called before importing findgcp.api.
"""

import sys
import types


class FakeNotFound(Exception):
    """Stands in for rest_framework.exceptions.NotFound / Django 404."""


class Registry:
    def __init__(self):
        self.tasks = {}          # pk(str) -> FakeTask
        self.results = {}        # celery_id -> dict(ready, state, info, value|exc)
        self.store = {}          # (namespace, user_id) -> {key: value}
        self.perm_calls = []     # recorded (perms tuple) passed to check_project_perms

    def reset(self):
        self.tasks.clear()
        self.results.clear()
        self.store.clear()
        self.perm_calls.clear()


REG = Registry()


class FakeProject:
    def __init__(self, pid=1):
        self.id = pid


class FakeTask:
    def __init__(self, pk, project=None, images=("a.JPG", "b.JPG"), name=None):
        self.id = pk
        self.project = project or FakeProject()
        self.name = name or "task-{}".format(pk)
        self._images = list(images)

    def scan_images(self):
        return list(self._images)

    def get_image_path(self, filename):
        return "/imgs/{}".format(filename)


class FakeUser:
    def __init__(self, uid=1, perms=("change_project",)):
        self.id = uid
        self.perms = set(perms)

    def has_perm(self, perm, obj=None):
        return perm in self.perms


class FakeFile:
    def __init__(self, content=b"", size=None):
        self._c = content
        self.size = len(content) if size is None else size

    def read(self):
        return self._c


class FakeRequest:
    def __init__(self, user, data=None, files=None):
        self.user = user
        self.data = data or {}
        self.FILES = files or {}


def _module(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def install():
    REG.reset()

    # rest_framework
    status = types.SimpleNamespace(HTTP_200_OK=200)
    permissions = types.SimpleNamespace(IsAuthenticated=object(), AllowAny=object())
    _module("rest_framework", status=status, permissions=permissions)

    class APIView:
        pass

    _module("rest_framework.views", APIView=APIView)

    class Response:
        def __init__(self, data, status=None):
            self.data = data
            self.status_code = status

    _module("rest_framework.response", Response=Response)

    # django
    _module("django")
    _module("django.core")
    _module("django.core.exceptions",
            ValidationError=type("ValidationError", (Exception,), {}),
            ObjectDoesNotExist=type("ObjectDoesNotExist", (Exception,), {}))
    _module("django.utils")
    _module("django.utils.translation", gettext_lazy=lambda s: s)

    ObjectDoesNotExist = sys.modules["django.core.exceptions"].ObjectDoesNotExist

    # app.models.Task with a chainable .objects.only().get(pk=)
    class _Query:
        def only(self, *a, **k):
            return self

        def get(self, pk=None):
            t = REG.tasks.get(str(pk))
            if t is None:
                raise ObjectDoesNotExist()
            return t

    class Task:
        objects = _Query()

    _module("app")
    _module("app.models", Task=Task)

    # app.plugins.UserDataStore (per (namespace, user))
    class UserDataStore:
        def __init__(self, namespace, user):
            self._k = (namespace, getattr(user, "id", user))
            REG.store.setdefault(self._k, {})

        def get_string(self, key, default=""):
            return REG.store[self._k].get(key, default)

        def set_string(self, key, value):
            REG.store[self._k][key] = value

        def has_key(self, key):
            return key in REG.store[self._k]

        def del_key(self, key):
            return REG.store[self._k].pop(key, None) is not None

    _module("app.plugins", UserDataStore=UserDataStore)

    class TaskView:
        # Tests set the task to return; mirrors get_and_check_task's contract.
        def get_and_check_task(self, request, pk):
            return REG.tasks[str(pk)]

    _module("app.plugins.views", TaskView=TaskView)

    def run_function_async(func, *args, **kwargs):
        return types.SimpleNamespace(task_id="celery-xyz")

    _module("app.plugins.worker", run_function_async=run_function_async)

    def check_project_perms(request, project, perms=("view_project",)):
        REG.perm_calls.append(tuple(perms))
        for perm in perms:
            if not request.user.has_perm(perm, project):
                raise FakeNotFound()

    _module("app.api")
    _module("app.api.common", check_project_perms=check_project_perms)

    class TestSafeAsyncResult:
        def __init__(self, cid):
            self._r = REG.results.get(cid, {})

        @property
        def state(self):
            return self._r.get("state", "PENDING")

        @property
        def info(self):
            return self._r.get("info")

        def ready(self):
            return self._r.get("ready", False)

        def get(self, propagate=True):
            if "exc" in self._r:
                if propagate:
                    raise self._r["exc"]
                return self._r["exc"]
            return self._r.get("value")

    _module("worker")
    _module("worker.tasks", TestSafeAsyncResult=TestSafeAsyncResult)

    return REG
