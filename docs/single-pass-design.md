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

## Deliverable 2 — UI button (task-creation dialog)

Hook: `PluginsAPI.Dashboard.addNewTaskPanelItem` (verified in
`app/static/app/js/components/NewTaskPanel.jsx`). The panel item is rendered in
the new-task form and receives props `taskInfo`, `getFiles`, `filesCount`.

Component:
- A "Detect GCPs (ArUco)" button + a file input for the coordinate file +
  the detection params (collapsible, defaults preset).
- On click: resolve the partial task id → call detect → poll → upload
  `gcp_list.txt` to the task → show the summary. The user then clicks
  "Start Processing" (commit) as usual.

This requires `build_jsx_components` in the plugin (webpack build runs in
`build_plugins`), so the plugin gains a `public/` JSX entry and a build step.

### Key risk — obtaining the partial task id
The panel-item props do **not** include the partial task id. It lives in the
dropzone of the surrounding `ProjectListItem` (`this.dz._taskInfo.id`), which is
a WebODM internal, not part of the plugin contract. Candidate strategies, to be
decided after the live check:
- **(a)** Read it via the WebODM frontend (e.g. a documented event, a global, or
  walking from `getFiles`'s bound dropzone). Cleanest if a stable accessor
  exists; otherwise version-fragile.
- **(b)** Fallback: the button creates its **own** partial task and uploads the
  selected `getFiles()` to it for detection. Avoids the internal coupling but
  **double-uploads** the images. Acceptable only for small sets.

We verify (a) on the live instance before committing to the UI build. If no
stable accessor exists, we ship the scriptable path as the supported single-pass
and keep the button experimental.

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
2. Can a panel item obtain the partial task id without fragile coupling? (Drives
   the UI feasibility — still open, for Phase 3.)
4. Commit retry / timing semantics when injecting a step before commit. (Phase 3.)

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
