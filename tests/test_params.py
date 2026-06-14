"""Tests for signa/params.py (detect-endpoint parameter validation).

params.py is Django-free on purpose; we load it standalone (the plugin package
__init__ imports WebODM, which is absent in CI).
"""

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS_PATH = os.path.join(HERE, "..", "signa", "params.py")


def _load():
    spec = importlib.util.spec_from_file_location("signa_params", PARAMS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_params = _load()
validate_params = _params.validate_params


def test_all_opencv_dicts_and_custom_accepted():
    # every id offered in the UI (0..20 predefined + 99 custom) must validate
    for value, _label in _params.DICT_CHOICES:
        p, err = validate_params({"epsg": "28191", "dict": value})
        assert err is None, (value, err)
        assert p["dict_id"] == int(value)


def test_dict_choices_match_valid_dicts():
    # the UI list and the accepted-id set are derived from the same source
    assert {int(v) for v, _ in _params.DICT_CHOICES} == _params.VALID_DICTS
    assert _params.VALID_DICTS == set(range(0, 21)) | {99}


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


def test_minrate_below_floor_rejected():
    # below the documented 0.005 floor (the old code accepted down to 0.0001)
    params, err = validate_params({"epsg": "28191", "minrate": "0.0001"})
    assert params is None and "minrate" in err


def test_minrate_at_floor_accepted():
    params, err = validate_params({"epsg": "28191", "minrate": "0.005"})
    assert err is None and params["minrate"] == 0.005


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


# --- validate_marker_params (marker-sheet printing) -------------------------

validate_marker_params = _params.validate_marker_params


def test_marker_defaults():
    params, err = validate_marker_params({})
    assert err is None
    assert params == {"dict_id": 1, "id_from": 0, "id_to": 0,
                      "page": "a4", "gray": False, "aid": "cross"}


def test_marker_all_fields():
    params, err = validate_marker_params({
        "dict": "99", "id_from": "5", "id_to": "16",
        "page": "A3", "gray": "on", "aid": "dot_ring"})
    assert err is None
    assert params == {"dict_id": 99, "id_from": 5, "id_to": 16,
                      "page": "a3", "gray": True, "aid": "dot_ring"}


def test_marker_bad_dict():
    params, err = validate_marker_params({"dict": "50"})
    assert params is None and "Unsupported" in err


def test_marker_bad_range():
    for data in ({"id_from": "x"}, {"id_from": "-1"},
                 {"id_from": "5", "id_to": "4"}):
        params, err = validate_marker_params(data)
        assert params is None and "range" in err, data


def test_marker_range_too_large():
    params, err = validate_marker_params({"dict": "3", "id_from": "0", "id_to": "100"})
    assert params is None and "too large" in err
    params, err = validate_marker_params({"dict": "3", "id_from": "0", "id_to": "99"})
    assert err is None


def test_marker_range_must_fit_dictionary():
    # DICT_4X4_50 has ids 0..49; AprilTag 16h5 only 0..29
    params, err = validate_marker_params({"dict": "0", "id_to": "50"})
    assert params is None and "capacity" in err
    params, err = validate_marker_params({"dict": "0", "id_to": "49"})
    assert err is None
    params, err = validate_marker_params({"dict": "17", "id_to": "30"})
    assert params is None and "capacity" in err


def test_marker_capacity_table_covers_all_dicts():
    assert set(_params.DICT_CAPACITY) == _params.VALID_DICTS


def test_marker_bad_page():
    params, err = validate_marker_params({"page": "letter"})
    assert params is None and "page size" in err


def test_marker_bad_aid():
    params, err = validate_marker_params({"aid": "bullseye"})
    assert params is None and "aiming aid" in err
