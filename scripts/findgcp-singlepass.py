#!/usr/bin/env python3
"""
findgcp-singlepass.py — single-pass GCP workflow against a live WebODM.

Detects ArUco GCPs on the SERVER (via the Find-GCP plugin) and feeds the result
into the SAME processing run, so a georeferenced model is produced in one pass:

    login -> create(partial) -> upload(images) -> detect -> upload(gcp_list) -> commit

Auth: a Django **session** + CSRF token (via /login/). The Find-GCP plugin API
is dispatched by WebODM's `api_view_handler`, a plain Django view that is NOT
csrf_exempt (app/api/urls.py), so a JWT token alone is rejected with HTTP 403
"CSRF verification failed". Session + X-CSRFToken is what the WebODM frontend
itself uses, and it works for the core task endpoints too.

Needs:
  - WebODM >= 2.9.5 with the Find-GCP plugin installed and enabled,
  - a worker that has OpenCV (cv2) — see docker/.

Unlike standalone/findgcp-webodm.sh (which detects LOCALLY and needs local
OpenCV/Find-GCP), this script runs detection on the server.

stdlib only — no pip install required.

Example:
    ./scripts/findgcp-singlepass.py \\
        --url http://localhost:8000 --user me --password secret \\
        --create-project "findgcp-e2e" \\
        --images ~/Downloads/findgcp-fixture \\
        --coords ~/Downloads/findgcp-fixture/gcp_coords.txt \\
        --epsg 28191 --name "fixture run" --dry-run
"""

import argparse
import glob
import http.cookiejar
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def log(msg):
    print("\033[1;34m[singlepass]\033[0m {}".format(msg), flush=True)


def warn(msg):
    print("\033[1;33m[warn]\033[0m {}".format(msg), file=sys.stderr, flush=True)


def die(msg):
    print("\033[1;31m[err ]\033[0m {}".format(msg), file=sys.stderr, flush=True)
    sys.exit(1)


def _encode_multipart(fields, files):
    """Build a multipart/form-data body.

    fields: dict of str -> str
    files:  list of (field_name, filename, bytes)
    Returns (content_type, body_bytes).
    """
    boundary = "----findgcp{}".format(uuid.uuid4().hex)
    crlf = b"\r\n"
    out = []
    for name, value in fields.items():
        out.append(b"--" + boundary.encode())
        out.append('Content-Disposition: form-data; name="{}"'.format(name).encode())
        out.append(b"")
        out.append(str(value).encode())
    for field, filename, content in files:
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        out.append(b"--" + boundary.encode())
        out.append('Content-Disposition: form-data; name="{}"; filename="{}"'
                   .format(field, filename).encode())
        out.append("Content-Type: {}".format(ctype).encode())
        out.append(b"")
        out.append(content)
    out.append(b"--" + boundary.encode() + b"--")
    out.append(b"")
    body = crlf.join(out)
    return "multipart/form-data; boundary={}".format(boundary), body


class WebODM:
    def __init__(self, base_url, timeout=600):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urlrequest.build_opener(urlrequest.HTTPCookieProcessor(self.jar))

    def _csrf(self):
        for c in self.jar:
            if c.name == "csrftoken":
                return c.value
        return None

    def _headers(self, method, extra=None):
        h = {"Accept": "application/json"}
        if method not in SAFE_METHODS:
            token = self._csrf()
            if token:
                h["X-CSRFToken"] = token
            h["Referer"] = self.base + "/"   # satisfies Django's CSRF referer check on HTTPS
        if extra:
            h.update(extra)
        return h

    def _request(self, method, path, headers=None, data=None):
        url = path if path.startswith("http") else self.base + path
        req = urlrequest.Request(url, data=data, method=method,
                                 headers=self._headers(method, headers))
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            raise RuntimeError("HTTP {} on {} {}: {}".format(e.code, method, path, body[:800]))
        except URLError as e:
            raise RuntimeError("connection error on {} {}: {}".format(method, path, e))
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return raw

    def get(self, path):
        return self._request("GET", path)

    def post_form(self, path, fields):
        return self._request("POST", path,
                             {"Content-Type": "application/x-www-form-urlencoded"},
                             urlencode(fields).encode())

    def post_multipart(self, path, fields=None, files=None):
        ctype, body = _encode_multipart(fields or {}, files or [])
        return self._request("POST", path, {"Content-Type": ctype}, body)

    # --- auth (session + CSRF) ---

    def login(self, username, password):
        # GET the login page to obtain the csrftoken cookie + the form token.
        with self.opener.open(self.base + "/login/", timeout=self.timeout) as r:
            html = r.read().decode("utf-8", "replace")
        m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
        if not m:
            raise RuntimeError("could not find a CSRF token on /login/")
        self.post_form("/login/", {
            "csrfmiddlewaretoken": m.group(1),
            "username": username,
            "password": password,
            "next": "/",
        })
        if not any(c.name == "sessionid" for c in self.jar):
            raise RuntimeError("login failed (no session cookie) — check credentials")

    # --- high-level steps ---

    def create_project(self, name):
        return self.post_form("/api/projects/", {"name": name})["id"]

    def create_partial_task(self, project_id, name=None, options=None, node="auto"):
        fields = {"partial": "true"}
        if name:
            fields["name"] = name
        if node and node != "auto":
            fields["processing_node"] = node
        if options:
            fields["options"] = json.dumps(options)
        return self.post_multipart("/api/projects/{}/tasks/".format(project_id), fields)["id"]

    def upload_file(self, project_id, task_id, path_or_name, content=None, retries=3):
        if content is None:
            with open(path_or_name, "rb") as f:
                content = f.read()
        filename = os.path.basename(path_or_name)
        last = None
        for attempt in range(1, retries + 1):
            try:
                return self.post_multipart(
                    "/api/projects/{}/tasks/{}/upload/".format(project_id, task_id),
                    files=[("images", filename, content)])
            except RuntimeError as e:
                last = e
                warn("upload {} failed (attempt {}/{}): {}".format(filename, attempt, retries, e))
                time.sleep(2 * attempt)
        raise last

    def commit(self, project_id, task_id):
        return self.post_form(
            "/api/projects/{}/tasks/{}/commit/".format(project_id, task_id), {})

    def remove_task(self, project_id, task_id):
        """Best-effort delete of a partial task. Used to clean up after a
        failure so a half-built task is not left orphaned in the project."""
        try:
            self._request("DELETE", "/api/projects/{}/tasks/{}/".format(project_id, task_id))
        except Exception as e:  # noqa: BLE001 - cleanup must never mask the original error
            warn("could not remove partial task {}: {}".format(task_id, e))

    # --- plugin detection ---

    def detect(self, task_id, coords_path, epsg, dict_id, minrate, ignore, adjust,
               poll_interval=2, poll_timeout=1800):
        with open(coords_path, "rb") as f:
            coords = f.read()
        fields = {"epsg": epsg, "dict": dict_id, "minrate": minrate,
                  "ignore": ignore, "adjust": "true" if adjust else "false"}
        started = self.post_multipart(
            "/api/plugins/findgcp/task/{}/detect".format(task_id),
            fields, [("coords", "gcp_coords.txt", coords)])
        if started.get("error"):
            raise RuntimeError("detection rejected: {}".format(started["error"]))
        cid = started.get("celery_task_id")
        if not cid:
            raise RuntimeError("detect did not return a celery_task_id: {}".format(started))

        deadline = time.time() + poll_timeout
        while time.time() < deadline:
            res = self.get("/api/plugins/findgcp/task/{}/check/{}".format(task_id, cid))
            if not res.get("ready"):
                time.sleep(poll_interval)
                continue
            if res.get("error"):
                raise RuntimeError("detection failed: {}".format(res["error"]))
            return res.get("summary", {})
        raise RuntimeError("detection timed out after {}s".format(poll_timeout))


def find_images(images_arg):
    if os.path.isdir(images_arg):
        return [os.path.join(images_arg, n) for n in sorted(os.listdir(images_arg))
                if n.lower().endswith(IMAGE_EXTS)]
    return sorted(glob.glob(images_arg))


def main():
    ap = argparse.ArgumentParser(
        description="Single-pass GCP workflow against a live WebODM "
                    "(server-side ArUco detection via the Find-GCP plugin).")
    ap.add_argument("--url", required=True, help="WebODM base URL, e.g. http://localhost:8000")
    ap.add_argument("--user", required=True, help="WebODM username")
    ap.add_argument("--password", default=os.environ.get("WEBODM_PASS"),
                    help="WebODM password (or env WEBODM_PASS)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--project", type=int, help="existing project id")
    g.add_argument("--create-project", metavar="NAME", help="create a new project")
    ap.add_argument("--images", required=True, help="image directory or glob")
    ap.add_argument("--coords", required=True, help="GCP coordinate file (id easting northing elevation)")
    ap.add_argument("--epsg", type=int, default=28191)
    ap.add_argument("--dict", dest="dict_id", type=int, default=1, help="ArUco dict (1=4x4_100, 99=custom 3x3)")
    ap.add_argument("--minrate", type=float, default=0.01)
    ap.add_argument("--ignore", type=float, default=0.33)
    ap.add_argument("--no-adjust", dest="adjust", action="store_false", default=True)
    ap.add_argument("--name", default=None, help="task name")
    ap.add_argument("--node", default="auto", help="processing node id (default: auto)")
    ap.add_argument("--options", default=None, help="WebODM processing options as JSON")
    ap.add_argument("--dry-run", action="store_true",
                    help="stop before commit (detect + attach GCP, but do not start processing)")
    ap.add_argument("--keep-on-error", action="store_true",
                    help="do not delete the partial task if a step fails (default: clean up)")
    args = ap.parse_args()

    if not args.password:
        die("provide --password or set WEBODM_PASS.")

    images = find_images(args.images)
    if len(images) < 2:
        die("need at least 2 images, found {} in {}".format(len(images), args.images))
    if not os.path.isfile(args.coords):
        die("coordinate file not found: {}".format(args.coords))
    options = json.loads(args.options) if args.options else None

    wo = WebODM(args.url)
    log("logging in as {} ...".format(args.user))
    wo.login(args.user, args.password)

    project_id = args.project
    if args.create_project:
        project_id = wo.create_project(args.create_project)
        log("created project {} ({})".format(project_id, args.create_project))

    log("creating partial task ...")
    task_id = wo.create_partial_task(project_id, name=args.name, options=options, node=args.node)
    log("task {} (partial)".format(task_id))

    process_task(wo, project_id, task_id, images, args)


def process_task(wo, project_id, task_id, images, args):
    """Attach GCP to an existing partial task via detection, then commit.

    Cleanup contract (covered by tests/test_singlepass.py):
      * any failure *before* commit removes the partial task, so the run does
        not leave a half-built orphan in the project — unless --keep-on-error;
      * once commit is in flight the task is *kept* even on failure, because the
        server may already have started processing (a lost response / Ctrl-C
        must not delete a started task); a genuinely rejected commit leaves a
        recoverable partial task instead;
      * --dry-run stops before commit and keeps the prepared (uncommitted) task.
    """
    keep = False
    try:
        log("uploading {} images ...".format(len(images)))
        for i, img in enumerate(images, 1):
            wo.upload_file(project_id, task_id, img)
            if i % 10 == 0 or i == len(images):
                log("  uploaded {}/{}".format(i, len(images)))

        log("running server-side GCP detection ...")
        summary = wo.detect(task_id, args.coords, args.epsg, args.dict_id,
                            args.minrate, args.ignore, args.adjust)
        log("detection: {} entries, {} unique markers, weak={}".format(
            summary.get("detections"), summary.get("unique_markers"), summary.get("weak_markers")))
        for key in ("coord_skipped_lines", "coord_duplicate_ids", "unmatched_ids"):
            if summary.get(key):
                warn("{}: {}".format(key, summary[key]))
        gcp_list = summary.get("gcp_list")
        if not gcp_list:
            raise RuntimeError("detection produced no gcp_list")

        log("attaching gcp_list.txt to the task ...")
        wo.upload_file(project_id, task_id, "gcp_list.txt", content=gcp_list.encode("ascii"))

        if args.dry_run:
            keep = True
            log("--dry-run: task {} is prepared with GCP but NOT committed.".format(task_id))
            log("Inspect it, then commit via the UI or:")
            log("  POST {}/api/projects/{}/tasks/{}/commit/".format(args.url, project_id, task_id))
            return

        log("committing — processing starts WITH the GCP ...")
        # Mark the task as kept BEFORE issuing commit: once the request is in
        # flight the server may have already started processing, so a lost
        # response or Ctrl-C during commit must not delete a started task. A
        # genuinely rejected commit leaves a recoverable partial task instead.
        keep = True
        wo.commit(project_id, task_id)
        log("done. Task {} is processing with georeferencing.".format(task_id))
        log("  {}/dashboard/?project_task_open={}".format(args.url, task_id))
    except BaseException:
        if not keep and not args.keep_on_error:
            warn("cleaning up partial task {} after failure ...".format(task_id))
            wo.remove_task(project_id, task_id)
        raise


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        die("interrupted.")
    except RuntimeError as e:
        die(str(e))
