"""Print-ready ArUco marker sheets as a PDF download.

Renders one DIN-A page per marker id: the marker centered with a one-module
quiet zone, an optional red center aiming aid (the marker center is the point
Signa reports, so that is where the total station / disto target belongs)
and a human-readable label. Every page is run through the ArUco detector
before it is embedded — a sheet that would not be detectable in the field can
never leave the server.

Django-free so it can be unit-tested in CI without a running WebODM. OpenCV is
imported lazily with the same site-packages fallback gcp_detect uses: in the
webapp process WebODM puts the plugin's site-packages on sys.path when the
plugin loads, but a clear error beats an ImportError if that ever fails.

The PDF itself is assembled by a minimal built-in writer (one Flate-compressed
RGB image per page) — deliberately no PDF library dependency.
"""

import os
import sys
import zlib

try:
    from .params import PAGE_SIZES_MM, DICT_CHOICES
except ImportError:
    # Loaded standalone (the test suite loads modules via importlib, because
    # importing the signa package would import WebODM).
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        "signa_params", os.path.join(os.path.dirname(os.path.abspath(__file__)), "params.py"))
    _params = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_params)
    PAGE_SIZES_MM = _params.PAGE_SIZES_MM
    DICT_CHOICES = _params.DICT_CHOICES

DPI = 300
GRAY = 170          # "white" value of the gray variant (burnt-in prevention)
RED = (30, 30, 220)  # BGR — aiming-aid color
QUIET_MODULES = 1   # white quiet zone around the marker, in marker modules

# Aiming-aid geometry (mm). Kept thin/small on purpose: red reads dark
# (~76/255) in grayscale, so a fat mark on a white module could flip a bit
# during the detector's cell sampling. The per-page self-check would catch
# that, but these sizes are chosen so it never triggers.
CROSS_SPAN_MM = 10
CROSS_WIDTH_MM = 1.0
HALO_WIDTH_MM = 3.0
RING_RADIUS_MM = 4.0
DOT_RADIUS_MM = 1.5

# Cap height of the big id number under the marker. Sized to be readable from
# standing height with the sheet on the ground (shrunk when a small page
# leaves less room).
ID_HEIGHT_MM = 30

# ASCII-safe dictionary names for the printed label (cv2.putText is
# Hershey/ASCII only, so e.g. "custom 3×3" must become "custom 3x3").
DICT_LABELS = {int(v): label.split('— ', 1)[-1].replace('×', 'x')
               for v, label in DICT_CHOICES}

_ERR_NO_CV2 = ("OpenCV with the ArUco module (cv2.aruco) is not available in "
               "the webapp. It is installed automatically when the plugin is "
               "enabled (after a webapp restart); see the plugin README.")
_ERR_CAPACITY = 'Marker id range exceeds the capacity of the selected dictionary.'
_ERR_SELF_CHECK = ('Marker self-check failed: a rendered page was not detectable. '
                   'Try a larger page size or a different center aiming aid.')


def _load_cv2():
    """Import cv2 + aruco, retrying with the plugin's site-packages dir."""
    def _import():
        import cv2 as _cv2
        from cv2 import aruco as _aruco
        return _cv2, _aruco

    try:
        return _import()
    except ImportError:
        site_packages = []
        try:
            from django.conf import settings as _dj
            site_packages.append(os.path.join(_dj.MEDIA_ROOT, "plugins", "signa", "site-packages"))
        except Exception:
            pass
        site_packages.append("/webodm/app/media/plugins/signa/site-packages")
        for sp in site_packages:
            if os.path.isdir(sp) and sp not in sys.path:
                sys.path.insert(0, sp)
        try:
            return _import()
        except ImportError:
            return None, None


def _build_dictionary(aruco, dict_id):
    if int(dict_id) == 99:
        if hasattr(aruco, 'extendDictionary'):
            return aruco.extendDictionary(32, 3)
        return aruco.Dictionary_create(32, 3)
    if hasattr(aruco, 'getPredefinedDictionary'):
        return aruco.getPredefinedDictionary(int(dict_id))
    return aruco.Dictionary_get(int(dict_id))


def _px(mm):
    return int(round(mm / 25.4 * DPI))


def _render_page(cv2, aruco, adict, marker_id, page_key, gray, aid, dict_id):
    """One portrait page as a BGR uint8 array at DPI."""
    import numpy as np

    white = GRAY if gray else 255
    page_w_mm, page_h_mm = PAGE_SIZES_MM[page_key]
    page_w, page_h = _px(page_w_mm), _px(page_h_mm)

    # Largest marker that keeps a one-module quiet zone inside the page width,
    # rounded down to whole pixels per module for crisp edges.
    modules = int(adict.markerSize) + 2  # bits + black border
    side = page_w * modules // (modules + 2 * QUIET_MODULES)
    side -= side % modules

    if hasattr(aruco, 'generateImageMarker'):
        marker = aruco.generateImageMarker(adict, marker_id, side)
    else:
        marker = aruco.drawMarker(adict, marker_id, side)
    marker = np.where(marker > 127, np.uint8(white), np.uint8(0))

    canvas = np.full((page_h, page_w), np.uint8(white))
    x = (page_w - side) // 2
    y = (page_h - side) // 2 - _px(8)  # nudge up, label goes below
    canvas[y:y + side, x:x + side] = marker
    page = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)

    cx, cy = x + side // 2, y + side // 2
    bg = (int(white),) * 3
    if aid in ('cross', 'cross_halo'):
        arm = _px(CROSS_SPAN_MM) // 2
        if aid == 'cross_halo':
            halo = max(1, _px(HALO_WIDTH_MM))
            cv2.line(page, (cx - arm, cy), (cx + arm, cy), bg, halo)
            cv2.line(page, (cx, cy - arm), (cx, cy + arm), bg, halo)
        w = max(1, _px(CROSS_WIDTH_MM))
        cv2.line(page, (cx - arm, cy), (cx + arm, cy), RED, w)
        cv2.line(page, (cx, cy - arm), (cx, cy + arm), RED, w)
    elif aid == 'dot_ring':
        cv2.circle(page, (cx, cy), _px(RING_RADIUS_MM), bg, -1)
        cv2.circle(page, (cx, cy), _px(DOT_RADIUS_MM), RED, -1)

    # Meta line directly under the marker, big id number below it. Drawn with
    # Pillow (a WebODM dependency) so the typeface matches the standalone
    # markers/make_markers.py generator; falls back to OpenCV's Hershey font if
    # Pillow is somehow unavailable.
    meta = "{}  -  {} mm  -  top ^".format(
        DICT_LABELS[int(dict_id)], int(round(side / DPI * 25.4)))
    big = str(marker_id)
    drawn = _draw_labels_pil(np, page, x, y, side, page_w, page_h, meta, big)
    if drawn is None:
        _draw_labels_cv2(cv2, page, x, y, side, page_w, page_h, meta, big)
        return page
    return drawn


def _draw_labels_pil(np, page, x, y, side, page_w, page_h, meta, big):
    """Draw the labels with Pillow (DejaVu Sans). Returns the new BGR array, or
    None if Pillow is unavailable (caller falls back to Hershey)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    img = Image.fromarray(page[:, :, ::-1])  # BGR -> RGB
    draw = ImageDraw.Draw(img)
    avail_w = page_w - 2 * _px(10)

    def fit(text, size, stroke=0, min_size=_px(2)):
        while size > min_size:
            font = ImageFont.load_default(size=size)
            if draw.textlength(text, font=font) + 2 * stroke <= avail_w:
                return font
            size -= max(1, size // 12)
        return ImageFont.load_default(size=min_size)

    meta_font = fit(meta, _px(6))
    mw = draw.textlength(meta, font=meta_font)
    mtop, mbot = meta_font.getbbox(meta)[1], meta_font.getbbox(meta)[3]
    meta_y = y + side + _px(5)
    draw.text(((page_w - mw) / 2, meta_y), meta, fill=0, font=meta_font)

    # Big bare number, mildly bold via stroke; shrink to the room left below the
    # meta line (small pages / tall dictionaries) and never wider than the page.
    big_y = meta_y + (mbot - mtop) + _px(6)
    stroke = _px(0.8)
    space = page_h - big_y - _px(6)  # bottom margin
    big_font = fit(big, min(_px(ID_HEIGHT_MM), max(_px(8), space)), stroke)
    bw = draw.textlength(big, font=big_font) + 2 * stroke
    draw.text(((page_w - bw) / 2 + stroke, big_y), big, fill=0, font=big_font,
              stroke_width=stroke, stroke_fill=0)

    return np.asarray(img)[:, :, ::-1].copy()  # RGB -> BGR


def _draw_labels_cv2(cv2, page, x, y, side, page_w, page_h, meta, big):
    """Hershey fallback (used only when Pillow is unavailable)."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    avail_w = page_w - 2 * _px(10)

    (mw1, _mh1), _ = cv2.getTextSize(meta, font, 1.0, 2)
    meta_scale = min(1.2, avail_w / max(mw1, 1))
    meta_th = max(2, int(round(2 * meta_scale)))
    (mw, mh), _ = cv2.getTextSize(meta, font, meta_scale, meta_th)
    meta_baseline = y + side + _px(5) + mh
    cv2.putText(page, meta, ((page_w - mw) // 2, meta_baseline),
                font, meta_scale, (0, 0, 0), meta_th, cv2.LINE_AA)

    (bw1, bh1), _ = cv2.getTextSize(big, font, 1.0, 3)
    space = page_h - meta_baseline - _px(5 + 6)
    big_scale = min(_px(ID_HEIGHT_MM), max(_px(8), space)) / max(bh1, 1)
    big_scale = min(big_scale, avail_w / max(bw1, 1))
    big_th = max(3, int(round(4 * big_scale)))
    (bw, bh), _ = cv2.getTextSize(big, font, big_scale, big_th)
    cv2.putText(page, big, ((page_w - bw) // 2, meta_baseline + _px(5) + bh),
                font, big_scale, (0, 0, 0), big_th, cv2.LINE_AA)


def _detectable(cv2, aruco, adict, page, marker_id):
    gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
    if hasattr(aruco, 'ArucoDetector'):
        corners, ids, _ = aruco.ArucoDetector(adict, aruco.DetectorParameters()).detectMarkers(gray)
    else:
        corners, ids, _ = aruco.detectMarkers(gray, adict, parameters=aruco.DetectorParameters_create())
    return ids is not None and len(ids) == 1 and int(ids[0][0]) == int(marker_id)


def _pdf_from_pages(pages, page_mm):
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


def build_marker_pdf(dict_id, id_from, id_to, page='a4', gray=False, aid='cross'):
    """Build the marker-sheet PDF.

    :returns: ``(pdf_bytes, None)`` on success, ``(None, error_message)`` on
        failure (error strings are msgids in the de catalog, like params.py).
    """
    cv2, aruco = _load_cv2()
    if cv2 is None:
        return None, _ERR_NO_CV2

    adict = _build_dictionary(aruco, dict_id)
    if id_to >= int(adict.bytesList.shape[0]):
        return None, _ERR_CAPACITY

    pages = []
    for marker_id in range(id_from, id_to + 1):
        rendered = _render_page(cv2, aruco, adict, marker_id, page, gray, aid, dict_id)
        if not _detectable(cv2, aruco, adict, rendered, marker_id):
            return None, _ERR_SELF_CHECK
        # Compress immediately and drop the array — an A2 page is ~100 MB raw.
        rgb = cv2.cvtColor(rendered, cv2.COLOR_BGR2RGB)
        pages.append((zlib.compress(rgb.tobytes(), 6), rendered.shape[1], rendered.shape[0]))

    return _pdf_from_pages(pages, PAGE_SIZES_MM[page]), None
