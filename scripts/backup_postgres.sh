#!/usr/bin/env bash
set -Eeuo pipefail

# backup_postgres.sh — Dump Psi Function PostgreSQL databases
#
# Usage:
#   bash scripts/backup_postgres.sh <testing|staging|production|all>
#
# Stores pg_dump custom-format backups in /opt/consulting-site/backups/
# with date-stamped filenames.  Retains the last 7 daily backups per
# database and prunes older ones.
#
# Suitable for cron:
#   0 3 * * * /opt/consulting-site/scripts/backup_postgres.sh all >> /var/log/pg_backup.log 2>&1

VALID_ENVS=("testing" "staging" "production")
DB_PREFIX="psifunction"
BACKUP_DIR="/opt/consulting-site/backups"
KEEP_DAYS=7

log() {
  printf '[%s] [backup] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

usage() {
  echo "Usage: $0 <testing|staging|production|all>" >&2
  exit 1
}

TARGET="${1:-}"
[ -n "$TARGET" ] || usage

# Validate target
if [ "$TARGET" != "all" ]; then
  FOUND=0
  for env in "${VALID_ENVS[@]}"; do
    [ "$env" = "$TARGET" ] && FOUND=1
  done
  [ "$FOUND" = "1" ] || { echo "Invalid environment: $TARGET" >&2; usage; }
fi

# Build list of environments to back up
if [ "$TARGET" = "all" ]; then
  ENVS=("${VALID_ENVS[@]}")
else
  ENVS=("$TARGET")
fi

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

DATE_STAMP="$(date +%Y-%m-%d)"
ERRORS=0

for env in "${ENVS[@]}"; do
  DB="${DB_PREFIX}_${env}"
  OUTFILE="${BACKUP_DIR}/${DB}_${DATE_STAMP}.dump"

  log "Backing up database '${DB}'"

  # pg_dump as the postgres user with custom format (compressed, restorable)
  if sudo -u postgres pg_dump --format=custom --dbname="$DB" > "$OUTFILE" 2>/dev/null; then
    SIZE="$(du -h "$OUTFILE" | cut -f1)"
    log "  -> ${OUTFILE} (${SIZE})"
  else
    log "  FAILED to dump '${DB}' — database may not exist yet"
    rm -f "$OUTFILE"
    ERRORS=$((ERRORS + 1))
    continue
  fi

  # Prune old backups for this database (keep last N days)
  log "  Pruning backups older than ${KEEP_DAYS} days for '${DB}'"
  PRUNED=0
  while IFS= read -r old_backup; do
    [ -n "$old_backup" ] || continue
    rm -f "$old_backup"
    PRUNED=$((PRUNED + 1))
  done < <(find "$BACKUP_DIR" -name "${DB}_*.dump" -type f -mtime +"$KEEP_DAYS" 2>/dev/null)

  if [ "$PRUNED" -gt 0 ]; then
    log "  Removed ${PRUNED} old backup(s)"
  fi
done

if [ "$ERRORS" -gt 0 ]; then
  log "Completed with ${ERRORS} error(s)"
  exit 1
fi

log "All backups complete"
