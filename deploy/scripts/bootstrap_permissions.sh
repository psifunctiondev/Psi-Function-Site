#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/consulting-site"
SHARED_DIR="$APP_DIR/shared"
RELEASES_DIR="$APP_DIR/releases"
SOURCE_DIR="$APP_DIR/source"

APP_USER="deploy"
APP_GROUP="deploy"
WEB_GROUP="www-data"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

require_cmd sudo
require_cmd find
require_cmd chown
require_cmd chmod
require_cmd chgrp
require_cmd id
require_cmd namei

id "$APP_USER" >/dev/null 2>&1 || fail "User does not exist: $APP_USER"
getent group "$APP_GROUP" >/dev/null 2>&1 || fail "Group does not exist: $APP_GROUP"
getent group "$WEB_GROUP" >/dev/null 2>&1 || fail "Group does not exist: $WEB_GROUP"

log "Ensuring base directory structure exists"
sudo mkdir -p \
  "$APP_DIR" \
  "$RELEASES_DIR" \
  "$SOURCE_DIR" \
  "$SHARED_DIR/env" \
  "$SHARED_DIR/logs" \
  "$SHARED_DIR/uploads" \
  "$SHARED_DIR/tmp"

log "Setting ownership for application tree"
sudo chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"

log "Granting web server group access to uploads"
sudo chgrp -R "$WEB_GROUP" "$SHARED_DIR/uploads"

log "Setting directory traversal permissions"
sudo chmod 755 /opt
sudo chmod 750 "$APP_DIR"
sudo chmod 750 "$SHARED_DIR"
sudo chmod 750 "$SHARED_DIR/uploads"
sudo chmod 750 "$SHARED_DIR/logs"
sudo chmod 750 "$SHARED_DIR/tmp"
sudo chmod 750 "$SHARED_DIR/env"
sudo chmod 750 "$RELEASES_DIR"
sudo chmod 750 "$SOURCE_DIR"

log "Setting permissions inside uploads"
sudo find "$SHARED_DIR/uploads" -type d -exec chmod 750 {} \;
sudo find "$SHARED_DIR/uploads" -type f -exec chmod 640 {} \;

log "Setting permissions inside logs"
sudo find "$SHARED_DIR/logs" -type d -exec chmod 750 {} \;
sudo find "$SHARED_DIR/logs" -type f -exec chmod 640 {} \;

log "Setting permissions inside tmp"
sudo find "$SHARED_DIR/tmp" -type d -exec chmod 750 {} \;
sudo find "$SHARED_DIR/tmp" -type f -exec chmod 640 {} \;

log "Setting permissions inside env"
sudo find "$SHARED_DIR/env" -type d -exec chmod 750 {} \;
sudo find "$SHARED_DIR/env" -type f -exec chmod 640 {} \;

log "Ensuring new upload files inherit www-data group"
sudo chmod g+s "$SHARED_DIR/uploads"

log "Verifying path traversal for Nginx-readable uploads path"
namei -l "$SHARED_DIR/uploads"

log "Bootstrap permissions complete"
log "App owner: $APP_USER:$APP_GROUP"
log "Web-readable uploads group: $WEB_GROUP"
