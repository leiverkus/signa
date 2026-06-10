#!/usr/bin/env python3
"""Generate a synthetic ArUco GCP test dataset — no drone flight needed.

Renders synthetic images containing ArUco markers (dict DICT_4X4_100, id 1) at
known positions, writes a matching coordinate file, and produces the
`gcp_list.txt` the plugin is expected to output (by actually running the same
detection code on the rendered images).

Usage:
    python tests/fixtures/make_aruco_fixture.py [OUTDIR]
    # default OUTDIR: tests/fixtures/dataset/

Outputs in OUTDIR:
    img1.JPG … img6.JPG       synthetic images, each with 4 of the 5 markers
    gcp_coords.txt            world coordinates: id easting northing elevation
    expected_gcp_list.txt     the gcp_list.txt detection should produce

Requires opencv-contrib-python (cv2.aruco) and numpy.

Used by tests/test_integration_opencv.py (real-OpenCV round trip) and by the
manual end-to-end test in docs/manual-test.md (upload the JPGs as a WebODM task,
upload gcp_coords.txt in the Find-GCP page, run detection, compare the download
against expected_gcp_list.txt).
"""

import importlib.util
import inspect
import os
import sys

DICT_ID = 1            # DICT_4X4_100
CANVAS = 1000
MARKER = 180
EPSG = 28191

# Fixed canvas position per marker id (the "same GCP" seen across images).
POSITIONS = {
    0: (500, 500),     # center
    1: (220, 220),     # top-left
    2: (780, 220),     # top-right
    3: (220, 780),     # bottom-left
    4: (780, 780),     # bottom-right
}

# World coordinates per marker id (id easting northing elevation), EPSG:28191.
COORDS = {
    0: ("698025.0", "3540025.0", "414.0"),
    1: ("698000.0", "3540000.0", "410.0"),
    2: ("698050.0", "3540000.0", "411.0"),
    3: ("698000.0", "3540050.0", "412.0"),
    4: ("698050.0", "3540050.0", "413.0"),
}

# 6 images; each omits one marker (rotating), so every id appears on 4-5 images
# (>= 3 — no "weak marker" warnings, 5 unique markers).
IMAGES = ["img{}.JPG".format(i + 1) for i in range(6)]


def coords_text():
    return "".join("{} {} {} {}\n".format(mid, *COORDS[mid])
                   for mid in sorted(COORDS))


def render_dataset(outdir):
    """Render the JPGs into outdir. Returns the list of image paths."""
    import numpy as np
    import cv2
    from cv2 import aruco

    os.makedirs(outdir, exist_ok=True)
    dictionary = aruco.getPredefinedDictionary(DICT_ID)

    paths = []
    for idx, name in enumerate(IMAGES):
        omit = idx % 5
        canvas = np.full((CANVAS, CANVAS, 3), 255, np.uint8)
        for mid, (cx, cy) in POSITIONS.items():
            if mid == omit:
                continue
            marker = aruco.generateImageMarker(dictionary, mid, MARKER)
            tile = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
            y0, x0 = cy - MARKER // 2, cx - MARKER // 2
            canvas[y0:y0 + MARKER, x0:x0 + MARKER] = tile
        path = os.path.join(outdir, name)
        cv2.imwrite(path, canvas)
        paths.append(path)
    return paths


def _load_detect():
    """Load detect_gcps the way the WebODM worker does (from source)."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "..", "findgcp", "gcp_detect.py")
    spec = importlib.util.spec_from_file_location("gcp_detect_std", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = inspect.getsource(mod.detect_gcps)
    ns = {}
    exec(compile(src, "worker", "exec"), ns, ns)
    return ns["detect_gcps"]


def main(outdir):
    paths = render_dataset(outdir)

    coords = coords_text()
    with open(os.path.join(outdir, "gcp_coords.txt"), "w", encoding="ascii") as f:
        f.write("# id easting northing elevation  (EPSG:{})\n".format(EPSG))
        f.write(coords)

    detect = _load_detect()
    res = detect(image_paths=paths, coords_text=coords, epsg=EPSG,
                 dict_id=DICT_ID, minrate=0.01, ignore=0.33, adjust=True)
    if "error" in res:
        print("Detection failed: {}".format(res["error"]), file=sys.stderr)
        return 1

    summary = res["output"]
    with open(os.path.join(outdir, "expected_gcp_list.txt"), "w", encoding="ascii") as f:
        f.write(summary["gcp_list"])

    print("Wrote {} images + gcp_coords.txt + expected_gcp_list.txt to {}".format(
        len(paths), outdir))
    print("Unique markers: {} | detections: {} | weak: {}".format(
        summary["unique_markers"], summary["detections"], summary["weak_markers"]))
    return 0


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "dataset")
    raise SystemExit(main(out))
