# SPDX-License-Identifier: MIT
"""Reusable marker-sheet rendering primitives (print-ready ArUco/AprilTag PDFs).

GUI-/WebODM-free, shared by the Signa WebODM plugin (one fit-to-page marker per
sheet, size is a *result*) and Mensura (one marker per sheet at an *exact*
physical mm size — the scale reference). The layout decision (how big the marker
is) stays with the caller; everything generic lives here:

- marker raster generation (OpenCV-version compatible),
- center aiming aid (cross / cross+halo / dot+ring),
- human-readable labels (Pillow primary, OpenCV Hershey fallback),
- a per-page detectability self-check,
- a minimal built-in PDF writer (one Flate-compressed RGB image per page),
- ``compose_page`` which assembles a full BGR page given a marker pixel size.

Module-level imports are kept to pure stdlib + the dictionary tables, so callers
that only need the geometry constants (e.g. parameter validation) can import this
without pulling in cv2/numpy/Pillow. All heavy imports are lazy, inside functions.
"""

import zlib

from .dictionaries import DICT_CHOICES, load_aruco, make_dictionary

# --- Geometry / appearance constants ----------------------------------------

DPI = 300
GRAY = 170          # "white" value of the gray variant (burnt-in prevention)
RED = (30, 30, 220)  # BGR — aiming-aid color
QUIET_MODULES = 1   # white quiet zone around the marker, in marker modules

# Aiming-aid geometry (mm). Kept thin/small on purpose: red reads dark
# (~76/255) in grayscale, so a fat mark on a white module could flip a bit
# during the detector's cell sampling. The per-page self-check would catch that,
# but these sizes are chosen so it never triggers.
CROSS_SPAN_MM = 10
CROSS_WIDTH_MM = 1.0
HALO_WIDTH_MM = 3.0
RING_RADIUS_MM = 4.0
DOT_RADIUS_MM = 1.5

# Cap height of the big id number under the marker.
ID_HEIGHT_MM = 30

# DIN A page formats, portrait (width, height) in mm.
PAGE_SIZES_MM = {
    'a6': (105, 148),
    'a5': (148, 210),
    'a4': (210, 297),
    'a3': (297, 420),
    'a2': (420, 594),
}

# Center aiming aids (put a total station / laser disto target on the exact
# marker center). The labels live in the settings templates as {% trans %}
# strings so this module stays Django-free.
MARKER_AIDS = ('none', 'cross', 'cross_halo', 'dot_ring')

# Ids per dictionary, verified against opencv-contrib 4.10/4.13 (bytesList row
# counts). Lets validation reject an out-of-range id without importing cv2;
# build_*_pdf re-checks against the real dictionary as belt and braces.
DICT_CAPACITY = {
    0: 50, 1: 100, 2: 250, 3: 1000,         # 4x4
    4: 50, 5: 100, 6: 250, 7: 1000,         # 5x5
    8: 50, 9: 100, 10: 250, 11: 1000,       # 6x6
    12: 50, 13: 100, 14: 250, 15: 1000,     # 7x7
    16: 1024,                               # ARUCO_ORIGINAL
    17: 30, 18: 35, 19: 2320, 20: 587,      # AprilTag 16h5/25h9/36h10/36h11
    99: 32,                                 # legacy custom 3x3
}

# One page per marker; keeps a synchronous request (and the PDF) bounded.
MAX_MARKER_PAGES = 100

# ASCII-safe dictionary names for the printed label (cv2.putText is
# Hershey/ASCII only, so e.g. "custom 3×3" must become "custom 3x3").
DICT_LABELS = {int(v): label.split('— ', 1)[-1].replace('×', 'x')
               for v, label in DICT_CHOICES}


def mm_to_px(mm, dpi=DPI):
    """Millimetres to whole pixels at ``dpi``."""
    return int(round(mm / 25.4 * dpi))


def marker_capacity(adict):
    """Number of distinct markers a built dictionary holds."""
    return int(adict.bytesList.shape[0])


def render_marker_raster(adict, marker_id, side_px, white=255, aruco=None):
    """A pure-binary marker raster (``white`` or 0), ``side_px`` square."""
    import numpy as np
    if aruco is None:
        _, aruco = load_aruco()
    if hasattr(aruco, 'generateImageMarker'):
        marker = aruco.generateImageMarker(adict, marker_id, side_px)
    else:
        marker = aruco.drawMarker(adict, marker_id, side_px)
    return np.where(marker > 127, np.uint8(white), np.uint8(0))


def draw_aiming_aid(cv2, page, cx, cy, aid, white):
    """Overlay the center aiming aid on a BGR page at ``(cx, cy)`` in place."""
    bg = (int(white),) * 3
    if aid in ('cross', 'cross_halo'):
        arm = mm_to_px(CROSS_SPAN_MM) // 2
        if aid == 'cross_halo':
            halo = max(1, mm_to_px(HALO_WIDTH_MM))
            cv2.line(page, (cx - arm, cy), (cx + arm, cy), bg, halo)
            cv2.line(page, (cx, cy - arm), (cx, cy + arm), bg, halo)
        w = max(1, mm_to_px(CROSS_WIDTH_MM))
        cv2.line(page, (cx - arm, cy), (cx + arm, cy), RED, w)
        cv2.line(page, (cx, cy - arm), (cx, cy + arm), RED, w)
    elif aid == 'dot_ring':
        cv2.circle(page, (cx, cy), mm_to_px(RING_RADIUS_MM), bg, -1)
        cv2.circle(page, (cx, cy), mm_to_px(DOT_RADIUS_MM), RED, -1)


def _draw_labels_pil(np, page, x, y, side, page_w, page_h, meta, big):
    """Draw the labels with Pillow (DejaVu Sans). Returns the new BGR array, or
    None if Pillow is unavailable (caller falls back to Hershey)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    img = Image.fromarray(page[:, :, ::-1])  # BGR -> RGB
    draw = ImageDraw.Draw(img)
    avail_w = page_w - 2 * mm_to_px(10)

    def fit(text, size, stroke=0, min_size=mm_to_px(2)):
        while size > min_size:
            font = ImageFont.load_default(size=size)
            if draw.textlength(text, font=font) + 2 * stroke <= avail_w:
                return font
            size -= max(1, size // 12)
        return ImageFont.load_default(size=min_size)

    meta_font = fit(meta, mm_to_px(6))
    mw = draw.textlength(meta, font=meta_font)
    mtop, mbot = meta_font.getbbox(meta)[1], meta_font.getbbox(meta)[3]
    meta_y = y + side + mm_to_px(5)
    draw.text(((page_w - mw) / 2, meta_y), meta, fill=0, font=meta_font)

    # Big bare number, mildly bold via stroke; shrink to the room left below the
    # meta line (small pages / tall dictionaries) and never wider than the page.
    big_y = meta_y + (mbot - mtop) + mm_to_px(6)
    stroke = mm_to_px(0.8)
    space = page_h - big_y - mm_to_px(6)  # bottom margin
    big_font = fit(big, min(mm_to_px(ID_HEIGHT_MM), max(mm_to_px(8), space)), stroke)
    bw = draw.textlength(big, font=big_font) + 2 * stroke
    draw.text(((page_w - bw) / 2 + stroke, big_y), big, fill=0, font=big_font,
              stroke_width=stroke, stroke_fill=0)

    return np.asarray(img)[:, :, ::-1].copy()  # RGB -> BGR


def _draw_labels_cv2(cv2, page, x, y, side, page_w, page_h, meta, big):
    """Hershey fallback (used only when Pillow is unavailable)."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    avail_w = page_w - 2 * mm_to_px(10)

    (mw1, _mh1), _ = cv2.getTextSize(meta, font, 1.0, 2)
    meta_scale = min(1.2, avail_w / max(mw1, 1))
    meta_th = max(2, int(round(2 * meta_scale)))
    (mw, mh), _ = cv2.getTextSize(meta, font, meta_scale, meta_th)
    meta_baseline = y + side + mm_to_px(5) + mh
    cv2.putText(page, meta, ((page_w - mw) // 2, meta_baseline),
                font, meta_scale, (0, 0, 0), meta_th, cv2.LINE_AA)

    (bw1, bh1), _ = cv2.getTextSize(big, font, 1.0, 3)
    space = page_h - meta_baseline - mm_to_px(5 + 6)
    big_scale = min(mm_to_px(ID_HEIGHT_MM), max(mm_to_px(8), space)) / max(bh1, 1)
    big_scale = min(big_scale, avail_w / max(bw1, 1))
    big_th = max(3, int(round(4 * big_scale)))
    (bw, bh), _ = cv2.getTextSize(big, font, big_scale, big_th)
    cv2.putText(page, big, ((page_w - bw) // 2, meta_baseline + mm_to_px(5) + bh),
                font, big_scale, (0, 0, 0), big_th, cv2.LINE_AA)


def draw_labels(np, cv2, page, x, y, side, page_w, page_h, meta, big):
    """Draw the meta line + big id number; returns the resulting BGR page."""
    drawn = _draw_labels_pil(np, page, x, y, side, page_w, page_h, meta, big)
    if drawn is None:
        _draw_labels_cv2(cv2, page, x, y, side, page_w, page_h, meta, big)
        return page
    return drawn


def is_detectable(cv2, aruco, adict, page, marker_id):
    """True iff the rendered page contains exactly the one expected marker."""
    gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
    if hasattr(aruco, 'ArucoDetector'):
        corners, ids, _ = aruco.ArucoDetector(adict, aruco.DetectorParameters()).detectMarkers(gray)
    else:
        corners, ids, _ = aruco.detectMarkers(gray, adict, parameters=aruco.DetectorParameters_create())
    return ids is not None and len(ids) == 1 and int(ids[0][0]) == int(marker_id)


def compose_page(cv2, aruco, adict, marker_id, *, page_key, marker_side_px,
                 gray, aid, meta, big):
    """Assemble one portrait BGR page at :data:`DPI`.

    The caller decides ``marker_side_px`` (fit-to-page or exact-mm) and supplies
    the ``meta`` line and ``big`` number text; everything else is generic.
    """
    import numpy as np

    white = GRAY if gray else 255
    page_w_mm, page_h_mm = PAGE_SIZES_MM[page_key]
    page_w, page_h = mm_to_px(page_w_mm), mm_to_px(page_h_mm)
    side = int(marker_side_px)

    marker = render_marker_raster(adict, marker_id, side, white=white, aruco=aruco)
    canvas = np.full((page_h, page_w), np.uint8(white))
    x = (page_w - side) // 2
    y = (page_h - side) // 2 - mm_to_px(8)  # nudge up, label goes below
    canvas[y:y + side, x:x + side] = marker
    page = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)

    draw_aiming_aid(cv2, page, x + side // 2, y + side // 2, aid, white)
    return draw_labels(np, cv2, page, x, y, side, page_w, page_h, meta, big)


def pages_to_pdf(pages, page_mm):
    """Minimal PDF writer: one Flate-compressed RGB image per page.

    ``pages`` is a list of (deflated_rgb_bytes, width_px, height_px). Object
    layout: 1 = catalog, 2 = page tree, then (page, contents, image) triples.
    """
    w_pt = page_mm[0] * 72.0 / 25.4
    h_pt = page_mm[1] * 72.0 / 25.4

    objects = []  # 1-based bodies, in object-number order

    def ref(n):
        return "{} 0 R".format(n)

    first_page_obj = 3
    kids = " ".join(ref(first_page_obj + 3 * i) for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append("<< /Type /Pages /Kids [ {} ] /Count {} >>".format(
        kids, len(pages)).encode("ascii"))

    for i, (deflated, w_px, h_px) in enumerate(pages):
        page_n = first_page_obj + 3 * i
        objects.append((
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {:.2f} {:.2f}] "
            "/Resources << /XObject << /Im0 {} >> >> /Contents {} >>".format(
                w_pt, h_pt, ref(page_n + 2), ref(page_n + 1))).encode("ascii"))
        content = "q {:.2f} 0 0 {:.2f} 0 0 cm /Im0 Do Q".format(w_pt, h_pt).encode("ascii")
        objects.append("<< /Length {} >>\nstream\n".format(len(content)).encode("ascii")
                       + content + b"\nendstream")
        head = ("<< /Type /XObject /Subtype /Image /Width {} /Height {} "
                "/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
                "/Length {} >>\nstream\n".format(w_px, h_px, len(deflated)))
        objects.append(head.encode("ascii") + deflated + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += "{} 0 obj\n".format(n).encode("ascii") + body + b"\nendobj\n"
    xref_at = len(out)
    out += "xref\n0 {}\n".format(len(objects) + 1).encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += "{:010d} 00000 n \n".format(off).encode("ascii")
    out += ("trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{}\n%%EOF\n".format(
        len(objects) + 1, xref_at)).encode("ascii")
    return bytes(out)


def compress_page(cv2, page):
    """BGR page → ``(flate_rgb_bytes, width_px, height_px)`` for ``pages_to_pdf``."""
    rgb = cv2.cvtColor(page, cv2.COLOR_BGR2RGB)
    return zlib.compress(rgb.tobytes(), 6), page.shape[1], page.shape[0]
