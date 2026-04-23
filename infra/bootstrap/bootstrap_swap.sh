#!/usr/bin/env bash
set -Eeuo pipefail

# bootstrap_swap.sh — Create a 2GB swap file if none exists
#
# Idempotent: skips creation if swap is already active.
# Useful on low-memory DigitalOcean droplets where pip installs or
# migrations can OOM without swap.
#
# Usage (as root or with sudo):
#   bash infra/bootstrap/bootstrap_swap.sh

SWAP_FILE="/swapfile"
SWAP_SIZE="2G"

log() {
  printf '[%s] [swap] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
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

# Check if swap is already active
SWAP_TOTAL="$(free -m | awk '/^Swap:/ {print $2}')"
if [ "${SWAP_TOTAL:-0}" -gt 0 ]; then
  log "Swap is already active (${SWAP_TOTAL}MB). Nothing to do."
  exit 0
fi

# Check if swapfile exists but isn't active
if [ -f "$SWAP_FILE" ]; then
  log "Swap file exists but is inactive — activating"
  chmod 0600 "$SWAP_FILE"
  mkswap "$SWAP_FILE"
  swapon "$SWAP_FILE"
else
  log "Creating ${SWAP_SIZE} swap file at ${SWAP_FILE}"
  fallocate -l "$SWAP_SIZE" "$SWAP_FILE"
  chmod 0600 "$SWAP_FILE"
  mkswap "$SWAP_FILE"
  swapon "$SWAP_FILE"
  log "Swap file created and activated"
fi

# Persist across reboots via /etc/fstab
if ! grep -qF "$SWAP_FILE" /etc/fstab; then
  log "Adding swap entry to /etc/fstab"
  echo "${SWAP_FILE}   none   swap   sw   0   0" >> /etc/fstab
else
  log "Swap entry already in /etc/fstab"
fi

# Tune swappiness for a server (prefer RAM, use swap as safety net)
CURRENT_SWAPPINESS="$(cat /proc/sys/vm/swappiness)"
if [ "$CURRENT_SWAPPINESS" -gt 10 ]; then
  log "Reducing vm.swappiness from ${CURRENT_SWAPPINESS} to 10"
  sysctl vm.swappiness=10
  if ! grep -qF "vm.swappiness" /etc/sysctl.conf; then
    echo "vm.swappiness=10" >> /etc/sysctl.conf
  fi
else
  log "vm.swappiness is already ${CURRENT_SWAPPINESS}"
fi

log "Swap setup complete"
free -h | grep -i swap
