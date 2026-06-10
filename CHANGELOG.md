# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the version is `0.x` the plugin is under active development and the API
and behaviour may change between minor releases.

## [Unreleased]

## [0.2.0] - 2026-06-10

Hardening release after two internal reviews. Addresses production-blocking
issues; not yet verified against a live WebODM instance.

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
- **Dependency documentation**: corrected the false claim that WebODM installs
  `requirements.txt` for the worker. The per-plugin site-packages path is only
  on `sys.path` during web-side calls, so `opencv-contrib-python` and `numpy`
  must be present in the **worker image**. Documented with a Dockerfile snippet.
- **Anonymous compute**: the detect endpoint now requires authentication and
  `change_project` permission, enforced even for public tasks (WebODM's default
  task views are `AllowAny` and bypass permission checks for public tasks).
- **Result exposure**: removed the celery-id-only download endpoint. The
  `gcp_list` text now travels back in the worker result and is downloaded
  client-side via a Blob; the status/result endpoint requires authentication.
  No server-side temporary files or directories are created. Results are further
  bound to the user who started the run (via the plugin's per-user datastore)
  and to the task pk: the status endpoint only returns a result whose celery id
  is recorded in the requesting user's store with a matching task. The ownership
  record is released once a terminal result has been served.

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

### Changed
- Reproducible Docker build: `worker.Dockerfile` defaults `WEBODM_VERSION` to a
  concrete tag (`3.2.4`, override to match your install) instead of `latest`,
  and pins `opencv-contrib-python-headless==4.10.0.84`. `requirements.txt`
  pinned to the same OpenCV version. Removed the obsolete `version:` key from
  `docker-compose.findgcp.yml`.
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
