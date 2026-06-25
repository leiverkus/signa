# Changelog

All notable changes to **signa-core** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this package adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-06-25

### Added
- `signa_core.markers` — reusable, GUI-free marker-sheet rendering primitives,
  extracted from the Signa plugin's `marker_pdf.py` so both Signa (fit-to-page
  GCP markers) and Mensura (exact-mm scale markers) share one implementation:
  marker raster generation, center aiming aids, label drawing (Pillow primary,
  OpenCV/Hershey fallback), a per-page detectability self-check, `compose_page`,
  a minimal built-in PDF writer (`pages_to_pdf`), and the shared geometry tables
  (`PAGE_SIZES_MM`, `MARKER_AIDS`, `DICT_CAPACITY`, `DICT_LABELS`).
- Optional `labels` extra (`signa-core[labels]`) pulling in Pillow; without it,
  label rendering falls back to OpenCV's Hershey font.

## [0.1.0] - 2026-06-25

### Added
- Initial release: GUI-/WebODM-free ArUco detection core (`detect_markers`,
  dictionary/parameter/detector helpers, `DICT_CHOICES`/`VALID_DICTS`).
