"""Unit tests for signa/api.py (auth gating, change_project enforcement,
run-binding, permission re-check, celery error handling).

The WebODM / DRF / Django surface is faked (see conftest_webodm_fakes.py) so the
view branching is exercised in CI without a live WebODM. detect_gcps is never
actually run here (run_function_async is faked); these tests are about the API
security/error logic, not detection.
"""

import importlib
import importlib.util
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SIGNA_DIR = os.path.abspath(os.path.join(HERE, "..", "signa"))

# Load the fakes helper by path and install the fake modules BEFORE importing
# signa.api (which imports them at module load).
_spec = importlib.util.spec_from_file_location(
    "webodm_fakes", os.path.join(HERE, "conftest_webodm_fakes.py"))
fakes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fakes)
REG = fakes.install()

# Register an EMPTY `signa` package so importing signa.api does NOT execute
# the real __init__ (which pulls in plugin.py -> app.plugins). Submodules
# (api/params/gcp_detect) are found via __path__ and run for real.
_pkg = types.ModuleType("signa")
_pkg.__path__ = [SIGNA_DIR]
sys.modules["signa"] = _pkg

api = importlib.import_module("signa.api")

FakeUser = fakes.FakeUser
FakeTask = fakes.FakeTask
FakeFile = fakes.FakeFile
FakeRequest = fakes.FakeRequest
FakeNotFound = fakes.FakeNotFound


@pytest.fixture(autouse=True)
def _reset():
    REG.reset()
    yield


def _task(pk="t1", images=("a.JPG", "b.JPG")):
    t = FakeTask(pk, images=images)
    REG.tasks[pk] = t
    return t


def _coords_file(text="0 1 2 3\n"):
    return FakeFile(text.encode("utf-8"))


# ----------------------------- detect -----------------------------

def detect(request, pk="t1"):
    return api.TaskSignaDetect().post(request, pk=pk)


def test_detect_happy_path_starts_run_and_binds():
    _task()
    user = FakeUser(perms=("change_project",))
    req = FakeRequest(user, data={"epsg": "28191"},
                      files={"coords": _coords_file()})
    resp = detect(req)
    assert resp.data["celery_task_id"] == "celery-xyz"
    # change_project was enforced
    assert ("change_project",) in REG.perm_calls
    # run bound to this user + task
    store = REG.store[("signa", user.id)]
    assert store["run:celery-xyz"] == "t1"
    assert store["last:t1"] == "celery-xyz"


def test_detect_denied_without_change_project():
    _task()
    user = FakeUser(perms=())  # no change_project
    req = FakeRequest(user, data={"epsg": "28191"},
                      files={"coords": _coords_file()})
    with pytest.raises(FakeNotFound):
        detect(req)


def test_detect_requires_coords_file():
    _task()
    req = FakeRequest(FakeUser(), data={"epsg": "28191"}, files={})
    resp = detect(req)
    assert "No GCP coordinate file" in str(resp.data["error"])


def test_detect_rejects_oversized_coords():
    _task()
    big = FakeFile(b"x", size=6 * 1024 * 1024)
    req = FakeRequest(FakeUser(), data={"epsg": "28191"}, files={"coords": big})
    resp = detect(req)
    assert "too large" in str(resp.data["error"])


def test_detect_validates_params():
    _task()
    req = FakeRequest(FakeUser(), data={"epsg": "5"},  # out of range
                      files={"coords": _coords_file()})
    resp = detect(req)
    assert "EPSG" in str(resp.data["error"])


def test_detect_rejects_task_without_images():
    _task(images=())
    req = FakeRequest(FakeUser(), data={"epsg": "28191"},
                      files={"coords": _coords_file()})
    resp = detect(req)
    assert "no images" in str(resp.data["error"]).lower()


def test_detect_prunes_previous_run_for_same_task():
    _task()
    user = FakeUser()
    # seed a previous run for this (user, task)
    REG.store[("signa", user.id)] = {"run:old": "t1", "last:t1": "old"}
    req = FakeRequest(user, data={"epsg": "28191"},
                      files={"coords": _coords_file()})
    detect(req)
    store = REG.store[("signa", user.id)]
    assert "run:old" not in store           # previous run pruned
    assert store["last:t1"] == "celery-xyz"


# ----------------------------- check -----------------------------

def check(request, pk="t1", cid="celery-xyz"):
    return api.TaskSignaCheck().get(request, pk=pk, celery_task_id=cid)


def _own(user, pk="t1", cid="celery-xyz"):
    REG.store.setdefault(("signa", user.id), {})["run:" + cid] = pk


def test_check_result_not_found_when_task_missing():
    user = FakeUser()
    resp = check(FakeRequest(user))  # no task registered
    assert resp.data == {"ready": True, "error": "Result not found."}


def test_check_denied_when_permission_revoked():
    _task()
    user = FakeUser(perms=())  # change_project revoked since start
    _own(user)
    resp = check(FakeRequest(user))
    assert resp.data["error"] == "Result not found."


def test_check_denied_when_not_owner():
    _task()
    user = FakeUser()           # has perm, but no run binding recorded
    resp = check(FakeRequest(user))
    assert resp.data["error"] == "Result not found."


def test_check_not_ready_passthrough():
    _task()
    user = FakeUser()
    _own(user)
    REG.results["celery-xyz"] = {"ready": False, "state": "PROGRESS",
                                 "info": {"status": "working", "progress": 42}}
    resp = check(FakeRequest(user))
    assert resp.data["ready"] is False
    assert resp.data["progress"] == 42


def test_check_worker_exception_becomes_terminal_error_and_cleans_up():
    _task()
    user = FakeUser()
    _own(user)
    REG.results["celery-xyz"] = {"ready": True,
                                 "exc": RuntimeError("No module named 'cv2'")}
    resp = check(FakeRequest(user))
    assert resp.data["ready"] is True
    assert "Detection failed in the worker" in str(resp.data["error"])
    assert "cv2" in str(resp.data["error"])
    # ownership record released on failure
    assert "run:celery-xyz" not in REG.store[("signa", user.id)]


def test_check_clean_error_result():
    _task()
    user = FakeUser()
    _own(user)
    REG.results["celery-xyz"] = {"ready": True, "value": {"error": "No detected markers match."}}
    resp = check(FakeRequest(user))
    assert resp.data == {"ready": True, "error": "No detected markers match."}


def test_check_success_returns_summary_and_keeps_record():
    _task()
    user = FakeUser()
    _own(user)
    summary = {"detections": 12, "unique_markers": 5, "gcp_list": "EPSG:28191\n"}
    REG.results["celery-xyz"] = {"ready": True, "value": {"output": summary}}
    resp = check(FakeRequest(user))
    assert resp.data["ready"] is True
    assert resp.data["summary"] == summary
    # successful result is kept (re-fetchable), not deleted
    assert REG.store[("signa", user.id)]["run:celery-xyz"] == "t1"
