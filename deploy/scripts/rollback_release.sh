#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: $0 <staging|production> [release_name]" >&2
  exit 1
}

ENVIRONMENT="${1:-}"
TARGET_ARG="${2:-}"

[ -n "$ENVIRONMENT" ] || usage

case "$ENVIRONMENT" in
  staging|production) ;;
  *)
    echo "Invalid environment: $ENVIRONMENT" >&2
    usage
    ;;
esac

APP_DIR="/opt/consulting-site/${ENVIRONMENT}"
RELEASES_DIR="$APP_DIR/releases"
CURRENT_LINK="$APP_DIR/current"
PREVIOUS_LINK="$APP_DIR/previous"
SERVICE_NAME="consulting-site@${ENVIRONMENT}"
SOCKET_PATH="$APP_DIR/shared/run/gunicorn.sock"
APP_HEALTH_TIMEOUT="${APP_HEALTH_TIMEOUT:-30}"

log() {
  printf '[%s] [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$ENVIRONMENT" "$*"
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
require_cmd curl

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
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl is-active --quiet "$SERVICE_NAME" || fail "$SERVICE_NAME failed to start after rollback"

log "Checking Gunicorn health endpoint over unix socket"
for i in $(seq 1 "$APP_HEALTH_TIMEOUT"); do
  if [ -S "$SOCKET_PATH" ] && \
     curl --silent --show-error --fail \
       --unix-socket "$SOCKET_PATH" \
       http://localhost/health >/dev/null; then
    log "Gunicorn health check passed after rollback"
    break
  fi

  if [ "$i" -eq "$APP_HEALTH_TIMEOUT" ]; then
    fail "Gunicorn health check failed after rollback after ${APP_HEALTH_TIMEOUT}s"
  fi

  sleep 1
done

log "Rollback successful"
log "Current release: $(readlink -f "$CURRENT_LINK")"
log "Current revision: $(cat "$CURRENT_LINK/REVISION" 2>/dev/null || echo 'unknown')"
if [ -L "$PREVIOUS_LINK" ]; then
  log "Previous release: $(readlink -f "$PREVIOUS_LINK")"
fi
