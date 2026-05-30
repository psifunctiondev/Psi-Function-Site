# Psi-Function-Site

Local Development Setup

This project uses Python (Flask) and Node (Vite). Both environments must be initialized on a new machine.

## Documentation

* [`docs/clients/acme-showcase.md`](docs/clients/acme-showcase.md) — runbook for the ACME public-safe showcase tenant (CLI seeders, deploy hook, smoke test).

## Bootstrap procedure

> **Note:** nvm 0.40+ installs to `~/.config/nvm` instead of `~/.nvm`. Use whichever path exists on your machine.

```bash
# For nvm 0.40+ (default on fresh installs)
export NVM_DIR="$HOME/.config/nvm"
source "$NVM_DIR/nvm.sh"

# For older nvm installs
# export NVM_DIR="$HOME/.nvm"
# source "$NVM_DIR/nvm.sh"

nvm use 20
bash deploy/scripts/bootstrap_local.sh
```

Then:

```bash
source .venv/bin/activate
npm run build
flask run
```
