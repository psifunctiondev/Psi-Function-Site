#!/usr/bin/env bash
#
# Path-C (2026-07-16) — installer for the DrifterBot worker systemd unit.
#
# Mirrors install_systemd_service.sh but for consulting-site-drifterbot@.service
# instead of consulting-site@.service (the gunicorn template).
#
# The worker is bundled with the Psi-Function-Site release but runs in
# its own systemd unit, decoupling its lifecycle from gunicorn:
#   - Different restart cadence (worker is fire-and-exit; gunicorn is long-lived)
#   - Different memory ceiling
#   - Different deploy triggers (cron on Belel fires the worker via SSH to
#     the droplet; this script just makes the unit available)
#
# --apply gated: by default prints a [DRY-RUN] plan; pass --apply to actually
# install the unit, reload systemd, enable it, and start it.
#
# The unit runs as a long-lived loop (Restart=always in the unit file)
# that polls every few seconds for new submissions and exits cleanly
# when idle. After --apply, it stays running; deploy_release.sh
# restarts it on every deploy to pick up new code.
#

set -Eeuo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: $0 <testing|staging|production> [--apply]

By default, runs in dry-run mode (prints [DRY-RUN] plan, exits 0).
Pass --apply to install the unit, reload systemd, enable it, and
start it. After --apply the worker runs continuously and
deploy_release.sh restarts it on every deploy.
EOF
  exit 1
}

ENVIRONMENT="${1:-}"
APPLY=0
shift || true
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply)
      APPLY=1
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
  shift
done

[ -n "$ENVIRONMENT" ] || usage

case "$ENVIRONMENT" in
  testing|staging|production) ;;
  *)
    echo "Invalid environment: $ENVIRONMENT" >&2
    usage
    ;;
esac

SERVICE_BASENAME="consulting-site-drifterbot"
SERVICE_INSTANCE="${SERVICE_BASENAME}@${ENVIRONMENT}"
APP_DIR="/opt/consulting-site/${ENVIRONMENT}"
SOURCE_DIR="$APP_DIR/source"

TEMPLATE_SRC="$SOURCE_DIR/deploy/systemd/${SERVICE_BASENAME}@.service"
INSTANCE_SRC="$SOURCE_DIR/deploy/systemd/${SERVICE_INSTANCE}.service"

DEST_TEMPLATE="/etc/systemd/system/${SERVICE_BASENAME}@.service"
DEST_INSTANCE="/etc/systemd/system/${SERVICE_INSTANCE}.service"

# In dry-run mode, don't fail if the source isn't on the production path —
# the point of dry-run is to print the plan regardless of whether we're
# running it on Belel (where /opt/.../source/ doesn't exist) or on the
# droplet (where it does).
if [ "$APPLY" -eq 0 ]; then
  if [ -f "$TEMPLATE_SRC" ]; then
    SRC="$TEMPLATE_SRC"
    DEST="$DEST_TEMPLATE"
  elif [ -f "$INSTANCE_SRC" ]; then
    SRC="$INSTANCE_SRC"
    DEST="$DEST_INSTANCE"
  else
    # Fall back to the template path even if the file isn't there yet —
    # dry-run is about communicating intent, not validating state.
    SRC="$TEMPLATE_SRC"
    DEST="$DEST_TEMPLATE"
  fi
else
  if [ -f "$TEMPLATE_SRC" ]; then
    SRC="$TEMPLATE_SRC"
    DEST="$DEST_TEMPLATE"
  elif [ -f "$INSTANCE_SRC" ]; then
    SRC="$INSTANCE_SRC"
    DEST="$DEST_INSTANCE"
  else
    echo "ERROR: Missing source unit file. Expected one of: $TEMPLATE_SRC or $INSTANCE_SRC" >&2
    exit 1
  fi
fi

# --apply gated: dry-run by default. The dry-run path exits 0 and prints
# every step with a [DRY-RUN] prefix so a chat-ops command can see what
# would happen without committing anything.
log() {
  if [ "$APPLY" -eq 1 ]; then
    printf '[%s] [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$ENVIRONMENT" "$*"
  else
    printf '[DRY-RUN] [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
  fi
}

if [ "$APPLY" -eq 0 ]; then
  log "Would install systemd unit from $SRC"
  log "Would copy to $DEST (mode 0644)"
  log "Would run: sudo systemctl daemon-reload"
  log "Would NOT enable or start the unit (cron will fire it)"
  log "Dry-run complete. Pass --apply to perform these actions."
  exit 0
fi

# --apply path
log "Installing systemd unit from $SRC"
sudo install -m 0644 "$SRC" "$DEST"

log "Reloading systemd daemon"
sudo systemctl daemon-reload

log "Enabling and starting $SERVICE_INSTANCE"
sudo systemctl enable "$SERVICE_INSTANCE"
sudo systemctl restart "$SERVICE_INSTANCE"

log "Installed + enabled + started unit:"
sudo systemctl status "$SERVICE_INSTANCE" --no-pager || true

log "Done. The unit is enabled at $DEST and running. deploy_release.sh"
log "will restart it on every deploy to pick up new code."