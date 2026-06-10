"""
Tests for findgcp/gcp_detect.py.

The key test (test_self_contained_under_worker_eval) reproduces exactly how
WebODM runs the function in the worker: app/plugins/worker.py does
`inspect.getsource(func)`, compiles it in an EMPTY namespace and calls it. If
detect_gcps referenced any module-level name, that would raise NameError in the
worker — this suite catches that class of bug, which plain import-and-call hides.

OpenCV is mocked (real cv2 is not needed in CI); numpy is used for real.
The plugin package __init__ imports WebODM, so we load gcp_detect.py directly
via importlib instead of importing the package.
"""

import importlib.util
import inspect
import os
import sys
import types

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GCP_DETECT_PATH = os.path.join(HERE, "..", "findgcp", "gcp_detect.py")


def load_detect_source_fn():
    """Load gcp_detect.py standalone, then re-exec detect_gcps the way the
    WebODM worker does: from its source text, in an empty namespace."""
    spec = importlib.util.spec_from_file_location("gcp_detect_std", GCP_DETECT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    source = inspect.getsource(mod.detect_gcps)
    ns = {}
    exec(compile(source, "worker", "exec"), ns, ns)  # mirror eval_async
    return ns["detect_gcps"]


def make_cv2(detections, unreadable=()):
    """Build a fake cv2 module.

    detections: {image_basename: [(marker_id, corners_4x2), ...]}
    unreadable: iterable of basenames for which imread returns None.

    imread returns the path string; LUT/cvtColor pass it through, so the
    `gray` handed to detectMarkers IS the path and can be looked up.
    """
    cv2 = types.ModuleType("cv2")
    cv2.__version__ = "4.10.0"
    cv2.COLOR_BGR2GRAY = 6
    unreadable = set(unreadable)

    def imread(path):
        return None if os.path.basename(path) in unreadable else path

    cv2.imread = imread
    cv2.cvtColor = lambda x, code: x
    cv2.LUT = lambda x, lut: x

    aruco = types.ModuleType("cv2.aruco")

    class DetectorParameters:
        def __init__(self):
            self.minMarkerPerimeterRate = 0.0
            self.perspectiveRemoveIgnoredMarginPerCell = 0.0

    def lookup(gray):
        items = detections.get(os.path.basename(gray), [])
        if not items:
            return ([], None, None)
        corners = [np.array([c], dtype=float) for (_id, c) in items]
        ids = np.array([[mid] for (mid, _c) in items])
        return (corners, ids, None)

    class ArucoDetector:
        def __init__(self, d, p):
            pass

        def detectMarkers(self, gray):
            return lookup(gray)

    aruco.DetectorParameters = DetectorParameters
    aruco.ArucoDetector = ArucoDetector
    aruco.getPredefinedDictionary = lambda d: ("predef", d)
    aruco.extendDictionary = lambda a, b: ("custom", a, b)
    cv2.aruco = aruco
    return cv2, aruco


SQUARE = np.array([[90, 190], [110, 190], [110, 210], [90, 210]], dtype=float)  # centroid (100, 200)


@pytest.fixture
def install_cv2(monkeypatch):
    def _install(detections, unreadable=()):
        cv2, aruco = make_cv2(detections, unreadable)
        monkeypatch.setitem(sys.modules, "cv2", cv2)
        monkeypatch.setitem(sys.modules, "cv2.aruco", aruco)
        return cv2
    return _install


def run(detect, **kw):
    defaults = dict(epsg=28191, dict_id=1, minrate=0.01, ignore=0.33, adjust=True)
    defaults.update(kw)
    return detect(**defaults)


# --------------------------------------------------------------------------

def test_self_contained_under_worker_eval(install_cv2):
    """The regression guard: detect_gcps must run from its source in an empty
    namespace (no module-level helper/constant references)."""
    install_cv2({"a.JPG": [(5, SQUARE)]})
    detect = load_detect_source_fn()
    res = run(detect, image_paths=["/imgs/a.JPG"], coords_text="5 100 200 30")
    assert "error" not in res, res
    assert res["output"]["detections"] == 1


def test_odm_output_format(install_cv2):
    install_cv2({"DJI_1.JPG": [(5, SQUARE)], "DJI_2.JPG": [(5, SQUARE)]})
    detect = load_detect_source_fn()
    res = run(detect,
              image_paths=["/x/DJI_1.JPG", "/x/DJI_2.JPG"],
              coords_text="5 698000.123 3540000.456 412.7\n")
    lines = res["output"]["gcp_list"].splitlines()
    assert lines[0] == "EPSG:28191"
    assert lines[1] == "698000.123 3540000.456 412.7 100 200 DJI_1.JPG 5"
    assert res["output"]["unique_markers"] == 1


def test_rejects_non_integer_id(install_cv2):
    install_cv2({"a.JPG": [(1, SQUARE)]})
    detect = load_detect_source_fn()
    # "1.9" must NOT be accepted as marker 1 -> no coordinates -> error
    res = run(detect, image_paths=["/x/a.JPG"], coords_text="1.9 100 200 30")
    assert "error" in res


def test_rejects_nan_inf_coords(install_cv2):
    install_cv2({"a.JPG": [(5, SQUARE)]})
    detect = load_detect_source_fn()
    res = run(detect, image_paths=["/x/a.JPG"], coords_text="5 nan inf 30")
    assert "error" in res  # line rejected -> no valid coords


def test_duplicate_ids_keep_first_and_report(install_cv2):
    install_cv2({"a.JPG": [(5, SQUARE)]})
    detect = load_detect_source_fn()
    res = run(detect, image_paths=["/x/a.JPG"],
              coords_text="5 111 222 1\n5 999 999 9\n")
    line = res["output"]["gcp_list"].splitlines()[1]
    assert line.startswith("111 222 1 "), line        # first kept
    assert 5 in res["output"]["coord_duplicate_ids"]


def test_unreadable_images_counted(install_cv2):
    install_cv2({"a.JPG": [(5, SQUARE)]}, unreadable=["broken.JPG"])
    detect = load_detect_source_fn()
    res = run(detect, image_paths=["/x/a.JPG", "/x/broken.JPG"],
              coords_text="5 1 2 3")
    assert res["output"]["images_unreadable"] == 1
    assert res["output"]["images_total"] == 2


def test_no_matching_markers_errors(install_cv2):
    install_cv2({"a.JPG": [(7, SQUARE)]})
    detect = load_detect_source_fn()
    res = run(detect, image_paths=["/x/a.JPG"], coords_text="5 1 2 3")
    assert "error" in res
    assert "No detected markers match" in res["error"]


def test_weak_marker_flagged(install_cv2):
    install_cv2({"a.JPG": [(5, SQUARE)]})
    detect = load_detect_source_fn()
    res = run(detect, image_paths=["/x/a.JPG"], coords_text="5 1 2 3")
    assert res["output"]["weak_markers"] == [5]   # on < 3 images


def test_unmatched_detection_reported(install_cv2):
    install_cv2({"a.JPG": [(5, SQUARE), (8, SQUARE)]})
    detect = load_detect_source_fn()
    res = run(detect, image_paths=["/x/a.JPG"], coords_text="5 1 2 3")
    assert res["output"]["unmatched_ids"] == [8]


def test_dict_99_uses_custom(install_cv2):
    install_cv2({"a.JPG": [(5, SQUARE)]})
    detect = load_detect_source_fn()
    res = run(detect, image_paths=["/x/a.JPG"], coords_text="5 1 2 3", dict_id=99)
    assert "error" not in res


def test_missing_cv2_returns_friendly_error(monkeypatch):
    """When cv2 can't be imported (and no shared site-packages exists), detect
    returns a clear error pointing to docker/ — not a raw ImportError."""
    # Setting sys.modules['cv2'] = None makes `import cv2` raise ImportError,
    # even in an environment that has OpenCV installed.
    monkeypatch.setitem(sys.modules, "cv2", None)
    monkeypatch.setitem(sys.modules, "cv2.aruco", None)
    detect = load_detect_source_fn()
    res = run(detect, image_paths=["/x/a.JPG"], coords_text="5 1 2 3")
    assert "error" in res
    assert "cv2" in res["error"] and "docker/" in res["error"]


def test_cv2_without_aruco_returns_friendly_error():
    """A cv2 present but WITHOUT the aruco module must NOT crash with an uncaught
    ImportError (the regression of finding #2: `from cv2 import aruco` used to
    sit *after* the guarded import). It is caught, the fallback is tried, and a
    clear "fix the worker image" error is returned.

    We manage sys.modules by hand (not monkeypatch): the cv2 entry must be
    *fully* replaced — any leftover real ``cv2.aruco`` submodule from another
    test would let ``from cv2 import aruco`` succeed and mask the case."""
    saved = {k: sys.modules[k] for k in list(sys.modules) if k == "cv2" or k.startswith("cv2.")}
    for k in saved:
        del sys.modules[k]
    fake_cv2 = types.ModuleType("cv2")  # no `aruco` attribute, no __path__
    fake_cv2.__version__ = "4.10.0"
    sys.modules["cv2"] = fake_cv2
    try:
        detect = load_detect_source_fn()
        res = run(detect, image_paths=["/x/a.JPG", "/x/b.JPG"], coords_text="5 1 2 3")
        assert "error" in res                       # no uncaught exception
        assert "cv2.aruco" in res["error"] and "docker/" in res["error"]
    finally:
        for k in [k for k in list(sys.modules) if k == "cv2" or k.startswith("cv2.")]:
            del sys.modules[k]
        sys.modules.update(saved)


def test_legacy_aruco_api(monkeypatch):
    """No ArucoDetector attribute -> fall back to aruco.detectMarkers()."""
    cv2, aruco = make_cv2({"a.JPG": [(5, SQUARE)]})
    delattr(aruco, "ArucoDetector")
    aruco.detectMarkers = lambda gray, d, parameters=None: (
        [np.array([SQUARE], dtype=float)], np.array([[5]]), None)
    aruco.DetectorParameters_create = aruco.DetectorParameters
    delattr(aruco, "DetectorParameters")
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    monkeypatch.setitem(sys.modules, "cv2.aruco", aruco)
    detect = load_detect_source_fn()
    res = run(detect, image_paths=["/x/a.JPG"], coords_text="5 1 2 3")
    assert res["output"]["detections"] == 1
