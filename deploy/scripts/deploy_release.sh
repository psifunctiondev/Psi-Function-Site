#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

APP_DIR="/opt/consulting-site"
RELEASES_DIR="$APP_DIR/releases"
SOURCE_DIR="$APP_DIR/source"
SHARED_DIR="$APP_DIR/shared"
CURRENT_LINK="$APP_DIR/current"
PREVIOUS_LINK="$APP_DIR/previous"
KEEP_RELEASES="${KEEP_RELEASES:-5}"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
NEW_RELEASE="$RELEASES_DIR/$TIMESTAMP"
VENV_DIR="$NEW_RELEASE/.venv"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

cleanup_on_error() {
  local exit_code=$?
  log "Deploy failed with exit code ${exit_code}"
  log "Leaving current release unchanged"
  if [ -d "$NEW_RELEASE" ]; then
    log "Removing incomplete release: $NEW_RELEASE"
    rm -rf "$NEW_RELEASE"
  fi
  exit "$exit_code"
}

trap cleanup_on_error ERR

require_cmd rsync
require_cmd python3
require_cmd systemctl
require_cmd nginx
require_cmd readlink

mkdir -p \
  "$RELEASES_DIR" \
  "$SOURCE_DIR" \
  "$SHARED_DIR/env" \
  "$SHARED_DIR/logs" \
  "$SHARED_DIR/uploads" \
  "$SHARED_DIR/tmp"

[ -d "$SOURCE_DIR" ] || fail "Source directory missing: $SOURCE_DIR"

log "Creating new release directory: $NEW_RELEASE"
mkdir -p "$NEW_RELEASE"

log "Syncing source into release"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.github' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.mypy_cache' \
  --exclude 'node_modules' \
  "$SOURCE_DIR"/ "$NEW_RELEASE"/

cd "$NEW_RELEASE"

if [ -f "$SHARED_DIR/env/app.env" ]; then
  log "Loading environment: $SHARED_DIR/env/app.env"
  set -a
  # shellcheck disable=SC1091
  source "$SHARED_DIR/env/app.env"
  set +a
else
  log "No shared env file found; continuing"
fi

log "Creating Python virtual environment"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --upgrade pip wheel

if [ -f "pyproject.toml" ]; then
  log "Installing Python package from pyproject.toml"
  pip install .
elif [ -f "requirements.txt" ]; then
  log "Installing Python dependencies from requirements.txt"
  pip install -r requirements.txt
else
  log "No pyproject.toml or requirements.txt found; skipping Python dependency install"
fi

if [ -f "package-lock.json" ]; then
  require_cmd npm
  log "Installing Node dependencies with npm ci"
  npm ci
elif [ -f "package.json" ]; then
  require_cmd npm
  log "Installing Node dependencies with npm install"
  npm install
fi

if [ -f "package.json" ]; then
  log "Building frontend assets"
  npm run build
fi

log "Linking shared writable paths"
rm -rf "$NEW_RELEASE/uploads" "$NEW_RELEASE/logs" "$NEW_RELEASE/tmp"
ln -sfn "$SHARED_DIR/uploads" "$NEW_RELEASE/uploads"
ln -sfn "$SHARED_DIR/logs" "$NEW_RELEASE/logs"
ln -sfn "$SHARED_DIR/tmp" "$NEW_RELEASE/tmp"

if [ -f "manage.py" ]; then
  log "Running database migrations"
  python manage.py db upgrade
fi

log "Running pre-activation validation"

if [ -f "manage.py" ]; then
  python - <<'PY'
import importlib.util
import sys
spec = importlib.util.spec_from_file_location("manage", "manage.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print("manage.py import OK")
PY
fi

if [ -L "$CURRENT_LINK" ]; then
  CURRENT_TARGET="$(readlink -f "$CURRENT_LINK")"
  if [ -n "$CURRENT_TARGET" ] && [ -d "$CURRENT_TARGET" ]; then
    log "Updating previous symlink -> $CURRENT_TARGET"
    ln -sfn "$CURRENT_TARGET" "$PREVIOUS_LINK"
  fi
fi

log "Activating new release"
ln -sfn "$NEW_RELEASE" "$CURRENT_LINK"

log "Restarting application service"
sudo systemctl restart consulting-site
sudo systemctl is-active --quiet consulting-site || fail "consulting-site service failed to start"

log "Validating nginx configuration"
sudo nginx -t

log "Reloading nginx"
sudo systemctl reload nginx

log "Pruning old releases, keeping newest $KEEP_RELEASES"
cd "$RELEASES_DIR"
ls -1dt */ 2>/dev/null | tail -n +"$((KEEP_RELEASES + 1))" | xargs -r rm -rf

log "Deploy successful"
log "Current release:  $(readlink -f "$CURRENT_LINK")"
if [ -L "$PREVIOUS_LINK" ]; then
  log "Previous release: $(readlink -f "$PREVIOUS_LINK")"
fi
