# Signa for WebODM

[![CI](https://github.com/leiverkus/signa-webodm-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/leiverkus/signa-webodm-plugin/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/leiverkus/signa-webodm-plugin?sort=semver)](https://github.com/leiverkus/signa-webodm-plugin/releases)
[![License: AGPL v3](https://img.shields.io/github/license/leiverkus/signa-webodm-plugin)](LICENSE)
[![WebODM ≥ 2.9.5](https://img.shields.io/badge/WebODM-%E2%89%A5%202.9.5-1f6feb.svg)](https://github.com/WebODM/WebODM)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab.svg)](https://www.python.org/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20715426.svg)](https://doi.org/10.5281/zenodo.20715426)

A [WebODM](https://github.com/WebODM/WebODM) plugin for **automatic ArUco ground
control point detection**. It detects ArUco markers in a task's images, matches
them against your measured GCP coordinates and produces an ODM-compatible
`gcp_list.txt` — directly inside WebODM, no command line required.

The detection logic uses OpenCV's ArUco module and runs server-side in the
WebODM worker. Headless/orchestrated runs can call the Signa API directly; see
[`scripts/signa-singlepass.py`](scripts/signa-singlepass.py) for a complete
client workflow.

## Install in WebODM

1. Download `signa-<version>.zip` from the
   [Releases](https://github.com/leiverkus/signa-webodm-plugin/releases) page.
2. In WebODM: **Administration → Plugins → Load Plugin (.zip)** and upload the zip.
3. Enable the plugin. A **Signa** entry appears in the main menu.
4. **Restart the web app** after every install or update
   (`docker restart webapp`). **This is required, not optional.** Uploading a
   plugin swaps the files on disk, but the running gunicorn workers keep the old
   plugin module in `sys.modules` (Python does not re-import it) — and each
   worker is independent. Without a restart you get intermittent symptoms across
   reloads: the **Signa page 404s** on some workers, and the **"Signa
   task" dashboard button appears and disappears** (workers that still run the
   old module don't inject its JavaScript). A restart re-imports the plugin in
   every worker. After restarting, hard-refresh the browser once.

### OpenCV in the worker

Detection runs in the **Celery worker**, which needs `cv2` (OpenCV). There are
two paths; the plugin tries both.

**Single-host WebODM — automatic, nothing to do.** The plugin ships a
`requirements.txt`; WebODM installs OpenCV into the plugin's per-plugin
site-packages on enable. That path is on the media volume the `webapp` and
`worker` containers **share**, so the worker imports `cv2` from it (the
detection code adds the path to `sys.path` as a fallback). `numpy` already ships
with WebODM and is reused. So on a standard single-host install, just install
the plugin and **restart the web app** — no manual step. (One exception: if the
worker process has *already* imported a base `opencv-python` without the
`aruco` contrib module, the shared-volume copy can't replace it — OpenCV's
bootstrap is not re-entrant — and detection returns the clear "fix the worker
image" error instead. Use the worker image below for that setup.)

**Distributed / server — use the worker image (robust).** If the worker runs on
a different host without the shared media volume, the above can't reach it. Bake
OpenCV into the image instead. In WebODM's compose the `worker` and `webapp`
share one image (`webodm/webodm_webapp`); extend it and use it for both:

```bash
docker build -t webodm-signa:local \
  --build-arg WEBODM_VERSION=<your-webodm-image-tag> \
  -f docker/worker.Dockerfile docker/
# then add docker/docker-compose.signa.yml as a final -f to your compose command
```

Ready-made files and steps are in [`docker/`](docker/) /
[`docker/README.md`](docker/README.md). Pin `WEBODM_VERSION` to your WebODM
image tag (no `latest`). If `cv2` is missing, detection returns a clear error
pointing here rather than failing cryptically.

### Permissions

The detect endpoint requires an authenticated user with `change_project`
permission on the task's project — enforced even for public tasks (unlike
WebODM's default `AllowAny` task views), because detection is expensive.

Each run is bound to the user who started it (recorded in the plugin's per-user
datastore) and to the task. The status/result endpoint only returns a run whose
celery id is registered to the requesting user with a matching task pk, so one
user cannot read another's result by knowing its celery id.

## Usage

The plugin offers two entry points:

**Signa menu page — standalone detection tool** (like the core `posm-gcpi`
GCP interface, but automatic):

1. Open **Signa** from the menu.
2. **Drop drone images** (or click to choose) and select the **GCP coordinate
   file** — one marker per line: `id easting northing elevation` (whitespace or
   comma separated). Optionally declare the CRS in a comment (`# … (EPSG:28191)`)
   to catch a wrong EPSG choice — see [below](#declare-the-coordinate-crs-in-the-file-recommended).
3. Set the parameters (see below) and click **Detect GCPs**.
4. Review the summary (markers, image counts, warnings) and **download
   `gcp_list.txt`**.

It runs the detection on a throwaway scratch task that is deleted again
afterwards — nothing is processed. Use this to produce or QA a `gcp_list.txt`.

**Dashboard "Signa Task" button — single pass** (detect **and** georeference
in one run): see [Single-pass](#single-pass-detect-before-processing) below.

### Parameters

| Field | Maps to (OpenCV/Signa) | Default | Notes |
|-------|------------------------|---------|-------|
| EPSG | `--epsg` | `28191` | target CRS of the coordinates; written as the `gcp_list.txt` header |
| ArUco dictionary | dictionary id | `1` (DICT_4X4_100) | `99` = legacy custom 3×3 |
| minrate | `--minrate` → `minMarkerPerimeterRate` | `0.01` | lower to detect smaller markers (enforced floor `0.005`) |
| ignore | `--ignore` → `perspectiveRemoveIgnoredMarginPerCell` | `0.33` | burnt-in protection for strong sunlight |
| Color adjustment | grayscale equalization | on | conservative contrast enhancement before detection |

### Print marker sheets

The **Signa Settings** page can generate print-ready ArUco marker PDFs
(one marker per page) — so the markers you lay out in the field are guaranteed
to match the dictionary the detector expects:

- **Dictionary** — pre-selected from your saved default; all supported
  dictionaries (0–20, 99) work. The id range is capacity-checked per
  dictionary (max 100 pages per PDF).
- **Page size** — DIN A6–A2. The marker is sized to the page with a one-module
  white quiet zone (e.g. ~157 mm on A4 for a 4×4 dictionary). Rule of thumb:
  marker side ≥ 40 × GSD of the planned flight.
- **Gray variant** — prints gray instead of white module cells; less burn-in
  under strong sunlight (pairs with `ignore 0.33` / color adjustment).
- **Center aiming aid** — none, red cross, red cross with white halo, or red
  dot with white ring. It marks the marker center, which is exactly the point
  the detection reports, so a total station / laser disto target placed on it
  measures the photogrammetric GCP with zero offset. The aids are deliberately
  thin/small: red reads dark in grayscale, and an oversized mark on a white
  module could flip a dictionary bit.

Below the marker each page carries a small meta line (dictionary, printed
size, `top ^` orientation) and a large, bold marker number readable from
standing height with the sheet on the ground. Every page is verified with the
ArUco detector before it is embedded in the PDF (self-check) — an undetectable
sheet can never be produced. Print at **100% scale** (no fit-to-page), check
the printed size with a ruler, and laminate **matte**, not glossy.

#### Declare the coordinate CRS in the file (recommended)

A wrong EPSG is a silent error: the codes are plausible numbers in the same
range, so an ITM file (EPSG:2039) accidentally run as `28191` georeferences
cleanly but in the wrong place. To guard against this, **add the CRS to the
coordinate file as a comment** — any `EPSG:xxxx` token in a `#` line is read:

```
# id easting northing elevation  (EPSG:28191)
1 698000.0 3540000.0 410.0
2 698050.0 3540000.0 411.0
```

When the file declares a single CRS, detection **refuses to run** if it
disagrees with the chosen EPSG, with a clear "CRS mismatch" error — instead of
producing a plausible but wrong georeference. A file that declares **several
conflicting** EPSG codes is also rejected (a contradictory header is stronger
evidence of a mistake than none, so it fails closed). A file with **no** header
is not blocked, so the comment is optional but strongly recommended. Only `#`
comment lines are scanned; data rows never trip it. (The fixture generator
already writes this header.)

> Always measure GCP coordinates in the target CRS (or reproject beforehand) —
> WebODM does not reproject them. The image EXIF (WGS84) may differ; ODX
> reprojects the EXIF internally.

The **Signa** menu page detects GCPs on a task that already exists — useful
for QA and for producing a `gcp_list.txt`. Because GCPs are an input to ODM's
reconstruction (not a post-hoc transform), applying them to an *already
processed* task means reprocessing. To georeference in **one** run, use the
single-pass entry points below.

### Single-pass (detect before processing)

Detect the GCPs and feed them into the **same** processing run:

- **Dashboard button** — next to *Select Images and GCP*, a **Signa Task**
  button opens a dialog (images + coordinate file + params) and does
  `create → upload → detect → attach gcp_list → start processing` for you.
- **Script** — [`scripts/signa-singlepass.py`](scripts/signa-singlepass.py)
  does the same headless, for automation:

  ```bash
  WEBODM_PASS=… scripts/signa-singlepass.py --url http://localhost:8000 \
    --user me --create-project "site-2026" \
    --images ./raw --coords ./gcp_coords.txt --epsg 28191 [--dry-run]
  ```

Both detect server-side (the worker needs OpenCV — see Worker image
requirement) and produce a georeferenced model in one pass.

### Partial-task cleanup

The single-pass flow creates a *partial* task first, then uploads, detects and
commits. If a step fails — or you cancel — the partial task is removed so it
doesn't linger in the project. A known limitation: if the **create** request is
processed server-side but its response is lost (a network drop right after the
task is created), the client never learns the task id and cannot clean it up, so
a stray partial task can remain. Delete it manually from the project if that
happens. (Once *commit* is in flight the task is kept on purpose — the server
may already have started it — so a lost response there never deletes a started
run.) A fully race-proof create would need a server-side idempotency key, which
WebODM does not currently offer.

## Plugin layout

```
signa/                  # ← single root dir required by WebODM's plugin loader
├── __init__.py
├── manifest.json         # name, version, webodmMinVersion, …
├── plugin.py             # Plugin(PluginBase): menu, app + API mount points, JS
├── api.py                # detect + check endpoints (DRF TaskView), auth-gated
├── params.py             # Django-free parameter validation (unit-tested)
├── requirements.txt      # OpenCV for the worker (single-host auto-install)
├── gcp_detect.py         # OpenCV ArUco detection — self-contained for the worker
├── marker_pdf.py         # print-ready marker sheets (built-in PDF writer, self-check)
├── templates/
│   ├── app.html          # standalone detection tool (drop images → download gcp_list)
│   └── settings.html     # per-user default detection parameters + marker printing
├── locale/de/…/django.po # German catalog (+ compiled .mo; en is the source)
└── public/
    ├── load_buttons.js   # "Signa task" dashboard button (single-pass)
    ├── style.css
    └── icon.svg
```

This mirrors WebODM's core-plugin conventions (cf. `coreplugins/contours`,
`coreplugins/posm-gcpi`). The loader (`app/admin.py → plugin_upload`) requires
the archive to contain **exactly one** root directory holding `plugin.py`,
`manifest.json` and `__init__.py`.

## Building the release zip

```bash
./build-plugin.sh          # → dist/signa-<version>.zip
```

The script reads the version from `manifest.json`, zips the `signa/` directory
as a single root folder, and verifies the archive structure.

**Automated releases:** push a tag matching the manifest version to build the
zip and publish a GitHub Release with the archive attached:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

See [`.github/workflows/release.yml`](.github/workflows/release.yml). CI
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs shellcheck, a
Python compile-check, the unit tests and a test build on every push/PR.

## Tests

```bash
pip install "numpy>=1.23,<3" "opencv-contrib-python-headless==4.10.0.84" pytest
python -m pytest tests/ -q
```

- **Unit tests** (`test_gcp_detect.py`, `test_params.py`) mock OpenCV. The key
  one (`test_self_contained_under_worker_eval`) reproduces WebODM's worker model
  — it takes `detect_gcps` *by source*, compiles it in an empty namespace and
  calls it — so a regression to module-level helpers (which would raise
  `NameError` only in the live worker) fails in CI instead.
- **API tests** (`test_api.py`) cover the view security/binding/error logic
  (`change_project` enforcement, run-binding + pruning, the status endpoint's
  permission re-check and ownership checks, celery error/not-ready/success
  branches). The WebODM/DRF surface is faked, so real guardian/DRF integration
  is still confirmed only by the manual checklist.
- **Integration test** (`test_integration_opencv.py`) renders real ArUco markers
  and runs detection end to end; it is skipped automatically if `cv2` is absent
  (CI installs it). It uses the fixture generator
  [`tests/fixtures/make_aruco_fixture.py`](tests/fixtures/make_aruco_fixture.py),
  which can also produce a standalone synthetic dataset for manual testing.

For the **live WebODM** path (plugin loader, worker `cv2`, permissions, UI) see
[`docs/manual-test.md`](docs/manual-test.md) — a checklist that uses the
synthetic fixture, so no drone flight is needed.

## Languages

The plugin is available in **English** and **German** and follows WebODM's
active language (gettext, like WebODM itself). The catalogs live in
[`signa/locale/`](signa/locale/) and are compiled by
[`scripts/compile_messages.py`](scripts/compile_messages.py) (pure Python, no
gettext toolchain needed) during the plugin build. CI guards that every
translatable string has a catalog entry. To add a language, copy
`locale/de/LC_MESSAGES/django.po`, translate the msgstrs, and add a matching
dictionary to `public/load_buttons.js` for the dashboard dialog.

Known limits: detection-internal error texts from the worker
(`gcp_detect.py`) stay English (the function is deliberately Django-free), and
the dashboard dialog infers the language from Django's language cookie or the
browser language.

## Changelog

See [CHANGELOG.md](CHANGELOG.md). The plugin follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## License

The WebODM plugin is licensed under the
[GNU Affero General Public License v3.0 or later](LICENSE) © 2026 Patrick Leiverkus.

The reusable detection core in [`signa-core/`](signa-core/) is licensed
**MIT** — a GUI-free OpenCV detection library shared with other consumers (e.g.
Mensura). This split (permissive core + AGPL plugin) mirrors the Itinera pattern.

## References

- WebODM: <https://github.com/WebODM/WebODM>
- ArUco detector parameters: <https://docs.opencv.org/trunk/d5/dae/tutorial_aruco_detection.html>
