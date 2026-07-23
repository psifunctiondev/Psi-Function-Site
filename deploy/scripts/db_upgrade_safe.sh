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
# Why Python+psycopg instead of psql
# ----------------------------------
# Earlier versions of this script used psql directly, but the
# deploy hosts don't ship the psql binary. The Python interpreter
# + psycopg (already a runtime dep of the Flask app, installed by
# deploy_release.sh's pip install step) is always available, so
# the bridge SQL runs through `python -c "import psycopg; ..."`.
#
# Refs: PR #71, PR #72 (wrapper), PR #73 (URL-parsing fix),
# the 2026-07-23 Drift & Anchor pivot from portal-DB to email
# intake.
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

# Locate Python. deploy_release.sh puts the app's .venv at
# $NEW_RELEASE/.venv (the release dir for the just-built version).
# Fall back to whatever python3 is on PATH if that doesn't exist
# (e.g. local dry-run).
#
# NOTE: deploy_release.sh does NOT export $NEW_RELEASE / $SOURCE_DIR
# into the subshell, so we use ${VAR:-} defaults to keep `set -u`
# happy on the first reference.
PYTHON_BIN=""
for candidate in "${NEW_RELEASE:-}/.venv/bin/python" "${SOURCE_DIR:-}/.venv/bin/python" "$(command -v python3)"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then
    PYTHON_BIN="$candidate"
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: no usable python interpreter found" >&2
  exit 1
fi

# Verify the chosen Python can import psycopg (the runtime DB
# driver). If not, fall back to PATH python3 which has the app's
# site-packages from deploy_release.sh's pip install step.
if ! "$PYTHON_BIN" -c "import psycopg" 2>/dev/null; then
  for fallback in "$(command -v python3)" "$(command -v python)"; do
    if [ -n "$fallback" ] && [ -x "$fallback" ] && "$fallback" -c "import psycopg" 2>/dev/null; then
      PYTHON_BIN="$fallback"
      break
    fi
  done
fi

echo "[db_upgrade_safe] env=$ENV_NAME python=$PYTHON_BIN"

# Run the bridge SQL through psycopg. We inline a Python heredoc
# so the script doesn't need a separate .py file in the deploy
# dir. Captures stdout (the version string) and exits non-zero
# on any error so set -e + pipefail surface the failure.
read_current_version() {
  "$PYTHON_BIN" - "$DATABASE_URL" <<'PYEOF'
import sys
import psycopg

url = sys.argv[1]
with psycopg.connect(url, connect_timeout=10) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
        if row is None:
            print("__MISSING__", end="")
            sys.exit(2)
        print(row[0], end="")
PYEOF
}

stamp_to_version() {
  local target_version="$1"
  "$PYTHON_BIN" - "$DATABASE_URL" "$target_version" <<'PYEOF'
import sys
import psycopg

url = sys.argv[1]
target = sys.argv[2]
with psycopg.connect(url, connect_timeout=10) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE alembic_version SET version_num = %s",
            (target,),
        )
    conn.commit()
PYEOF
}

CURRENT_VERSION="$(read_current_version)" || {
  rc=$?
  echo "[db_upgrade_safe] ERROR: could not read alembic_version (rc=$rc)" >&2
  exit 1
}

echo "[db_upgrade_safe] current alembic_version = $CURRENT_VERSION"

if [ "$CURRENT_VERSION" = "$BRIDGE_FROM" ]; then
  echo "[db_upgrade_safe] DB stuck at deleted $BRIDGE_FROM — stamping to $BRIDGE_TO"
  stamp_to_version "$BRIDGE_TO"
  echo "[db_upgrade_safe] stamped. alembic_version now $BRIDGE_TO"
else
  echo "[db_upgrade_safe] no bridge needed (current=$CURRENT_VERSION, bridge_from=$BRIDGE_FROM)"
fi

# Now run the normal upgrade — should walk forward cleanly.
FLASK_APP="${FLASK_APP:-wsgi:app}"
echo "[db_upgrade_safe] running: $FLASK_APP flask db upgrade head"
FLASK_APP="$FLASK_APP" flask db upgrade head

# Sanity-check the result.
NEW_VERSION="$(read_current_version)" || {
  rc=$?
  echo "[db_upgrade_safe] ERROR: could not re-read alembic_version (rc=$rc)" >&2
  exit 1
}
echo "[db_upgrade_safe] new alembic_version = $NEW_VERSION"
echo "[db_upgrade_safe] OK"
