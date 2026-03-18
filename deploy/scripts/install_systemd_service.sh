#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: $0 <staging|production>" >&2
  exit 1
}

ENVIRONMENT="${1:-}"
[ -n "$ENVIRONMENT" ] || usage

case "$ENVIRONMENT" in
  staging|production) ;;
  *)
    echo "Invalid environment: $ENVIRONMENT" >&2
    usage
    ;;
esac

SERVICE_BASENAME="consulting-site"
SERVICE_INSTANCE="${SERVICE_BASENAME}@${ENVIRONMENT}"
APP_DIR="/opt/consulting-site/${ENVIRONMENT}"
SOURCE_DIR="$APP_DIR/source"

TEMPLATE_SRC="$SOURCE_DIR/deploy/systemd/${SERVICE_BASENAME}@.service"
INSTANCE_SRC="$SOURCE_DIR/deploy/systemd/${SERVICE_INSTANCE}.service"

DEST_TEMPLATE="/etc/systemd/system/${SERVICE_BASENAME}@.service"
DEST_INSTANCE="/etc/systemd/system/${SERVICE_INSTANCE}.service"

log() {
  printf '[%s] [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$ENVIRONMENT" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

if [ -f "$TEMPLATE_SRC" ]; then
  SRC="$TEMPLATE_SRC"
  DEST="$DEST_TEMPLATE"
elif [ -f "$INSTANCE_SRC" ]; then
  SRC="$INSTANCE_SRC"
  DEST="$DEST_INSTANCE"
else
  fail "Missing source unit file. Expected one of: $TEMPLATE_SRC or $INSTANCE_SRC"
fi

log "Installing systemd unit from $SRC"
sudo install -m 0644 "$SRC" "$DEST"

log "Reloading systemd daemon"
sudo systemctl daemon-reload

log "Enabling service instance $SERVICE_INSTANCE"
sudo systemctl enable "$SERVICE_INSTANCE"

log "Installed unit:"
sudo systemctl cat "$SERVICE_INSTANCE"
