#!/usr/bin/env bash
set -euo pipefail

JAIL_LOCAL="/etc/fail2ban/jail.local"

if [[ ! -f "$JAIL_LOCAL" ]]; then
  echo "ERROR: $JAIL_LOCAL does not exist"
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "ERROR: curl is required but not installed"
  exit 1
fi

MY_IP="$(curl -4 --silent --show-error --fail https://ifconfig.me)"
if [[ -z "$MY_IP" ]]; then
  echo "ERROR: could not determine current public IPv4"
  exit 1
fi

if [[ ! "$MY_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  echo "ERROR: detected IP does not look like a valid IPv4 address: $MY_IP"
  exit 1
fi

MY_CIDR="${MY_IP}/32"

echo "Detected current public IP: $MY_IP"

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

sudo cp "$JAIL_LOCAL" "${JAIL_LOCAL}.bak.$(date +%Y%m%d_%H%M%S)"

CURRENT_IGNOREIP="$(sudo awk -F'=' '
  /^[[:space:]]*ignoreip[[:space:]]*=/ {
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2)
    print $2
    exit
  }
' "$JAIL_LOCAL")"

if [[ -z "$CURRENT_IGNOREIP" ]]; then
  echo "ERROR: no ignoreip line found in $JAIL_LOCAL"
  exit 1
fi

if grep -qw "$MY_CIDR" <<< "$CURRENT_IGNOREIP"; then
  echo "IP already present in ignoreip: $MY_CIDR"
else
  NEW_IGNOREIP="${CURRENT_IGNOREIP} ${MY_CIDR}"

  sudo awk -v new_line="ignoreip = ${NEW_IGNOREIP}" '
    BEGIN { replaced = 0 }
    /^[[:space:]]*ignoreip[[:space:]]*=/ && replaced == 0 {
      print new_line
      replaced = 1
      next
    }
    { print }
  ' "$JAIL_LOCAL" | sudo tee "$TMP_FILE" >/dev/null

  sudo mv "$TMP_FILE" "$JAIL_LOCAL"
  echo "Added $MY_CIDR to ignoreip"
fi

echo
echo "Validating Fail2Ban configuration..."
sudo fail2ban-client -d >/dev/null

echo "Reloading Fail2Ban..."
sudo fail2ban-client reload >/dev/null

echo
echo "Current ignoreip line:"
sudo grep -nE '^[[:space:]]*ignoreip[[:space:]]*=' "$JAIL_LOCAL"

echo
echo "Fail2Ban status:"
sudo fail2ban-client status