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
- After the admin upload, `/plugins/findgcp/` returned 404 intermittently until
  `webapp` was restarted — the plugin cache is per-gunicorn-worker, so a
  `docker restart webapp` is needed for all workers to pick up a hot-uploaded
  plugin.
- OpenCV was provided to the worker transiently (`docker exec worker pip install
  opencv-contrib-python-headless==4.10.0.84`) for the run. That run **predates**
  the self-contained auto-install (plugin 1.1.0, section 2a), so the automatic
  path has **not yet been exercised end to end live** — verify it per the
  checklist there. For a durable distributed setup, the `docker/` worker image
  (section 2b) remains the robust path.

## 0. Prerequisites

- A running WebODM you can administer (e.g. `http://localhost:8000`).
- A superuser/staff account (for the plugin upload + admin).
- Docker access to build/deploy the custom worker image.
- This repo checked out, with `opencv-contrib-python` available locally to run
  the fixture generator (`pip install opencv-contrib-python-headless==4.10.0.84 numpy`).

## 1. Build the plugin zip

```bash
./build-plugin.sh           # → dist/findgcp-<version>.zip
```

- [ ] `dist/findgcp-<version>.zip` exists and unzips to a single `findgcp/` root.

## 2. Give the worker `cv2`

Detection runs in the Celery worker, which uses the stock `webodm/webodm_webapp`
image without OpenCV. There are two ways to provide it — pick **one**.

### 2a. Single-host — automatic (default, plugin 1.1.0+)

Nothing to build. The plugin ships a `requirements.txt`; WebODM installs OpenCV
into the plugin's per-plugin site-packages on enable. That directory lives on
the media volume the `webapp` and `worker` containers **share**, and the
detection code adds it to `sys.path`. So just install + enable the plugin
(section 3) and `docker restart webapp` — no manual step.

- [ ] **To verify live — not yet exercised end to end.** Starting from a clean
      worker (`docker compose exec worker python -c "import cv2"` →
      `ModuleNotFoundError`), install + enable the plugin, `docker restart
      webapp`, then run detection (section 6) and confirm it succeeds **without**
      any manual `pip install`. Check that
      `<MEDIA_ROOT>/plugins/findgcp/site-packages` exists and contains a `cv2*`
      package.

### 2b. Distributed / robust — bake it into the worker image

If the worker runs on a different host (no shared media volume), or you want a
durable image, build and deploy the custom image (see [`../docker/`](../docker/)):

```bash
# match the tag to your WebODM (docker image ls | grep webodm_webapp)
docker build -t webodm-findgcp:local \
  --build-arg WEBODM_VERSION=3.2.4 \
  -f docker/worker.Dockerfile docker/
```

Point `webapp` and `worker` at it by adding `docker/docker-compose.findgcp.yml`
as a final `-f` to your compose command, then restart the stack.

- [ ] `docker compose exec worker python -c "import cv2; print(cv2.__version__)"`
      prints a version (not `ModuleNotFoundError`).

> If neither path provides OpenCV, detection returns a terminal error
> *"OpenCV with the ArUco module (cv2.aruco) is not available in the worker…"* —
> which itself is a valid check that the error handling (not an HTTP 500) works.

## 3. Install the plugin

- [ ] WebODM → **Administration → Plugins → Load Plugin (.zip)** → upload
      `dist/findgcp-<version>.zip`.
- [ ] The plugin appears in the list and is **enabled**.
- [ ] A **Find-GCP** entry appears in the main menu.
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

- [ ] Open **Find-GCP**, select the project and the task.
- [ ] Upload `tests/fixtures/dataset/gcp_coords.txt`.
- [ ] Leave defaults (EPSG 28191, dict 1, minrate 0.01, ignore 0.33, adjust on).
- [ ] Click **Detect GCPs**. The status shows progress, then a summary.

Expected summary:

- [ ] Images: 6, GCP entries written: **24**, Unique markers: **5**.
- [ ] No "weak marker" / "fewer than 5" warnings.
- [ ] **Download gcp_list.txt** and diff it against the fixture reference:

  ```bash
  diff <(sort gcp_list.txt) <(sort tests/fixtures/dataset/expected_gcp_list.txt)
  ```

  - [ ] Only ordering may differ; sorted contents are identical.

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
      `/api/plugins/findgcp/task/<task_id>/detect` is rejected (401/403).
- [ ] A logged-in user **without** `change_project` on that project cannot start
      a run (403/Not found).
- [ ] Polling `/api/plugins/findgcp/task/<task_id>/check/<celery_id>` as a
      **different** user returns `{"ready": true, "error": "Result not found."}`.

## 9. Cleanup

- [ ] Remove the test task/project if desired.
- [ ] To uninstall: **Administration → Plugins → Find-GCP → Delete**.

---

If steps 6–8 pass, the live integration is confirmed for this WebODM version.
Record the version tested and any deviations here.
