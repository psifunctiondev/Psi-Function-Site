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
# install the unit, reload systemd, and print final state. Never enables
# or starts the unit — cron will fire it.
#

set -Eeuo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: $0 <staging|production> [--apply]

By default, runs in dry-run mode (prints [DRY-RUN] plan, exits 0).
Pass --apply to actually install the unit and reload systemd.

The installer never enables or starts the unit — cron on Belel fires
the worker via SSH to the droplet.
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
  staging|production) ;;
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

log "Installed unit (NOT enabled, NOT started — cron will fire it):"
sudo systemctl cat "$SERVICE_INSTANCE" || true

log "Done. The unit is available at $DEST but not enabled. Cron on Belel"
log "will fire 'ssh ... $SERVICE_INSTANCE' to run the worker."