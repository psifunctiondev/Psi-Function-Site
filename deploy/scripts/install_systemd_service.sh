#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="consulting-site"
APP_DIR="/opt/consulting-site"
SOURCE_DIR="$APP_DIR/source"

SRC="$SOURCE_DIR/deploy/systemd/${SERVICE_NAME}.service"
DEST="/etc/systemd/system/${SERVICE_NAME}.service"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

[ -f "$SRC" ] || fail "Missing source unit file: $SRC"

log "Installing systemd unit"
sudo install -m 0644 "$SRC" "$DEST"

log "Reloading systemd daemon"
sudo systemctl daemon-reload

log "Enabling service"
sudo systemctl enable "$SERVICE_NAME"

log "Installed unit:"
sudo systemctl cat "$SERVICE_NAME"
