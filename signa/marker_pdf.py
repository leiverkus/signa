"""Print-ready ArUco marker sheets as a PDF download (Signa).

Thin layout layer over :mod:`signa_core.markers`: one DIN-A page per marker id,
the marker sized to **fill the page** (keeping a one-module quiet zone) — the
printed size is a *result*, shown in the meta line. The generic machinery
(marker raster, aiming aid, labels, self-check, PDF writer) lives in signa-core;
only the fit-to-page sizing is Signa-specific. (Mensura uses the same primitives
with an exact-mm sizing instead.)

Django-free so it can be unit-tested in CI without a running WebODM. OpenCV is
imported lazily with the same site-packages fallback gcp_detect uses.
"""

import os
import sys

from signa_core import load_aruco, make_dictionary
from signa_core import markers as _m

# Re-exported for callers/tests that referenced these via this module.
DPI = _m.DPI
PAGE_SIZES_MM = _m.PAGE_SIZES_MM
DICT_LABELS = _m.DICT_LABELS

_ERR_NO_CV2 = ("OpenCV with the ArUco module (cv2.aruco) is not available in "
               "the webapp. It is installed automatically when the plugin is "
               "enabled (after a webapp restart); see the plugin README.")
_ERR_CAPACITY = 'Marker id range exceeds the capacity of the selected dictionary.'
_ERR_SELF_CHECK = ('Marker self-check failed: a rendered page was not detectable. '
                   'Try a larger page size or a different center aiming aid.')


def _load_cv2():
    """cv2 + aruco via signa-core, retrying with the plugin's site-packages dir.

    The site-packages fallback covers WebODM's per-plugin install layout where
    OpenCV is not on the default path; the actual import lives in signa-core.
    """
    try:
        return load_aruco()
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
            return load_aruco()
        except ImportError:
            return None, None


def _px(mm):
    return _m.mm_to_px(mm)


def _fit_page_side(adict, page_w):
    """Largest marker side (px) that keeps a one-module quiet zone in the page,
    rounded down to whole pixels per module for crisp edges."""
    modules = int(adict.markerSize) + 2  # bits + black border
    side = page_w * modules // (modules + 2 * _m.QUIET_MODULES)
    return side - side % modules


def _render_page(cv2, aruco, adict, marker_id, page_key, gray, aid, dict_id):
    """One portrait page as a BGR uint8 array at DPI (marker fills the page)."""
    page_w = _m.mm_to_px(_m.PAGE_SIZES_MM[page_key][0])
    side = _fit_page_side(adict, page_w)
    meta = "{}  -  {} mm  -  top ^".format(
        _m.DICT_LABELS[int(dict_id)], int(round(side / _m.DPI * 25.4)))
    return _m.compose_page(cv2, aruco, adict, marker_id, page_key=page_key,
                           marker_side_px=side, gray=gray, aid=aid,
                           meta=meta, big=str(marker_id))


def build_marker_pdf(dict_id, id_from, id_to, page='a4', gray=False, aid='cross'):
    """Build the marker-sheet PDF.

    :returns: ``(pdf_bytes, None)`` on success, ``(None, error_message)`` on
        failure (error strings are msgids in the de catalog, like params.py).
    """
    cv2, aruco = _load_cv2()
    if cv2 is None:
        return None, _ERR_NO_CV2

    adict = make_dictionary(dict_id, aruco)
    if id_to >= _m.marker_capacity(adict):
        return None, _ERR_CAPACITY

    pages = []
    for marker_id in range(id_from, id_to + 1):
        rendered = _render_page(cv2, aruco, adict, marker_id, page, gray, aid, dict_id)
        if not _m.is_detectable(cv2, aruco, adict, rendered, marker_id):
            return None, _ERR_SELF_CHECK
        # Compress immediately and drop the array — an A2 page is ~100 MB raw.
        pages.append(_m.compress_page(cv2, rendered))

    return _m.pages_to_pdf(pages, _m.PAGE_SIZES_MM[page]), None
