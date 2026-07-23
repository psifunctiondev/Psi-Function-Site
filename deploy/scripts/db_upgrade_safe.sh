#!/usr/bin/env bash
# db_upgrade_safe.sh — defensive alembic upgrade wrapper
#
# Runs `flask db upgrade head` but first detects the "stuck at a
# deleted migration" failure mode (testing/staging/production DBs
# after PR #71) and bridges it with a manual alembic_version
# overwrite.
#
# Why this exists
# ---------------
# PR #71 (chore/revert-driftbot-portal-worker) deleted the
# `e3f4a5b6c7d8` alembic migration (DrifterBot worker extension
# to competitive_audit_submission) as part of the 24-commit
# revert chain that abandoned the portal-DB intake + worker-
# as-daemon architecture.
#
# The revert correctly removed the migration file, but the testing
# (and any other) DB that had already applied it still has
# `e3f4a5b6c7d8` recorded in `alembic_version`. When
# `flask db upgrade head` runs against that DB, alembic tries to
# walk forward from the recorded version, can't find the file in
# the codebase, and fails with:
#
#   ERROR [flask_migrate] Error: Can't locate revision identified
#   by 'e3f4a5b6c7d8'
#
# Worse: even `flask db stamp d2e3f4a5b6c7` (the pre-revert head)
# can't proceed — alembic still has to look up `e3f4a5b6c7d8` to
# know where to stamp from.
#
# The only escape is a raw SQL update to `alembic_version` so the
# recorded version matches a migration that exists. Then the
# normal `flask db upgrade head` can find its starting point and
# run the new migration (`f1a2b3c4d5e6`) that drops the worker
# columns.
#
# Idempotency
# -----------
# If the DB is already at `d2e3f4a5b6c7` or any of its
# descendants (e.g. `f1a2b3c4d5e6`), the stamp step is skipped —
# the raw UPDATE only fires when the recorded version is exactly
# `e3f4a5b6c7d8`. Safe to run on every deploy, including future
# deploys that don't need the bridge.
#
# Once `f1a2b3c4d5e6` has been applied to all environments, this
# script can be retired and deploy_release.sh can go back to
# calling `flask db upgrade` directly. Until then, prefer this
# wrapper.
#
# Refs: PR #71, the 2026-07-23 Drift & Anchor pivot from
# portal-DB to email intake.
#
# Usage: bash deploy/scripts/db_upgrade_safe.sh [env_name]
#
# When called from deploy_release.sh the env is auto-detected from
# $DEPLOY_ENVIRONMENT (set by deploy_release.sh) and the script
# loads $SHARED_DIR/env/app.env so DATABASE_URL is available.
set -Eeuo pipefail

# Auto-detect env when called from deploy_release.sh
if [ -n "${DEPLOY_ENVIRONMENT:-}" ]; then
  ENV_NAME="$DEPLOY_ENVIRONMENT"
elif [ -n "${1:-}" ]; then
  ENV_NAME="$1"
else
  echo "ERROR: db_upgrade_safe.sh needs DEPLOY_ENVIRONMENT env var or \$1" >&2
  exit 1
fi

case "$ENV_NAME" in
  testing|staging|production) ;;
  *)
    echo "ERROR: invalid env: $ENV_NAME (must be testing|staging|production)" >&2
    exit 1
    ;;
esac

SHARED_DIR="/opt/consulting-site/${ENV_NAME}/shared"

# Load env so DATABASE_URL is in scope for flask commands
if [ -f "$SHARED_DIR/env/app.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$SHARED_DIR/env/app.env"
  set +a
fi

: "${DATABASE_URL:?DATABASE_URL must be set (load $SHARED_DIR/env/app.env or set explicitly)}"

# Constants for the bridge logic.
#
# BRIDGE_FROM is the deleted migration's revision ID. Any DB
# recorded at exactly this version needs the bridge — its chain
# point exists in the codebase's history but the file is gone.
#
# BRIDGE_TO is the pre-existing head that the code is at before
# the new migration runs. Once we overwrite alembic_version to
# this, `flask db upgrade head` can find its starting point and
# walk forward through f1a2b3c4d5e6.
BRIDGE_FROM='e3f4a5b6c7d8'
BRIDGE_TO='d2e3f4a5b6c7'

# Locate psql. PostgreSQL only — these are Linux deploy hosts.
PSQL_BIN="$(command -v psql)"
if [ -z "$PSQL_BIN" ]; then
  echo "ERROR: psql not found on PATH" >&2
  exit 1
fi

# Parse the connection string. We don't try to be clever —
# the deploy hosts use postgresql://user:pass@host:port/dbname
# and the testing config matches exactly (see
# deploy/env/testing.app.env.example). If a future env uses
# a different shape, update this parsing.
DB_URL_NO_SCHEME="${DATABASE_URL#postgresql://}"
DB_USER_PASS="${DB_URL_NO_SCHEME%%@*}"
DB_HOST_PORT_DB="${DB_URL_NO_SCHEME#*@}"

DB_USER="${DB_USER_PASS%%:*}"
DB_PASS="${DB_USER_PASS#*:}"
DB_HOST_PORT_DB="${DB_HOST_PORT_DB%%/*}"
DB_HOST="${DB_HOST_PORT_DB%%:*}"
DB_PORT="${DB_HOST_PORT_DB#*:}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_URL_NO_SCHEME##*/}"

# Strip query params from db name (rare, but defensive).
DB_NAME="${DB_NAME%%\?*}"

echo "[db_upgrade_safe] env=$ENV_NAME db=$DB_NAME host=$DB_HOST:$DB_PORT"

# Read current alembic version. Use a single-quoted SQL string
# with the password passed via PGPASSWORD (cleaner than URL-encoding).
CURRENT_VERSION="$(
  PGPASSWORD="$DB_PASS" "$PSQL_BIN" \
    -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -tA -c "SELECT version_num FROM alembic_version" 2>&1
)"

if [ -z "$CURRENT_VERSION" ]; then
  echo "[db_upgrade_safe] ERROR: could not read alembic_version (table missing?)" >&2
  exit 1
fi

echo "[db_upgrade_safe] current alembic_version = $CURRENT_VERSION"

if [ "$CURRENT_VERSION" = "$BRIDGE_FROM" ]; then
  echo "[db_upgrade_safe] DB stuck at deleted $BRIDGE_FROM — stamping to $BRIDGE_TO"
  PGPASSWORD="$DB_PASS" "$PSQL_BIN" \
    -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -q -c "UPDATE alembic_version SET version_num = '$BRIDGE_TO'"
  echo "[db_upgrade_safe] stamped. alembic_version now $BRIDGE_TO"
else
  echo "[db_upgrade_safe] no bridge needed (current=$CURRENT_VERSION, bridge_from=$BRIDGE_FROM)"
fi

# Now run the normal upgrade — should walk forward cleanly.
FLASK_APP="${FLASK_APP:-wsgi:app}"
echo "[db_upgrade_safe] running: $FLASK_APP flask db upgrade head"
FLASK_APP="$FLASK_APP" flask db upgrade head

# Sanity-check the result.
NEW_VERSION="$(
  PGPASSWORD="$DB_PASS" "$PSQL_BIN" \
    -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -tA -c "SELECT version_num FROM alembic_version"
)"
echo "[db_upgrade_safe] new alembic_version = $NEW_VERSION"
echo "[db_upgrade_safe] OK"
