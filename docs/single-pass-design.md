# Design: single-pass GCP workflow (detect before processing)

Status: **draft** — design only, not yet implemented.

## Goal

Let a user (or a script) produce a **georeferenced** model in **one** WebODM
processing run, with ArUco GCPs detected by this plugin — instead of today's
two-step (process once without GCP → detect → reprocess with GCP).

Two deliverables, built in this order:

1. **Scriptable path** — headless, pure WebODM REST API. The robust core.
2. **UI button** — a "Detect GCPs" control inside the task-creation dialog. A
   convenience layer on top of the same API sequence.

## Background (verified against WebODM master / 3.2.4)

### GCPs are an input to reconstruction, not a post-hoc transform
ODM consumes `gcp_list.txt` during the bundle adjustment / georeferencing
(`app/models/task.py`: `reconstruction_statistics.has_gcp`, `gcp_errors`). A
finished model cannot be "re-georeferenced" by attaching GCPs afterwards — they
must be present **before** the processing run.

### Task creation is already a partial → upload → commit flow
`app/api/tasks.py`:
- `create` (`POST /api/projects/<pid>/tasks/`) with `partial: true` → a task that
  is **not** processed (line ~390: "If this is a partial task, we're going to
  upload images later").
- `upload` (`POST /api/projects/<pid>/tasks/<tid>/upload/`) → add files to the
  partial task (line ~303).
- `commit` (`POST /api/projects/<pid>/tasks/<tid>/commit/`) → sets
  `task.partial = False` (line ~289) → **now** it processes.

So the images are uploaded to the server **before** "Start Processing"
(commit). This is the injection point: detect on the uploaded images and add the
GCP **between upload and commit**.

### WebODM treats an uploaded `.txt` as the GCP file
`task.py: resize_gcp` finds the GCP by scanning task files for a `.txt` that is
not `geo.txt` / `image_groups.txt` / `align.*`. So uploading `gcp_list.txt` to
the (partial) task registers it as the GCP. *(To verify live — see open
questions.)*

### Our existing detection endpoints work on a partial task
`TaskFindGCPDetect` reads `task.scan_images()` / `get_image_path()`, which return
the uploaded images regardless of processing state. A partial task that has had
its images uploaded is a valid detection target.

## Shared core: the single-pass API sequence

```
1. POST /api/token-auth/                                  -> JWT
2. POST /api/projects/<pid>/tasks/        {partial:true}  -> task <tid>
3. POST /api/projects/<pid>/tasks/<tid>/upload/  (images, possibly chunked)
4. POST /api/plugins/findgcp/task/<tid>/detect   (coords file + params) -> celery id
   GET  /api/plugins/findgcp/task/<tid>/check/<celery id>  (poll) -> {summary, gcp_list}
5. POST /api/projects/<pid>/tasks/<tid>/upload/  (gcp_list.txt)   # becomes the GCP
6. POST /api/projects/<pid>/tasks/<tid>/commit/                  # processes WITH GCP
```

Both deliverables use this exact sequence; only the driver differs (a script vs.
the browser).

## Deliverable 1 — scriptable path

A headless client (Python preferred for the multipart/chunked upload; a Bash
variant is possible) that runs the sequence above.

Inputs:
- WebODM URL + credentials (or token), project id (or create one)
- image directory
- GCP coordinate file (`id easting northing elevation`)
- detection params (epsg, dict, minrate, ignore, adjust) — defaults as in the plugin
- task options (name, processing node, options profile)

Behaviour:
- Create partial task, upload images (with progress + retry, mirroring WebODM's
  resumable upload — `parallelUploads`, commit retries).
- Trigger plugin detection, poll until ready, fail loudly on worker error.
- Surface the detection summary (markers, weak markers, skipped/duplicate coords)
  before committing, with an optional `--dry-run` that stops before commit.
- Upload `gcp_list.txt`, commit.

Relationship to the existing `standalone/findgcp-webodm.sh`: that script detects
**locally** (needs local OpenCV/Find-GCP) and creates one task with images+GCP.
This new path detects **server-side** (no local OpenCV; needs the plugin + a
worker with `cv2`). We keep both and document when to use which.

Deliverable: `scripts/findgcp-singlepass.py` (+ `--help`, no third-party deps
beyond the stdlib + `requests` if acceptable, else `urllib`).

## Deliverable 2 — UI button

### Why NOT the inline panel item (`addNewTaskPanelItem`)
The original plan was a button **inside** the create dialog that detects on the
already-uploaded images. Reading the frontend (`ProjectListItem.jsx`) showed this
premise is **false**: the dropzone uses `autoProcessQueue: false` and only
`handleTaskSaved` (the "Start Processing" click) creates the partial task
(`POST partial:true`), sets `_taskInfo.id`, and starts the upload — then commits.
So when the panel item is on screen, **no task exists and nothing is uploaded**;
the panel item only has the browser `File` objects via `getFiles()`. An inline
button would therefore need either client-side ArUco detection (a second,
inconsistent detector) or to inject the GCP into the dropzone queue (fragile).

### Chosen hook: `addNewTaskButton`
`PluginsAPI.Dashboard.addNewTaskButton` (rendered in `ProjectListItem.jsx`,
line ~399) lets a plugin add its **own** new-task entry point next to "Select
Images and GCP", receiving `{projectId, onNewTaskAdded}`. This is clean: our
button owns the whole flow and reuses the **verified** single-pass sequence
(the exact `findgcp-singlepass.py` logic, in the browser via `fetch`):

1. Our button opens a dialog: image picker + coordinate file + detection params.
2. `create(partial)` → `upload(images)` → `detect` (plugin) → poll →
   `upload(gcp_list)` → `commit` — same-origin, so the session cookie is present
   and we send `X-CSRFToken` from the cookie (no JWT/CSRF issue).
3. Call `onNewTaskAdded()` to refresh the task list.

No partial-task-id coupling (we create and own the task), no client-side
detection, single processing pass. The cost: a separate button rather than an
in-panel control, plus a `build_jsx_components` webpack build in the plugin
(`public/` JSX entry + `main.js` registering via the hook, like
`coreplugins/contours/public/main.js`).

Bonus: bridging from `gcp_check`/QA is unnecessary — this button IS the
single-pass entry point.

### Open question #2 — RESOLVED
The "how does a panel item get the partial task id" risk is moot: we no longer
use the panel item. `addNewTaskButton` hands us `projectId` and we create the
task ourselves.

## Open questions

1. **RESOLVED — yes.** Uploading `gcp_list.txt` to a partial task via `/upload/`
   places it in the task directory, and WebODM's own GCP discovery recognizes it:
   on a live 3.2.4 run (project 10, task `45762e20…`), the file landed next to the
   6 images and `app.classes.gcp.GCPFile` reported `exists()=True`, 24 entries,
   SRS `EPSG:28191`. (Minor: `images_count` read 7 with 6 images — a cosmetic
   WebODM counter quirk; ODM scans images by extension and gets the GCP via
   `--gcp`, so it does not affect processing.)
3. **RESOLVED — yes.** `/upload/` accepts a single non-image `.txt` after the
   images (`flatten_files` + `handle_images_upload`); no need to batch it with the
   images.
2. **RESOLVED — moot.** Reading `ProjectListItem.jsx` showed the partial task is
   created only at "Start Processing", so an inline panel item has no task to act
   on. Deliverable 2 switched to `addNewTaskButton`, where we create and own the
   task — no partial-task-id coupling needed. (See Deliverable 2.)
4. Commit retry / timing — the button reuses the verified
   create→upload→detect→upload→commit sequence; no step is injected before an
   existing commit, so the dropzone's auto-commit timing is not involved.

### Auth note (learned during the live run)
The Find-GCP plugin API is dispatched by WebODM's `api_view_handler`, a plain
Django view registered **without** `csrf_exempt` (`app/api/urls.py`). A JWT token
alone is rejected with HTTP 403 "CSRF verification failed" — the core DRF
ViewSets are csrf_exempt and accept JWT, but the plugin endpoints require a
**session + `X-CSRFToken`** (what the frontend uses). `findgcp-singlepass.py`
logs in via `/login/` and sends the CSRF header on every unsafe request.

## Test plan

- **Unit (mock):** extend the fake-WebODM harness to cover the new endpoint(s)
  if we add any (e.g. a server-side "attach gcp + commit" helper).
- **Integration (real OpenCV):** the existing synthetic fixture already provides
  images + coords + expected `gcp_list.txt`.
- **Live (scriptable):** run `findgcp-singlepass.py` against the synthetic
  fixture end to end; assert the committed task has a GCP and the georeferencing
  uses it (`has_gcp` true). Record in `docs/manual-test.md`.
- **Live (UI):** once the partial-task-id question is resolved, repeat via the
  dialog button.

## Milestones

1. **This document** + live verification of open questions 1–3.
2. **Scriptable path** (`scripts/findgcp-singlepass.py`) + live run on the fixture.
3. **UI button** (panel item + JSX build) + live run, if the id risk is resolved.

Each milestone is a separate change with its own tests and a live-run record.
