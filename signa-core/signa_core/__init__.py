# SPDX-License-Identifier: MIT
"""signa-core — reusable ArUco marker detection for the Evidentia pipeline.

GUI-/WebODM-free OpenCV detection shared by the Signa WebODM plugin (GCP
detection) and Mensura (metric scale calibration).
"""
from . import markers
from .detect import corner_center, detect_markers, prepare_image
from .dictionaries import (
    DICT_CHOICES,
    VALID_DICTS,
    load_aruco,
    make_detector,
    make_dictionary,
    make_parameters,
)
from .markers import (
    DICT_CAPACITY,
    DICT_LABELS,
    MARKER_AIDS,
    MAX_MARKER_PAGES,
    PAGE_SIZES_MM,
    compose_page,
    compress_page,
    is_detectable,
    marker_capacity,
    mm_to_px,
    pages_to_pdf,
    render_marker_raster,
)

__version__ = "0.2.0"

__all__ = [
    "detect_markers",
    "corner_center",
    "prepare_image",
    "make_dictionary",
    "make_parameters",
    "make_detector",
    "load_aruco",
    "DICT_CHOICES",
    "VALID_DICTS",
    # marker-sheet rendering primitives (see signa_core.markers)
    "markers",
    "PAGE_SIZES_MM",
    "MARKER_AIDS",
    "DICT_CAPACITY",
    "DICT_LABELS",
    "MAX_MARKER_PAGES",
    "mm_to_px",
    "marker_capacity",
    "render_marker_raster",
    "compose_page",
    "compress_page",
    "is_detectable",
    "pages_to_pdf",
    "__version__",
]
