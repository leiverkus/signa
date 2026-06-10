#!/usr/bin/env bash
#
# build-plugin.sh
# ---------------
# Packages the findgcp/ plugin into a WebODM-installable .zip.
#
# WebODM (app/admin.py -> plugin_upload) requires the archive to contain
# EXACTLY ONE root directory (the plugin folder) holding plugin.py,
# manifest.json and __init__.py. We zip the `findgcp/` directory as-is so the
# archive root is `findgcp/...`.
#
# Output: dist/findgcp-<version>.zip   (version read from manifest.json)
#
# License: MIT

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$SCRIPT_DIR/findgcp"
DIST_DIR="$SCRIPT_DIR/dist"

err() { printf "\033[1;31m[ERR ]\033[0m %s\n" "$*" >&2; exit 1; }
log() { printf "\033[1;34m[build]\033[0m %s\n" "$*"; }

# ---------- Validate plugin layout (mirror WebODM's valid_plugin) ----------
[[ -d "$PLUGIN_DIR" ]] || err "Plugin directory not found: $PLUGIN_DIR"
for required in plugin.py manifest.json __init__.py; do
  [[ -f "$PLUGIN_DIR/$required" ]] || err "Missing required file: findgcp/$required"
done

# ---------- Read version from manifest.json ----------
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$PLUGIN_DIR/manifest.json")" \
  || err "Cannot read version from manifest.json"
[[ -n "$VERSION" ]] || err "Empty version in manifest.json"

ZIP_NAME="findgcp-${VERSION}.zip"
ZIP_PATH="$DIST_DIR/$ZIP_NAME"

# ---------- Build ----------
mkdir -p "$DIST_DIR"
rm -f "$ZIP_PATH"

log "Packaging findgcp v$VERSION → dist/$ZIP_NAME"
( cd "$SCRIPT_DIR" && zip -r -q "$ZIP_PATH" findgcp \
    -x '*.pyc' '*/__pycache__/*' '*/.DS_Store' '*.swp' )

# ---------- Verify the archive has a single root dir ----------
ROOTS="$(unzip -Z1 "$ZIP_PATH" | awk -F/ '{print $1}' | sort -u | wc -l | tr -d ' ')"
[[ "$ROOTS" == "1" ]] || err "Archive has $ROOTS root entries (must be exactly 1)"

log "Done: $ZIP_PATH"
log "Install in WebODM via Administration → Plugins → Load Plugin (.zip)"
