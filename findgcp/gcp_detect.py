"""
Server-side ArUco ground control point detection.

Ported from Find-GCP (https://github.com/zsiki/Find-GCP, gcp_find.py) to run
inside the WebODM worker without the external Find-GCP installation. Faithful to
the original detection behaviour:

  * dict 99   -> custom 3x3 dictionary (aruco.extendDictionary(32, 3))
  * --minrate -> DetectorParameters.minMarkerPerimeterRate
  * --ignore  -> DetectorParameters.perspectiveRemoveIgnoredMarginPerCell
  * --adjust  -> color LUT correction against overexposure (Levante sun)
  * marker image coordinate = centroid of the four corners
  * ODM output: first line "EPSG:<code>", then
    "easting northing elevation pixel_x pixel_y image_name marker_id"

The function is intentionally dependency-light at import time: cv2/numpy are
imported inside detect_gcps() so loading the plugin never requires OpenCV.
"""

# Find-GCP color LUT for --adjust (gcp_find.py LUT_IN / LUT_OUT)
LUT_IN = [0, 158, 216, 255]
LUT_OUT = [0, 22, 80, 176]


def parse_coords(coords_text):
    """Parse a GCP coordinate file body.

    Format per line: ``id easting northing elevation`` (whitespace or comma
    separated). Lines that are empty, comments (#) or non-numeric are skipped.
    Returns a dict {marker_id: (easting, northing, elevation)} with the original
    string precision preserved.
    """
    coords = {}
    for line in coords_text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.replace(',', ' ').split()
        if len(parts) < 4:
            continue
        try:
            marker_id = int(float(parts[0]))
            easting, northing, elevation = parts[1], parts[2], parts[3]
            float(easting)
            float(northing)
            float(elevation)
        except ValueError:
            continue
        coords[marker_id] = (easting, northing, elevation)
    return coords


def _build_dictionary(aruco, dict_id):
    """Return an ArUco dictionary, handling old/new OpenCV APIs and dict 99."""
    if int(dict_id) == 99:
        if hasattr(aruco, 'extendDictionary'):
            return aruco.extendDictionary(32, 3)
        return aruco.Dictionary_create(32, 3)
    if hasattr(aruco, 'getPredefinedDictionary'):
        return aruco.getPredefinedDictionary(int(dict_id))
    return aruco.Dictionary_get(int(dict_id))


def _build_params(aruco, minrate, ignore):
    if hasattr(aruco, 'DetectorParameters'):
        params = aruco.DetectorParameters()
    else:
        params = aruco.DetectorParameters_create()
    params.minMarkerPerimeterRate = float(minrate)
    params.perspectiveRemoveIgnoredMarginPerCell = float(ignore)
    return params


def detect_gcps(image_paths, coords_text, epsg, dict_id=1, minrate=0.01,
                ignore=0.33, adjust=True, task_name=None):
    """Detect ArUco GCPs and write an ODM-compatible gcp_list.txt.

    Runs in the WebODM worker via run_function_async. Returns either
    ``{'file': <path>, 'output': <summary dict>}`` or ``{'error': <message>}``.
    """
    import os
    import tempfile

    import numpy as np
    import cv2
    from cv2 import aruco

    coords = parse_coords(coords_text)
    if not coords:
        return {'error': 'No valid GCP coordinates parsed '
                         '(expected per line: id easting northing elevation).'}

    try:
        adict = _build_dictionary(aruco, dict_id)
    except Exception as e:  # noqa: BLE001 - surfaced to the UI
        return {'error': 'Invalid ArUco dictionary {}: {}'.format(dict_id, e)}

    params = _build_params(aruco, minrate, ignore)
    detector = aruco.ArucoDetector(adict, params) if hasattr(aruco, 'ArucoDetector') else None

    lut = np.interp(np.arange(0, 256), LUT_IN, LUT_OUT).astype(np.uint8)

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
        detected_ids = sorted(found.keys())
        return {'error': 'No detected markers match the coordinate file. '
                         'Detected IDs: {}. Coordinate IDs: {}. '
                         'Check --dict, --minrate and image quality.'.format(
                             detected_ids or 'none', sorted(coords.keys()))}

    tmpdir = tempfile.mkdtemp('_findgcp')
    out_path = os.path.join(tmpdir, 'gcp_list.txt')
    with open(out_path, 'w', encoding='ascii') as f:
        f.write('EPSG:{}\n'.format(int(epsg)))
        for (x, y, base, marker_id) in matched:
            easting, northing, elevation = coords[marker_id]
            f.write('{} {} {} {} {} {} {}\n'.format(
                easting, northing, elevation, x, y, base, marker_id))

    matched_ids = sorted({g[3] for g in matched})
    weak = [m for m in matched_ids if found.get(m, 0) < 3]
    summary = {
        'images_total': len(image_paths),
        'images_unreadable': unreadable,
        'detections': len(matched),
        'unique_markers': len(matched_ids),
        'markers_per_id': {str(m): found[m] for m in matched_ids},
        'weak_markers': weak,                       # appear on < 3 images
        'unmatched_ids': sorted(set(found.keys()) - set(coords.keys())),
        'epsg': int(epsg),
    }
    return {'file': out_path, 'output': summary}
