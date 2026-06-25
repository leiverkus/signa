# SPDX-License-Identifier: MIT
"""Tests for the marker-sheet rendering primitives (signa_core.markers)."""
import pytest

from signa_core import markers
from signa_core.dictionaries import load_aruco, make_dictionary

try:
    load_aruco()
    HAVE_CV2 = True
except ImportError:  # pragma: no cover
    HAVE_CV2 = False

cv2_required = pytest.mark.skipif(not HAVE_CV2, reason="opencv-contrib not installed")


def test_mm_to_px_exact():
    # 50 mm at 300 DPI = 50 / 25.4 * 300 = 590.55 -> 591 px
    assert markers.mm_to_px(50) == 591
    assert markers.mm_to_px(0) == 0
    assert markers.mm_to_px(25.4) == 300


def test_dict_capacity_table_matches_choices():
    # every offered dictionary id has a capacity entry
    ids = {int(v) for v, _ in markers.DICT_LABELS.items()}
    assert ids == set(markers.DICT_CAPACITY)


@cv2_required
def test_marker_capacity_matches_table():
    cv2, aruco = load_aruco()
    for dict_id in (0, 1, 16):
        adict = make_dictionary(dict_id, aruco)
        assert markers.marker_capacity(adict) == markers.DICT_CAPACITY[dict_id]


@cv2_required
def test_render_marker_raster_shape_and_binary():
    import numpy as np
    cv2, aruco = load_aruco()
    adict = make_dictionary(1, aruco)
    side = markers.mm_to_px(50)
    raster = markers.render_marker_raster(adict, 0, side, white=255, aruco=aruco)
    assert raster.shape == (side, side)
    assert set(np.unique(raster)).issubset({0, 255})


@cv2_required
@pytest.mark.parametrize("aid", ["none", "cross", "cross_halo", "dot_ring"])
def test_compose_page_exact_mm_round_trips(aid):
    """An exact-mm marker page must be detectable as exactly its own id."""
    cv2, aruco = load_aruco()
    adict = make_dictionary(1, aruco)
    side = markers.mm_to_px(50)
    page = markers.compose_page(
        cv2, aruco, adict, 7, page_key="a4", marker_side_px=side,
        gray=False, aid=aid, meta="DICT_4X4_100  -  exact 50 mm  -  top ^", big="7")
    page_w = markers.mm_to_px(markers.PAGE_SIZES_MM["a4"][0])
    page_h = markers.mm_to_px(markers.PAGE_SIZES_MM["a4"][1])
    assert page.shape == (page_h, page_w, 3)
    assert markers.is_detectable(cv2, aruco, adict, page, 7)


@cv2_required
def test_pages_to_pdf_structure():
    cv2, aruco = load_aruco()
    adict = make_dictionary(1, aruco)
    side = markers.mm_to_px(30)
    pdf_pages = []
    for mid in (0, 1):
        page = markers.compose_page(
            cv2, aruco, adict, mid, page_key="a6", marker_side_px=side,
            gray=False, aid="cross", meta="m", big=str(mid))
        assert markers.is_detectable(cv2, aruco, adict, page, mid)
        pdf_pages.append(markers.compress_page(cv2, page))
    pdf = markers.pages_to_pdf(pdf_pages, markers.PAGE_SIZES_MM["a6"])
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert b"/Count 2" in pdf
