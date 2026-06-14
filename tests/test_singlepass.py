"""Unit tests for scripts/signa-singlepass.py.

The pure helpers (multipart encoder, image globbing) are tested directly. The
networked workflow is exercised through ``process_task`` with a fake WebODM
client — covering the cleanup contract (orphan removal, the commit-in-flight
race, --keep-on-error, --dry-run) without a live server. The full live round
trip is still covered by docs/manual-test.md.
"""

import importlib.util
import os
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "signa-singlepass.py")


def _load():
    spec = importlib.util.spec_from_file_location("singlepass", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sp = _load()


def test_encode_multipart_fields_and_file():
    ctype, body = sp._encode_multipart(
        {"epsg": "28191", "adjust": "true"},
        [("coords", "gcp_coords.txt", b"0 1 2 3\n")])
    assert ctype.startswith("multipart/form-data; boundary=")
    boundary = ctype.split("boundary=", 1)[1]
    assert isinstance(body, bytes)
    text = body.decode("utf-8")
    # boundary present and closed
    assert text.count("--" + boundary) >= 3            # 2 parts + closing
    assert text.rstrip().endswith("--" + boundary + "--")
    # field + file headers
    assert 'name="epsg"' in text and "28191" in text
    assert 'name="coords"; filename="gcp_coords.txt"' in text
    assert "Content-Type: text/plain" in text
    assert "0 1 2 3" in text


def test_encode_multipart_empty():
    ctype, body = sp._encode_multipart({}, [])
    boundary = ctype.split("boundary=", 1)[1]
    assert body.decode("utf-8").strip() == "--{}--".format(boundary)


def test_find_images_directory(tmp_path):
    for name in ["b.JPG", "a.jpg", "c.PNG", "notes.txt", "d.tif"]:
        (tmp_path / name).write_bytes(b"x")
    found = [os.path.basename(p) for p in sp.find_images(str(tmp_path))]
    # images only, sorted, case-insensitive extensions; .txt excluded
    assert found == ["a.jpg", "b.JPG", "c.PNG", "d.tif"]


def test_find_images_glob(tmp_path):
    (tmp_path / "x1.JPG").write_bytes(b"x")
    (tmp_path / "x2.JPG").write_bytes(b"x")
    found = sp.find_images(str(tmp_path / "*.JPG"))
    assert len(found) == 2


# --- process_task cleanup contract (findings #1, #5) -----------------------

class FakeWebODM:
    """Records calls; lets a test make any step raise to simulate a failure."""

    def __init__(self, fail_on=None, summary=None):
        self.fail_on = fail_on                       # method name that raises
        self.summary = summary if summary is not None else {
            "detections": 24, "unique_markers": 5, "weak_markers": [],
            "gcp_list": "EPSG:28191\n1 1 2 3 4 5 img1.JPG 1\n",
        }
        self.calls = []

    def _maybe_fail(self, name):
        self.calls.append(name)
        if name == self.fail_on:
            raise RuntimeError("simulated {} failure".format(name))

    def upload_file(self, project_id, task_id, path_or_name, content=None):
        # only the gcp_list upload is interesting to fail on; image uploads
        # share the method but we key the failure on a distinct name below
        self._maybe_fail("upload_gcp" if content is not None else "upload_image")

    def detect(self, *a, **k):
        self._maybe_fail("detect")
        return self.summary

    def commit(self, project_id, task_id):
        self._maybe_fail("commit")

    def remove_task(self, project_id, task_id):
        self.calls.append("remove_task")


def _args(**over):
    base = dict(url="http://x", coords="gcp.txt", epsg=28191, dict_id=1,
                minrate=0.01, ignore=0.33, adjust=True,
                dry_run=False, keep_on_error=False)
    base.update(over)
    return types.SimpleNamespace(**base)


IMAGES = ["a.JPG", "b.JPG"]


def test_success_commits_and_keeps_task():
    wo = FakeWebODM()
    sp.process_task(wo, 7, 42, IMAGES, _args())
    assert "commit" in wo.calls
    assert "remove_task" not in wo.calls


def test_failure_before_commit_removes_orphan():
    wo = FakeWebODM(fail_on="detect")
    with pytest.raises(RuntimeError):
        sp.process_task(wo, 7, 42, IMAGES, _args())
    assert wo.calls.count("remove_task") == 1
    assert "commit" not in wo.calls


def test_commit_in_flight_failure_keeps_task():
    # The core of finding #1: a lost response *during* commit must NOT delete a
    # task the server may already have started.
    wo = FakeWebODM(fail_on="commit")
    with pytest.raises(RuntimeError):
        sp.process_task(wo, 7, 42, IMAGES, _args())
    assert "commit" in wo.calls
    assert "remove_task" not in wo.calls


def test_keep_on_error_skips_cleanup():
    wo = FakeWebODM(fail_on="detect")
    with pytest.raises(RuntimeError):
        sp.process_task(wo, 7, 42, IMAGES, _args(keep_on_error=True))
    assert "remove_task" not in wo.calls


def test_dry_run_stops_before_commit_and_keeps_task():
    wo = FakeWebODM()
    sp.process_task(wo, 7, 42, IMAGES, _args(dry_run=True))
    assert "commit" not in wo.calls
    assert "remove_task" not in wo.calls


def test_empty_gcp_list_is_treated_as_failure():
    wo = FakeWebODM(summary={"detections": 0, "unique_markers": 0,
                             "weak_markers": [], "gcp_list": ""})
    with pytest.raises(RuntimeError):
        sp.process_task(wo, 7, 42, IMAGES, _args())
    assert wo.calls.count("remove_task") == 1
