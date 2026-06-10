# Find-GCP for WebODM

[![CI](https://github.com/leiverkus/find-gcp-webodm-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/leiverkus/find-gcp-webodm-plugin/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/leiverkus/find-gcp-webodm-plugin?sort=semver)](https://github.com/leiverkus/find-gcp-webodm-plugin/releases)
[![License: MIT](https://img.shields.io/github/license/leiverkus/find-gcp-webodm-plugin)](LICENSE)
[![WebODM ≥ 2.9.5](https://img.shields.io/badge/WebODM-%E2%89%A5%202.9.5-1f6feb.svg)](https://github.com/WebODM/WebODM)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab.svg)](https://www.python.org/)

A [WebODM](https://github.com/WebODM/WebODM) plugin for **automatic ArUco ground
control point detection**. It detects ArUco markers in a task's images, matches
them against your measured GCP coordinates and produces an ODM-compatible
`gcp_list.txt` — directly inside WebODM, no command line required.

The detection logic is ported from [Find-GCP](https://github.com/zsiki/Find-GCP)
(`gcp_find.py`) and runs server-side in the WebODM worker.

A standalone Bash CLI for the same workflow (run Find-GCP outside WebODM and
optionally upload via the API) is kept under [`standalone/`](standalone/).

## Install in WebODM

1. Download `findgcp-<version>.zip` from the
   [Releases](https://github.com/leiverkus/find-gcp-webodm-plugin/releases) page.
2. In WebODM: **Administration → Plugins → Load Plugin (.zip)** and upload the zip.
3. Enable the plugin. A **Find-GCP** entry appears in the main menu.
4. **Restart the web app** after every install or update
   (`docker restart webapp`). **This is required, not optional.** Uploading a
   plugin swaps the files on disk, but the running gunicorn workers keep the old
   plugin module in `sys.modules` (Python does not re-import it) — and each
   worker is independent. Without a restart you get intermittent symptoms across
   reloads: the **Find-GCP page 404s** on some workers, and the **"Find-GCP
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
docker build -t webodm-findgcp:local \
  --build-arg WEBODM_VERSION=<your-webodm-image-tag> \
  -f docker/worker.Dockerfile docker/
# then add docker/docker-compose.findgcp.yml as a final -f to your compose command
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

**Find-GCP menu page — standalone detection tool** (like the core `posm-gcpi`
GCP interface, but automatic):

1. Open **Find-GCP** from the menu.
2. **Drop drone images** (or click to choose) and select the **GCP coordinate
   file** — one marker per line: `id easting northing elevation` (whitespace or
   comma separated). Optionally declare the CRS in a comment (`# … (EPSG:28191)`)
   to catch a wrong EPSG choice — see [below](#declare-the-coordinate-crs-in-the-file-recommended).
3. Set the parameters (see below) and click **Detect GCPs**.
4. Review the summary (markers, image counts, warnings) and **download
   `gcp_list.txt`**.

It runs the detection on a throwaway scratch task that is deleted again
afterwards — nothing is processed. Use this to produce or QA a `gcp_list.txt`.

**Dashboard "Find-GCP Task" button — single pass** (detect **and** georeference
in one run): see [Single-pass](#single-pass-detect-before-processing) below.

### Parameters

| Field | Maps to (Find-GCP) | Default | Notes |
|-------|--------------------|---------|-------|
| EPSG | `--epsg` | `28191` | target CRS of the coordinates; written as the `gcp_list.txt` header |
| ArUco dictionary | `-d` | `1` (DICT_4X4_100) | `99` = custom 3×3 |
| minrate | `--minrate` → `minMarkerPerimeterRate` | `0.01` | lower to detect smaller markers (enforced floor `0.005`) |
| ignore | `--ignore` → `perspectiveRemoveIgnoredMarginPerCell` | `0.33` | burnt-in protection for strong sunlight |
| Color adjustment | `--adjust` | on | LUT correction against overexposure |

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

The **Find-GCP** menu page detects GCPs on a task that already exists — useful
for QA and for producing a `gcp_list.txt`. Because GCPs are an input to ODM's
reconstruction (not a post-hoc transform), applying them to an *already
processed* task means reprocessing. To georeference in **one** run, use the
single-pass entry points below.

### Single-pass (detect before processing)

Detect the GCPs and feed them into the **same** processing run:

- **Dashboard button** — next to *Select Images and GCP*, a **Find-GCP Task**
  button opens a dialog (images + coordinate file + params) and does
  `create → upload → detect → attach gcp_list → start processing` for you.
- **Script** — [`scripts/findgcp-singlepass.py`](scripts/findgcp-singlepass.py)
  does the same headless, for automation:

  ```bash
  WEBODM_PASS=… scripts/findgcp-singlepass.py --url http://localhost:8000 \
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
findgcp/                  # ← single root dir required by WebODM's plugin loader
├── __init__.py
├── manifest.json         # name, version, webodmMinVersion, …
├── plugin.py             # Plugin(PluginBase): menu, app + API mount points, JS
├── api.py                # detect + check endpoints (DRF TaskView), auth-gated
├── params.py             # Django-free parameter validation (unit-tested)
├── requirements.txt      # OpenCV for the worker (single-host auto-install)
├── gcp_detect.py         # ported ArUco detection — self-contained for the worker
├── templates/
│   ├── app.html          # standalone detection tool (drop images → download gcp_list)
│   └── settings.html     # per-user default detection parameters
├── locale/de/…/django.po # German catalog (+ compiled .mo; en is the source)
└── public/
    ├── load_buttons.js   # "Find-GCP task" dashboard button (single-pass)
    ├── style.css
    └── icon.svg
```

This mirrors WebODM's core-plugin conventions (cf. `coreplugins/contours`,
`coreplugins/posm-gcpi`). The loader (`app/admin.py → plugin_upload`) requires
the archive to contain **exactly one** root directory holding `plugin.py`,
`manifest.json` and `__init__.py`.

## Building the release zip

```bash
./build-plugin.sh          # → dist/findgcp-<version>.zip
```

The script reads the version from `manifest.json`, zips the `findgcp/` directory
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

## Standalone CLI (alternative)

If you prefer to run detection outside WebODM, the original Bash pipeline is in
[`standalone/findgcp-webodm.sh`](standalone/findgcp-webodm.sh) — it wraps
Find-GCP (`gcp_find.py`), builds a sanity report and can prep/upload a
WebODM-ready folder. Run `standalone/findgcp-webodm.sh --help` for details.

## Languages

The plugin is available in **English** and **German** and follows WebODM's
active language (gettext, like WebODM itself). The catalogs live in
[`findgcp/locale/`](findgcp/locale/) and are compiled by
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

[MIT](LICENSE) © 2026 Patrick Leiverkus

## References

- WebODM: <https://github.com/WebODM/WebODM>
- Find-GCP: <https://github.com/zsiki/Find-GCP>
- ArUco detector parameters: <https://docs.opencv.org/trunk/d5/dae/tutorial_aruco_detection.html>
- Siki 2021, *Baltic Journal of Modern Computing*:
  <https://www.bjmc.lu.lv/fileadmin/user_upload/lu_portal/projekti/bjmc/Contents/9_1_06_Siki.pdf>
