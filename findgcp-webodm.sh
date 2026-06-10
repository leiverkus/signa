#!/usr/bin/env bash
#
# findgcp-webodm.sh
# -----------------
# Automates the Find-GCP → WebODM workflow for archaeological drone
# surveys using ArUco markers.
#
# Pipeline:
#   1. Detect ArUco markers in the images (Find-GCP / gcp_find.py)
#   2. Statistics & sanity check (which GCPs on how many images?)
#   3. Optional visual review via gcp_check.py
#   4. Build a WebODM-ready folder structure
#   5. Optional upload via the WebODM API (NodeODX endpoint)
#
# License: MIT

set -euo pipefail
IFS=$'\n\t'

# ---------- Defaults ----------
FINDGCP_DIR="${FINDGCP_DIR:-$HOME/src/Find-GCP}"
EPSG="28191"               # Palestine 1923 / Palestine Belt - project default CRS
ARUCO_DICT="1"             # 1 = DICT_4X4_100, 99 = custom 3x3
MINRATE="0.01"             # rel. minimum marker size
IGNORE="0.33"              # burnt-in protection for strong sunlight
ADJUST="--adjust"          # color LUT against overexposure (set empty to disable)
IMAGE_PATTERN="*.JPG"
DO_CHECK="false"
DO_PREP="false"
DO_UPLOAD="false"
WEBODM_URL=""
WEBODM_USER=""
WEBODM_PASS=""
PROJECT_NAME=""

# ---------- Helpers ----------
log()  { printf "\033[1;34m[%s]\033[0m %s\n" "$(date +%H:%M:%S)" "$*"; }
warn() { printf "\033[1;33m[WARN]\033[0m %s\n" "$*" >&2; }
err()  { printf "\033[1;31m[ERR ]\033[0m %s\n" "$*" >&2; exit 1; }

usage() {
  cat <<EOF
findgcp-webodm.sh - Find-GCP → WebODM workflow

USAGE:
  $0 -i <image_dir> -c <gcp_coords.txt> -o <output_dir> [OPTIONS]

REQUIRED:
  -i, --images DIR        directory with drone images
  -c, --coords FILE       GCP coordinate file (id easting northing elevation)
  -o, --output DIR        output directory for gcp_list.txt + reports

OPTIONAL:
  -e, --epsg CODE         EPSG code of the GCP coordinates (default: $EPSG)
  -d, --dict ID           ArUco dictionary ID (default: $ARUCO_DICT, 99 for 3x3 custom)
  -p, --pattern GLOB      image file glob (default: $IMAGE_PATTERN)
  --minrate VAL           min. relative marker size (default: $MINRATE)
  --ignore VAL            pixel ignore rate for burnt-in (default: $IGNORE)
  --no-adjust             disable color adjustment
  --findgcp-dir DIR       path to the Find-GCP installation (default: $FINDGCP_DIR)

WORKFLOW OPTIONS:
  --check                 launch the gcp_check.py GUI after detection
  --prep                  build a WebODM-ready folder structure
  --upload                upload to a WebODM server via the NodeODX API
  --webodm-url URL        e.g. http://webodm.example.org:8000
  --webodm-user USER      WebODM username
  --webodm-pass PASS      WebODM password (or via WEBODM_PASS env)
  --project NAME          project name in WebODM

  -h, --help              this help

EXAMPLES:

  # Simple run with the regional default (EPSG:28191, 4x4 markers):
  $0 -i ~/fieldwork/zira2025/raw -c gcps.txt -o ~/fieldwork/zira2025/processed

  # 3x3 custom markers, smaller minimum size:
  $0 -i ./images -c gcps.txt -o ./out -d 99 --minrate 0.01

  # ITM (Israeli standard CRS) instead of Palestine Belt:
  $0 -i ./images -c gcps.txt -o ./out -e 2039

  # With visual check:
  $0 -i ./images -c gcps.txt -o ./out --check

  # Full pipeline including upload:
  $0 -i ./images -c gcps.txt -o ./out --prep --upload \\
     --webodm-url http://192.168.1.10:8000 --webodm-user user \\
     --project "Site-Area3-2026"

EOF
  exit 0
}

# ---------- Argument parsing ----------
IMAGES=""
COORDS=""
OUTPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--images)        IMAGES="$2"; shift 2 ;;
    -c|--coords)        COORDS="$2"; shift 2 ;;
    -o|--output)        OUTPUT="$2"; shift 2 ;;
    -e|--epsg)          EPSG="$2"; shift 2 ;;
    -d|--dict)          ARUCO_DICT="$2"; shift 2 ;;
    -p|--pattern)       IMAGE_PATTERN="$2"; shift 2 ;;
    --minrate)          MINRATE="$2"; shift 2 ;;
    --ignore)           IGNORE="$2"; shift 2 ;;
    --no-adjust)        ADJUST=""; shift ;;
    --findgcp-dir)      FINDGCP_DIR="$2"; shift 2 ;;
    --check)            DO_CHECK="true"; shift ;;
    --prep)             DO_PREP="true"; shift ;;
    --upload)           DO_UPLOAD="true"; shift ;;
    --webodm-url)       WEBODM_URL="$2"; shift 2 ;;
    --webodm-user)      WEBODM_USER="$2"; shift 2 ;;
    --webodm-pass)      WEBODM_PASS="$2"; shift 2 ;;
    --project)          PROJECT_NAME="$2"; shift 2 ;;
    -h|--help)          usage ;;
    *)                  err "Unknown argument: $1 (see -h)" ;;
  esac
done

# ---------- Validation ----------
[[ -z "$IMAGES" ]] && err "Missing: -i / --images"
[[ -z "$COORDS" ]] && err "Missing: -c / --coords"
[[ -z "$OUTPUT" ]] && err "Missing: -o / --output"
[[ ! -d "$IMAGES" ]] && err "Image directory does not exist: $IMAGES"
[[ ! -f "$COORDS" ]] && err "Coordinate file does not exist: $COORDS"

GCP_FIND="$FINDGCP_DIR/gcp_find.py"
GCP_CHECK="$FINDGCP_DIR/gcp_check.py"
[[ ! -f "$GCP_FIND" ]] && err "gcp_find.py not found in $FINDGCP_DIR (set --findgcp-dir or FINDGCP_DIR)"

# Check Python dependencies
python3 -c "import cv2" 2>/dev/null || err "OpenCV (cv2) missing. Install with: pip install opencv-python opencv-contrib-python"
python3 -c "import cv2.aruco" 2>/dev/null || err "OpenCV-contrib missing. Install with: pip install opencv-contrib-python"

mkdir -p "$OUTPUT"
GCP_LIST="$OUTPUT/gcp_list.txt"
LOG_FILE="$OUTPUT/findgcp_$(date +%Y%m%d_%H%M%S).log"
REPORT_FILE="$OUTPUT/gcp_report.txt"

# ---------- 1. GCP detection ----------
log "=== Find-GCP detection ==="
log "Images:    $IMAGES ($IMAGE_PATTERN)"
log "Coords:    $COORDS"
log "EPSG:      $EPSG"
log "Dict:      $ARUCO_DICT (1=4x4_100, 99=custom 3x3)"
log "Minrate:   $MINRATE"
log "Ignore:    $IGNORE"
log "Output:    $GCP_LIST"

# Count images
shopt -s nullglob nocaseglob
IMG_FILES=("$IMAGES"/$IMAGE_PATTERN)
shopt -u nullglob nocaseglob
IMG_COUNT=${#IMG_FILES[@]}
[[ $IMG_COUNT -eq 0 ]] && err "No images found with pattern '$IMAGE_PATTERN' in $IMAGES"
log "Found: $IMG_COUNT images"

# Run Find-GCP
log "Starting marker detection ..."
python3 "$GCP_FIND" \
  -v \
  -t ODM \
  -i "$COORDS" \
  --epsg "$EPSG" \
  -o "$GCP_LIST" \
  --minrate "$MINRATE" \
  --ignore "$IGNORE" \
  -d "$ARUCO_DICT" \
  $ADJUST \
  "${IMG_FILES[@]}" 2>&1 | tee "$LOG_FILE"

[[ ! -s "$GCP_LIST" ]] && err "gcp_list.txt is empty - no markers detected. Check --minrate, --dict and image quality."

# ---------- 2. Report ----------
log "=== Sanity check / report ==="
{
  echo "Find-GCP report - $(date -Iseconds)"
  echo "==========================================="
  echo "Image directory: $IMAGES"
  echo "Images total:    $IMG_COUNT"
  echo "EPSG:            $EPSG"
  echo "ArUco dict:      $ARUCO_DICT"
  echo
  echo "GCP entries (without header): $(($(wc -l < "$GCP_LIST") - 1))"
  echo
  echo "GCPs per marker ID:"
  echo "-------------------"
  # Column 7 = marker id (after the EPSG header)
  tail -n +2 "$GCP_LIST" | awk '{print $NF}' | sort | uniq -c | sort -rn
  echo
  echo "GCPs per image (top 20):"
  echo "------------------------"
  tail -n +2 "$GCP_LIST" | awk '{print $6}' | sort | uniq -c | sort -rn | head -20
  echo
  echo "Images without GCP:"
  echo "-------------------"
  comm -23 \
    <(printf '%s\n' "${IMG_FILES[@]##*/}" | sort -u) \
    <(tail -n +2 "$GCP_LIST" | awk '{print $6}' | sort -u) \
    | head -20
  echo
  echo "QUALITY CHECKS:"
  echo "---------------"
  UNIQUE_MARKERS=$(tail -n +2 "$GCP_LIST" | awk '{print $NF}' | sort -u | wc -l)
  echo "  Unique markers detected: $UNIQUE_MARKERS"
  if [[ $UNIQUE_MARKERS -lt 5 ]]; then
    echo "  ⚠  WARNING: <5 markers. 5-10+ are recommended for a robust bundle adjustment."
  fi
  # Check for markers on <3 images
  WEAK=$(tail -n +2 "$GCP_LIST" | awk '{print $NF}' | sort | uniq -c | awk '$1 < 3 {print $2}' | tr '\n' ' ')
  if [[ -n "$WEAK" ]]; then
    echo "  ⚠  Markers on <3 images (should be min. 3, better 5+): $WEAK"
  fi
} | tee "$REPORT_FILE"

log "Report saved:  $REPORT_FILE"
log "GCP list:      $GCP_LIST"

# ---------- 3. Optional: GUI check ----------
if [[ "$DO_CHECK" == "true" ]]; then
  log "=== Visual check (gcp_check.py) ==="
  [[ ! -f "$GCP_CHECK" ]] && warn "gcp_check.py not found, skipping" || \
    python3 "$GCP_CHECK" --path "$IMAGES" "$GCP_LIST"
fi

# ---------- 4. Optional: WebODM prep ----------
if [[ "$DO_PREP" == "true" ]]; then
  log "=== Build WebODM folder structure ==="
  PREP_DIR="$OUTPUT/webodm_ready"
  mkdir -p "$PREP_DIR/images"

  # Symlinks instead of copies - saves space on large datasets
  log "Creating symlinks to images in $PREP_DIR/images ..."
  for img in "${IMG_FILES[@]}"; do
    ln -sf "$(realpath "$img")" "$PREP_DIR/images/$(basename "$img")"
  done

  cp "$GCP_LIST" "$PREP_DIR/gcp_list.txt"

  # README with the task options you should set in WebODM
  cat > "$PREP_DIR/README_webodm.md" <<MDEOF
# WebODM task setup

Dataset:  $(basename "$OUTPUT")
Created:  $(date -Iseconds)
Images:   $IMG_COUNT
EPSG:     $EPSG

## Upload to WebODM

1. Create a new task in WebODM
2. Upload all files from \`images/\`
3. Add \`gcp_list.txt\` via the GCP upload button
4. Recommended task options (regional survey, archaeological ortho/DEM):

\`\`\`
feature-quality: high
pc-quality: high
matcher-neighbors: 16
mesh-octree-depth: 11
dem-resolution: 2.0
orthophoto-resolution: 1.5
crop: 3
optimize-disk-space: true
use-3dmesh: false              # set to true if a 3D model is needed
\`\`\`

For memory constraints (>500 images, <16GB RAM):
\`\`\`
split: 200
split-overlap: 50
feature-quality: medium
pc-quality: medium
\`\`\`
MDEOF

  log "WebODM setup ready: $PREP_DIR"
fi

# ---------- 5. Optional: upload ----------
if [[ "$DO_UPLOAD" == "true" ]]; then
  log "=== Upload to WebODM via API ==="
  [[ -z "$WEBODM_URL" ]]  && err "--webodm-url missing"
  [[ -z "$WEBODM_USER" ]] && err "--webodm-user missing"
  [[ -z "$WEBODM_PASS" ]] && err "--webodm-pass or env WEBODM_PASS missing"
  [[ -z "$PROJECT_NAME" ]] && PROJECT_NAME="findgcp-$(date +%Y%m%d-%H%M)"

  command -v jq >/dev/null || err "jq missing (apt install jq / brew install jq)"

  # Get token
  log "Authenticating against $WEBODM_URL ..."
  TOKEN=$(curl -sf -X POST "$WEBODM_URL/api/token-auth/" \
    -d "username=$WEBODM_USER&password=$WEBODM_PASS" | jq -r .token)
  [[ -z "$TOKEN" || "$TOKEN" == "null" ]] && err "Authentication failed"
  log "Token received"

  # Create project
  log "Creating project '$PROJECT_NAME' ..."
  PROJECT_ID=$(curl -sf -X POST "$WEBODM_URL/api/projects/" \
    -H "Authorization: JWT $TOKEN" \
    -d "name=$PROJECT_NAME" | jq -r .id)
  [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "null" ]] && err "Project creation failed"
  log "Project ID: $PROJECT_ID"

  # Task with images + GCP list
  log "Creating task & uploading images (may take a while) ..."
  CURL_FILES=()
  for img in "${IMG_FILES[@]}"; do
    CURL_FILES+=(-F "images=@$img")
  done
  CURL_FILES+=(-F "images=@$GCP_LIST;filename=gcp_list.txt")

  TASK_ID=$(curl -sf -X POST "$WEBODM_URL/api/projects/$PROJECT_ID/tasks/" \
    -H "Authorization: JWT $TOKEN" \
    "${CURL_FILES[@]}" | jq -r .id)

  [[ -z "$TASK_ID" || "$TASK_ID" == "null" ]] && err "Task creation failed"
  log "Task ID: $TASK_ID"
  log "→ $WEBODM_URL/dashboard/?project_task_open=$TASK_ID"
fi

log "=== Done ==="
