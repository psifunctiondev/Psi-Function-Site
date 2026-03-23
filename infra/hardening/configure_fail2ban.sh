#!/usr/bin/env bash
set -euo pipefail

sudo tee /etc/fail2ban/jail.local > /dev/null <<'EOF'
[DEFAULT]
ignoreip = 127.0.0.1/8 ::1
findtime = 10m
bantime = 1h
maxretry = 5
backend = auto

[nginx-http-auth]
enabled = true
logpath = /var/log/nginx/*error.log

[sshd]
enabled = true
findtime = 30m
maxretry = 8
bantime = 1h

[nginx-404-scan]
enabled = true
filter = nginx-404-scan
logpath = /var/log/nginx/*access.log
port = http,https
maxretry = 5
findtime = 1m
bantime = 1h
EOF

sudo tee /etc/fail2ban/filter.d/nginx-404-scan.conf > /dev/null <<'EOF'
[Definition]
failregex = ^<HOST> -.*"(GET|POST).*" (400|404|444)
ignoreregex =
EOF

echo "Validating parsed Fail2Ban configuration..."
sudo fail2ban-client -d > /dev/null

echo "Finding an nginx access log for regex testing..."
LOG_FILE="$(find /var/log/nginx -maxdepth 1 -type f -name '*access.log' | head -n 1)"

if [[ -z "${LOG_FILE}" ]]; then
  echo "ERROR: no nginx access log found under /var/log/nginx"
  exit 1
fi

echo "Testing filter against: $LOG_FILE"
sudo fail2ban-regex "$LOG_FILE" /etc/fail2ban/filter.d/nginx-404-scan.conf

echo "Restarting Fail2Ban..."
sudo systemctl restart fail2ban

echo "Checking Fail2Ban service state..."
sudo systemctl is-active --quiet fail2ban || {
  echo "ERROR: fail2ban is not active after restart"
  sudo systemctl status fail2ban --no-pager -l
  sudo journalctl -u fail2ban -n 100 --no-pager
  exit 1
}

echo "Checking Fail2Ban control socket..."
sudo fail2ban-client ping

echo "Fail2Ban overall status:"
sudo fail2ban-client status

echo "nginx-404-scan jail status:"
sudo fail2ban-client status nginx-404-scan