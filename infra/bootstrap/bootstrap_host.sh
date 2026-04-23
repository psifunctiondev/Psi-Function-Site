#!/usr/bin/env bash
set -Eeuo pipefail

# bootstrap_host.sh — Top-level bootstrap orchestrator
#
# Run all bootstrap scripts in order on a fresh host.
# Each script is idempotent, so re-running is safe.
#
# Usage (as root):
#   bash infra/bootstrap/bootstrap_host.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() {
  printf '[%s] [bootstrap] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

# bash infra/bootstrap/install_base_packages.sh
# bash infra/bootstrap/install_nginx.sh

log "Installing fail2ban"
bash "${SCRIPT_DIR}/install_fail2ban.sh"

log "Setting up swap"
bash "${SCRIPT_DIR}/bootstrap_swap.sh"

log "Setting up PostgreSQL"
bash "${SCRIPT_DIR}/bootstrap_postgres.sh"

# bash infra/bootstrap/configure_app_dirs.sh
# bash infra/bootstrap/install_systemd_units.sh

log "Host bootstrap complete"