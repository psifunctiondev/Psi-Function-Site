#!/usr/bin/env bash
set -euo pipefail

JAIL_LOCAL="/etc/fail2ban/jail.local"

usage() {
  echo "Usage: $0 <IPv4|IPv4/32>"
  exit 1
}

if [[ $# -ne 1 ]]; then
  usage
fi

TARGET="$1"

if [[ "$TARGET" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  TARGET_CIDR="${TARGET}/32"
elif [[ "$TARGET" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/32$ ]]; then
  TARGET_CIDR="$TARGET"
else
  echo "ERROR: argument must be an IPv4 address or IPv4/32 CIDR"
  exit 1
fi

if [[ ! -f "$JAIL_LOCAL" ]]; then
  echo "ERROR: $JAIL_LOCAL does not exist"
  exit 1
fi

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

if ! grep -qw "$TARGET_CIDR" <<< "$CURRENT_IGNOREIP"; then
  echo "IP not present in ignoreip: $TARGET_CIDR"
  exit 0
fi

NEW_IGNOREIP="$(awk -v target="$TARGET_CIDR" '
  {
    for (i = 1; i <= NF; i++) {
      if ($i != target) {
        out = out (out ? " " : "") $i
      }
    }
    print out
  }
' <<< "$CURRENT_IGNOREIP")"

if [[ -z "$NEW_IGNOREIP" ]]; then
  echo "ERROR: refusing to write empty ignoreip line"
  exit 1
fi

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

sudo cp "$JAIL_LOCAL" "${JAIL_LOCAL}.bak.$(date +%Y%m%d_%H%M%S)"

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

echo "Removed $TARGET_CIDR from ignoreip"

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