#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y fail2ban
sudo systemctl enable --now fail2ban
sudo fail2ban-client ping