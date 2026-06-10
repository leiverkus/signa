# Find-GCP → WebODM Workflow

Automated workflow for processing archaeological drone surveys: ArUco GCP
detection with [Find-GCP](https://github.com/zsiki/Find-GCP), preparation for
[WebODM](https://docs.webodm.org) (ODX engine), and integration into a
PostGIS / GeoDjango / QFieldCloud stack. Built for survey sites with
GNSS-measured ground control.

The core is a single Bash script, [`findgcp-webodm.sh`](findgcp-webodm.sh),
that wraps the following pipeline:

1. **Detection** — find ArUco markers in the images (`gcp_find.py`)
2. **Report** — sanity check: which GCP on how many images, warnings
3. **Check** *(optional)* — visual review via `gcp_check.py`
4. **Prep** *(optional)* — WebODM-ready folder structure (images as symlinks)
5. **Upload** *(optional)* — direct task upload via the WebODM API

## Requirements

- **Bash** 4+
- **Python** 3.10+ with OpenCV incl. ArUco contrib:
  ```bash
  pip install opencv-python opencv-contrib-python
  ```
- **Find-GCP** checked out locally (default path: `~/src/Find-GCP`):
  ```bash
  git clone https://github.com/zsiki/Find-GCP ~/src/Find-GCP
  ```
- `jq` and `curl` — only for the optional `--upload` step

## Quick start

```bash
# Simple run with the regional default (EPSG:28191, 4x4 markers)
./findgcp-webodm.sh \
  -i ~/fieldwork/zira2026/raw \
  -c gcp_coords.txt \
  -o ~/fieldwork/zira2026/processed
```

The GCP coordinate file uses the format `id easting northing elevation` and
must **already be in the target CRS** — WebODM does not reproject anything
(see below).

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-i, --images DIR` | directory with drone images *(required)* | — |
| `-c, --coords FILE` | GCP coordinate file *(required)* | — |
| `-o, --output DIR` | output directory *(required)* | — |
| `-e, --epsg CODE` | EPSG code of the GCP coordinates | `28191` |
| `-d, --dict ID` | ArUco dictionary (1 = 4x4_100, 99 = 3x3 custom) | `1` |
| `-p, --pattern GLOB` | image file glob | `*.JPG` |
| `--minrate VAL` | min. relative marker size | `0.01` |
| `--ignore VAL` | pixel ignore rate (burnt-in protection) | `0.33` |
| `--no-adjust` | disable color adjustment | on |
| `--findgcp-dir DIR` | path to the Find-GCP installation | `~/src/Find-GCP` |
| `--check` | `gcp_check.py` GUI after detection | off |
| `--prep` | build a WebODM-ready folder structure | off |
| `--upload` | upload via the WebODM API | off |
| `--webodm-url / --webodm-user / --webodm-pass / --project` | upload parameters | — |

Full help: `./findgcp-webodm.sh --help`.

### Examples

```bash
# 3x3 custom markers, smaller minimum size
./findgcp-webodm.sh -i ./images -c gcps.txt -o ./out -d 99 --minrate 0.01

# ITM (Israeli standard CRS) instead of Palestine Belt
./findgcp-webodm.sh -i ./images -c gcps.txt -o ./out -e 2039

# Full pipeline including upload
WEBODM_PASS=secret ./findgcp-webodm.sh -i ./images -c gcps.txt -o ./out \
  --prep --upload --webodm-url http://192.168.1.10:8000 \
  --webodm-user user --project "Site-Area3-2026"
```

## Coordinate reference systems

Always measure GCP coordinates in the target CRS, or reproject them beforehand —
never let WebODM do the conversion. The image EXIF (WGS84) and the GCP CRS may
differ; ODX reprojects the EXIF internally.

| EPSG | Name | When? |
|------|------|-------|
| `28191` | Palestine 1923 / Palestine Belt | regional default, West Bank, Jerusalem |
| `2039`  | Israeli Transverse Mercator (ITM) | modern Israeli standard CRS |
| `32636` | UTM zone 36N | generic Israel |
| `32637` | UTM zone 37N | Jordan |
| `4326`  | WGS84 geographic | only as input CRS from EXIF GPS |

## Output structure

```
<output>/
├── gcp_list.txt              # ODM-compatible GCP file (Find-GCP output)
├── gcp_report.txt            # sanity report
├── findgcp_<timestamp>.log
└── webodm_ready/             # only with --prep
    ├── images/               # symlinks (saves space on 1000+ images)
    ├── gcp_list.txt
    └── README_webodm.md      # recommended WebODM task options
```

## Known pitfalls

- **Strong sunlight**: the default `--ignore 0.33` is tuned for harsh summer
  light; consider printing gray markers instead of white.
- **DJI EXIF altitudes** are relative to take-off, not absolute — fine for the
  bundle block, but not for direct DEM validation against GCP heights.
- **`gcp_check.py` needs X11/display** — on headless servers use `ssh -X` or
  omit `--check`.
- **WebODM ODX ≠ ODM**: decoupled since 04/2026; uses the `webodm/odx`
  containers, not `opendronemap/*`.

## Development

```bash
bash -n findgcp-webodm.sh   # syntax check
shellcheck findgcp-webodm.sh
```

CI runs `shellcheck` automatically (see
[`.github/workflows/shellcheck.yml`](.github/workflows/shellcheck.yml)).

## License

[MIT](LICENSE) © 2026 Patrick Leiverkus

## References

- Find-GCP: <https://github.com/zsiki/Find-GCP>
- WebODM docs: <https://docs.webodm.org>
- ArUco detector parameters: <https://docs.opencv.org/trunk/d5/dae/tutorial_aruco_detection.html>
- Siki 2021, *Baltic Journal of Modern Computing*:
  <https://www.bjmc.lu.lv/fileadmin/user_upload/lu_portal/projekti/bjmc/Contents/9_1_06_Siki.pdf>
