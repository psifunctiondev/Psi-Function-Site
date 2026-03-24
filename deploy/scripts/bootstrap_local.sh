#!/usr/bin/env bash
set -Eeuo pipefail

python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

if command -v nvm >/dev/null 2>&1; then
  nvm install
  nvm use
fi

npm install
npm run build

echo "Local environment bootstrapped."
