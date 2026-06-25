# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.6.1] - 2026-06-25

### Fixed
- **Plugin would fail to load in WebODM** (same defect found and fixed in
  Mensura). `params.py`/`plugin.py` imported `signa_core` at **module load**, but
  WebODM installs a plugin's `requirements.txt` only from
  `PluginBase.check_requirements()` — which runs *after* the module imports — so
  the import failed before the deps could be installed (chicken-and-egg), the
  plugin never instantiated, and its directory lingered, blocking re-upload. Now
  all `signa_core` imports are lazy: the settings form uses a callable for
  `choices`, the views/`params.py` functions import inside the body, `params.py`
  re-exports the shared tables via a module `__getattr__`, and `signa/__init__.py`
  adds the plugin's `site-packages` to `sys.path`.
- **`requirements.txt` is now comment-free** and requires **`signa-core>=0.2.1`**
  (which lowered `requires-python` to `>=3.9` so it installs in WebODM's Python
  3.9; `0.2.0` was pinned `>=3.10`). WebODM's `parse_requirements` treats `#`
  comment lines as package names, so the previous commented file never verified
  as installed and WebODM re-ran the install every boot.

## [1.6.0] - 2026-06-25

### Changed
- Marker-sheet rendering moved into `signa-core` (`signa_core.markers`): the PDF
  writer, marker raster, center aiming aids, label drawing (Pillow primary,
  Hershey fallback) and the per-page self-check are now shared primitives.
  `signa/marker_pdf.py` keeps only the Signa-specific fit-to-page sizing; the
  shared geometry/capacity tables (`PAGE_SIZES_MM`, `MARKER_AIDS`,
  `DICT_CAPACITY`, `MAX_MARKER_PAGES`) are re-exported in `params.py` from
  signa-core. No change to the produced PDFs. Requires `signa-core>=0.2.0`.
- CI: bumped `softprops/action-gh-release@v2 → v3` (Node 24 runtime; the `v2`
  line still targets the now-deprecated Node 20). Release-workflow only.

## [1.5.0] - 2026-06-25

### Added
- `signa-core/` — reusable, GUI-free ArUco detection core (MIT), shared with
  Mensura. The repo is now split-licensed: core MIT, WebODM plugin AGPL-3.0.

### Changed
- The plugin's non-worker code consumes `signa-core` instead of duplicating it:
  `params.py` re-exports `DICT_CHOICES`/`VALID_DICTS` from `signa_core`, and
  `marker_pdf.py` uses `signa_core.make_dictionary` / `load_aruco` (dropped the
  duplicated `_build_dictionary`/import shims). Adds a `signa-core` runtime
  dependency (see `signa/requirements.txt`). The self-contained worker detector
  (`gcp_detect.py`) is unchanged — it keeps its inlined copy by necessity.
- CI: the test job installs `signa-core` (editable) so the plugin's
  `params.py`/`marker_pdf.py` imports resolve, and the dead `bash -n` check for
  the `standalone/` wrapper (removed in 1.4.1) was dropped (workflow-only).

## [1.4.1] - 2026-06-18

### Changed
- Rewrote the server-side ArUco detector as a Signa/OpenCV implementation and
  removed the Find-GCP-derived tone-curve path and provenance metadata. The
  worker-facing API and `gcp_list.txt` output format are unchanged.
- Renamed dictionary `99` in the UI/docs from "custom 3x3 (Find-GCP)" to
  "legacy custom 3x3"; the numeric id and OpenCV-generated dictionary remain
  available for existing marker sheets.

### Removed
- Removed the legacy local `standalone/signa-webodm.sh` wrapper. Automation now
  uses the server-side Signa API, with `scripts/signa-singlepass.py` as the
  headless/orchestrator reference client.

## [1.4.0] - 2026-06-16

### Changed
- **Rebranded the plugin from Find-GCP to Signa.** The plugin is now named
  *Signa*; internal `FindGCP*` symbols were renamed to `Signa*`, and the
  installable archive is now `signa-<version>.zip` (previously `findgcp-*`). The
  ArUco detection logic is still ported from Find-GCP (`gcp_find.py`).

### Added
- `CITATION.cff` (Citation File Format 1.2.0) for machine-readable software
  citation, listing the upstream Find-GCP paper (Siki & Takács 2021) and the
  Find-GCP tool as references. Enables GitHub's "Cite this repository" and a
  correct Zenodo archival record.

## [1.3.0] - 2026-06-12

### Added
- **Print-ready ArUco marker sheets from the settings page.** A new "Print
  ArUco markers" form (Signa Settings) generates a PDF with one marker per
  page: any supported dictionary (pre-selected from the user's default), a
  free id range (capacity-checked per dictionary, max 100 pages), DIN page
  sizes A6–A2, a gray variant against burnt-in markers in strong sunlight, and
  an optional center aiming aid for total station / laser disto work (red
  cross, red cross with white halo, or red dot with white ring — placed on the
  exact point Signa reports as the GCP). Markers are sized to the page with
  a one-module quiet zone; each page carries a small meta line (dictionary,
  printed size, `top ^`) and a large, bold marker number readable from standing
  height with the sheet on the ground. Every page is run through the ArUco
  detector before it is embedded (self-check), so an undetectable sheet can
  never be produced. The PDF is assembled by a minimal built-in writer — no new
  dependencies; labels use Pillow (already a WebODM dependency) so the typeface
  matches the standalone generator, with an OpenCV/Hershey fallback if Pillow is
  unavailable (`signa/marker_pdf.py`, endpoint `plugins/signa/markers/pdf`).

### Changed
- `build-plugin.sh` now clears previously built `dist/signa-*.zip` before
  packaging, so only the current version's artifact remains.

## [1.2.0] - 2026-06-11

### Added
- **All ArUco dictionaries are now selectable in the UI.** The settings form and
  both task dialogs (Signa page + dashboard button) previously offered only
  `1 — DICT_4X4_100` and `99 — custom 3×3`, while the backend already accepted
  every OpenCV predefined dictionary. They now list all 21 predefined dictionaries
  (ids 0–20: the 4×4/5×5/6×6/7×7 families, `DICT_ARUCO_ORIGINAL`, and the four
  AprilTag families) plus the custom 3×3 (99). The list lives once in
  `signa/params.py` (`DICT_CHOICES`), from which the form, the server-rendered
  dropdown and the API's accepted-id set are all derived, so they can't drift.

### Fixed
- CI: resolved two `shellcheck` findings in `standalone/signa-webodm.sh`
  (SC2206 intentional-glob directive, SC2015 `&&`/`||` rewritten as if-then-else).
  Lint-only; the helper script is not part of the plugin zip.

### Changed
- CI: bumped GitHub Actions off the deprecated Node.js 20 runtime —
  `actions/checkout@v4 → v6`, `actions/setup-python@v5 → v6`,
  `actions/upload-artifact@v4 → v7`. Workflow-only; no effect on the plugin.

## [1.1.2] - 2026-06-11

Robustness fixes from a second code review. The version bump also re-busts the
`load_buttons.js` cache (it doubles as the script's `?v=` query), so browsers
re-fetch the updated dashboard script.

### Fixed
- **CRS mismatches are now caught instead of silently georeferencing wrong.** If
  the coordinate file declares its own CRS in a comment (e.g. `# … (EPSG:2039)`),
  detection refuses to run when that disagrees with the chosen EPSG, rather than
  writing the wrong code through verbatim. A file that declares *several
  conflicting* EPSG codes is also rejected (fail closed — a contradictory header
  is stronger evidence of a config problem than no header). Files without a
  declared CRS are unaffected.
- **`minrate` now enforces its documented 0.005 floor.** The API and the
  settings form rejected values far below the "never below 0.005" guidance
  (down to `0.0001` / any value > 0), which invited massive false positives.
  Both now clamp to `[0.005, 1]`.
- **The Signa page no longer leaves scratch projects behind.** A `pagehide`
  handler removes the scratch project (keepalive DELETE) if the tab is closed or
  navigated away mid-run, and `cleanup()` now surfaces a failed delete instead of
  treating any HTTP error as success. A failed cleanup is tracked in a separate
  pending-list (so a new run can't overwrite and lose the orphan id), retried at
  the start of the next run and on unload, and shown as a UI notice listing the
  affected project id(s) — not console-only.
- **A lost response during `commit` no longer deletes an already-started task.**
  Both the dashboard dialog and `scripts/signa-singlepass.py` now mark the task
  as kept *before* issuing the commit request, so a network drop or cancel while
  the commit is in flight (where the server may already have started processing)
  leaves the task intact instead of cleaning it up. A genuinely rejected commit
  leaves a recoverable partial task rather than destroying a running one.

### Docs
- `docs/manual-test.md`: the single-host automatic OpenCV path (2a) is now
  verified live end to end (plugin 1.1.1) — auto-installed `site-packages`,
  worker `cv2.aruco`, and a full detection run matching the fixture.
- Completed the changelog compare links (they previously stopped at `0.2.0`;
  `1.0.0`–`1.1.1` were missing).

## [1.1.1] - 2026-06-10

Robustness fixes from a code review (no behaviour change to a successful run).

### Fixed
- **OpenCV without ArUco no longer crashes.** `from cv2 import aruco` now lives
  *inside* the guarded import in `detect_gcps`, so a base `opencv-python` that
  lacks the contrib `aruco` module triggers the fallback (and, if it still can't
  be satisfied, the clear "fix the worker image" error) instead of an uncaught
  `ImportError`. We deliberately do **not** purge/reimport a cached `cv2` —
  OpenCV's bootstrap is not re-entrant, so a runtime swap is fragile.
- **Cancelling the dashboard "Signa Task" dialog now aborts the run.** Closing
  or cancelling mid-flight aborts in-flight requests and deletes the partial task
  it created, instead of letting the workflow keep running and commit a task in
  the background.
- **Orphaned partial tasks are cleaned up on error.** Both the dashboard button
  and `scripts/signa-singlepass.py` now remove the half-built partial task if a
  step fails (the script adds `--keep-on-error` to opt out for debugging).
- **Browser polling has a 30-minute safety timeout.** The dashboard dialog and
  the Signa menu page no longer poll forever if the worker gets stuck.

### Docs
- Aligned the custom worker-image tag to a stable, version-independent
  `webodm-signa:local` across the README, `docker/`, and the manual-test doc
  (it previously drifted between `0.2.0` and `1.0.0`).
- `docs/single-pass-design.md`: marked implemented (was "design only") and
  removed the discarded JWT step from the API sequence (the plugin endpoints
  require session + CSRF, as the Auth note already explained).
- `docs/manual-test.md`: split the worker-OpenCV step into the single-host
  automatic path (2a, flagged as not yet exercised live) and the docker-image
  path (2b).

## [1.1.0] - 2026-06-10

### Added
- **Self-contained OpenCV for single-host setups.** The plugin ships a
  `requirements.txt` again; WebODM installs OpenCV into the plugin's per-plugin
  site-packages on enable, which lives on the media volume shared by the
  `webapp` and `worker` containers. `detect_gcps` imports `cv2` normally first
  (so a worker image with OpenCV still wins) and falls back to that shared
  site-packages path (resolved via `settings.MEDIA_ROOT`) — so a standard
  single-host install needs **no manual `pip install`**: install the plugin,
  restart the web app, done.
- If `cv2` still can't be imported (e.g. a distributed worker without the shared
  volume), detection now returns a **clear error** pointing to the `docker/`
  worker image instead of a cryptic `ModuleNotFoundError`.

### Notes
- The `docker/` worker image remains the **robust path for distributed/server
  deployments** and is documented as such (README "OpenCV in the worker").

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
  is now "Neuer Task mit Signa", and "Dieser Task hat keine Bilder." /
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
  Signa page, the settings form, and the dashboard dialog), in both
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
  (`signa/locale/de/LC_MESSAGES/django.po`/`.mo`) and appends its locale dir
  to Django's `LOCALE_PATHS` at plugin registration (WebODM has no official
  plugin-translation support; `register()` runs at worker boot, and the
  per-language catalog cache is reset so the merged catalog always applies).
  Covers both pages, menu entries, the settings form and all API/validation
  error messages.
- The dashboard **Signa Task** dialog carries its own small dictionary
  (WebODM's JS catalog is restricted to `packages=['app']`); language is taken
  from Django's language cookie with a browser-language fallback.
- `scripts/compile_messages.py`: pure-Python `.po → .mo` compiler (no gettext
  toolchain needed); wired into `build-plugin.sh`.
- Translation drift guards in CI: every `{% trans %}`/`{% blocktrans %}` string
  and every python-side message (incl. all `params.py` validation errors) must
  exist in the catalog, and the committed `.mo` must match the `.po`.

## [0.5.0] - 2026-06-10

### Added
- **Signa Settings page** (new menu entry): set the default detection
  parameters (EPSG, ArUco dictionary, minrate, ignore, color adjustment) per
  user. Saved in the plugin's per-user datastore. Both detection UIs pre-fill
  from these defaults — the Signa page (server-rendered) and the dashboard
  **Signa Task** dialog (via a new `GET /api/plugins/signa/settings`
  endpoint). Values can still be overridden per run.

## [0.4.0] - 2026-06-10

### Changed
- **The Signa menu page is now a standalone detection tool** (like the core
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
- **"Signa task" dashboard button** (`signa/public/load_buttons.js`, via
  `PluginsAPI.Dashboard.addNewTaskButton`): a second new-task entry point that
  opens a dialog (images + coordinate file + params) and runs the single-pass
  flow in the browser — `create(partial) → upload → detect → upload(gcp_list) →
  commit`. Build-free (plain `React.createElement` + a vanilla dialog; no
  JSX/webpack). Live-verified end to end against WebODM 3.2.4.
- **Headless single-pass script** (`scripts/signa-singlepass.py`, stdlib only):
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
  OpenCV and a `docker-compose.signa.yml` override (with `docker/README.md`),
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
  `version:` key from `docker-compose.signa.yml`.
- Pinned `ludeeus/action-shellcheck@2.0.0` (was `@master`).
- CI now runs the unit tests in addition to shellcheck, compile-check and the
  test build.
- Marked the plugin `experimental` in the manifest while in `0.x`.

## [0.1.0] - 2026-06-10

Initial WebODM plugin.

### Added
- WebODM plugin (`signa/`) following the core-plugin conventions: menu entry,
  app page and API mount points, single-root-directory release zip.
- Automatic ArUco GCP detection ported from
  [Find-GCP](https://github.com/zsiki/Find-GCP) (`gcp_find.py`): custom 3×3
  dictionary (id 99), `minrate`/`ignore` parameter mapping, `--adjust` color
  LUT, corner-centroid pixel coordinates, ODM `gcp_list.txt` output.
- Browser UI to pick a project/task, upload coordinates, set parameters, run
  detection and review a summary.
- `build-plugin.sh` to package `dist/signa-<version>.zip`, and a GitHub
  Actions workflow to publish a release on a `v*` tag.
- Standalone Bash CLI retained under `standalone/`.

[Unreleased]: https://github.com/leiverkus/signa/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/leiverkus/signa/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/leiverkus/signa/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/leiverkus/signa/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/leiverkus/signa/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/leiverkus/signa/compare/v1.1.2...v1.2.0
[1.1.2]: https://github.com/leiverkus/signa/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/leiverkus/signa/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/leiverkus/signa/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/leiverkus/signa/compare/v0.6.3...v1.0.0
[0.6.3]: https://github.com/leiverkus/signa/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/leiverkus/signa/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/leiverkus/signa/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/leiverkus/signa/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/leiverkus/signa/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/leiverkus/signa/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/leiverkus/signa/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/leiverkus/signa/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/leiverkus/signa/releases/tag/v0.1.0
