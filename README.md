# Psi-Function-Site

Local Development Setup

This project uses Python (Flask) and Node (Vite). Both environments must be initialized on a new machine.

## Documentation

* [`docs/clients/acme-showcase.md`](docs/clients/acme-showcase.md) — runbook for the ACME public-safe showcase tenant (CLI seeders, deploy hook, smoke test).

## Bootstrap procedure

> **Note:** nvm 0.40+ installs to `~/.config/nvm` instead of `~/.nvm`. Use whichever path exists on your machine.

```bash
export NVM_DIR="$HOME/.config/nvm"  # or ~/.nvm for older nvm installs
source "$NVM_DIR/nvm.sh"
nvm use 20
bash deploy/scripts/bootstrap_local.sh
```

> **Tip:** If bootstrap fails with a `JSONDecodeError` from pip, your network may be truncating large HTTPS responses (a known pip 24.x issue). Work around it by pre-installing a newer pip directly before running bootstrap:
>
> ```bash
> rm -rf .venv
> python3 -m venv .venv
> .venv/bin/pip install https://files.pythonhosted.org/packages/3a/eb/fea4d1d51c49832120f7f285d07306db3960f423a2612c6057caf3e8196f/pip-26.1.1-py3-none-any.whl
> bash deploy/scripts/bootstrap_local.sh
> ```

Then:

```bash
source .venv/bin/activate
npm run build
flask run
```
