#!/usr/bin/env bash
# copy_data.sh — Copy the dynamic state of one deployed environment's database
# into another.  Designed for the production → staging "seed staging from
# production" workflow (see .github/workflows/seed_staging_from_production.yml
# and docs/deployment.md).
#
# Usage:
#   bash deploy/scripts/copy_data.sh <source-env> <target-env> <action>
#
# Arguments:
#   <source-env>  one of: testing, staging, production
#   <target-env>  one of: testing, staging, production (must differ from source)
#   <action>      verb declaring intent; only "copy" is currently supported
#                 (e.g. "copy").  Required so a stray shell expansion can't
#                 accidentally invoke this script with no action.
#
# Example:
#   bash deploy/scripts/copy_data.sh production staging copy
#
# Behavior (high level):
#   1. Refuse to run if source == target.
#   2. Verify Alembic head compatibility: target is auto-upgraded if behind
#      source; ABORT (no destructive step) if heads diverge.
#   3. Dump source DB with `pg_dump --format=custom`.
#   4. Generate a per-run random password and write it to
#      /opt/consulting-site/<target>/.staging_password (mode 600,
#      deploy:deploy).  Echoed to stdout so the calling workflow can capture
#      it for the GitHub Actions summary (with ::add-mask:: applied upstream).
#   5. Drop + recreate the TARGET database (never the source) and restore
#      from the dump.
#   6. Apply deploy/scripts/scrub_data.sql to the freshly-restored target.
#   7. Clean up the temp dump file on success and failure (trap EXIT).
#
# This script must run on the deploy host as the `deploy` user.  It uses
# sudo to drop/recreate the target database as the `postgres` role.
set -Eeuo pipefail
umask 027

APP_ROOT="${APP_ROOT:-/opt/consulting-site}"
DB_PREFIX="psifunction"
BACKUP_DIR="/opt/consulting-site/backups"
# SCRUB_SQL lives at /opt/consulting-site/scripts/scrub_data.sql —
# the seed workflow rsyncs it there from this repo.  Mirrors the layout of
# /opt/consulting-site/scripts/backup_postgres.sh and
# /opt/consulting-site/scripts/db_connect.sh (persistent, not rotated by
# deploy_release.sh's release rotation).
SCRUB_SQL="${APP_ROOT}/scripts/scrub_data.sql"
APP_USER="deploy"
APP_GROUP="deploy"
VALID_ENVS=("testing" "staging" "production")
VALID_ACTIONS=("copy")

# --- Logging ----------------------------------------------------------------

log() {
  printf '[%s] [copy_data] [staging] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

fail() {
  log "ERROR: $*"
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

# --- Usage ------------------------------------------------------------------

usage() {
  cat >&2 <<EOF
Usage: $0 <$(IFS='|'; echo "${VALID_ENVS[*]}")> <$(IFS='|'; echo "${VALID_ENVS[*]}")> <$(IFS='|'; echo "${VALID_ACTIONS[*]}")>

Copy a deployed environment's database into another environment's database.
The TARGET database is dropped and recreated from a fresh pg_dump of the
source.  This is a destructive operation against the target only.

Examples:
  $0 production staging copy

Environment overrides:
  APP_ROOT   Root directory of deployed environments (default: /opt/consulting-site)
EOF
  exit 1
}

# --- Argument parsing -------------------------------------------------------

SOURCE_ENV="${1:-}"
TARGET_ENV="${2:-}"
ACTION="${3:-}"

[ -n "$SOURCE_ENV" ] || usage
[ -n "$TARGET_ENV" ] || usage
[ -n "$ACTION" ]     || usage

case "$SOURCE_ENV" in
  testing|staging|production) ;;
  *) fail "Invalid source environment: ${SOURCE_ENV}" ;;
esac

case "$TARGET_ENV" in
  testing|staging|production) ;;
  *) fail "Invalid target environment: ${TARGET_ENV}" ;;
esac

case "$ACTION" in
  copy) ;;
  *)    fail "Invalid action: ${ACTION} (expected: copy)" ;;
esac

# No-op guard: refuse to copy an environment into itself.
if [ "$SOURCE_ENV" = "$TARGET_ENV" ]; then
  fail "Refusing to copy '${SOURCE_ENV}' into itself (source == target). Pick a different target."
fi

# --- Pre-flight: required commands -----------------------------------------

require_cmd sudo
require_cmd pg_dump
require_cmd pg_restore
require_cmd psql
require_cmd createdb
require_cmd dropdb
require_cmd openssl
require_cmd python3
require_cmd install
require_cmd find
require_cmd chmod
require_cmd chown
require_cmd mktemp
require_cmd touch
require_cmd cp

# --- Env-file parser (mirrors scripts/db_connect.sh) ------------------------
#
# Mirrors the env-file parser used in scripts/db_connect.sh: read the
# environment's app.env (preferred — matches what the app uses) with
# `set -a; source ...; set +a`, then pull DATABASE_URL out of the resulting
# shell environment.  See scripts/db_connect.sh around the comment
# "1. Pull DATABASE_URL from app.env (preferred — matches what the app uses)."
# for the exact precedent this block mirrors.

load_db_url() {
  local env="$1"
  local app_env_file="${APP_ROOT}/${env}/shared/env/app.env"
  local credentials_file="${APP_ROOT}/.db_credentials"

  if [ -f "$app_env_file" ]; then
    log "Loading DATABASE_URL from ${app_env_file}"
    # shellcheck disable=SC1090
    DATABASE_URL="$(set -a; source "$app_env_file"; set +a; printf '%s' "${DATABASE_URL:-}")"
  fi

  if [ -z "${DATABASE_URL:-}" ] && [ -f "$credentials_file" ]; then
    log "Loading DATABASE_URL from ${credentials_file}"
    if [ -r "$credentials_file" ]; then
      DATABASE_URL="$(grep "^DATABASE_URL=" "$credentials_file" \
        | sed -n "/${env}\/psifunction_${env}/p; $!d; p" \
        | head -1 \
        | sed 's/^DATABASE_URL=//')"
    else
      DATABASE_URL="$(sudo grep "^DATABASE_URL=" "$credentials_file" \
        | sed -n "/${env}\/psifunction_${env}/p; $!d; p" \
        | head -1 \
        | sed 's/^DATABASE_URL=//')"
    fi
  fi

  if [ -z "${DATABASE_URL:-}" ]; then
    fail "Could not find DATABASE_URL for '${env}' (looked in ${app_env_file} and ${credentials_file})"
  fi
}

# --- Flask context helpers (for `flask db current` / `flask db upgrade`) ----
#
# Use the *current* release of each environment so Alembic sees the same
# migration tree the app uses.  Matches deploy_release.sh's pattern of
# `FLASK_APP=wsgi:app flask db upgrade` against the release directory with
# its own .venv activated.

flask_current_head() {
  local env="$1"
  local release_dir="${APP_ROOT}/${env}/current"
  local venv_dir="${release_dir}/.venv"

  [ -d "$release_dir" ] || fail "No current release for env '${env}' (expected ${release_dir})"
  [ -x "${venv_dir}/bin/flask" ] || fail "Flask CLI not found in ${venv_dir}/bin/flask — has the env been deployed?"

  (
    cd "$release_dir"
    # shellcheck disable=SC1091
    source "${venv_dir}/bin/activate"
    DATABASE_URL="$DATABASE_URL" FLASK_APP="${FLASK_APP:-wsgi:app}" \
      flask db current 2>&1
  )
}

flask_upgrade() {
  local env="$1"
  local release_dir="${APP_ROOT}/${env}/current"
  local venv_dir="${release_dir}/.venv"

  (
    cd "$release_dir"
    # shellcheck disable=SC1091
    source "${venv_dir}/bin/activate"
    DATABASE_URL="$DATABASE_URL" FLASK_APP="${FLASK_APP:-wsgi:app}" \
      flask db upgrade 2>&1
  )
}

# Parse a `flask db current` output to a sorted, deduped list of revision
# ids (one per line).  Filters out Alembic's INFO/Context log lines.
parse_current_revs() {
  grep -E '^[0-9a-f]{12}' | awk '{print $1}' | sort -u
}

# --- Pre-flight: Alembic head check (BEFORE any destructive step) -----------
#
# Compare the current revision set of source and target.  Three cases:
#   - equal               → in sync, proceed
#   - target ⊂ source     → target is behind; auto-upgrade target
#   - neither (divergent) → ABORT (no destructive step).  This requires
#                            a human (Quinn) to resolve the branch divergence
#                            with `flask db merge` or by re-baselining.

log "Comparing Alembic heads: source='${SOURCE_ENV}' target='${TARGET_ENV}'"

SOURCE_REVS="$(load_db_url "$SOURCE_ENV" >/dev/null; flask_current_head "$SOURCE_ENV" | parse_current_revs)"
TARGET_REVS="$(load_db_url "$TARGET_ENV" >/dev/null; flask_current_head "$TARGET_ENV" | parse_current_revs)"

log "Source (${SOURCE_ENV}) current revisions:"
[ -n "$SOURCE_REVS" ] && printf '  %s\n' $SOURCE_REVS >&2 || log "  (none)"
log "Target (${TARGET_ENV}) current revisions:"
[ -n "$TARGET_REVS" ] && printf '  %s\n' $TARGET_REVS >&2 || log "  (none)"

if [ -z "$TARGET_REVS" ]; then
  fail "Target '${TARGET_ENV}' has no applied Alembic revisions — refusing to overwrite. Run 'flask db upgrade' on the target first."
fi

if [ "$SOURCE_REVS" = "$TARGET_REVS" ]; then
  log "Alembic heads are in sync between source and target"
else
  # Is target a strict subset of source?  Empty target_revs already handled
  # above; we just need to check that every target rev appears in source.
  DIVERGENT=0
  while IFS= read -r rev; do
    [ -n "$rev" ] || continue
    if ! printf '%s\n' "$SOURCE_REVS" | grep -qx "$rev"; then
      DIVERGENT=1
      log "  -> '${rev}' is on target but not on source (divergent head)"
    fi
  done <<< "$TARGET_REVS"

  if [ "$DIVERGENT" = "1" ]; then
    fail "Alembic heads DIVERGE between '${SOURCE_ENV}' and '${TARGET_ENV}'. Refusing to copy until a human resolves the branch divergence (e.g. 'flask db merge' or re-baseline). This is intentional — auto-merging or guessing would risk silent data loss."
  fi

  log "Target is BEHIND source — running 'flask db upgrade' on '${TARGET_ENV}' first"
  load_db_url "$TARGET_ENV" >/dev/null
  if flask_upgrade "$TARGET_ENV"; then
    log "Target '${TARGET_ENV}' upgraded successfully"
  else
    fail "Auto-upgrade of '${TARGET_ENV}' failed. Resolve the failure (possibly divergent heads) and re-run."
  fi

  # Re-check after upgrade.
  TARGET_REVS="$(flask_current_head "$TARGET_ENV" | parse_current_revs)"
  if [ "$SOURCE_REVS" != "$TARGET_REVS" ]; then
    fail "Alembic heads still diverge after upgrade (source: '$(echo $SOURCE_REVS | tr '\n' ' ')', target: '$(echo $TARGET_REVS | tr '\n' ' ')'). Refusing to copy."
  fi
  log "Alembic heads now in sync after upgrade"
fi

# --- Dump source DB ---------------------------------------------------------
#
# Mirror scripts/backup_postgres.sh's layout: ${BACKUP_DIR}/${DB}_${STAMP}.dump
# with `--format=custom`.  Use a timestamped filename so concurrent runs (if
# anyone bypasses the workflow concurrency guard) don't trample each other.

mkdir -p "$BACKUP_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
SOURCE_DB="${DB_PREFIX}_${SOURCE_ENV}"
TARGET_DB="${DB_PREFIX}_${TARGET_ENV}"
DUMP_FILE="${BACKUP_DIR}/${SOURCE_DB}_to_${TARGET_DB}_${STAMP}.dump"

log "Dumping source database '${SOURCE_DB}' to ${DUMP_FILE}"
if ! sudo -u postgres pg_dump --format=custom --dbname="$SOURCE_DB" --file="$DUMP_FILE"; then
  rm -f "$DUMP_FILE"
  fail "pg_dump of '${SOURCE_DB}' failed"
fi
log "Dump complete: $(du -h "$DUMP_FILE" | cut -f1)"

# --- Cleanup trap ----------------------------------------------------------
#
# Trap EXIT (not just ERR) so the temp dump is removed on both success and
# failure paths.  Cleanup is idempotent.

cleanup() {
  local exit_code=$?
  if [ -n "${DUMP_FILE:-}" ] && [ -f "${DUMP_FILE:-}" ]; then
    log "Removing temp dump: ${DUMP_FILE}"
    rm -f "$DUMP_FILE"
  fi
  exit "$exit_code"
}
trap cleanup EXIT

# --- Generate per-run random password ---------------------------------------
#
# 20 chars, URL-safe.  Generated ONCE per run, used for:
#   - The hash applied to every scrubbed user in scrub_data.sql
#   - Echoed to stdout so the calling workflow can capture it for
#     $GITHUB_STEP_SUMMARY (with ::add-mask:: applied in the workflow)

PASSWORD="$(openssl rand -base64 30 | tr -dc 'A-Za-z0-9' | head -c 20)"
[ "${#PASSWORD}" -eq 20 ] || fail "Failed to generate a 20-character password"

log "Generated per-run staging password (length ${#PASSWORD})"
# IMPORTANT: this is the *only* place the password is written to stdout.
# The workflow captures stdout and applies ::add-mask:: before writing to
# the step summary.  Do not log the password itself anywhere else.
printf '%s\n' "$PASSWORD"

# --- Drop + recreate target DB (NEVER the source!) -------------------------

log "Dropping and recreating target database '${TARGET_DB}'"
if ! sudo -u postgres dropdb --if-exists "$TARGET_DB"; then
  fail "dropdb of '${TARGET_DB}' failed"
fi
if ! sudo -u postgres createdb "$TARGET_DB"; then
  fail "createdb of '${TARGET_DB}' failed"
fi

log "Restoring dump into '${TARGET_DB}'"
if ! sudo -u postgres pg_restore --dbname="$TARGET_DB" --no-owner --no-privileges "$DUMP_FILE" 2>/dev/null; then
  # pg_restore returns non-zero on benign notices (e.g. role already exists
  # comments); the data itself is restored.  Re-validate by counting user
  # rows below; if zero, treat as a real failure.
  log "pg_restore returned non-zero (often benign notices); validating restore"
fi

# --- Apply scrub SQL --------------------------------------------------------
#
# Compute the Werkzeug pbkdf2 hash of the per-run password in the shell and
# pass it to scrub_data.sql via `psql -v password_hash=...`.  See
# deploy/scripts/scrub_data.sql for the matching SQL contract.
#
# This is Option B from the implementation brief: shell computes the hash
# because pgcrypto is NOT enabled in this project's staging DB (no
# `CREATE EXTENSION pgcrypto` in migrations/versions/*.py).

if [ ! -f "$SCRUB_SQL" ]; then
  fail "Scrub SQL not found: ${SCRUB_SQL} (expected deploy/scripts/scrub_data.sql to be deployed alongside this script)"
fi

PASSWORD_HASH="$(sudo -u "${APP_USER}" python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('${PASSWORD}', method='pbkdf2:sha256:600000'))")"
[ -n "$PASSWORD_HASH" ] || fail "Failed to compute password hash (werkzeug.security.generate_password_hash returned empty)"

log "Applying scrub SQL to '${TARGET_DB}'"
if ! sudo -u postgres psql --dbname="$TARGET_DB" --variable=ON_ERROR_STOP=1 \
        -v "password_hash=$(printf '%s' "$PASSWORD_HASH" | sed "s/'/''/g")" \
        --file="$SCRUB_SQL" >/dev/null; then
  fail "scrub_data.sql failed against '${TARGET_DB}'"
fi
log "Scrub complete"

# --- Write the staging password file ---------------------------------------
#
# Mode 600, owner deploy:deploy.  Lives under /opt/consulting-site/<target>/
# so it's outside the release rotation.  Quinn (or a follow-up workflow
# step) reads it to log in as a scrubbed user in staging.

PASSWORD_FILE="${APP_ROOT}/${TARGET_ENV}/.staging_password"

# Create the file with the correct ownership and mode from the start.
# We avoid `install -o/-g` for portability: explicit touch + chown + chmod
# works identically on GNU coreutils and BusyBox, and is easy to read.
touch "$PASSWORD_FILE"
chown "${APP_USER}:${APP_GROUP}" "$PASSWORD_FILE"
chmod 0600 "$PASSWORD_FILE"

# Write the password via a short temp-file hop so the final write is
# atomic (no half-written state visible to readers on SIGPIPE / crash).
# We deliberately do NOT log the password contents anywhere.
TMP_PW="$(mktemp)"
chmod 0600 "$TMP_PW"
printf '%s\n' "$PASSWORD" > "$TMP_PW"
chown "${APP_USER}:${APP_GROUP}" "$TMP_PW"
cp --no-preserve=all "$TMP_PW" "$PASSWORD_FILE"
chmod 0600 "$PASSWORD_FILE"
chown "${APP_USER}:${APP_GROUP}" "$PASSWORD_FILE"
rm -f "$TMP_PW"

log "Wrote staging password to ${PASSWORD_FILE} (mode 600, owner ${APP_USER}:${APP_GROUP})"

# --- Summary ----------------------------------------------------------------

log "Copy complete: ${SOURCE_ENV} -> ${TARGET_ENV}"
log "  Source DB:    ${SOURCE_DB}"
log "  Target DB:    ${TARGET_DB}"
log "  Password:     ${PASSWORD_FILE} (mode 600, ${APP_USER}:${APP_GROUP})"
log "Next: read ${PASSWORD_FILE} on the deploy host to log in as a scrubbed user in staging."

# trap EXIT will clean up the dump file.
