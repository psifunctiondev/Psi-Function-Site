#!/usr/bin/env bash
set -Eeuo pipefail

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_cmd curl
require_cmd sudo
require_cmd apt-get

log "Updating apt metadata"
sudo apt-get update

log "Installing base packages"
sudo apt-get install -y \
  ca-certificates \
  curl \
  gnupg \
  python3 \
  python3-venv \
  python3-pip \
  rsync \
  nginx

log "Installing NodeSource LTS repository"
curl -fsSL https://deb.nodesource.com/setup_lts.x -o /tmp/nodesource_setup.sh
sudo -E bash /tmp/nodesource_setup.sh

log "Installing Node.js LTS"
sudo apt-get install -y nodejs

log "Installed versions"
python3 --version
node --version
npm --version
nginx -v
