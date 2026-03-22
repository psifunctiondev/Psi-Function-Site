#!/usr/bin/env bash
set -euo pipefail

# bash infra/bootstrap/install_base_packages.sh
# bash infra/bootstrap/install_nginx.sh
bash infra/bootstrap/install_fail2ban.sh
# bash infra/bootstrap/configure_app_dirs.sh
# bash infra/bootstrap/install_systemd_units.sh