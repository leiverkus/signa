"""
Server-side ArUco ground control point detection.

IMPORTANT - execution model:
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
            site_packages.append(os.path.join(_dj.MEDIA_ROOT, "plugins", "signa", "site-packages"))
        except Exception:
            pass
        site_packages.append("/webodm/app/media/plugins/signa/site-packages")
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

    def parse_coords(text):
        """id easting northing elevation [check] -> ({id: (e, n, z)}, check_ids).

        - the id must be a plain integer (``1.9`` is rejected, not truncated)
        - coordinates must be finite numbers (nan/inf rejected)
        - duplicate ids keep the first occurrence and are reported
        - an optional trailing ``check`` token (case-insensitive) holds that point
          out as an INDEPENDENT check point: it is excluded from the georeferencing
          solve by the Effigies node, which then reports an honest check-point RMSE.
          Without the token a point is a normal control GCP (backward compatible).
        """
        coords = {}
        check_ids = set()
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
            if len(parts) >= 5 and parts[4].lower() == 'check':
                check_ids.add(marker_id)
        return coords, check_ids, skipped, duplicates

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

    def make_dictionary(dictionary_id):
        dictionary_id = int(dictionary_id)
        if dictionary_id == 99:
            if hasattr(aruco, 'extendDictionary'):
                return aruco.extendDictionary(32, 3)
            return aruco.Dictionary_create(32, 3)
        if hasattr(aruco, 'getPredefinedDictionary'):
            return aruco.getPredefinedDictionary(dictionary_id)
        return aruco.Dictionary_get(dictionary_id)

    def make_parameters(minrate_value, ignore_value):
        if hasattr(aruco, 'DetectorParameters'):
            params = aruco.DetectorParameters()
        else:
            params = aruco.DetectorParameters_create()
        params.minMarkerPerimeterRate = float(minrate_value)
        params.perspectiveRemoveIgnoredMarginPerCell = float(ignore_value)
        return params

    def make_detector(dictionary, params):
        if hasattr(aruco, 'ArucoDetector'):
            detector = aruco.ArucoDetector(dictionary, params)
            return lambda gray: detector.detectMarkers(gray)
        return lambda gray: aruco.detectMarkers(gray, dictionary, parameters=params)

    def prepare_image(frame, enhance_contrast):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if not enhance_contrast:
            return gray
        # Local to Signa: a conservative grayscale equalization pass. It avoids
        # project-specific tone curves while helping with low-contrast marker
        # cells in flat lighting.
        if hasattr(cv2, 'equalizeHist'):
            return cv2.equalizeHist(gray)
        return gray

    def corner_center(corner_set):
        pts = np.asarray(corner_set, dtype=float).reshape(-1, 2)
        return (
            int(round(float(np.mean(pts[:, 0])))),
            int(round(float(np.mean(pts[:, 1])))),
        )

    # --- parse coordinates ---
    coords, check_ids, skipped_lines, duplicate_ids = parse_coords(coords_text)
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
        dictionary = make_dictionary(dict_id)
    except Exception as e:  # noqa: BLE001 - surfaced to the UI
        return {'error': 'Invalid ArUco dictionary {}: {}'.format(dict_id, e)}

    detect_markers = make_detector(dictionary, make_parameters(minrate, ignore))

    # --- detect ---
    gcps = []          # (pixel_x, pixel_y, image_basename, marker_id)
    found = {}         # marker_id -> number of images it appears on
    unreadable = 0
    for path in image_paths:
        frame = cv2.imread(path)
        if frame is None:
            unreadable += 1
            continue
        gray = prepare_image(frame, adjust)
        corners, ids, _ = detect_markers(gray)

        if ids is None:
            continue

        base = os.path.basename(path)
        for i in range(len(ids)):
            marker_id = int(ids[i][0])
            x, y = corner_center(corners[i])
            gcps.append((x, y, base, marker_id))
            found[marker_id] = found.get(marker_id, 0) + 1

    matched = [g for g in gcps if g[3] in coords]
    if not matched:
        return {'error': 'No detected markers match the coordinate file. '
                         'Detected IDs: {}. Coordinate IDs: {}. '
                         'Check the dictionary, minrate and image quality.'.format(
                             sorted(found.keys()) or 'none', sorted(coords.keys()))}

    # --- build ODM gcp_list.txt as text ---
    # A check point's lines end in ' check' (every image row of a check marker
    # carries it); the Effigies node holds those out of the solve and reports an
    # independent check-point RMSE. ODM ignores the token on non-Effigies nodes.
    lines = ['EPSG:{}'.format(int(epsg))]
    for (x, y, base, marker_id) in matched:
        e, n, z = coords[marker_id]
        line = '{} {} {} {} {} {} {}'.format(e, n, z, x, y, base, marker_id)
        if marker_id in check_ids:
            line += ' check'
        lines.append(line)
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
        'check_ids': sorted(check_ids & set(matched_ids)),
        'coord_skipped_lines': skipped_lines,
        'coord_duplicate_ids': sorted(set(duplicate_ids)),
        'epsg': int(epsg),
        'gcp_list': gcp_list,
    }
    return {'output': summary}
