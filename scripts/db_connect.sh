#!/usr/bin/env bash
set -Eeuo pipefail

# db_connect.sh — Open a psql session against a deployed environment's database.
#
# Reads DATABASE_URL from the environment's app.env (or, as a fallback, from
# the root-only credentials file written by bootstrap_postgres.sh), then
# launches psql.  Any extra arguments are forwarded to psql, so e.g.
#
#   scripts/db_connect.sh staging
#   scripts/db_connect.sh staging -c '\dt'
#   scripts/db_connect.sh production -c 'SELECT count(*) FROM work_item;'
#
# Connections use the local Unix socket with scram-sha-256 auth (the same
# rules bootstrap_postgres.sh installs in pg_hba.conf), so the script must
# run on the database host.

APP_ROOT="${APP_ROOT:-/opt/consulting-site}"
VALID_ENVS=("testing" "staging" "production")

usage() {
  cat >&2 <<EOF
Usage: $0 <$(IFS='|'; echo "${VALID_ENVS[*]}">> [psql-args...]

Open an interactive psql session against the named environment's database.
Any additional arguments are passed through to psql.

Environment overrides:
  APP_ROOT   Root directory of deployed environments (default: /opt/consulting-site)
EOF
  exit 1
}

log() {
  printf '[%s] [db_connect] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

fail() {
  log "ERROR: $*"
  exit 1
}

ENVIRONMENT="${1:-}"
if [ -z "$ENVIRONMENT" ]; then
  usage
fi
shift || true

case "$ENVIRONMENT" in
  testing|staging|production) ;;
  *) fail "Invalid environment: ${ENVIRONMENT}" ;;
esac

command -v psql >/dev/null 2>&1 || fail "psql is not installed on this host"

APP_ENV_FILE="${APP_ROOT}/${ENVIRONMENT}/shared/env/app.env"
CREDENTIALS_FILE="${APP_ROOT}/.db_credentials"

# 1. Pull DATABASE_URL from app.env (preferred — matches what the app uses).
if [ -f "$APP_ENV_FILE" ]; then
  log "Loading DATABASE_URL from ${APP_ENV_FILE}"
  # shellcheck disable=SC1090
  DATABASE_URL="$(set -a; source "$APP_ENV_FILE"; set +a; printf '%s' "${DATABASE_URL:-}")"
fi

# 2. Fall back to the root-only credentials file (may need sudo).
if [ -z "${DATABASE_URL:-}" ] && [ -f "$CREDENTIALS_FILE" ]; then
  log "Loading DATABASE_URL from ${CREDENTIALS_FILE}"
  if [ -r "$CREDENTIALS_FILE" ]; then
    DATABASE_URL="$(grep "^DATABASE_URL=" "$CREDENTIALS_FILE" \
      | sed -n "/${ENVIRONMENT}\/psifunction_${ENVIRONMENT}/p; $!d; p" \
      | head -1 \
      | sed 's/^DATABASE_URL=//')"
  else
    log "Credentials file is not readable; trying sudo"
    DATABASE_URL="$(sudo grep "^DATABASE_URL=" "$CREDENTIALS_FILE" \
      | sed -n "/${ENVIRONMENT}\/psifunction_${ENVIRONMENT}/p; $!d; p" \
      | head -1 \
      | sed 's/^DATABASE_URL=//')"
  fi
fi

if [ -z "${DATABASE_URL:-}" ]; then
  fail "Could not find DATABASE_URL for '${ENVIRONMENT}' (looked in ${APP_ENV_FILE} and ${CREDENTIALS_FILE})"
fi

# 3. Parse the SQLAlchemy-style URL.  Handles the postgresql+psycopg scheme
#    that bootstrap_postgres.sh writes.
URL_NO_SCHEME="${DATABASE_URL#*://}"
USER="$(printf '%s' "$URL_NO_SCHEME" | sed -n 's|^\([^:]*\):.*|\1|p')"
PASSWORD="$(printf '%s' "$URL_NO_SCHEME" | sed -n 's|^[^:]*:\([^@]*\)@.*|\1|p')"
HOSTDB="$(printf '%s' "$URL_NO_SCHEME" | sed -n 's|^[^@]*@||p')"
HOST="${HOSTDB%%/*}"
HOST="${HOST%%:*}"
DB="${HOSTDB#*/}"
DB="${DB%%\?*}"

if [ -z "$USER" ] || [ -z "$DB" ]; then
  fail "Could not parse DATABASE_URL: ${DATABASE_URL}"
fi

# 4. Local-socket connection (matches the HBA rules bootstrap_postgres.sh
#    installs).  We blank PGHOST so libpq uses /var/run/postgresql, then
#    pass the rest explicitly.
export PGHOST=
export PGPORT=
export PGUSER="$USER"
export PGDATABASE="$DB"
export PGPASSWORD="$PASSWORD"

log "Connecting to '${DB}' as '${USER}' via local socket (env: ${ENVIRONMENT})"
exec psql "$@"
