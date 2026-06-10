"""Real-OpenCV integration test for detect_gcps.

Unlike test_gcp_detect.py (which mocks cv2), this renders actual ArUco markers
with OpenCV and runs the detection end to end, so it exercises cv2.aruco, the
color LUT and the corner-centroid maths for real. Skipped automatically when
opencv-contrib is not installed; CI installs it so this runs there.
"""

import importlib.util
import inspect
import os

import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("cv2.aruco")

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_PATH = os.path.join(HERE, "fixtures", "make_aruco_fixture.py")
GCP_DETECT_PATH = os.path.join(HERE, "..", "findgcp", "gcp_detect.py")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_detect_source_fn():
    mod = _load(GCP_DETECT_PATH, "gcp_detect_std")
    src = inspect.getsource(mod.detect_gcps)
    ns = {}
    exec(compile(src, "worker", "exec"), ns, ns)
    return ns["detect_gcps"]


@pytest.fixture(scope="module")
def fixture_mod():
    return _load(FIXTURE_PATH, "make_aruco_fixture")


def test_real_detection_roundtrip(fixture_mod, tmp_path):
    paths = fixture_mod.render_dataset(str(tmp_path))
    detect = _load_detect_source_fn()

    res = detect(image_paths=paths, coords_text=fixture_mod.coords_text(),
                 epsg=fixture_mod.EPSG, dict_id=fixture_mod.DICT_ID,
                 minrate=0.01, ignore=0.33, adjust=True)

    assert "error" not in res, res.get("error")
    out = res["output"]
    # All 5 markers detected, each on >= 3 images (no weak markers).
    assert out["unique_markers"] == 5
    assert out["weak_markers"] == []
    assert out["unmatched_ids"] == []
    assert set(out["markers_per_id"].keys()) == {"0", "1", "2", "3", "4"}

    lines = out["gcp_list"].splitlines()
    assert lines[0] == "EPSG:28191"

    # World coordinates must map correctly, and the detected centroid must be
    # within a few px of the known placement for each marker id.
    for line in lines[1:]:
        e, n, z, px, py, image, mid = line.split()
        mid = int(mid)
        assert (e, n, z) == fixture_mod.COORDS[mid]
        cx, cy = fixture_mod.POSITIONS[mid]
        assert abs(int(px) - cx) <= 2
        assert abs(int(py) - cy) <= 2


def test_no_markers_without_targets(fixture_mod, tmp_path):
    """A coordinate file with ids that aren't in the images yields a clean error."""
    paths = fixture_mod.render_dataset(str(tmp_path))
    detect = _load_detect_source_fn()
    res = detect(image_paths=paths, coords_text="90 1 2 3\n91 4 5 6\n",
                 epsg=28191, dict_id=1, minrate=0.01, ignore=0.33, adjust=True)
    assert "error" in res
    assert "No detected markers match" in res["error"]


def test_adjust_off_also_detects(fixture_mod, tmp_path):
    paths = fixture_mod.render_dataset(str(tmp_path))
    detect = _load_detect_source_fn()
    res = detect(image_paths=paths, coords_text=fixture_mod.coords_text(),
                 epsg=28191, dict_id=1, minrate=0.01, ignore=0.33, adjust=False)
    assert "error" not in res
    assert res["output"]["unique_markers"] == 5
