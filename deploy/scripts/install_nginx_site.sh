#!/usr/bin/env bash
# install_nginx_site.sh — install (or update) the nginx site + snippet
# files for one of the consulting-site environments.
#
# Idempotent. Safe to run repeatedly on every deploy.
#
# Usage:
#   install_nginx_site.sh <testing|staging|production>
#
# What it does:
#   1. Copies deploy/nginx/${ENV}.conf -> /etc/nginx/sites-available/${SITE_NAME}
#   2. Ensures /etc/nginx/sites-enabled/${SITE_NAME} symlinks to the above
#   3. Removes the default site if present
#   4. Copies every file in deploy/nginx/snippets/ -> /etc/nginx/snippets/
#      (this was the missing piece in 2026-07-22 — slice-9 CSP changes
#      were never reaching the live server because the snippet files
#      were only ever written at original droplet provisioning, never
#      on deploy. See commit history for the postmortem.)
#   5. Validates the full nginx config and reloads.
#
# `install -m 0644` is content-aware: if the source and destination
# are byte-identical, the file mtime is preserved. This keeps `nginx
# reload` cheap when nothing has changed.
set -Eeuo pipefail

usage() {
  echo "Usage: $0 <testing|staging|production>" >&2
  exit 1
}

ENVIRONMENT="${1:-}"
[ -n "$ENVIRONMENT" ] || usage

case "$ENVIRONMENT" in
  testing|staging|production) ;;
  *)
    echo "Invalid environment: $ENVIRONMENT" >&2
    usage
    ;;
esac

APP_DIR="/opt/consulting-site/${ENVIRONMENT}"
SOURCE_DIR="$APP_DIR/source"

SITE_NAME="consulting-site-${ENVIRONMENT}"
SRC_CONF="$SOURCE_DIR/deploy/nginx/${ENVIRONMENT}.conf"
DEST_CONF="/etc/nginx/sites-available/${SITE_NAME}"
ENABLED="/etc/nginx/sites-enabled/${SITE_NAME}"
DEFAULT_ENABLED="/etc/nginx/sites-enabled/default"

# Snippet source/destination. Both are directories of .conf files
# (security-headers.conf + hardening-common.conf at the moment).
SNIPPETS_SRC="$SOURCE_DIR/deploy/nginx/snippets"
SNIPPETS_DEST="/etc/nginx/snippets"

log() {
  printf '[%s] [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$ENVIRONMENT" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

[ -f "$SRC_CONF" ] || fail "Missing nginx site file: $SRC_CONF"
[ -d "$SNIPPETS_SRC" ] || fail "Missing nginx snippets dir: $SNIPPETS_SRC"

# ---- Main site config ----

log "Installing nginx site ($SRC_CONF -> $DEST_CONF)"
sudo install -m 0644 "$SRC_CONF" "$DEST_CONF"

log "Enabling nginx site (symlink $ENABLED -> $DEST_CONF)"
sudo ln -sfn "$DEST_CONF" "$ENABLED"

if [ -L "$DEFAULT_ENABLED" ] || [ -e "$DEFAULT_ENABLED" ]; then
  log "Disabling default nginx site"
  sudo rm -f "$DEFAULT_ENABLED"
fi

# ---- Snippet files ----

log "Installing nginx snippets ($SNIPPETS_SRC -> $SNIPPETS_DEST)"
# Ensure the destination directory exists with sane perms.
sudo install -d -m 0755 "$SNIPPETS_DEST"

# Copy each file individually with install -m 0644 so the mtime is
# preserved when content is unchanged (avoids spurious nginx reloads
# on every deploy when the snippet hasn't actually changed).
shopt -s nullglob
SNIPPET_FILES=("$SNIPPETS_SRC"/*.conf)
shopt -u nullglob

if [ "${#SNIPPET_FILES[@]}" -eq 0 ]; then
  log "WARN: no .conf files found in $SNIPPETS_SRC — snippet copy is a no-op"
else
  for f in "${SNIPPET_FILES[@]}"; do
    name="$(basename "$f")"
    log "  snippet: $name"
    sudo install -m 0644 "$f" "$SNIPPETS_DEST/$name"
  done
fi

# ---- Validate + reload ----

log "Validating nginx configuration"
sudo nginx -t

log "Reloading nginx"
sudo systemctl reload nginx
