# Psi-Function-Site

## Local development setup
Note that you now have a local machine setup script in:
	./deploy/scripts/bootstrap_local.sh

### Python
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

### Node + frontend assets
nvm install
nvm use
npm install
npm run build

### Run locally
flask run
