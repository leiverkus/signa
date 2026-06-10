# Find-GCP for WebODM

A [WebODM](https://github.com/WebODM/WebODM) plugin for **automatic ArUco ground
control point detection**. It detects ArUco markers in a task's images, matches
them against your measured GCP coordinates and produces an ODM-compatible
`gcp_list.txt` — directly inside WebODM, no command line required.

The detection logic is ported from [Find-GCP](https://github.com/zsiki/Find-GCP)
(`gcp_find.py`) and runs server-side in the WebODM worker.

A standalone Bash CLI for the same workflow (run Find-GCP outside WebODM and
optionally upload via the API) is kept under [`standalone/`](standalone/).

## Install in WebODM

1. Download `findgcp-<version>.zip` from the
   [Releases](https://github.com/leiverkus/Find-GCP-WebODM-Workflow/releases) page.
2. In WebODM: **Administration → Plugins → Load Plugin (.zip)** and upload the zip.
3. Enable the plugin. A **Find-GCP** entry appears in the main menu.

The plugin declares `opencv-contrib-python-headless` and `numpy` in
`requirements.txt`; WebODM installs these when the plugin is built. They must be
available to the **worker** container that runs the detection.

## Usage

Open **Find-GCP** from the menu, then:

1. Pick a **project** and a **task** (the task must already have its images).
2. Upload the **GCP coordinate file** — one marker per line:
   `id easting northing elevation` (whitespace or comma separated).
3. Set the parameters (see below) and click **Detect GCPs**.
4. Review the summary (markers, image counts, warnings) and **download
   `gcp_list.txt`**. Add it to the task's GCP field before processing.

### Parameters

| Field | Maps to (Find-GCP) | Default | Notes |
|-------|--------------------|---------|-------|
| EPSG | `--epsg` | `28191` | target CRS of the coordinates; written as the `gcp_list.txt` header |
| ArUco dictionary | `-d` | `1` (DICT_4X4_100) | `99` = custom 3×3 |
| minrate | `--minrate` → `minMarkerPerimeterRate` | `0.01` | lower to detect smaller markers (don't go below ~0.005) |
| ignore | `--ignore` → `perspectiveRemoveIgnoredMarginPerCell` | `0.33` | burnt-in protection for strong sunlight |
| Color adjustment | `--adjust` | on | LUT correction against overexposure |

> Always measure GCP coordinates in the target CRS (or reproject beforehand) —
> WebODM does not reproject them. The image EXIF (WGS84) may differ; ODX
> reprojects the EXIF internally.

## Plugin layout

```
findgcp/                  # ← single root dir required by WebODM's plugin loader
├── __init__.py
├── manifest.json         # name, version, webodmMinVersion, …
├── plugin.py             # Plugin(PluginBase): menu, app + API mount points
├── api.py                # detect / check / download endpoints (DRF TaskView)
├── gcp_detect.py         # ported ArUco detection (runs in the worker)
├── requirements.txt      # opencv-contrib-python-headless, numpy
├── templates/app.html    # UI (vanilla JS + fetch, no JSX build)
└── public/               # style.css, icon.svg
```

This mirrors WebODM's core-plugin conventions (cf. `coreplugins/contours`,
`coreplugins/posm-gcpi`). The loader (`app/admin.py → plugin_upload`) requires
the archive to contain **exactly one** root directory holding `plugin.py`,
`manifest.json` and `__init__.py`.

## Building the release zip

```bash
./build-plugin.sh          # → dist/findgcp-<version>.zip
```

The script reads the version from `manifest.json`, zips the `findgcp/` directory
as a single root folder, and verifies the archive structure.

**Automated releases:** push a tag matching the manifest version to build the
zip and publish a GitHub Release with the archive attached:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

See [`.github/workflows/release.yml`](.github/workflows/release.yml). CI
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs shellcheck, a
Python compile-check and a test build on every push/PR.

## Standalone CLI (alternative)

If you prefer to run detection outside WebODM, the original Bash pipeline is in
[`standalone/findgcp-webodm.sh`](standalone/findgcp-webodm.sh) — it wraps
Find-GCP (`gcp_find.py`), builds a sanity report and can prep/upload a
WebODM-ready folder. Run `standalone/findgcp-webodm.sh --help` for details.

## License

[MIT](LICENSE) © 2026 Patrick Leiverkus

## References

- WebODM: <https://github.com/WebODM/WebODM>
- Find-GCP: <https://github.com/zsiki/Find-GCP>
- ArUco detector parameters: <https://docs.opencv.org/trunk/d5/dae/tutorial_aruco_detection.html>
- Siki 2021, *Baltic Journal of Modern Computing*:
  <https://www.bjmc.lu.lv/fileadmin/user_upload/lu_portal/projekti/bjmc/Contents/9_1_06_Siki.pdf>
