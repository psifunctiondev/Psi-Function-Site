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
SOURCE_DIR="${APP_DIR}/source"
SHARED_DIR="${APP_DIR}/shared"
CURRENT_LINK="${APP_DIR}/current"
RELEASE_SCRIPT="${SOURCE_DIR}/deploy/scripts/deploy_release.sh"

SERVICE_TEMPLATE="/etc/systemd/system/consulting-site@.service"
SERVICE_NAME="consulting-site@${ENVIRONMENT}"

case "$ENVIRONMENT" in
  staging)
    NGINX_SITE_NAME="staging.conf"
    ;;
  production)
    NGINX_SITE_NAME="production.conf"
    ;;
esac

NGINX_SITE_AVAILABLE="/etc/nginx/sites-available/${NGINX_SITE_NAME}"
NGINX_SITE_ENABLED="/etc/nginx/sites-enabled/${NGINX_SITE_NAME}"

SOCKET_PATH="${SHARED_DIR}/run/gunicorn.sock"

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

check_path_exists() {
  local path="$1"
  local label="$2"

  [ -e "$path" ] || fail "${label} not found: ${path}"
}

check_path_dir() {
  local path="$1"
  local label="$2"

  [ -d "$path" ] || fail "${label} not found or not a directory: ${path}"
}

check_path_executable() {
  local path="$1"
  local label="$2"

  [ -x "$path" ] || fail "${label} not found or not executable: ${path}"
}

check_systemd_unit() {
  log "Verifying systemd unit presence"

  check_path_exists "$SERVICE_TEMPLATE" "Systemd template unit"

  if ! sudo systemctl cat "$SERVICE_NAME" >/dev/null 2>&1; then
    fail "Systemd cannot read unit: ${SERVICE_NAME}"
  fi

  if ! sudo systemctl is-enabled "$SERVICE_NAME" >/dev/null 2>&1; then
    fail "Systemd instance is not enabled: ${SERVICE_NAME}"
  fi

  log "Verified systemd unit: ${SERVICE_NAME}"
}

check_nginx_site() {
  log "Verifying nginx site presence"

  check_path_exists "$NGINX_SITE_AVAILABLE" "Nginx site in sites-available"
  check_path_exists "$NGINX_SITE_ENABLED" "Nginx site symlink in sites-enabled"

  sudo nginx -t >/dev/null 2>&1 || fail "nginx configuration test failed"

  log "Verified nginx site: ${NGINX_SITE_NAME}"
}

check_app_layout() {
  log "Verifying application layout"

  check_path_dir "$APP_DIR" "App directory"
  check_path_dir "$SOURCE_DIR" "Source directory"
  check_path_dir "$SHARED_DIR" "Shared directory"
  check_path_dir "${SHARED_DIR}/env" "Shared env directory"
  check_path_dir "${SHARED_DIR}/logs" "Shared logs directory"
  check_path_dir "${SHARED_DIR}/uploads" "Shared uploads directory"
  check_path_dir "${SHARED_DIR}/run" "Shared run directory"

  check_path_executable "$RELEASE_SCRIPT" "Release script"

  log "Verified application layout"
}

check_deploy_permissions() {
  log "Verifying deploy permissions"

  [ -w "$SOURCE_DIR" ] || fail "Source directory is not writable: ${SOURCE_DIR}"
  [ -w "${APP_DIR}/releases" ] || fail "Releases directory is not writable: ${APP_DIR}/releases"
  [ -w "${SHARED_DIR}/run" ] || fail "Shared run directory is not writable: ${SHARED_DIR}/run"

  if ! sudo -n true >/dev/null 2>&1; then
    fail "Passwordless sudo is required for deploy operations"
  fi

  if ! sudo systemctl status "$SERVICE_NAME" --no-pager >/dev/null 2>&1; then
    fail "Cannot query systemd service with sudo: ${SERVICE_NAME}"
  fi

  log "Verified deploy permissions"
}

check_current_state() {
  if [ -L "$CURRENT_LINK" ]; then
    local current_target
    current_target="$(readlink -f "$CURRENT_LINK" || true)"
    if [ -n "$current_target" ] && [ -d "$current_target" ]; then
      log "Current release target: ${current_target}"
      if [ -f "${current_target}/REVISION" ]; then
        log "Current revision: $(cat "${current_target}/REVISION")"
      fi
    else
      log "Current symlink exists but target is broken"
    fi
  else
    log "No current release symlink yet; first deploy is allowed"
  fi
}

main() {
  require_cmd sudo
  require_cmd systemctl
  require_cmd nginx
  require_cmd grep
  require_cmd readlink
  require_cmd bash

  log "Starting deploy preflight for SHA ${GIT_SHA}"

  check_app_layout
  check_deploy_permissions
  check_systemd_unit

  if [ "${REQUIRE_NGINX:-1}" = "1" ]; then
    check_nginx_site
  else
    log "Skipping nginx verification because REQUIRE_NGINX=${REQUIRE_NGINX:-1}"
  fi

  check_current_state

  log "Running release deployment"
  bash "$RELEASE_SCRIPT" "$ENVIRONMENT" "$GIT_SHA"

  log "Post-deploy verification"
  if [ ! -L "$CURRENT_LINK" ]; then
    fail "Current symlink missing after deploy: ${CURRENT_LINK}"
  fi

  if [ ! -S "$SOCKET_PATH" ]; then
    fail "Gunicorn socket missing after deploy: ${SOCKET_PATH}"
  fi

  if [ ! -f "${CURRENT_LINK}/REVISION" ]; then
    fail "REVISION file missing in current release after deploy"
  fi

  local deployed_revision
  deployed_revision="$(cat "${CURRENT_LINK}/REVISION")"
  if [ "$deployed_revision" != "$GIT_SHA" ]; then
    fail "Deployed revision mismatch: expected ${GIT_SHA}, found ${deployed_revision}"
  fi

  log "Deploy completed successfully"
  log "Active service: ${SERVICE_NAME}"
  log "Active release: $(readlink -f "$CURRENT_LINK")"
  log "Active revision: ${deployed_revision}"
}

main "$@"
