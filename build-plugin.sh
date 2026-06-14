#!/usr/bin/env bash
#
# build-plugin.sh
# ---------------
# Packages the signa/ plugin into a WebODM-installable .zip.
#
# WebODM (app/admin.py -> plugin_upload) requires the archive to contain
# EXACTLY ONE root directory (the plugin folder) holding plugin.py,
# manifest.json and __init__.py. We zip the `signa/` directory as-is so the
# archive root is `signa/...`.
#
# Output: dist/signa-<version>.zip   (version read from manifest.json)
#
# License: MIT

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$SCRIPT_DIR/signa"
DIST_DIR="$SCRIPT_DIR/dist"

err() { printf "\033[1;31m[ERR ]\033[0m %s\n" "$*" >&2; exit 1; }
log() { printf "\033[1;34m[build]\033[0m %s\n" "$*"; }

# ---------- Validate plugin layout (mirror WebODM's valid_plugin) ----------
[[ -d "$PLUGIN_DIR" ]] || err "Plugin directory not found: $PLUGIN_DIR"
for required in plugin.py manifest.json __init__.py; do
  [[ -f "$PLUGIN_DIR/$required" ]] || err "Missing required file: signa/$required"
done

# ---------- Read version from manifest.json ----------
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$PLUGIN_DIR/manifest.json")" \
  || err "Cannot read version from manifest.json"
[[ -n "$VERSION" ]] || err "Empty version in manifest.json"

ZIP_NAME="signa-${VERSION}.zip"
ZIP_PATH="$DIST_DIR/$ZIP_NAME"

# ---------- Compile translations ----------
if [[ -d "$PLUGIN_DIR/locale" ]]; then
  log "Compiling translations (.po -> .mo)"
  python3 "$SCRIPT_DIR/scripts/compile_messages.py" "$PLUGIN_DIR/locale" \
    || err "Translation compilation failed"
fi

# ---------- Build ----------
mkdir -p "$DIST_DIR"
# Keep dist/ to a single artifact: drop any previously built plugin zips
# (older versions included) so they don't pile up across releases.
rm -f "$DIST_DIR"/signa-*.zip

log "Packaging signa v$VERSION → dist/$ZIP_NAME"
( cd "$SCRIPT_DIR" && zip -r -q "$ZIP_PATH" signa \
    -x '*.pyc' '*/__pycache__/*' '*/.DS_Store' '*.swp' )

# ---------- Verify the archive has a single root dir ----------
ROOTS="$(unzip -Z1 "$ZIP_PATH" | awk -F/ '{print $1}' | sort -u | wc -l | tr -d ' ')"
[[ "$ROOTS" == "1" ]] || err "Archive has $ROOTS root entries (must be exactly 1)"

log "Done: $ZIP_PATH"
log "Install in WebODM via Administration → Plugins → Load Plugin (.zip)"
