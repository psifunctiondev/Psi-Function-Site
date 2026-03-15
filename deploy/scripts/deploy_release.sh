#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/consulting-site"
RELEASES_DIR="$APP_DIR/releases"
SOURCE_DIR="$APP_DIR/source"
SHARED_DIR="$APP_DIR/shared"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
NEW_RELEASE="$RELEASES_DIR/$TIMESTAMP"

mkdir -p "$NEW_RELEASE"
rsync -av --exclude '.git' "$SOURCE_DIR"/ "$NEW_RELEASE"/

cd "$NEW_RELEASE"

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
if [ -f pyproject.toml ]; then
  pip install .
fi

if [ -f package.json ]; then
  npm ci || npm install
  npm run build || true
fi

ln -sfn "$NEW_RELEASE" "$APP_DIR/current"

if [ -f "$SHARED_DIR/env/app.env" ]; then
  set -a
  source "$SHARED_DIR/env/app.env"
  set +a
fi

if [ -f manage.py ]; then
  python manage.py db upgrade || true
fi

sudo systemctl restart consulting-site
sudo systemctl reload nginx
