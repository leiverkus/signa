"""Pure parameter validation for the detect endpoint.

Deliberately free of Django/WebODM imports so it can be unit-tested in CI
without a running WebODM. Returns plain English error strings; the API view
surfaces them to the client as JSON.
"""

# Predefined OpenCV ArUco dictionary ids span 0..20; 99 is Find-GCP's custom 3x3.
VALID_DICTS = set(range(0, 21)) | {99}

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
