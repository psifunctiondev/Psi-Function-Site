#!/usr/bin/env bash
set -Eeuo pipefail

# bootstrap_postgres.sh — Idempotent PostgreSQL setup for Psi Function consulting site
#
# Creates three isolated databases (testing, staging, production) with dedicated
# roles and scram-sha-256 auth.  Safe to run multiple times.
#
# Usage (as root or with sudo):
#   bash infra/bootstrap/bootstrap_postgres.sh [--rotate-passwords]
#
# Outputs DATABASE_URL values for each environment to stdout and writes them
# to /opt/consulting-site/.db_credentials (mode 0600, root-only).
#
# By default, existing roles keep their current passwords. Pass
# --rotate-passwords to regenerate all passwords (you'll need to update
# each environment's app.env afterward).

ENVIRONMENTS=("testing" "staging" "production")
DB_PREFIX="psifunction"
CREDENTIALS_FILE="/opt/consulting-site/.db_credentials"
ROTATE_PASSWORDS=0

for arg in "$@"; do
  case "$arg" in
    --rotate-passwords) ROTATE_PASSWORDS=1 ;;
    *) ;;
  esac
done

log() {
  printf '[%s] [postgres] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    fail "This script must be run as root (or via sudo)"
  fi
}

require_root

# ---------------------------------------------------------------------------
# 1. Install PostgreSQL
# ---------------------------------------------------------------------------
log "Ensuring PostgreSQL is installed"
if ! command -v psql >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq postgresql postgresql-contrib
  log "PostgreSQL installed"
else
  log "PostgreSQL already installed ($(psql --version))"
fi

# Make sure the cluster is running
systemctl enable --now postgresql
systemctl is-active --quiet postgresql || fail "PostgreSQL service failed to start"
log "PostgreSQL service is active"

# ---------------------------------------------------------------------------
# 2. Enforce scram-sha-256 password encryption
# ---------------------------------------------------------------------------
PG_VERSION="$(pg_lsclusters -h | awk '{print $1; exit}')"
PG_CONF="/etc/postgresql/${PG_VERSION}/main/postgresql.conf"
PG_HBA="/etc/postgresql/${PG_VERSION}/main/pg_hba.conf"

if [ ! -f "$PG_CONF" ]; then
  fail "Cannot find postgresql.conf at $PG_CONF"
fi

# Set password_encryption to scram-sha-256 if not already
if grep -q "^password_encryption\s*=\s*'scram-sha-256'" "$PG_CONF" 2>/dev/null; then
  log "password_encryption already set to scram-sha-256"
else
  log "Setting password_encryption = scram-sha-256"
  # Remove any existing (possibly commented) line, then append
  sed -i '/^#\?password_encryption/d' "$PG_CONF"
  echo "password_encryption = 'scram-sha-256'" >> "$PG_CONF"
  PG_NEEDS_RELOAD=1
fi

# ---------------------------------------------------------------------------
# 3. Configure pg_hba.conf for local socket auth
# ---------------------------------------------------------------------------
# We add scram-sha-256 rules for each app role on local sockets.
# Existing peer auth for postgres and other system users is left intact.
HBA_MARKER="# --- Psi Function app roles (managed by bootstrap_postgres.sh) ---"

if grep -qF "$HBA_MARKER" "$PG_HBA" 2>/dev/null; then
  log "pg_hba.conf already contains Psi Function rules"
else
  log "Adding scram-sha-256 local socket rules to pg_hba.conf"

  # Build the HBA block
  HBA_BLOCK="
${HBA_MARKER}
# Allow each app role to connect to its own database via local socket
"
  for env in "${ENVIRONMENTS[@]}"; do
    HBA_BLOCK+="local   ${DB_PREFIX}_${env}   ${DB_PREFIX}_${env}   scram-sha-256
"
  done

  # Insert before the first uncommented "local" line so our rules take priority
  # over the catch-all "local all all peer" rule.
  FIRST_LOCAL_LINE="$(grep -n '^local' "$PG_HBA" | head -1 | cut -d: -f1 || true)"
  if [ -n "$FIRST_LOCAL_LINE" ]; then
    # Write the block to a temp file, then use sed to read it in
    HBA_TMP="$(mktemp)"
    printf '%s\n' "$HBA_BLOCK" > "$HBA_TMP"
    sed -i "${FIRST_LOCAL_LINE}r ${HBA_TMP}" "$PG_HBA"
    rm -f "$HBA_TMP"
  else
    # No existing local lines — just append
    printf '%s\n' "$HBA_BLOCK" >> "$PG_HBA"
  fi

  PG_NEEDS_RELOAD=1
fi

# Reload if config changed
if [ "${PG_NEEDS_RELOAD:-0}" = "1" ]; then
  log "Reloading PostgreSQL configuration"
  systemctl reload postgresql
  sleep 1
fi

# ---------------------------------------------------------------------------
# 4. Generate passwords and create roles + databases
# ---------------------------------------------------------------------------
generate_password() {
  # 32-char random alphanumeric password
  openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 32
}

# Helper: run SQL as the postgres system user
pg_exec() {
  sudo -u postgres psql -tAc "$1"
}

# Helper: check if a role or database exists (returns 0 or 1, safe under set -e)
role_exists() {
  local result
  result="$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$1'" 2>/dev/null || true)"
  [[ "$result" == *"1"* ]]
}

db_exists() {
  local result
  result="$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$1'" 2>/dev/null || true)"
  [[ "$result" == *"1"* ]]
}

mkdir -p "$(dirname "$CREDENTIALS_FILE")"

# We'll accumulate credential output here
CRED_OUTPUT=""

for env in "${ENVIRONMENTS[@]}"; do
  ROLE="${DB_PREFIX}_${env}"
  DB="${DB_PREFIX}_${env}"

  # Create role if it doesn't exist
  if role_exists "${ROLE}"; then
    log "Role '${ROLE}' already exists"
    if [ "$ROTATE_PASSWORDS" = "1" ]; then
      PASSWORD="$(generate_password)"
      pg_exec "ALTER ROLE ${ROLE} WITH PASSWORD '${PASSWORD}'"
      log "Password rotated for role '${ROLE}'"
    else
      # Read existing password from credentials file if available
      if [ -f "$CREDENTIALS_FILE" ]; then
        EXISTING_URL="$(grep "^DATABASE_URL=postgresql://${ROLE}:" "$CREDENTIALS_FILE" | head -1 | sed 's/^DATABASE_URL=//')"
        if [ -n "$EXISTING_URL" ]; then
          PASSWORD="$(echo "$EXISTING_URL" | sed "s|postgresql://${ROLE}:\(.*\)@localhost/${DB}|\1|")"
          log "Keeping existing password for role '${ROLE}'"
        else
          PASSWORD="$(generate_password)"
          pg_exec "ALTER ROLE ${ROLE} WITH PASSWORD '${PASSWORD}'"
          log "No existing password found — generated new one for role '${ROLE}'"
        fi
      else
        PASSWORD="$(generate_password)"
        pg_exec "ALTER ROLE ${ROLE} WITH PASSWORD '${PASSWORD}'"
        log "No credentials file — generated new password for role '${ROLE}'"
      fi
    fi
  else
    PASSWORD="$(generate_password)"
    pg_exec "CREATE ROLE ${ROLE} WITH LOGIN PASSWORD '${PASSWORD}'"
    log "Created role '${ROLE}'"
  fi

  # Create database if it doesn't exist
  if db_exists "${DB}"; then
    log "Database '${DB}' already exists"
  else
    pg_exec "CREATE DATABASE ${DB} OWNER ${ROLE}"
    log "Created database '${DB}'"
  fi

  # Ensure ownership (idempotent)
  pg_exec "ALTER DATABASE ${DB} OWNER TO ${ROLE}"

  # Revoke public access (idempotent)
  pg_exec "REVOKE ALL ON DATABASE ${DB} FROM PUBLIC"

  URL="postgresql://${ROLE}:${PASSWORD}@localhost/${DB}"
  CRED_OUTPUT+="# ${env}
DATABASE_URL=${URL}

"
done

# ---------------------------------------------------------------------------
# 5. Write credentials file
# ---------------------------------------------------------------------------
log "Writing credentials to ${CREDENTIALS_FILE}"
cat > "$CREDENTIALS_FILE" <<EOF
# Psi Function database credentials
# Generated by bootstrap_postgres.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Keep this file safe — it contains database passwords.
#
# Copy the DATABASE_URL for each environment into its respective app.env:
#   /opt/consulting-site/{env}/shared/env/app.env

${CRED_OUTPUT}EOF

chmod 0600 "$CREDENTIALS_FILE"
chown root:root "$CREDENTIALS_FILE"

# ---------------------------------------------------------------------------
# 6. Print summary
# ---------------------------------------------------------------------------
log "PostgreSQL bootstrap complete"
echo ""
echo "========================================================"
echo "  DATABASE CREDENTIALS"
echo "========================================================"
echo ""
echo "$CRED_OUTPUT"
echo "Credentials also saved to: ${CREDENTIALS_FILE}"
echo ""
echo "Next steps:"
echo "  1. Copy each DATABASE_URL into the corresponding environment's app.env:"
echo "     /opt/consulting-site/{testing,staging,production}/shared/env/app.env"
echo "  2. Run 'flask db upgrade' via deploy to apply migrations"
echo "========================================================"
