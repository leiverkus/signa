"""Build a georeferencing-accuracy report from Effigies' georef_transform.json.

Signa does NOT re-do any geometry: the Effigies reconstruction node solves the
georeferencing and, when GCPs are flagged as held-out CHECK points, reports an
INDEPENDENT check-point RMSE. This module turns that file's residuals into a
human-readable accuracy report. Django-free so it can be unit-tested without WebODM.

Unlike a marker's known size (Mensura's scale report), absolute georeferencing
accuracy can only be verified against EXTERNALLY surveyed coordinates — the honest
metric is the held-out check-point RMSE. Without a check point only the
control-point fit is available, which is optimistic by construction (every GCP went
into the solve) and is reported as such, explicitly NOT as an accuracy.

Effigies sources (georef_transform.json ``source``):
  - ``colmap-gcp-ba``  GCP-constrained bundle adjustment — carries split
    ``control_*`` and ``check_*`` residuals (the honest check-point RMSE).
  - ``colmap-gcp``     post-hoc Umeyama similarity — a flat control fit; an
    ``arbitration`` sidecar may still record the held-out check-point RMSE.
  - ``colmap-exif`` / ``exif``  EXIF-GPS — georeferenced but consumer-GPS accuracy.
  - ``none`` / ``local`` / ``local-only``  not georeferenced.
"""

# Sources that place the model in a world CRS (vs a local frame).
_GCP_SOURCES = ('colmap-gcp', 'colmap-gcp-ba', 'gcp')
_GEOREF_SOURCES = _GCP_SOURCES + ('colmap-exif', 'exif')

# Above this INDEPENDENT check-point 3D RMSE the georeferencing is flagged. OPEN
# (survey-domain) — RTK/total-station GCP work is typically 1-3 cm; 5 cm is a
# conservative "something is wrong" bound. Tunable.
WARN_CHECK_RMS_M = 0.05
# Same bound applied to the control fit when no check point is available — but the
# verdict always notes this is NOT an independent accuracy.
WARN_CONTROL_RMS_M = 0.05


def _mm(v):
    return float(v) * 1000.0 if v is not None else None


def _cm(v):
    return v * 100.0 if v is not None else None


def _resolve(transform):
    """Resolve control + check residuals (metres) across the source cases.

    Returns ``(source, control, check, n_control, n_check, has_independent)`` where
    control/check are ``{rms_3d, rms_horizontal, rms_vertical}`` (values may be None).
    First matching case wins: BA -> post-hoc+arbitration -> post-hoc-plain.
    """
    source = str(transform.get('source', 'unknown'))
    res = transform.get('residuals') or {}
    arb = transform.get('arbitration') or {}

    control = {'rms_3d': None, 'rms_horizontal': None, 'rms_vertical': None}
    check = {'rms_3d': None, 'rms_horizontal': None, 'rms_vertical': None}
    n_control = n_check = None

    if source == 'colmap-gcp-ba':
        # BA path: split control/check residuals are written directly.
        n_control = res.get('n_control')
        control['rms_3d'] = res.get('control_rms_3d')
        control['rms_horizontal'] = res.get('control_rms_horizontal')
        control['rms_vertical'] = res.get('control_rms_vertical')
        if res.get('check_rms_3d') is not None:   # BA with no check -> control only
            n_check = res.get('n_check')
            check['rms_3d'] = res.get('check_rms_3d')
            check['rms_horizontal'] = res.get('check_rms_horizontal')
            check['rms_vertical'] = res.get('check_rms_vertical')
    else:
        # Post-hoc paths: residuals is the (flat) control fit.
        n_control = res.get('count')
        control['rms_3d'] = res.get('rms_3d')
        control['rms_horizontal'] = res.get('rms_horizontal')
        control['rms_vertical'] = res.get('rms_vertical')
        # An 'auto'-mode arbitration sidecar may still carry the held-out CP-RMSE of
        # the APPLIED transform (3D only). Resolve by the recorded winner.
        if arb and (arb.get('n_check') or 0) > 0:
            cp = arb.get('cp_ba') if arb.get('winner') == 'ba' else arb.get('cp_umeyama')
            if cp is not None:
                n_check = arb.get('n_check')
                check['rms_3d'] = cp

    has_independent = check['rms_3d'] is not None
    return source, control, check, n_control, n_check, has_independent


def _verdict(georeferenced, source, has_independent, check_rms_m, n_check,
             control_rms_m):
    if not georeferenced:
        return ("No GCP/EXIF georeferencing was applied — the model is in a local "
                "frame. Check that markers were detected and the GCP file was "
                "attached before processing.")
    if has_independent:
        c, n = _cm(check_rms_m), (n_check or 0)
        if check_rms_m <= WARN_CHECK_RMS_M:
            return ("Independent check on {} held-out GCP(s): {:.1f} cm 3D RMSE — "
                    "accuracy independently verified.".format(n, c))
        return ("Independent check on {} held-out GCP(s): {:.1f} cm 3D RMSE exceeds "
                "the {:.0f} cm bound — accuracy may be insufficient (check the GCP "
                "measurement, marker placement, or image coverage).".format(
                    n, c, WARN_CHECK_RMS_M * 100.0))
    if control_rms_m is not None:
        return ("Georeferenced via {}; control GCP fit {:.1f} cm 3D RMSE. This is the "
                "fit of the control points used in the solve, NOT an independent "
                "accuracy — end a coordinate line with 'check' to hold a point out "
                "for an honest check-point RMSE.".format(source, _cm(control_rms_m)))
    return "Georeferenced via {}; no GCP fit residual was recorded.".format(source)


def build_accuracy_report(transform):
    """Turn a parsed georef_transform.json dict into a georeferencing-accuracy report.

    :param transform: parsed ``georef_transform.json`` (``source``, ``crs``,
        ``residuals``, optional ``arbitration``).
    :returns: a JSON-serialisable report dict (metres -> mm keys; the UI renders cm).
    """
    source, control, check, n_control, n_check, has_independent = _resolve(transform)
    georeferenced = source in _GEOREF_SOURCES
    check_rms_m = check['rms_3d']
    control_rms_m = control['rms_3d']

    # One source of truth for the pass/fail banner (used by the UI directly). With
    # no independent check the control fit can pass, but the verdict flags that it
    # is not an independent accuracy.
    ok = bool(georeferenced and (
        (has_independent and check_rms_m <= WARN_CHECK_RMS_M)
        or (not has_independent and control_rms_m is not None
            and control_rms_m <= WARN_CONTROL_RMS_M)))

    return {
        'available': True,
        'ok': ok,
        'source': source,
        'georeferenced': georeferenced,
        'crs': transform.get('crs'),
        'n_control': int(n_control) if n_control is not None else None,
        'control_rms_mm': _mm(control['rms_3d']),
        'control_rms_horizontal_mm': _mm(control['rms_horizontal']),
        'control_rms_vertical_mm': _mm(control['rms_vertical']),
        'has_independent_check': has_independent,
        'n_check': int(n_check) if n_check is not None else None,
        'check_rms_mm': _mm(check['rms_3d']),
        'check_rms_horizontal_mm': _mm(check['rms_horizontal']),
        'check_rms_vertical_mm': _mm(check['rms_vertical']),
        'verdict': _verdict(georeferenced, source, has_independent, check_rms_m,
                            n_check, control_rms_m),
    }
