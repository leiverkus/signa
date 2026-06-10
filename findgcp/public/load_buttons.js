/*
 * Find-GCP — "New task with Find-GCP" button.
 *
 * Registered into the dashboard via PluginsAPI.Dashboard.addNewTaskButton, this
 * adds a second new-task entry point next to "Select Images and GCP". It runs
 * the SAME single-pass workflow as scripts/findgcp-singlepass.py, in the
 * browser, so a georeferenced model is produced in one processing run:
 *
 *   create(partial) -> upload(images) -> detect (plugin) -> upload(gcp_list) -> commit
 *
 * No JSX/webpack build: the button is a plain React.createElement and the dialog
 * is vanilla DOM (Bootstrap 3 classes, like the rest of WebODM). Requests are
 * same-origin, so the session cookie is sent and we add X-CSRFToken (the plugin
 * API is not csrf_exempt — see docs/single-pass-design.md).
 */
(function () {
    if (!window.PluginsAPI || !window.React) return;
    var React = window.React;

    function csrfToken() {
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : "";
    }

    function postForm(url, fields) {
        var body = Object.keys(fields)
            .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(fields[k]); })
            .join("&");
        return fetch(url, {
            method: "POST", credentials: "same-origin",
            headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/x-www-form-urlencoded" },
            body: body
        }).then(handle);
    }

    function postMultipart(url, formData) {
        return fetch(url, {
            method: "POST", credentials: "same-origin",
            headers: { "X-CSRFToken": csrfToken() },   // let the browser set the multipart boundary
            body: formData
        }).then(handle);
    }

    function getJson(url) {
        return fetch(url, { credentials: "same-origin" }).then(handle);
    }

    function handle(r) {
        return r.text().then(function (t) {
            var data;
            try { data = JSON.parse(t); } catch (e) { data = t; }
            if (!r.ok) {
                var msg = (data && data.detail) || (data && data.error) || (typeof data === "string" ? data.slice(0, 200) : r.statusText);
                throw new Error("HTTP " + r.status + ": " + msg);
            }
            return data;
        });
    }

    function el(tag, attrs, html) {
        var e = document.createElement(tag);
        if (attrs) Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
        if (html !== undefined) e.innerHTML = html;
        return e;
    }

    function openDialog(projectId, onNewTaskAdded) {
        var backdrop = el("div", { "class": "modal-backdrop fade in" });
        var modal = el("div", { "class": "modal fade in", style: "display:block", role: "dialog" });
        modal.innerHTML =
            '<div class="modal-dialog">' +
              '<div class="modal-content">' +
                '<div class="modal-header">' +
                  '<button type="button" class="close" data-x>&times;</button>' +
                  '<h4 class="modal-title"><i class="fa fa-map-marker-alt"></i> New task with Find-GCP</h4>' +
                '</div>' +
                '<div class="modal-body">' +
                  '<div class="form-group"><label>Task name</label>' +
                    '<input type="text" class="form-control" data-name placeholder="(optional)"></div>' +
                  '<div class="form-group"><label>Images</label>' +
                    '<input type="file" data-images multiple accept=".jpg,.jpeg,.png,.tif,.tiff,image/*">' +
                    '<p class="help-block">Drone images containing the ArUco markers.</p></div>' +
                  '<div class="form-group"><label>GCP coordinate file</label>' +
                    '<input type="file" data-coords accept=".txt,.csv,text/plain">' +
                    '<p class="help-block">id easting northing elevation (whitespace or comma separated).</p></div>' +
                  '<div class="row">' +
                    '<div class="col-sm-3 form-group"><label>EPSG</label>' +
                      '<input type="number" class="form-control" data-epsg value="28191"></div>' +
                    '<div class="col-sm-3 form-group"><label>Dictionary</label>' +
                      '<select class="form-control" data-dict><option value="1" selected>1 — 4x4_100</option><option value="99">99 — 3x3</option></select></div>' +
                    '<div class="col-sm-3 form-group"><label>minrate</label>' +
                      '<input type="number" step="0.001" min="0.005" class="form-control" data-minrate value="0.01"></div>' +
                    '<div class="col-sm-3 form-group"><label>ignore</label>' +
                      '<input type="number" step="0.01" min="0" max="0.99" class="form-control" data-ignore value="0.33"></div>' +
                  '</div>' +
                  '<div class="checkbox"><label><input type="checkbox" data-adjust checked> Color adjustment (strong sunlight)</label></div>' +
                  '<div data-status style="display:none;margin-top:10px;padding:8px 12px;border-radius:4px;background:#f3f3f3;"></div>' +
                '</div>' +
                '<div class="modal-footer">' +
                  '<button type="button" class="btn btn-default" data-x>Cancel</button>' +
                  '<button type="button" class="btn btn-primary" data-go><i class="fa fa-cogs"></i> Create &amp; detect GCPs</button>' +
                '</div>' +
              '</div>' +
            '</div>';

        function close() {
            document.body.removeChild(modal);
            document.body.removeChild(backdrop);
        }
        function q(sel) { return modal.querySelector(sel); }
        function status(html, kind) {
            var s = q("[data-status]");
            s.style.display = "block";
            s.style.background = kind === "error" ? "#f8d7da" : (kind === "ok" ? "#d4edda" : "#f3f3f3");
            s.innerHTML = html;
        }

        Array.prototype.forEach.call(modal.querySelectorAll("[data-x]"), function (b) { b.onclick = close; });

        q("[data-go]").onclick = function () {
            var images = q("[data-images]").files;
            var coords = q("[data-coords]").files[0];
            if (!images || images.length < 2) { status("Please select at least 2 images.", "error"); return; }
            if (!coords) { status("Please select a GCP coordinate file.", "error"); return; }

            var params = {
                epsg: q("[data-epsg]").value,
                dict: q("[data-dict]").value,
                minrate: q("[data-minrate]").value,
                ignore: q("[data-ignore]").value,
                adjust: q("[data-adjust]").checked ? "true" : "false"
            };
            var name = q("[data-name]").value;
            q("[data-go]").disabled = true;
            runSinglePass(projectId, images, coords, params, name, status)
                .then(function (taskId) {
                    status('<i class="fa fa-check"></i> Task created and processing with GCP. Closing…', "ok");
                    setTimeout(function () { close(); if (onNewTaskAdded) onNewTaskAdded(); }, 1200);
                })
                .catch(function (e) {
                    status('<i class="fa fa-exclamation-triangle"></i> ' + e.message, "error");
                    q("[data-go]").disabled = false;
                });
        };

        document.body.appendChild(backdrop);
        document.body.appendChild(modal);
    }

    function runSinglePass(projectId, images, coordsFile, params, name, status) {
        var base = "/api/projects/" + projectId + "/tasks/";
        var taskId;
        status('<i class="fa fa-spinner fa-spin"></i> Creating task…');
        var createFd = new FormData();
        createFd.append("partial", "true");
        if (name) createFd.append("name", name);

        return postMultipart(base, createFd).then(function (task) {
            taskId = task.id;
            // Upload images sequentially (robust; mirrors the script).
            var chain = Promise.resolve();
            Array.prototype.forEach.call(images, function (file, i) {
                chain = chain.then(function () {
                    status('<i class="fa fa-spinner fa-spin"></i> Uploading images… ' + (i + 1) + "/" + images.length);
                    var fd = new FormData();
                    fd.append("images", file, file.name);
                    return postMultipart(base + taskId + "/upload/", fd);
                });
            });
            return chain;
        }).then(function () {
            status('<i class="fa fa-spinner fa-spin"></i> Detecting GCPs…');
            var fd = new FormData();
            fd.append("coords", coordsFile, "gcp_coords.txt");
            fd.append("epsg", params.epsg);
            fd.append("dict", params.dict);
            fd.append("minrate", params.minrate);
            fd.append("ignore", params.ignore);
            fd.append("adjust", params.adjust);
            return postMultipart("/api/plugins/findgcp/task/" + taskId + "/detect", fd);
        }).then(function (started) {
            if (started.error) throw new Error(started.error);
            return pollDetect(taskId, started.celery_task_id, status);
        }).then(function (summary) {
            status('<i class="fa fa-spinner fa-spin"></i> Detected ' + summary.detections +
                   " GCP entries (" + summary.unique_markers + " markers). Attaching…");
            var fd = new FormData();
            fd.append("images", new Blob([summary.gcp_list], { type: "text/plain" }), "gcp_list.txt");
            return postMultipart(base + taskId + "/upload/", fd);
        }).then(function () {
            status('<i class="fa fa-spinner fa-spin"></i> Starting processing…');
            return postForm(base + taskId + "/commit/", {});
        }).then(function () {
            return taskId;
        });
    }

    function pollDetect(taskId, celeryId, status) {
        var url = "/api/plugins/findgcp/task/" + taskId + "/check/" + celeryId;
        return new Promise(function (resolve, reject) {
            (function tick() {
                getJson(url).then(function (res) {
                    if (!res.ready) { setTimeout(tick, 2000); return; }
                    if (res.error) { reject(new Error(res.error)); return; }
                    resolve(res.summary || {});
                }).catch(reject);
            })();
        });
    }

    PluginsAPI.Dashboard.addNewTaskButton(function (args) {
        return React.createElement("button", {
            key: "findgcp-newtask",
            className: "btn btn-default",
            style: { marginLeft: 4 },
            onClick: function () { openDialog(args.projectId, args.onNewTaskAdded); }
        }, React.createElement("i", { className: "fa fa-map-marker-alt" }), " Find-GCP Task");
    });
})();
