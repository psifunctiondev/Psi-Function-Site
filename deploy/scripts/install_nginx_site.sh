#!/usr/bin/env bash
set -Eeuo pipefail

SITE_NAME="consulting-site"
APP_DIR="/opt/consulting-site"
SOURCE_DIR="$APP_DIR/source"

SRC="$SOURCE_DIR/deploy/nginx/${SITE_NAME}.conf"
DEST="/etc/nginx/sites-available/${SITE_NAME}"
ENABLED="/etc/nginx/sites-enabled/${SITE_NAME}"
DEFAULT_ENABLED="/etc/nginx/sites-enabled/default"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

[ -f "$SRC" ] || fail "Missing nginx site file: $SRC"

log "Installing nginx site"
sudo install -m 0644 "$SRC" "$DEST"

log "Enabling nginx site"
sudo ln -sfn "$DEST" "$ENABLED"

if [ -L "$DEFAULT_ENABLED" ] || [ -e "$DEFAULT_ENABLED" ]; then
  log "Disabling default nginx site"
  sudo rm -f "$DEFAULT_ENABLED"
fi

log "Validating nginx configuration"
sudo nginx -t

log "Reloading nginx"
sudo systemctl reload nginx
