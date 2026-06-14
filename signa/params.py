"""Pure parameter validation for the detect and marker-print endpoints.

Deliberately free of Django/WebODM imports so it can be unit-tested in CI
without a running WebODM. Returns plain English error strings; the API view
surfaces them to the client as JSON.
"""

# The single source of truth for the ArUco dictionaries the plugin offers, as
# (value, label) pairs. Ids 0..20 are OpenCV's predefined dictionaries (verified
# against opencv-contrib 4.10.0); 99 is Find-GCP's custom 3x3 (aruco.extendDictionary).
# The settings form, both UI dropdowns and the API validation all derive from
# this list, so they can never drift apart.
DICT_CHOICES = [
    ("0", "0 — DICT_4X4_50"),
    ("1", "1 — DICT_4X4_100"),
    ("2", "2 — DICT_4X4_250"),
    ("3", "3 — DICT_4X4_1000"),
    ("4", "4 — DICT_5X5_50"),
    ("5", "5 — DICT_5X5_100"),
    ("6", "6 — DICT_5X5_250"),
    ("7", "7 — DICT_5X5_1000"),
    ("8", "8 — DICT_6X6_50"),
    ("9", "9 — DICT_6X6_100"),
    ("10", "10 — DICT_6X6_250"),
    ("11", "11 — DICT_6X6_1000"),
    ("12", "12 — DICT_7X7_50"),
    ("13", "13 — DICT_7X7_100"),
    ("14", "14 — DICT_7X7_250"),
    ("15", "15 — DICT_7X7_1000"),
    ("16", "16 — DICT_ARUCO_ORIGINAL"),
    ("17", "17 — DICT_APRILTAG_16h5"),
    ("18", "18 — DICT_APRILTAG_25h9"),
    ("19", "19 — DICT_APRILTAG_36h10"),
    ("20", "20 — DICT_APRILTAG_36h11"),
    ("99", "99 — custom 3×3 (Find-GCP)"),
]

# Accepted ids, derived from DICT_CHOICES so validation and UI stay in lockstep.
VALID_DICTS = {int(value) for value, _label in DICT_CHOICES}

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

# DIN A page formats offered by the print form, portrait (width, height) in mm.
PAGE_SIZES_MM = {
    'a6': (105, 148),
    'a5': (148, 210),
    'a4': (210, 297),
    'a3': (297, 420),
    'a2': (420, 594),
}

# Center aiming aids (for putting a total station / laser disto target on the
# exact point Find-GCP reports — the marker center). The labels live in the
# settings template as {% trans %} strings so this module stays Django-free.
MARKER_AIDS = ('none', 'cross', 'cross_halo', 'dot_ring')

# Ids per dictionary, verified against opencv-contrib 4.10/4.13 (bytesList row
# counts). Lets validation reject an out-of-range id without importing cv2;
# marker_pdf.py re-checks against the real dictionary as belt and braces.
DICT_CAPACITY = {
    0: 50, 1: 100, 2: 250, 3: 1000,         # 4x4
    4: 50, 5: 100, 6: 250, 7: 1000,         # 5x5
    8: 50, 9: 100, 10: 250, 11: 1000,       # 6x6
    12: 50, 13: 100, 14: 250, 15: 1000,     # 7x7
    16: 1024,                               # ARUCO_ORIGINAL
    17: 30, 18: 35, 19: 2320, 20: 587,      # AprilTag 16h5/25h9/36h10/36h11
    99: 32,                                 # Find-GCP custom 3x3
}

# One page per marker; keeps a synchronous request (and the PDF) bounded.
MAX_MARKER_PAGES = 100


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
