# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the version is `0.x` the plugin is under active development and the API
and behaviour may change between minor releases.

## [Unreleased]

## [1.0.0] - 2026-06-10

First stable release. Cleared the `experimental` flag in the manifest — the
review gates are met (automated unit/API/integration tests, drift-guarded
translations) and the full workflow has been verified end to end against a live
WebODM 3.2.4: standalone detection, the single-pass dashboard button, per-user
settings, and German/English UI. No functional changes versus 0.6.3.

### Changed
- `manifest.json`: `experimental: true → false`, version `1.0.0`.

## [0.6.3] - 2026-06-10

### Fixed
- German grammatical gender for "Task" (masculine "der Task"): the dialog title
  is now "Neuer Task mit Find-GCP", and "Dieser Task hat keine Bilder." /
  "ein temporärer Task" in the catalog.

## [0.6.2] - 2026-06-10

### Fixed
- **Unstable language selection** (pages flipping between German and English
  across navigations): the locale hook lived in `register()`, but WebODM's
  `boot()` is guarded by a shared-memory flag (`webodm.wsgi.booted`), so
  `register()` runs in only **one** gunicorn worker — German appeared only when
  that worker answered. The hook now runs in `Plugin.__init__`, which executes
  in **every** worker (plugins are instantiated on each page render via the
  plugin template tags), and re-activates the current language after merging
  the catalog.

## [0.6.1] - 2026-06-10

### Added
- Help texts for **minrate** and **ignore** wherever they can be changed (the
  Find-GCP page, the settings form, and the dashboard dialog), in both
  languages: what the parameter means and which values are sensible (minrate:
  lower stepwise 0.01 → 0.008 → 0.005, never below 0.005, markers ≥ 20×20 px;
  ignore: 0.13 OpenCV default up to 0.33 in strong sunlight).

### Fixed
- Settings-form labels and help texts now use `gettext_lazy` — they are
  evaluated at module import time, where plain `gettext` would freeze them in
  whatever language was active when the module loaded.

## [0.6.0] - 2026-06-10

### Added
- **German translation (de)** alongside English, using the same gettext
  mechanism as WebODM itself. The plugin ships its own catalog
  (`findgcp/locale/de/LC_MESSAGES/django.po`/`.mo`) and appends its locale dir
  to Django's `LOCALE_PATHS` at plugin registration (WebODM has no official
  plugin-translation support; `register()` runs at worker boot, and the
  per-language catalog cache is reset so the merged catalog always applies).
  Covers both pages, menu entries, the settings form and all API/validation
  error messages.
- The dashboard **Find-GCP Task** dialog carries its own small dictionary
  (WebODM's JS catalog is restricted to `packages=['app']`); language is taken
  from Django's language cookie with a browser-language fallback.
- `scripts/compile_messages.py`: pure-Python `.po → .mo` compiler (no gettext
  toolchain needed); wired into `build-plugin.sh`.
- Translation drift guards in CI: every `{% trans %}`/`{% blocktrans %}` string
  and every python-side message (incl. all `params.py` validation errors) must
  exist in the catalog, and the committed `.mo` must match the `.po`.

## [0.5.0] - 2026-06-10

### Added
- **Find-GCP Settings page** (new menu entry): set the default detection
  parameters (EPSG, ArUco dictionary, minrate, ignore, color adjustment) per
  user. Saved in the plugin's per-user datastore. Both detection UIs pre-fill
  from these defaults — the Find-GCP page (server-rendered) and the dashboard
  **Find-GCP Task** dialog (via a new `GET /api/plugins/findgcp/settings`
  endpoint). Values can still be overridden per run.

## [0.4.0] - 2026-06-10

### Changed
- **The Find-GCP menu page is now a standalone detection tool** (like the core
  `posm-gcpi` GCP interface, but automatic): drop drone images + a coordinate
  file, run ArUco detection, and **download `gcp_list.txt`** — no existing task
  required. It creates a scratch task on the server for the detection and
  deletes it again afterwards (nothing is processed). The previous page (pick an
  existing task → detect) is superseded by this and by the dashboard button.
  Reuses the existing detect/check endpoints; no new server code. Live-verified
  on WebODM 3.2.4: dropped the 6 fixture images, detected 24 GCP entries, and the
  downloaded `gcp_list.txt` matched the fixture exactly; the scratch project was
  marked for deletion afterwards.

## [0.3.0] - 2026-06-10

Single-pass workflow: detect GCPs **before** the (only) processing run, so a
georeferenced model is produced in one pass instead of process → detect →
reprocess. Grounded in WebODM's verified `partial → upload → commit` task API
(see `docs/single-pass-design.md`).

### Added
- **"Find-GCP task" dashboard button** (`findgcp/public/load_buttons.js`, via
  `PluginsAPI.Dashboard.addNewTaskButton`): a second new-task entry point that
  opens a dialog (images + coordinate file + params) and runs the single-pass
  flow in the browser — `create(partial) → upload → detect → upload(gcp_list) →
  commit`. Build-free (plain `React.createElement` + a vanilla dialog; no
  JSX/webpack). Live-verified end to end against WebODM 3.2.4.
- **Headless single-pass script** (`scripts/findgcp-singlepass.py`, stdlib only):
  the same sequence for automation. Server-side detection via the plugin (no
  local OpenCV). `--dry-run` stops before commit. Uses a Django session +
  `X-CSRFToken` (the plugin API is not csrf_exempt, so JWT alone is rejected).
- `docs/single-pass-design.md` and the open-question resolutions from the live
  runs (an uploaded `gcp_list.txt` is recognized as the task GCP).

## [0.2.0] - 2026-06-10

Hardening release after three internal reviews, verified end to end against a
live WebODM 3.2.4 on 2026-06-10: the plugin installed and loaded, detection ran
in the worker with real OpenCV, and the output matched the synthetic fixture
exactly (see `docs/manual-test.md`).

### Fixed
- **Parser warnings surfaced in the UI**: skipped coordinate lines and duplicate
  ids (already returned by the worker) are now shown as warnings in the result
  panel, so bad/missing coordinates can't pass unnoticed.
- **Worker exceptions no longer 500**: the status endpoint reads the result with
  `get(propagate=False)` and turns a worker failure (e.g. missing `cv2`, OOM,
  OpenCV error) into a terminal error response, releasing the ownership record
  instead of leaving it dangling.
- **Results are no longer one-shot**: the ownership record is kept after a
  successful read (a dropped connection no longer loses a finished
  `gcp_list.txt`); accumulation is bounded to one record per (user, task) by
  pruning the previous run on a new detect.
- **Worker `NameError`**: detection failed in the Celery worker because
  `run_function_async` serializes only the function source and exec's it in an
  empty namespace (`app/plugins/worker.py` → `eval_async`). `detect_gcps` is now
  fully self-contained — all helpers, constants and imports live inside the
  function body.
- **Dependency documentation**: clarified that detection runs in the Celery
  worker, so `opencv-contrib-python` must be present in the **worker image**
  (a web-side plugin install would not reach it). Documented with a Dockerfile
  snippet; the plugin ships no `requirements.txt` (see Changed).
- **Anonymous compute**: the detect endpoint now requires authentication and
  `change_project` permission, enforced even for public tasks (WebODM's default
  task views are `AllowAny` and bypass permission checks for public tasks).
- **Result exposure**: removed the celery-id-only download endpoint. The
  `gcp_list` text now travels back in the worker result and is downloaded
  client-side via a Blob; the status/result endpoint requires authentication.
  No server-side temporary files or directories are created. Results are further
  bound to the user who started the run (via the plugin's per-user datastore)
  and to the task pk: the status endpoint only returns a result whose celery id
  is recorded in the requesting user's store with a matching task, and it
  re-checks the user's current `change_project` permission on each poll (a
  revoked user can no longer read a finished result).

### Added
- `docker/` — a `worker.Dockerfile` extending `webodm/webodm_webapp` with
  OpenCV and a `docker-compose.findgcp.yml` override (with `docker/README.md`),
  so the worker has `cv2` reproducibly.
- Unit test suite (11 tests, OpenCV mocked). The key test reproduces WebODM's
  worker execution model (compile `detect_gcps` from source in an empty
  namespace) so the self-containment regression is caught in CI.
- Server-side validation of `epsg`, `dict`, `minrate`, `ignore` and a size cap
  on the uploaded coordinate file.
- Robust coordinate parsing: rejects non-integer ids (`1.9`), `nan`/`inf`
  coordinates, and reports duplicate ids and skipped lines instead of silently
  overwriting.
- Extracted parameter validation into a Django-free `params.py` and added 13
  unit tests for it (range/type/`nan` checks, dictionary whitelist, `adjust`
  parsing) — the API permission/run-binding logic still needs a live WebODM.
- Real-OpenCV integration test (`test_integration_opencv.py`) that renders
  actual ArUco markers and runs detection end to end (skipped when `cv2` is
  absent; CI installs it). Backed by a synthetic-fixture generator
  (`tests/fixtures/make_aruco_fixture.py`).
- API unit tests (`test_api.py`, 14 cases) for the security/binding/error logic:
  `change_project` enforcement on detect, run-binding storage and pruning, the
  status endpoint's permission re-check, ownership checks, and the celery
  error/not-ready/clean-error/success branches. The WebODM/DRF surface is faked
  (`conftest_webodm_fakes.py`); real guardian/DRF integration is still covered
  only by the manual checklist.
- `docs/manual-test.md`: a live-WebODM end-to-end checklist (loader, worker
  `cv2`, permissions, warnings UI) built around the synthetic fixture.

### Changed
- **`webodmMinVersion` raised to `2.9.5`** — the plugin imports
  `check_project_perms`, which only exists from WebODM 2.9.5; on 2.0.0–2.9.4 the
  plugin import would fail.
- **Removed `requirements.txt`** — WebODM would install OpenCV into the plugin's
  web-side site-packages, which does not help the worker (where detection runs)
  and only wastes space and install time. The worker gets OpenCV from the
  `docker/` image instead.
- Reproducible Docker build: `worker.Dockerfile` defaults `WEBODM_VERSION` to a
  concrete tag (`3.2.4`, override to match your install) instead of `latest`,
  and pins `opencv-contrib-python-headless==4.10.0.84`. Removed the obsolete
  `version:` key from `docker-compose.findgcp.yml`.
- Pinned `ludeeus/action-shellcheck@2.0.0` (was `@master`).
- CI now runs the unit tests in addition to shellcheck, compile-check and the
  test build.
- Marked the plugin `experimental` in the manifest while in `0.x`.

## [0.1.0] - 2026-06-10

Initial WebODM plugin.

### Added
- WebODM plugin (`findgcp/`) following the core-plugin conventions: menu entry,
  app page and API mount points, single-root-directory release zip.
- Automatic ArUco GCP detection ported from
  [Find-GCP](https://github.com/zsiki/Find-GCP) (`gcp_find.py`): custom 3×3
  dictionary (id 99), `minrate`/`ignore` parameter mapping, `--adjust` color
  LUT, corner-centroid pixel coordinates, ODM `gcp_list.txt` output.
- Browser UI to pick a project/task, upload coordinates, set parameters, run
  detection and review a summary.
- `build-plugin.sh` to package `dist/findgcp-<version>.zip`, and a GitHub
  Actions workflow to publish a release on a `v*` tag.
- Standalone Bash CLI retained under `standalone/`.

[Unreleased]: https://github.com/leiverkus/Find-GCP-WebODM-Workflow/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/leiverkus/Find-GCP-WebODM-Workflow/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/leiverkus/Find-GCP-WebODM-Workflow/releases/tag/v0.1.0
