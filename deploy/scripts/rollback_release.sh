#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/consulting-site"
RELEASES_DIR="$APP_DIR/releases"
CURRENT_LINK="$APP_DIR/current"
PREVIOUS_LINK="$APP_DIR/previous"

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

require_cmd readlink
require_cmd systemctl
require_cmd nginx

TARGET_ARG="${1:-}"
CURRENT_TARGET=""
ROLLBACK_TARGET=""

if [ -L "$CURRENT_LINK" ]; then
  CURRENT_TARGET="$(readlink -f "$CURRENT_LINK")"
fi

if [ -n "$TARGET_ARG" ]; then
  ROLLBACK_TARGET="$RELEASES_DIR/$TARGET_ARG"
  [ -d "$ROLLBACK_TARGET" ] || fail "Specified release does not exist: $ROLLBACK_TARGET"
else
  [ -L "$PREVIOUS_LINK" ] || fail "No previous symlink exists; cannot rollback automatically"
  ROLLBACK_TARGET="$(readlink -f "$PREVIOUS_LINK")"
  [ -d "$ROLLBACK_TARGET" ] || fail "Previous symlink target does not exist: $ROLLBACK_TARGET"
fi

if [ "$ROLLBACK_TARGET" = "$CURRENT_TARGET" ]; then
  fail "Rollback target is already current: $ROLLBACK_TARGET"
fi

if [ -n "$CURRENT_TARGET" ] && [ -d "$CURRENT_TARGET" ]; then
  log "Updating previous symlink -> $CURRENT_TARGET"
  ln -sfn "$CURRENT_TARGET" "$PREVIOUS_LINK"
fi

log "Switching current symlink -> $ROLLBACK_TARGET"
ln -sfn "$ROLLBACK_TARGET" "$CURRENT_LINK"

log "Restarting application service"
sudo systemctl restart consulting-site
sudo systemctl is-active --quiet consulting-site || fail "consulting-site service failed to start after rollback"

log "Validating nginx configuration"
sudo nginx -t

log "Reloading nginx"
sudo systemctl reload nginx

log "Rollback successful"
log "Current release: $(readlink -f "$CURRENT_LINK")"
if [ -L "$PREVIOUS_LINK" ]; then
  log "Previous release: $(readlink -f "$PREVIOUS_LINK")"
fi
