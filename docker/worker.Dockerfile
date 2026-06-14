# Custom WebODM image with OpenCV, for the Signa plugin.
#
# Why: the Signa detection runs in the Celery WORKER via WebODM's
# run_function_async -> eval_async (app/plugins/worker.py), which compiles the
# function source in a bare namespace in the worker process. So cv2 must exist
# in the image the worker runs. WebODM's docker-compose uses the SAME image for
# both the `webapp` and `worker` services: webodm/webodm_webapp. We extend it
# here and use this image for both services (see docker-compose.signa.yml).
#
# numpy already ships with WebODM, so we only add OpenCV (headless = no GUI/X11).
#
# IMPORTANT — reproducibility: override WEBODM_VERSION to match the EXACT tag
# your WebODM runs, so the worker executes the same code as the rest of the
# stack. The default below is a concrete published tag (not `latest`); both the
# base image and OpenCV are pinned exactly so a build without arguments cannot
# drift. Published webapp tags include 3.2.0 … 3.2.4.
#
# Build:
#   docker build -t webodm-signa:local \
#     --build-arg WEBODM_VERSION=<your-webodm-image-tag> \
#     -f docker/worker.Dockerfile docker/

ARG WEBODM_VERSION=3.2.4
FROM webodm/webodm_webapp:${WEBODM_VERSION}

RUN pip install --no-cache-dir "opencv-contrib-python-headless==4.10.0.84"
