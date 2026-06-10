"""Tests for findgcp/params.py (detect-endpoint parameter validation).

params.py is Django-free on purpose; we load it standalone (the plugin package
__init__ imports WebODM, which is absent in CI).
"""

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS_PATH = os.path.join(HERE, "..", "findgcp", "params.py")


def _load():
    spec = importlib.util.spec_from_file_location("findgcp_params", PARAMS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


validate_params = _load().validate_params


def test_valid_defaults():
    params, err = validate_params({"epsg": "28191"})
    assert err is None
    assert params == {"epsg": 28191, "dict_id": 1, "minrate": 0.01,
                      "ignore": 0.33, "adjust": True}


def test_all_fields():
    params, err = validate_params({
        "epsg": "2039", "dict": "99", "minrate": "0.008",
        "ignore": "0.2", "adjust": "false"})
    assert err is None
    assert params["epsg"] == 2039
    assert params["dict_id"] == 99
    assert params["minrate"] == 0.008
    assert params["ignore"] == 0.2
    assert params["adjust"] is False


def test_missing_epsg():
    params, err = validate_params({})
    assert params is None and "EPSG" in err


def test_non_numeric_epsg():
    params, err = validate_params({"epsg": "abc"})
    assert params is None and "EPSG" in err


def test_epsg_out_of_range():
    params, err = validate_params({"epsg": "5"})
    assert params is None and "range" in err


def test_bad_dict():
    params, err = validate_params({"epsg": "28191", "dict": "7.5"})
    assert params is None and "dictionary" in err


def test_unsupported_dict():
    params, err = validate_params({"epsg": "28191", "dict": "50"})
    assert params is None and "Unsupported" in err


def test_minrate_zero_rejected():
    params, err = validate_params({"epsg": "28191", "minrate": "0"})
    assert params is None and "minrate" in err


def test_minrate_above_one_rejected():
    params, err = validate_params({"epsg": "28191", "minrate": "1.5"})
    assert params is None and "minrate" in err


def test_minrate_nan_rejected():
    params, err = validate_params({"epsg": "28191", "minrate": "nan"})
    assert params is None and "minrate" in err


def test_ignore_one_rejected():
    params, err = validate_params({"epsg": "28191", "ignore": "1.0"})
    assert params is None and "ignore" in err


def test_ignore_negative_rejected():
    params, err = validate_params({"epsg": "28191", "ignore": "-0.1"})
    assert params is None and "ignore" in err


def test_adjust_truthy_variants():
    for v in ("1", "true", "On", "YES"):
        params, err = validate_params({"epsg": "28191", "adjust": v})
        assert err is None and params["adjust"] is True
    for v in ("0", "false", "no", "off"):
        params, err = validate_params({"epsg": "28191", "adjust": v})
        assert err is None and params["adjust"] is False
