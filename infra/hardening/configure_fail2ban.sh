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
maxretry = 5
findtime = 1m
bantime = 1h
EOF

sudo tee /etc/fail2ban/filter.d/nginx-404-scan.conf > /dev/null <<'EOF'
[Definition]
failregex = ^<HOST> -.*"(GET|POST).*" (400|404|444)
ignoreregex =
EOF

sudo fail2ban-client -d

LOG_FILE="$(ls /var/log/nginx/*access.log | head -n 1)"
sudo fail2ban-regex "$LOG_FILE" /etc/fail2ban/filter.d/nginx-404-scan.conf

sudo systemctl restart fail2ban
sudo fail2ban-client status