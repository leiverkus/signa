"""
Server-side ArUco ground control point detection.

Ported from Find-GCP (https://github.com/zsiki/Find-GCP, gcp_find.py).

IMPORTANT — execution model:
WebODM's run_function_async() serializes ONLY the source text of detect_gcps
(via inspect.getsource) and exec()'s it in an EMPTY namespace in the worker
(see app/plugins/worker.py -> eval_async). Therefore detect_gcps must be fully
self-contained: every helper, constant and import lives INSIDE the function
body. Do not reference any module-level name from detect_gcps, or the worker
will raise NameError.

This module intentionally contains nothing but detect_gcps for that reason.
"""


def detect_gcps(image_paths, coords_text, epsg, dict_id=1, minrate=0.01,
                ignore=0.33, adjust=True, task_name=None):
    """Detect ArUco GCPs and build an ODM-compatible gcp_list.txt.

    Runs in the WebODM worker via run_function_async. Self-contained by design
    (see module docstring). Returns ``{'output': {...summary..., 'gcp_list': str}}``
    on success or ``{'error': str}`` on failure. No files or temp dirs are
    created — the gcp_list text travels back in the result.
    """
    import os
    import sys
    import math

    import numpy as np

    # OpenCV (with the ArUco contrib module) must be importable in this
    # (Celery worker) process. Two supported ways, tried in order:
    #   1. cv2+aruco is in the worker image — the robust path (see docker/).
    #   2. self-contained single-host: WebODM installs the plugin's
    #      requirements.txt into <MEDIA_ROOT>/plugins/findgcp/site-packages, on
    #      the media volume shared with this worker. We add that to sys.path and
    #      retry. numpy is already loaded by WebODM, so cv2 reuses it.
    # We require BOTH cv2 and cv2.aruco, so a base opencv-python (no aruco)
    # cannot satisfy the check and silently skip detection — the `from cv2
    # import aruco` lives inside the guarded import, not after it. If everything
    # fails (no cv2 at all, a cv2 without aruco that we can't replace, or a
    # distributed worker without the shared volume), we return a clear error
    # pointing to the durable docker/ image rather than crashing. We do NOT
    # purge/reimport a cached cv2: OpenCV's bootstrap is not re-entrant, so a
    # runtime swap is fragile — fixing the worker image is the right remedy.
    def _load_cv2():
        import cv2 as _cv2
        from cv2 import aruco as _aruco
        return _cv2, _aruco

    try:
        cv2, aruco = _load_cv2()
    except ImportError:
        site_packages = []
        try:
            from django.conf import settings as _dj
            site_packages.append(os.path.join(_dj.MEDIA_ROOT, "plugins", "findgcp", "site-packages"))
        except Exception:
            pass
        site_packages.append("/webodm/app/media/plugins/findgcp/site-packages")
        for _sp in site_packages:
            if os.path.isdir(_sp) and _sp not in sys.path:
                sys.path.insert(0, _sp)
        try:
            cv2, aruco = _load_cv2()
        except ImportError:
            return {'error': "OpenCV with the ArUco module (cv2.aruco) is not "
                             "available in the worker. On a single-host WebODM it is "
                             "installed automatically when the plugin is enabled "
                             "(after a webapp restart); on a distributed/server "
                             "setup, add opencv-contrib to the worker image (see "
                             "the plugin's docker/ directory) or run: docker exec "
                             "worker pip install opencv-contrib-python-headless"}

    # --- Find-GCP color LUT for --adjust (gcp_find.py LUT_IN / LUT_OUT) ---
    LUT_IN = [0, 158, 216, 255]
    LUT_OUT = [0, 22, 80, 176]

    def parse_coords(text):
        """id easting northing elevation -> {id: (e, n, z)}.

        - the id must be a plain integer (``1.9`` is rejected, not truncated)
        - coordinates must be finite numbers (nan/inf rejected)
        - duplicate ids keep the first occurrence and are reported
        """
        coords = {}
        skipped = []
        duplicates = []
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.replace(',', ' ').split()
            if len(parts) < 4:
                skipped.append(lineno)
                continue
            try:
                marker_id = int(parts[0])          # rejects "1.9"
                vals = [float(x) for x in parts[1:4]]
            except ValueError:
                skipped.append(lineno)
                continue
            if not all(math.isfinite(v) for v in vals):  # rejects nan/inf
                skipped.append(lineno)
                continue
            if marker_id in coords:
                duplicates.append(marker_id)
                continue
            coords[marker_id] = (parts[1], parts[2], parts[3])
        return coords, skipped, duplicates

    def declared_epsgs(text):
        """CRS code(s) the coordinate file declares about itself.

        Scans comment (``#``) lines for ``EPSG:xxxx`` tokens (the header the
        fixture and the workflow docs write, e.g. ``# id easting northing
        elevation  (EPSG:28191)``). Returns the sorted list of distinct 4-6
        digit codes found — empty if none. Only comment lines are scanned, so a
        data row never trips this. The caller decides: zero = nothing to check,
        one = validate against the run, several = ambiguous (an error, since a
        contradictory header is stronger evidence of a config problem than none).
        """
        import re
        found = set()
        for raw in text.splitlines():
            line = raw.strip()
            if not line.startswith('#'):
                continue
            for m in re.finditer(r'EPSG[:\s]*([0-9]{4,6})', line, re.IGNORECASE):
                found.add(int(m.group(1)))
        return sorted(found)

    def build_dictionary(dict_id):
        if int(dict_id) == 99:
            if hasattr(aruco, 'extendDictionary'):
                return aruco.extendDictionary(32, 3)
            return aruco.Dictionary_create(32, 3)
        if hasattr(aruco, 'getPredefinedDictionary'):
            return aruco.getPredefinedDictionary(int(dict_id))
        return aruco.Dictionary_get(int(dict_id))

    def build_params(minrate, ignore):
        if hasattr(aruco, 'DetectorParameters'):
            params = aruco.DetectorParameters()
        else:
            params = aruco.DetectorParameters_create()
        params.minMarkerPerimeterRate = float(minrate)
        params.perspectiveRemoveIgnoredMarginPerCell = float(ignore)
        return params

    # --- parse coordinates ---
    coords, skipped_lines, duplicate_ids = parse_coords(coords_text)
    if not coords:
        return {'error': 'No valid GCP coordinates parsed '
                         '(expected per line: id easting northing elevation; '
                         'id must be an integer, coordinates finite numbers).'}

    # --- guard against the wrong CRS (silent-but-deadly georeferencing error) ---
    # The server otherwise only range-checks the EPSG number and writes it through
    # verbatim, so e.g. EPSG:28191 mistakenly chosen for ITM coordinates would
    # produce a plausible-looking but wrong georeference. If the coordinate file
    # declares its own CRS, validate it: a single declared code must match the
    # run; several conflicting codes are an outright error (a contradictory
    # header is stronger evidence of a config problem than no header at all, so
    # we fail closed rather than skip the check).
    file_epsgs = declared_epsgs(coords_text)
    if len(file_epsgs) > 1:
        return {'error': 'Ambiguous CRS: the coordinate file declares conflicting '
                         'EPSG codes {}. Remove the contradictory header(s) so the '
                         'coordinate CRS is unambiguous, then re-run.'.format(file_epsgs)}
    if len(file_epsgs) == 1 and file_epsgs[0] != int(epsg):
        return {'error': 'CRS mismatch: the coordinate file declares '
                         'EPSG:{} but this run is set to EPSG:{}. Fix the EPSG '
                         'field (or the file header) so they agree — this guards '
                         'against georeferencing with the wrong CRS.'.format(
                             file_epsgs[0], int(epsg))}

    # --- detector setup ---
    try:
        adict = build_dictionary(dict_id)
    except Exception as e:  # noqa: BLE001 - surfaced to the UI
        return {'error': 'Invalid ArUco dictionary {}: {}'.format(dict_id, e)}

    params = build_params(minrate, ignore)
    detector = aruco.ArucoDetector(adict, params) if hasattr(aruco, 'ArucoDetector') else None
    lut = np.interp(np.arange(0, 256), LUT_IN, LUT_OUT).astype(np.uint8)

    # --- detect ---
    gcps = []          # (pixel_x, pixel_y, image_basename, marker_id)
    found = {}         # marker_id -> number of images it appears on
    unreadable = 0
    for path in image_paths:
        frame = cv2.imread(path)
        if frame is None:
            unreadable += 1
            continue
        if adjust:
            gray = cv2.cvtColor(cv2.LUT(frame, lut), cv2.COLOR_BGR2GRAY)
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if detector is not None:
            corners, ids, _ = detector.detectMarkers(gray)
        else:
            corners, ids, _ = aruco.detectMarkers(gray, adict, parameters=params)

        if ids is None:
            continue

        base = os.path.basename(path)
        for i in range(len(ids)):
            marker_id = int(ids[i][0])
            x = int(round(float(np.average(corners[i][0][:, 0]))))
            y = int(round(float(np.average(corners[i][0][:, 1]))))
            gcps.append((x, y, base, marker_id))
            found[marker_id] = found.get(marker_id, 0) + 1

    matched = [g for g in gcps if g[3] in coords]
    if not matched:
        return {'error': 'No detected markers match the coordinate file. '
                         'Detected IDs: {}. Coordinate IDs: {}. '
                         'Check the dictionary, minrate and image quality.'.format(
                             sorted(found.keys()) or 'none', sorted(coords.keys()))}

    # --- build ODM gcp_list.txt as text ---
    lines = ['EPSG:{}'.format(int(epsg))]
    for (x, y, base, marker_id) in matched:
        e, n, z = coords[marker_id]
        lines.append('{} {} {} {} {} {} {}'.format(e, n, z, x, y, base, marker_id))
    gcp_list = '\n'.join(lines) + '\n'

    matched_ids = sorted({g[3] for g in matched})
    summary = {
        'images_total': len(image_paths),
        'images_unreadable': unreadable,
        'detections': len(matched),
        'unique_markers': len(matched_ids),
        'markers_per_id': {str(m): found[m] for m in matched_ids},
        'weak_markers': [m for m in matched_ids if found.get(m, 0) < 3],
        'unmatched_ids': sorted(set(found.keys()) - set(coords.keys())),
        'coord_skipped_lines': skipped_lines,
        'coord_duplicate_ids': sorted(set(duplicate_ids)),
        'epsg': int(epsg),
        'gcp_list': gcp_list,
    }
    return {'output': summary}
