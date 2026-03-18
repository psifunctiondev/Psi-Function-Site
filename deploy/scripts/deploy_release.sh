#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

usage() {
  echo "Usage: $0 <staging|production> <git-sha>" >&2
  exit 1
}

ENVIRONMENT="${1:-}"
GIT_SHA="${2:-}"

[ -n "$ENVIRONMENT" ] || usage
[ -n "$GIT_SHA" ] || usage

case "$ENVIRONMENT" in
  staging|production) ;;
  *)
    echo "Invalid environment: $ENVIRONMENT" >&2
    usage
    ;;
esac

APP_DIR="/opt/consulting-site/${ENVIRONMENT}"
RELEASES_DIR="$APP_DIR/releases"
SOURCE_DIR="$APP_DIR/source"
SHARED_DIR="$APP_DIR/shared"
CURRENT_LINK="$APP_DIR/current"
PREVIOUS_LINK="$APP_DIR/previous"
KEEP_RELEASES="${KEEP_RELEASES:-5}"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
NEW_RELEASE="$RELEASES_DIR/$TIMESTAMP"
VENV_DIR="$NEW_RELEASE/.venv"

OLD_CURRENT=""
ACTIVATED=0

SERVICE_NAME="consulting-site@${ENVIRONMENT}"
SOCKET_PATH="$SHARED_DIR/run/gunicorn.sock"
APP_HEALTH_TIMEOUT="${APP_HEALTH_TIMEOUT:-30}"

log() {
  printf '[%s] [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$ENVIRONMENT" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

version_ge() {
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

cleanup_on_error() {
  local exit_code=$?

  log "Deploy failed with exit code ${exit_code}"

  if [ "$ACTIVATED" = "1" ]; then
    if [ -n "$OLD_CURRENT" ] && [ -d "$OLD_CURRENT" ]; then
      log "Rolling current symlink back to previous release: $OLD_CURRENT"
      ln -sfn "$OLD_CURRENT" "$CURRENT_LINK"

      log "Attempting to restart application on previous release"
      sudo systemctl restart "$SERVICE_NAME" || true
    else
      log "No valid previous release available for rollback"
      rm -f "$CURRENT_LINK" || true
    fi
  else
    log "Activation never occurred; current symlink left unchanged"
  fi

  if [ -d "$NEW_RELEASE" ]; then
    log "Removing failed release: $NEW_RELEASE"
    rm -rf "$NEW_RELEASE"
  fi

  exit "$exit_code"
}

trap cleanup_on_error ERR

require_cmd rsync
require_cmd python3
require_cmd systemctl
require_cmd readlink
require_cmd sort
require_cmd curl

mkdir -p \
  "$RELEASES_DIR" \
  "$SOURCE_DIR" \
  "$SHARED_DIR/env" \
  "$SHARED_DIR/logs" \
  "$SHARED_DIR/uploads" \
  "$SHARED_DIR/run" \
  "$SHARED_DIR/tmp"

[ -d "$SOURCE_DIR" ] || fail "Source directory missing: $SOURCE_DIR"

if [ -L "$CURRENT_LINK" ]; then
  OLD_CURRENT="$(readlink -f "$CURRENT_LINK" || true)"
  if [ -n "$OLD_CURRENT" ] && [ ! -d "$OLD_CURRENT" ]; then
    log "Existing current target is broken: $OLD_CURRENT"
    OLD_CURRENT=""
  fi
fi

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

printf '%s\n' "$GIT_SHA" > REVISION
date -u +"%Y-%m-%dT%H:%M:%SZ" > RELEASED_AT
printf '%s\n' "$ENVIRONMENT" > DEPLOY_ENVIRONMENT

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

if [ -f "package.json" ]; then
  require_cmd node
  require_cmd npm

  NODE_VERSION_RAW="$(node -v)"
  NODE_VERSION="${NODE_VERSION_RAW#v}"

  log "Detected Node version: $NODE_VERSION_RAW"
  log "Detected npm version: $(npm -v)"

  if [[ "$NODE_VERSION" == 20.* ]]; then
    version_ge "$NODE_VERSION" "20.19.0" || \
      fail "Node.js 20.19.0+ required for this frontend build; found $NODE_VERSION_RAW"
  elif [[ "$NODE_VERSION" == 21.* ]]; then
    fail "Node.js 21 is not accepted for this frontend build; use 20.19+ or 22.12+"
  elif [[ "$NODE_VERSION" == 22.* ]]; then
    version_ge "$NODE_VERSION" "22.12.0" || \
      fail "Node.js 22.12.0+ required for this frontend build; found $NODE_VERSION_RAW"
  else
    NODE_MAJOR="${NODE_VERSION%%.*}"
    if [ "$NODE_MAJOR" -lt 20 ]; then
      fail "Node.js 20.19.0+ or 22.12.0+ required for this frontend build; found $NODE_VERSION_RAW"
    fi
  fi

  if [ -f "package-lock.json" ]; then
    log "Installing Node dependencies with npm ci"
    npm ci
  else
    log "Installing Node dependencies with npm install"
    npm install
  fi

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

if [ -f "wsgi.py" ]; then
  python - <<'PY'
import importlib.util

spec = importlib.util.spec_from_file_location("wsgi", "wsgi.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

assert getattr(module, "app", None) is not None
print("wsgi:app import OK")
PY
else
  log "No wsgi.py found; skipping Gunicorn target validation"
fi

if [ -n "$OLD_CURRENT" ] && [ -d "$OLD_CURRENT" ]; then
  log "Updating previous symlink -> $OLD_CURRENT"
  ln -sfn "$OLD_CURRENT" "$PREVIOUS_LINK"
fi

log "Activating new release"
ln -sfn "$NEW_RELEASE" "$CURRENT_LINK"
ACTIVATED=1

log "Restarting application service"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl is-active --quiet "$SERVICE_NAME" || fail "$SERVICE_NAME failed to start"

log "Checking Gunicorn health endpoint over unix socket"
for i in $(seq 1 "$APP_HEALTH_TIMEOUT"); do
  if [ -S "$SOCKET_PATH" ] && \
     curl --silent --show-error --fail \
       --unix-socket "$SOCKET_PATH" \
       http://localhost/health >/dev/null; then
    log "Gunicorn health check passed"
    break
  fi

  if [ "$i" -eq "$APP_HEALTH_TIMEOUT" ]; then
    fail "Gunicorn health check failed after ${APP_HEALTH_TIMEOUT}s"
  fi

  sleep 1
done

log "Pruning old releases, keeping newest $KEEP_RELEASES"
cd "$RELEASES_DIR"
ls -1dt */ 2>/dev/null | tail -n +"$((KEEP_RELEASES + 1))" | xargs -r rm -rf

log "Deploy successful"
log "Current release: $(readlink -f "$CURRENT_LINK")"
log "Current revision: $(cat "$CURRENT_LINK/REVISION")"
if [ -L "$PREVIOUS_LINK" ]; then
  log "Previous release: $(readlink -f "$PREVIOUS_LINK")"
fi
