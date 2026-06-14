/*
 * Signa — "New task with Signa" button.
 *
 * Registered into the dashboard via PluginsAPI.Dashboard.addNewTaskButton, this
 * adds a second new-task entry point next to "Select Images and GCP". It runs
 * the SAME single-pass workflow as scripts/signa-singlepass.py, in the
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
    // PluginsAPI / React may not be on `window` yet when this synchronous
    // <head> script runs (the main bundle can define them slightly later), so
    // we wait for PluginsAPI before registering instead of giving up. React is
    // read inside the button callback, which runs later at trigger time.

    // ArUco dictionaries offered in the dialog — a mirror of signa/params.py
    // DICT_CHOICES (ids 0..20 = OpenCV predefined, 99 = Find-GCP custom 3x3).
    // This page is a static script (no Django rendering), so the list is
    // duplicated here; keep it in sync with params.py if that ever changes.
    var DICT_CHOICES = [
        ["0", "0 — DICT_4X4_50"], ["1", "1 — DICT_4X4_100"], ["2", "2 — DICT_4X4_250"],
        ["3", "3 — DICT_4X4_1000"], ["4", "4 — DICT_5X5_50"], ["5", "5 — DICT_5X5_100"],
        ["6", "6 — DICT_5X5_250"], ["7", "7 — DICT_5X5_1000"], ["8", "8 — DICT_6X6_50"],
        ["9", "9 — DICT_6X6_100"], ["10", "10 — DICT_6X6_250"], ["11", "11 — DICT_6X6_1000"],
        ["12", "12 — DICT_7X7_50"], ["13", "13 — DICT_7X7_100"], ["14", "14 — DICT_7X7_250"],
        ["15", "15 — DICT_7X7_1000"], ["16", "16 — DICT_ARUCO_ORIGINAL"],
        ["17", "17 — DICT_APRILTAG_16h5"], ["18", "18 — DICT_APRILTAG_25h9"],
        ["19", "19 — DICT_APRILTAG_36h10"], ["20", "20 — DICT_APRILTAG_36h11"],
        ["99", "99 — custom 3×3 (Find-GCP)"]
    ];
    function dictOptions(selected) {
        return DICT_CHOICES.map(function (d) {
            return '<option value="' + d[0] + '"' + (d[0] === selected ? ' selected' : '') + '>' + d[1] + '</option>';
        }).join('');
    }

    function csrfToken() {
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : "";
    }

    function postForm(url, fields, signal) {
        var body = Object.keys(fields)
            .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(fields[k]); })
            .join("&");
        return fetch(url, {
            method: "POST", credentials: "same-origin",
            headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/x-www-form-urlencoded" },
            body: body, signal: signal
        }).then(handle);
    }

    function postMultipart(url, formData, signal) {
        return fetch(url, {
            method: "POST", credentials: "same-origin",
            headers: { "X-CSRFToken": csrfToken() },   // let the browser set the multipart boundary
            body: formData, signal: signal
        }).then(handle);
    }

    function getJson(url, signal) {
        return fetch(url, { credentials: "same-origin", signal: signal }).then(handle);
    }

    function deleteTask(projectId, taskId) {
        // Best-effort cleanup of an orphaned partial task (cancel/error before
        // commit). Fire and forget — never block or surface a failure.
        return fetch("/api/projects/" + projectId + "/tasks/" + taskId + "/", {
            method: "DELETE", credentials: "same-origin",
            headers: { "X-CSRFToken": csrfToken() }
        }).catch(function () {});
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

    // --- i18n -------------------------------------------------------------
    // WebODM's JS catalog (jsi18n) is restricted to packages=['app'], so plugin
    // strings can't ride on it. This dialog carries its own small dictionary.
    // Language: Django's language cookie if set, else the browser language.
    var MESSAGES = {
        de: {
            "New task with Signa": "Neuer Task mit Signa",
            "Task name": "Task-Name",
            "(optional)": "(optional)",
            "Images": "Bilder",
            "Drone images containing the ArUco markers.": "Drohnenbilder mit den ArUco-Markern.",
            "GCP coordinate file": "GCP-Koordinatendatei",
            "id easting northing elevation (whitespace or comma separated).": "id Rechtswert Hochwert Höhe (durch Leerzeichen oder Komma getrennt).",
            "EPSG (target CRS)": "EPSG (Ziel-CRS)",
            "ArUco dictionary": "ArUco-Dictionary",
            "Minimum relative marker size. Lower it step by step (0.01 → 0.008 → 0.005) if markers are missed — never below 0.005. Markers should be at least 20×20 px in the image.": "Minimale relative Markergröße. Bei nicht erkannten Markern schrittweise senken (0.01 → 0.008 → 0.005) — nie unter 0.005. Marker sollten im Bild mindestens 20×20 px groß sein.",
            "Ignored margin per marker cell, compensates overexposed (burnt-in) marker borders. 0.13 (OpenCV default) up to 0.33 in strong sunlight.": "Ignorierter Rand pro Markerzelle, gleicht überbelichtete (ausgebrannte) Markerränder aus. 0.13 (OpenCV-Standard) bis 0.33 bei starkem Sonnenlicht.",
            "Color adjustment (strong sunlight)": "Farbkorrektur (starkes Sonnenlicht)",
            "Cancel": "Abbrechen",
            "Create &amp; detect GCPs": "Anlegen &amp; GCPs erkennen",
            "Please select at least 2 images.": "Bitte mindestens 2 Bilder auswählen.",
            "Please select a GCP coordinate file.": "Bitte eine GCP-Koordinatendatei auswählen.",
            "Creating task…": "Lege Task an…",
            "Uploading images…": "Lade Bilder hoch…",
            "Detecting GCPs…": "Erkenne GCPs…",
            "Detected {n} GCP entries ({m} markers). Attaching…": "{n} GCP-Einträge erkannt ({m} Marker). Hänge an…",
            "Starting processing…": "Starte Verarbeitung…",
            "Task created and processing with GCP. Closing…": "Task angelegt, Verarbeitung mit GCP läuft. Schließe…",
            "Cancelled.": "Abgebrochen.",
            "Detection timed out.": "Zeitüberschreitung bei der Erkennung."
        }
    };

    function tr(s) {
        var m = document.cookie.match(/(?:^|;\s*)django_language=([^;]+)/);
        var lang = (m ? m[1] : (navigator.language || "en")).slice(0, 2).toLowerCase();
        var dict = MESSAGES[lang];
        return (dict && dict[s]) || s;
    }

    function openDialog(projectId, onNewTaskAdded) {
        var backdrop = el("div", { "class": "modal-backdrop fade in" });
        var modal = el("div", { "class": "modal fade in", style: "display:block", role: "dialog" });
        modal.innerHTML =
            '<div class="modal-dialog">' +
              '<div class="modal-content">' +
                '<div class="modal-header">' +
                  '<button type="button" class="close" data-x>&times;</button>' +
                  '<h4 class="modal-title"><i class="fa fa-map-marker-alt"></i> ' + tr("New task with Signa") + '</h4>' +
                '</div>' +
                '<div class="modal-body">' +
                  '<div class="form-group"><label>' + tr("Task name") + '</label>' +
                    '<input type="text" class="form-control" data-name placeholder="' + tr("(optional)") + '"></div>' +
                  '<div class="form-group"><label>' + tr("Images") + '</label>' +
                    '<input type="file" data-images multiple accept=".jpg,.jpeg,.png,.tif,.tiff,image/*">' +
                    '<p class="help-block">' + tr("Drone images containing the ArUco markers.") + '</p></div>' +
                  '<div class="form-group"><label>' + tr("GCP coordinate file") + '</label>' +
                    '<input type="file" data-coords accept=".txt,.csv,text/plain">' +
                    '<p class="help-block">' + tr("id easting northing elevation (whitespace or comma separated).") + '</p></div>' +
                  '<div class="row">' +
                    '<div class="col-sm-6 form-group"><label>' + tr("EPSG (target CRS)") + '</label>' +
                      '<input type="number" class="form-control" data-epsg value="28191"></div>' +
                    '<div class="col-sm-6 form-group"><label>' + tr("ArUco dictionary") + '</label>' +
                      '<select class="form-control" data-dict>' + dictOptions("1") + '</select></div>' +
                  '</div>' +
                  '<div class="row">' +
                    '<div class="col-sm-6 form-group"><label>minrate</label>' +
                      '<input type="number" step="0.001" min="0.005" class="form-control" data-minrate value="0.01">' +
                      '<p class="help-block">' + tr("Minimum relative marker size. Lower it step by step (0.01 → 0.008 → 0.005) if markers are missed — never below 0.005. Markers should be at least 20×20 px in the image.") + '</p></div>' +
                    '<div class="col-sm-6 form-group"><label>ignore</label>' +
                      '<input type="number" step="0.01" min="0" max="0.99" class="form-control" data-ignore value="0.33">' +
                      '<p class="help-block">' + tr("Ignored margin per marker cell, compensates overexposed (burnt-in) marker borders. 0.13 (OpenCV default) up to 0.33 in strong sunlight.") + '</p></div>' +
                  '</div>' +
                  '<div class="checkbox"><label><input type="checkbox" data-adjust checked> ' + tr("Color adjustment (strong sunlight)") + '</label></div>' +
                  '<div data-status style="display:none;margin-top:10px;padding:8px 12px;border-radius:4px;background:#f3f3f3;"></div>' +
                '</div>' +
                '<div class="modal-footer">' +
                  '<button type="button" class="btn btn-default" data-x>' + tr("Cancel") + '</button>' +
                  '<button type="button" class="btn btn-primary" data-go><i class="fa fa-cogs"></i> ' + tr("Create &amp; detect GCPs") + '</button>' +
                '</div>' +
              '</div>' +
            '</div>';

        // Tracks the in-flight single-pass run so closing/cancelling can abort
        // it and clean up the partial task it created (instead of letting the
        // workflow keep running and commit a task in the background).
        var state = { cancelled: false, committed: false, taskId: null, controller: null, signal: undefined };

        function cleanup() {
            if (state.controller) { try { state.controller.abort(); } catch (e) { /* ignore */ } }
            if (state.taskId && !state.committed) {
                var tid = state.taskId;
                state.taskId = null;
                deleteTask(projectId, tid);   // fire and forget
            }
        }
        function close() {
            state.cancelled = true;
            cleanup();
            if (modal.parentNode) document.body.removeChild(modal);
            if (backdrop.parentNode) document.body.removeChild(backdrop);
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
            if (!images || images.length < 2) { status(tr("Please select at least 2 images."), "error"); return; }
            if (!coords) { status(tr("Please select a GCP coordinate file."), "error"); return; }

            var params = {
                epsg: q("[data-epsg]").value,
                dict: q("[data-dict]").value,
                minrate: q("[data-minrate]").value,
                ignore: q("[data-ignore]").value,
                adjust: q("[data-adjust]").checked ? "true" : "false"
            };
            var name = q("[data-name]").value;
            // Fresh abort scope per run, so a retry after an error is not
            // pre-aborted and does not reuse the previous orphaned task.
            state.cancelled = false;
            state.committed = false;
            state.taskId = null;
            state.controller = window.AbortController ? new AbortController() : null;
            state.signal = state.controller ? state.controller.signal : undefined;
            q("[data-go]").disabled = true;
            runSinglePass(projectId, images, coords, params, name, status, state)
                .then(function (taskId) {
                    status('<i class="fa fa-check"></i> ' + tr("Task created and processing with GCP. Closing…"), "ok");
                    setTimeout(function () { close(); if (onNewTaskAdded) onNewTaskAdded(); }, 1200);
                })
                .catch(function (e) {
                    if (state.cancelled) return;   // closed/aborted — dialog already gone
                    status('<i class="fa fa-exclamation-triangle"></i> ' + e.message, "error");
                    // Remove the orphaned partial task so a retry starts clean.
                    if (state.taskId && !state.committed) {
                        deleteTask(projectId, state.taskId);
                        state.taskId = null;
                    }
                    q("[data-go]").disabled = false;
                });
        };

        document.body.appendChild(backdrop);
        document.body.appendChild(modal);

        // Pre-fill the params from the user's saved defaults (best-effort).
        getJson("/api/plugins/signa/settings").then(function (s) {
            if (s.epsg != null) q("[data-epsg]").value = s.epsg;
            if (s.dict != null) q("[data-dict]").value = s.dict;
            if (s.minrate != null) q("[data-minrate]").value = s.minrate;
            if (s.ignore != null) q("[data-ignore]").value = s.ignore;
            if (s.adjust != null) q("[data-adjust]").checked = !!s.adjust;
        }).catch(function () {});
    }

    function runSinglePass(projectId, images, coordsFile, params, name, status, state) {
        var base = "/api/projects/" + projectId + "/tasks/";
        var sig = state.signal;
        function ck() { if (state.cancelled) throw new Error(tr("Cancelled.")); }
        status('<i class="fa fa-spinner fa-spin"></i> ' + tr("Creating task…"));
        var createFd = new FormData();
        createFd.append("partial", "true");
        if (name) createFd.append("name", name);

        return postMultipart(base, createFd, sig).then(function (task) {
            state.taskId = task.id;
            ck();
            // Upload images sequentially (robust; mirrors the script).
            var chain = Promise.resolve();
            Array.prototype.forEach.call(images, function (file, i) {
                chain = chain.then(function () {
                    ck();
                    status('<i class="fa fa-spinner fa-spin"></i> ' + tr("Uploading images…") + ' ' + (i + 1) + "/" + images.length);
                    var fd = new FormData();
                    fd.append("images", file, file.name);
                    return postMultipart(base + state.taskId + "/upload/", fd, sig);
                });
            });
            return chain;
        }).then(function () {
            ck();
            status('<i class="fa fa-spinner fa-spin"></i> ' + tr("Detecting GCPs…"));
            var fd = new FormData();
            fd.append("coords", coordsFile, "gcp_coords.txt");
            fd.append("epsg", params.epsg);
            fd.append("dict", params.dict);
            fd.append("minrate", params.minrate);
            fd.append("ignore", params.ignore);
            fd.append("adjust", params.adjust);
            return postMultipart("/api/plugins/signa/task/" + state.taskId + "/detect", fd, sig);
        }).then(function (started) {
            if (started.error) throw new Error(started.error);
            return pollDetect(state.taskId, started.celery_task_id, status, state);
        }).then(function (summary) {
            ck();
            status('<i class="fa fa-spinner fa-spin"></i> ' +
                   tr("Detected {n} GCP entries ({m} markers). Attaching…")
                       .replace("{n}", summary.detections)
                       .replace("{m}", summary.unique_markers));
            var fd = new FormData();
            fd.append("images", new Blob([summary.gcp_list], { type: "text/plain" }), "gcp_list.txt");
            return postMultipart(base + state.taskId + "/upload/", fd, sig);
        }).then(function () {
            ck();
            status('<i class="fa fa-spinner fa-spin"></i> ' + tr("Starting processing…"));
            // Mark committed BEFORE issuing the request: once commit is in
            // flight the server may have already started the task, so a lost
            // response or a cancel during commit must not delete it. A genuinely
            // failed commit leaves a recoverable partial task rather than
            // destroying a started one.
            state.committed = true;
            return postForm(base + state.taskId + "/commit/", {}, sig);
        }).then(function () {
            return state.taskId;
        });
    }

    // 30-minute safety deadline so a stuck worker never leaves the dialog
    // polling forever; also bails out as soon as the run is cancelled.
    var POLL_TIMEOUT_MS = 30 * 60 * 1000;

    function pollDetect(taskId, celeryId, status, state) {
        var url = "/api/plugins/signa/task/" + taskId + "/check/" + celeryId;
        var deadline = Date.now() + POLL_TIMEOUT_MS;
        return new Promise(function (resolve, reject) {
            (function tick() {
                if (state && state.cancelled) { reject(new Error(tr("Cancelled."))); return; }
                if (Date.now() > deadline) { reject(new Error(tr("Detection timed out."))); return; }
                getJson(url, state && state.signal).then(function (res) {
                    if (state && state.cancelled) { reject(new Error(tr("Cancelled."))); return; }
                    if (!res.ready) { setTimeout(tick, 2000); return; }
                    if (res.error) { reject(new Error(res.error)); return; }
                    resolve(res.summary || {});
                }).catch(reject);
            })();
        });
    }

    function makeButton(args) {
        var React = window.React;
        return React.createElement("button", {
            key: "signa-newtask",
            className: "btn btn-default btn-sm",
            style: { marginLeft: 4 },
            onClick: function () { openDialog(args.projectId, args.onNewTaskAdded); }
        }, React.createElement("i", { className: "fa fa-map-marker-alt" }), " Signa Task");
    }

    function ready() {
        return !!(window.PluginsAPI && window.PluginsAPI.Dashboard &&
                  window.PluginsAPI.Dashboard.addNewTaskButton);
    }

    function register() {
        try { window.PluginsAPI.Dashboard.addNewTaskButton(makeButton); } catch (e) { /* ignore */ }
    }

    // PluginsAPI is normally available synchronously (the main bundle is a
    // synchronous <script> before the plugin scripts). The poll is a defensive
    // fallback in case a setup loads it slightly later.
    if (ready()) {
        register();
    } else {
        var tries = 0;
        var iv = setInterval(function () {
            if (ready()) { clearInterval(iv); register(); }
            else if (++tries > 100) { clearInterval(iv); }
        }, 100);
    }
})();
