# Custom worker image for the Signa plugin

The Signa detection runs in WebODM's **Celery worker**, which needs `cv2`
(OpenCV) importable in its own process (see the main README, "Worker image
requirement"). These files build a thin image that adds OpenCV and wire it into
both the `webapp` and `worker` services (they share one image in WebODM's
compose).

## Files

- [`worker.Dockerfile`](worker.Dockerfile) — extends `webodm/webodm_webapp`
  with `opencv-contrib-python-headless`.
- [`docker-compose.signa.yml`](docker-compose.signa.yml) — override that
  points `webapp` and `worker` at the custom image.

## Steps

1. **Find your WebODM image tag** (so the worker runs the same code as the rest
   of the stack):

   ```bash
   docker image ls | grep webodm_webapp
   ```

2. **Build** the custom image, pinning that tag:

   ```bash
   docker build -t webodm-signa:local \
     --build-arg WEBODM_VERSION=<your-webodm-image-tag> \
     -f docker/worker.Dockerfile docker/
   ```

3. **Apply** the override. Merge it into the same compose command WebODM uses,
   adding it as a final `-f` (so it overrides the two services' `image:`):

   ```bash
   docker compose -f docker-compose.yml \
     -f docker-compose.nodeodm.yml \
     -f /path/to/docker-compose.signa.yml up -d
   ```

   > `webodm.sh` has no flag to inject custom overrides — it assembles a fixed
   > `docker-compose -f …` command. Either run compose manually as above, or
   > copy `docker-compose.signa.yml` next to WebODM's compose files and add
   > `-f docker-compose.signa.yml` to that command.

4. **Verify** OpenCV is importable in the worker:

   ```bash
   docker compose exec worker python -c "import cv2; print(cv2.__version__)"
   ```

If this prints a version, the plugin can run detection. If it errors with
`No module named 'cv2'`, the worker is not using the custom image yet.

## Notes

- Pin `WEBODM_VERSION` and the local image tag — avoid `latest` for
  reproducibility.
- Keep the custom image in sync when you upgrade WebODM: rebuild with the new
  `WEBODM_VERSION`.
