"""Tests for signa/accuracy.py — build_accuracy_report (reads Effigies georef output).

Pure Python, no WebODM. Loaded standalone (the plugin package imports WebODM).
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "..", relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


acc = _load("signa_accuracy", "signa/accuracy.py")


def test_ba_independent_check_verified():
    tr = {"source": "colmap-gcp-ba", "crs": "EPSG:32637",
          "residuals": {"n_control": 6, "n_check": 2,
                        "control_rms_3d": 0.004, "control_rms_horizontal": 0.003,
                        "control_rms_vertical": 0.002,
                        "check_rms_3d": 0.012, "check_rms_horizontal": 0.008,
                        "check_rms_vertical": 0.009}}
    r = acc.build_accuracy_report(tr)
    assert r["available"] and r["georeferenced"] and r["has_independent_check"]
    assert r["n_check"] == 2 and abs(r["check_rms_mm"] - 12.0) < 1e-9
    assert abs(r["check_rms_horizontal_mm"] - 8.0) < 1e-9
    assert r["n_control"] == 6 and abs(r["control_rms_mm"] - 4.0) < 1e-9
    assert r["ok"] is True
    assert "independently verified" in r["verdict"]


def test_ba_check_exceeds_threshold_warns():
    tr = {"source": "colmap-gcp-ba", "crs": "EPSG:32637",
          "residuals": {"n_control": 6, "n_check": 2, "control_rms_3d": 0.01,
                        "check_rms_3d": 0.08, "check_rms_horizontal": 0.06,
                        "check_rms_vertical": 0.05}}
    r = acc.build_accuracy_report(tr)
    assert r["has_independent_check"] is True
    assert r["ok"] is False
    assert "exceeds" in r["verdict"]


def test_ba_no_check_falls_back_to_control():
    tr = {"source": "colmap-gcp-ba", "crs": "EPSG:32637",
          "residuals": {"n_control": 5, "control_rms_3d": 0.003, "check": None}}
    r = acc.build_accuracy_report(tr)
    assert r["has_independent_check"] is False
    assert r["check_rms_mm"] is None and r["n_check"] is None
    assert abs(r["control_rms_mm"] - 3.0) < 1e-9
    assert "NOT an independent accuracy" in r["verdict"]


def test_posthoc_with_arbitration_uses_cp_rmse():
    tr = {"source": "colmap-gcp", "crs": "EPSG:32637",
          "residuals": {"count": 8, "rms_3d": 0.006, "rms_horizontal": 0.004,
                        "rms_vertical": 0.003, "max_3d": 0.011},
          "arbitration": {"winner": "umeyama", "cp_umeyama": 0.02, "cp_ba": 0.05,
                          "n_check": 2}}
    r = acc.build_accuracy_report(tr)
    assert r["has_independent_check"] is True
    assert r["n_check"] == 2 and abs(r["check_rms_mm"] - 20.0) < 1e-9
    assert r["check_rms_horizontal_mm"] is None      # arbitration carries 3D only
    assert r["n_control"] == 8 and abs(r["control_rms_mm"] - 6.0) < 1e-9
    assert r["ok"] is True and "independently verified" in r["verdict"]


def test_posthoc_plain_has_no_independent_metric():
    tr = {"source": "colmap-gcp", "crs": "EPSG:32637",
          "residuals": {"count": 8, "rms_3d": 0.006, "rms_horizontal": 0.004,
                        "rms_vertical": 0.003, "max_3d": 0.011}}
    r = acc.build_accuracy_report(tr)
    assert r["has_independent_check"] is False
    assert r["check_rms_mm"] is None
    assert abs(r["control_rms_mm"] - 6.0) < 1e-9
    assert r["ok"] is True                            # control within 5 cm...
    assert "NOT an independent accuracy" in r["verdict"]   # ...but flagged as such


def test_not_georeferenced():
    r = acc.build_accuracy_report({"source": "local-only", "crs": "local"})
    assert r["georeferenced"] is False and r["ok"] is False
    assert r["control_rms_mm"] is None
    assert "local frame" in r["verdict"]


def test_exif_counts_as_georeferenced():
    tr = {"source": "colmap-exif", "crs": "EPSG:32637",
          "residuals": {"count": 30, "rms_3d": 1.5, "max_3d": 3.0}}
    r = acc.build_accuracy_report(tr)
    assert r["georeferenced"] is True
    assert r["has_independent_check"] is False
    assert r["ok"] is False                           # 150 cm control fit >> 5 cm
    assert "NOT an independent accuracy" in r["verdict"]


def test_missing_residuals():
    r = acc.build_accuracy_report({"source": "colmap-gcp", "crs": "EPSG:32637"})
    assert r["available"] is True
    assert r["control_rms_mm"] is None and r["check_rms_mm"] is None
    assert "no GCP fit residual" in r["verdict"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all accuracy tests passed")
