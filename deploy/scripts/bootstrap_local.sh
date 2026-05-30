#!/usr/bin/env bash
set -Eeuo pipefail

echo "==> Bootstrapping local development environment"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "==> Repository root: $REPO_ROOT"

echo "==> Ensuring Flask instance directory exists"
mkdir -p "$REPO_ROOT/instance"

echo "==> Setting up Python virtual environment"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# Upgrade pip first (pip 24.x has a known issue with large JSON index responses
# that causes JSONDecodeError at ~40KB; upgrading resolves it)
echo "==> Upgrading pip"
python -m pip install --quiet --upgrade pip setuptools wheel

echo "==> Installing Python dependencies"
python -m pip install -e .[dev] || python -m pip install -e .

echo "==> Verifying Node and npm"

if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: node is not available in PATH"
  echo "Open a shell where nvm is loaded, or run:"
  echo "  export NVM_DIR=\"\$HOME/.config/nvm\"  # or ~/.nvm for older nvm installs"
  echo "  source \"\$NVM_DIR/nvm.sh\""
  echo "  nvm use 20"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm is not available in PATH"
  exit 1
fi

echo "==> Node version: $(node -v)"
echo "==> npm version: $(npm -v)"

if [ -f "package-lock.json" ]; then
  echo "==> Installing frontend dependencies (npm ci)"
  npm ci
elif [ -f "package.json" ]; then
  echo "==> Installing frontend dependencies (npm install)"
  npm install
else
  echo "==> No package.json found; skipping frontend setup"
fi

if [ -f "package.json" ]; then
  echo "==> Building frontend assets"
  npm run build

  if [ -d "app/static/dist" ]; then
    echo "==> Asset build verified: app/static/dist"
  else
    echo "ERROR: app/static/dist not found after build"
    exit 1
  fi
fi

echo
echo "==> Bootstrap complete"
echo "Next steps:"
echo "  source .venv/bin/activate"
echo "  npm run build"
echo "  flask run"
