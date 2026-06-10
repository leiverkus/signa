# Find-GCP for WebODM

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
   [Releases](https://github.com/leiverkus/Find-GCP-WebODM-Workflow/releases) page.
2. In WebODM: **Administration → Plugins → Load Plugin (.zip)** and upload the zip.
3. Enable the plugin. A **Find-GCP** entry appears in the main menu.

### Worker image requirement (important)

Detection runs in the **Celery worker** via WebODM's `run_function_async`
(`eval_async`), which compiles the function source in a bare namespace in the
worker process. The plugin therefore does **not** ship a `requirements.txt`: a
web-side install would not reach the worker and would only waste space and time.

**OpenCV must be present in the worker image.** In WebODM's compose the `worker`
and `webapp` services share one image (`webodm/webodm_webapp`), so the fix is a
thin image that extends it with `opencv-contrib-python-headless` and is used for
both services. `numpy` already ships with WebODM; OpenCV does not. Without it,
runs fail with `ModuleNotFoundError: No module named 'cv2'`.

Ready-made files are in [`docker/`](docker/) — a `worker.Dockerfile` and a
compose override, with step-by-step instructions in
[`docker/README.md`](docker/README.md). In short:

```bash
docker build -t webodm-findgcp:0.2.0 \
  --build-arg WEBODM_VERSION=<your-webodm-image-tag> \
  -f docker/worker.Dockerfile docker/
# then add docker/docker-compose.findgcp.yml as a final -f to your compose command
```

Pin `WEBODM_VERSION` to your WebODM image tag (no `latest`) so the worker runs
the same code as the rest of the stack.

### Permissions

The detect endpoint requires an authenticated user with `change_project`
permission on the task's project — enforced even for public tasks (unlike
WebODM's default `AllowAny` task views), because detection is expensive.

Each run is bound to the user who started it (recorded in the plugin's per-user
datastore) and to the task. The status/result endpoint only returns a run whose
celery id is registered to the requesting user with a matching task pk, so one
user cannot read another's result by knowing its celery id.

## Usage

Open **Find-GCP** from the menu, then:

1. Pick a **project** and a **task** (the task must already have its images).
2. Upload the **GCP coordinate file** — one marker per line:
   `id easting northing elevation` (whitespace or comma separated).
3. Set the parameters (see below) and click **Detect GCPs**.
4. Review the summary (markers, image counts, warnings) and **download
   `gcp_list.txt`**. Add it to the task's GCP field before processing.

### Parameters

| Field | Maps to (Find-GCP) | Default | Notes |
|-------|--------------------|---------|-------|
| EPSG | `--epsg` | `28191` | target CRS of the coordinates; written as the `gcp_list.txt` header |
| ArUco dictionary | `-d` | `1` (DICT_4X4_100) | `99` = custom 3×3 |
| minrate | `--minrate` → `minMarkerPerimeterRate` | `0.01` | lower to detect smaller markers (don't go below ~0.005) |
| ignore | `--ignore` → `perspectiveRemoveIgnoredMarginPerCell` | `0.33` | burnt-in protection for strong sunlight |
| Color adjustment | `--adjust` | on | LUT correction against overexposure |

> Always measure GCP coordinates in the target CRS (or reproject beforehand) —
> WebODM does not reproject them. The image EXIF (WGS84) may differ; ODX
> reprojects the EXIF internally.

## Plugin layout

```
findgcp/                  # ← single root dir required by WebODM's plugin loader
├── __init__.py
├── manifest.json         # name, version, webodmMinVersion, …
├── plugin.py             # Plugin(PluginBase): menu, app + API mount points
├── api.py                # detect + check endpoints (DRF TaskView), auth-gated
├── gcp_detect.py         # ported ArUco detection — self-contained for the worker
├── templates/app.html    # UI (vanilla JS + fetch, no JSX build)
└── public/               # style.css, icon.svg
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
git tag v0.2.0 && git push origin v0.2.0
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

## Changelog

See [CHANGELOG.md](CHANGELOG.md). The plugin is `0.x` and under active
development; behaviour may change between minor releases.

## License

[MIT](LICENSE) © 2026 Patrick Leiverkus

## References

- WebODM: <https://github.com/WebODM/WebODM>
- Find-GCP: <https://github.com/zsiki/Find-GCP>
- ArUco detector parameters: <https://docs.opencv.org/trunk/d5/dae/tutorial_aruco_detection.html>
- Siki 2021, *Baltic Journal of Modern Computing*:
  <https://www.bjmc.lu.lv/fileadmin/user_upload/lu_portal/projekti/bjmc/Contents/9_1_06_Siki.pdf>
