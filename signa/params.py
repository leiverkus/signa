"""Pure parameter validation for the detect and marker-print endpoints.

Deliberately free of Django/WebODM imports so it can be unit-tested in CI
without a running WebODM. Returns plain English error strings; the API view
surfaces them to the client as JSON.
"""

# The ArUco dictionaries the plugin offers come from signa-core — the single
# source of truth shared with the detection layer and other consumers (e.g.
# Mensura). Re-exported here so the settings form, UI dropdowns and API
# validation can never drift from the detector. signa-core has no Django and no
# cv2 import at module level, so params.py stays Django-free and cv2-free.
from signa_core import DICT_CHOICES, VALID_DICTS  # noqa: F401  (re-exported)

# Marker-sheet tables also live in signa-core (shared with Mensura's scale
# markers), so the settings form, UI dropdowns, validation and the renderer can
# never drift. signa-core imports no Django and no cv2 at module level, so
# params.py stays Django-free and cv2-free.
from signa_core import (  # noqa: F401  (re-exported)
    DICT_CAPACITY,
    MARKER_AIDS,
    MAX_MARKER_PAGES,
    PAGE_SIZES_MM,
)

# Hard floor for minrate. The UI/docs say "never below 0.005"; below it the
# detector accepts tiny perimeters and produces a flood of false positives, so
# the API enforces the same limit the settings form and help texts state.
MIN_MINRATE = 0.005


def validate_params(data):
    """Validate detection parameters.

    :param data: a mapping (``request.data`` / dict) with optional keys
        ``epsg``, ``dict``, ``minrate``, ``ignore``, ``adjust``.
    :returns: ``(params_dict, None)`` on success, or ``(None, error_message)``.
    """
    try:
        epsg = int(data.get('epsg'))
    except (TypeError, ValueError):
        return None, 'A valid EPSG code is required.'
    if not (1024 <= epsg <= 999999):
        return None, 'EPSG code out of range (1024-999999).'

    try:
        dict_id = int(data.get('dict', 1))
    except (TypeError, ValueError):
        return None, 'Invalid ArUco dictionary id.'
    if dict_id not in VALID_DICTS:
        return None, 'Unsupported ArUco dictionary id (use 0-20 or 99).'

    try:
        minrate = float(data.get('minrate', 0.01))
        ignore = float(data.get('ignore', 0.33))
    except (TypeError, ValueError):
        return None, 'Invalid detection parameters.'
    # NaN fails both comparisons, so these bounds reject nan/inf too.
    if not (MIN_MINRATE <= minrate <= 1.0):
        return None, ('minrate must be in the range [{}, 1] — values below {} '
                      'cause excessive false positives.'.format(MIN_MINRATE, MIN_MINRATE))
    if not (0.0 <= ignore < 1.0):
        return None, 'ignore must be in the range [0, 1).'

    adjust = str(data.get('adjust', 'true')).lower() in ('1', 'true', 'on', 'yes')
    return {'epsg': epsg, 'dict_id': dict_id, 'minrate': minrate,
            'ignore': ignore, 'adjust': adjust}, None


# --- Marker-sheet printing (settings page → PDF download) -------------------
# PAGE_SIZES_MM, MARKER_AIDS, DICT_CAPACITY and MAX_MARKER_PAGES come from
# signa-core (imported at the top of this module).


def validate_marker_params(data):
    """Validate marker-sheet parameters (same contract as validate_params)."""
    try:
        dict_id = int(data.get('dict', 1))
    except (TypeError, ValueError):
        return None, 'Invalid ArUco dictionary id.'
    if dict_id not in VALID_DICTS:
        return None, 'Unsupported ArUco dictionary id (use 0-20 or 99).'

    try:
        id_from = int(data.get('id_from', 0))
        id_to = int(data.get('id_to', id_from))
    except (TypeError, ValueError):
        return None, 'Invalid marker id range.'
    if id_from < 0 or id_to < id_from:
        return None, 'Invalid marker id range.'
    if id_to - id_from + 1 > MAX_MARKER_PAGES:
        return None, 'Marker id range too large (max 100 markers per PDF).'
    if id_to >= DICT_CAPACITY[dict_id]:
        return None, 'Marker id range exceeds the capacity of the selected dictionary.'

    page = str(data.get('page', 'a4')).lower()
    if page not in PAGE_SIZES_MM:
        return None, 'Unsupported page size (use A2-A6).'

    aid = str(data.get('aid', 'cross')).lower()
    if aid not in MARKER_AIDS:
        return None, 'Unsupported center aiming aid.'

    gray = str(data.get('gray', 'false')).lower() in ('1', 'true', 'on', 'yes')
    return {'dict_id': dict_id, 'id_from': id_from, 'id_to': id_to,
            'page': page, 'gray': gray, 'aid': aid}, None
