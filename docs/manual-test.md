# Manual end-to-end test (live WebODM)

The automated suite mocks WebODM (and, for the integration test, renders real
ArUco markers). What it cannot cover is the live WebODM integration: the plugin
loader, the worker actually importing `cv2`, the DRF permission/run-binding
layer, and the browser UI. This checklist walks that path against a running
instance using the synthetic fixture, so no drone flight is required.

Written for WebODM 3.2.4 (`webodm/webodm_webapp:3.2.4`). Requires WebODM
**≥ 2.9.5** (the plugin uses `check_project_perms`).

**Live run — 2026-06-10, WebODM 3.2.4 (`webodm/webodm_webapp:latest`, content
3.2.4): PASSED.** Plugin installed via the admin upload and loaded; detection ran
in the Celery worker with real OpenCV; the downloaded `gcp_list.txt` was
byte-for-byte identical (sorted) to the fixture's `expected_gcp_list.txt`
(24 detections, 5 markers). Notes from that run:
- After the admin upload, `/plugins/signa/` returned 404 intermittently until
  `webapp` was restarted — the plugin cache is per-gunicorn-worker, so a
  `docker restart webapp` is needed for all workers to pick up a hot-uploaded
  plugin.
- OpenCV was provided to the worker transiently (`docker exec worker pip install
  opencv-contrib-python-headless==4.10.0.84`) for the run. That run **predates**
  the self-contained auto-install (plugin 1.1.0, section 2a). For a durable
  distributed setup, the `docker/` worker image (section 2b) remains the robust
  path.

**Self-contained auto-install — 2026-06-10, plugin 1.1.1: PASSED end to end.**
After a WebODM-Manager update reset the media volume to a clean state (the
`signa` plugin AND its `site-packages` gone; `cv2` absent in both `worker` and
`webapp`), re-uploading `dist/signa-1.1.1.zip`, enabling it and `docker
restart webapp` re-created `<MEDIA_ROOT>/plugins/signa/site-packages` with
`opencv_contrib_python_headless 4.10.0.84` + `numpy 2.0.2`. With that directory
on `sys.path` (as `detect_gcps` adds it), the worker imports `cv2 4.10.0` and
`cv2.aruco` cleanly. A full UI detection run (section 6) then ran on this
**auto-installed** cv2 with no manual `pip install`: 24 detections / 5 markers,
and the downloaded `gcp_list.txt` was byte-for-byte identical (sorted) to
`expected_gcp_list.txt` for every coordinate line — the only diff was the
`EPSG:` header, because the run used EPSG 6991 instead of the fixture's default
28191 (a UI choice, written through verbatim — not a bug). Note: a bare `docker
exec worker python -c "import cv2"` (without the site-packages path) still fails
— expected, since the path is injected at runtime by the detection code, not
added to the worker's base environment.

## 0. Prerequisites

- A running WebODM you can administer (e.g. `http://localhost:8000`).
- A superuser/staff account (for the plugin upload + admin).
- Docker access to build/deploy the custom worker image.
- This repo checked out, with `opencv-contrib-python` available locally to run
  the fixture generator (`pip install opencv-contrib-python-headless==4.10.0.84 numpy`).

## 1. Build the plugin zip

```bash
./build-plugin.sh           # → dist/signa-<version>.zip
```

- [ ] `dist/signa-<version>.zip` exists and unzips to a single `signa/` root.

## 2. Give the worker `cv2`

Detection runs in the Celery worker, which uses the stock `webodm/webodm_webapp`
image without OpenCV. There are two ways to provide it — pick **one**.

### 2a. Single-host — automatic (default, plugin 1.1.0+)

Nothing to build. The plugin ships a `requirements.txt`; WebODM installs OpenCV
into the plugin's per-plugin site-packages on enable. That directory lives on
the media volume the `webapp` and `worker` containers **share**, and the
detection code adds it to `sys.path`. So just install + enable the plugin
(section 3) and `docker restart webapp` — no manual step. The one case this
path does *not* cover: a worker that has already imported a base `opencv-python`
**without** the `aruco` contrib — OpenCV's bootstrap is not re-entrant, so the
site-packages copy can't replace it and detection returns the clear worker-image
error instead. Use 2b for that setup.

- [x] **Verified live end to end — 2026-06-10, plugin 1.1.1** (see header
      note). Starting from a clean worker (`import cv2` → `ModuleNotFoundError`,
      no `site-packages`), install + enable the plugin and `docker restart
      webapp` re-created `<MEDIA_ROOT>/plugins/signa/site-packages` with a
      `cv2*` package (opencv-contrib 4.10.0.84); the worker imports `cv2` +
      `cv2.aruco` via that path with **no** manual `pip install`, and a full
      detection run (section 6) on that auto-installed cv2 produced the expected
      `gcp_list.txt`.

### 2b. Distributed / robust — bake it into the worker image

If the worker runs on a different host (no shared media volume), or you want a
durable image, build and deploy the custom image (see [`../docker/`](../docker/)):

```bash
# match the tag to your WebODM (docker image ls | grep webodm_webapp)
docker build -t webodm-signa:local \
  --build-arg WEBODM_VERSION=3.2.4 \
  -f docker/worker.Dockerfile docker/
```

Point `webapp` and `worker` at it by adding `docker/docker-compose.signa.yml`
as a final `-f` to your compose command, then restart the stack.

- [ ] `docker compose exec worker python -c "import cv2; print(cv2.__version__)"`
      prints a version (not `ModuleNotFoundError`).

> If neither path provides OpenCV, detection returns a terminal error
> *"OpenCV with the ArUco module (cv2.aruco) is not available in the worker…"* —
> which itself is a valid check that the error handling (not an HTTP 500) works.

## 3. Install the plugin

- [ ] WebODM → **Administration → Plugins → Load Plugin (.zip)** → upload
      `dist/signa-<version>.zip`.
- [ ] The plugin appears in the list and is **enabled**.
- [ ] A **Signa** entry appears in the main menu.
- [ ] Opening it renders the page (project/task pickers, file input, parameters).

## 4. Generate the test dataset

```bash
python tests/fixtures/make_aruco_fixture.py
# → tests/fixtures/dataset/img1..6.JPG, gcp_coords.txt, expected_gcp_list.txt
```

- [ ] 6 JPGs + `gcp_coords.txt` + `expected_gcp_list.txt` are written.

## 5. Create a task from the fixture images

- [ ] In WebODM, create a project and a new task, uploading the 6 `imgN.JPG`.
- [ ] You do **not** need to process the task — detection only needs the images
      on disk. (Processing 6 synthetic images will fail reconstruction; that is
      expected and irrelevant to this test.)

## 6. Run detection

- [ ] Open **Signa**, select the project and the task.
- [ ] Upload `tests/fixtures/dataset/gcp_coords.txt`.
- [ ] Leave defaults (EPSG 28191, dict 1, minrate 0.01, ignore 0.33, adjust on).
      The fixture file declares `(EPSG:28191)` in its header, so the EPSG **must**
      stay 28191 — the CRS guard rejects a mismatching choice (see step 6a).
- [ ] Click **Detect GCPs**. The status shows progress, then a summary.

Expected summary:

- [ ] Images: 6, GCP entries written: **24**, Unique markers: **5**.
- [ ] No "weak marker" / "fewer than 5" warnings.
- [ ] **Download gcp_list.txt** and diff it against the fixture reference:

  ```bash
  diff <(sort gcp_list.txt) <(sort tests/fixtures/dataset/expected_gcp_list.txt)
  ```

  - [ ] Only ordering may differ; sorted contents are identical.

### 6a. Verify the CRS guard

The coordinate file declares its CRS in a comment (`# … (EPSG:28191)`); a
detection whose EPSG disagrees must be refused, not silently georeferenced wrong.

- [ ] Re-run detection with the **EPSG field set to a different code** (e.g.
      `2039`), leaving the same `gcp_coords.txt`.
- [ ] Detection is rejected with a clear **"CRS mismatch … declares EPSG:28191
      but this run is set to EPSG:2039"** error — no `gcp_list.txt` is produced.
- [ ] Set EPSG back to 28191 and confirm it runs again.

## 7. Verify the warnings UI (finding #1)

Edit a copy of `gcp_coords.txt` to add a malformed line and a duplicate id, then
re-run with that file:

```
0 698025.0 3540025.0 414.0
1 698000.0 3540000.0 410.0
1 111 222 333          # duplicate id 1
garbage line           # malformed
2 698050.0 3540000.0 411.0
3 698000.0 3540050.0 412.0
4 698050.0 3540050.0 413.0
```

- [ ] The result panel shows a **duplicate coordinate ids** warning (id 1).
- [ ] The result panel shows a **skipped lines** warning (the malformed line).
- [ ] Marker 1 still uses the first coordinate (`698000.0 …`), not `111 …`.

## 8. Verify access control (findings #3/#4)

- [ ] As an **anonymous** user (logged out), POSTing to
      `/api/plugins/signa/task/<task_id>/detect` is rejected (401/403).
- [ ] A logged-in user **without** `change_project` on that project cannot start
      a run (403/Not found).
- [ ] Polling `/api/plugins/signa/task/<task_id>/check/<celery_id>` as a
      **different** user returns `{"ready": true, "error": "Result not found."}`.

## 8a. Verify scratch-project cleanup (incl. a failed DELETE)

The Signa page runs detection on a throwaway scratch project and deletes it
afterwards. The delete path (and its failure handling) has no browser-automated
test, so check it here once.

- [ ] **Happy path:** run a detection from the Signa page, then confirm in the
      project list that **no** `Signa detection (scratch)` project lingers.
- [ ] **Simulated DELETE failure:** in DevTools, block the delete request
      (Network → request blocking for `DELETE /api/projects/*`, or set the tab
      offline right as the summary appears), then run a detection.
  - [ ] The result still renders, **plus** a UI notice: *"A temporary project
        could not be removed automatically … Affected id(s): &lt;n&gt;"*.
  - [ ] A `console.warn` names the same project id.
- [ ] **Retry on next run:** remove the block and start another detection; the
      previously stranded scratch project is deleted (pending-cleanup flush) and
      the notice no longer lists it.
- [ ] **Unload cleanup:** start a run and close the tab mid-run; the scratch
      project is removed shortly after (keepalive DELETE on `pagehide`).

## 9. Print ArUco marker sheets (settings page)

The **Signa Settings** page generates print-ready marker PDFs. This runs in
the `webapp` process (not the worker) and uses OpenCV + Pillow there.

- [ ] On **Signa Settings**, the **Print ArUco markers** section renders with
      a non-empty **ArUco dictionary** dropdown (pre-selected to your saved
      default) and all controls (page size, id range, aiming aid, gray).
- [ ] On a German UI, the whole section is German (label *ArUco-Marker drucken*,
      button *Marker-PDF erzeugen*). If it shows English, `webapp` is still
      running the pre-upload catalog — `docker restart webapp`.
- [ ] Generate a PDF (dict 1, ids 0–11, A4, red cross): the browser downloads
      `aruco-markers-dict1-id0-11-a4-cross.pdf` with **12 pages**.
- [ ] Each page: one centered marker, a red center cross, a small meta line
      (`DICT_4X4_100 - 157 mm - top ^`) and a large bold number below it.
- [ ] Re-detect roundtrip: the printed/exported marker is detectable — e.g.
      render a page to PNG and run `cv2.aruco.detectMarkers`, or simply trust the
      server-side self-check (an undetectable page is never embedded; it returns
      *"Marker self-check failed…"* instead).
- [ ] Capacity guard: dict **0** (DICT_4X4_50) with **last id 50** is rejected
      with *"Marker id range exceeds the capacity of the selected dictionary."*
- [ ] Range guard: **last id < first id**, or a range over **100**, is rejected.
- [ ] Gray variant + *cross with halo* / *dot with ring* also produce a valid
      PDF (self-check passes).

## 10. Cleanup

- [ ] Remove the test task/project if desired.
- [ ] To uninstall: **Administration → Plugins → Signa → Delete**.

---

If steps 6–8 pass, the live integration is confirmed for this WebODM version.
Record the version tested and any deviations here.
