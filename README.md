# Psi-Function-Site

Local Development Setup

This project uses Python (Flask) and Node (Vite). Both environments must be initialized on a new machine.

## Documentation

* [`docs/clients/acme-showcase.md`](docs/clients/acme-showcase.md) — runbook for the ACME public-safe showcase tenant (CLI seeders, deploy hook, smoke test).
* [`docs/clients/drift-and-anchor.md`](docs/clients/drift-and-anchor.md) — runbook for the Drift & Anchor client portal (brand story landing, resources seeder, Catherine invite flow).

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

## Administration CLI

The site ships with a set of `flask …` admin commands for managing users, clients, and resources without going through the web UI. All commands are registered by `app/cli.py` and run inside the Flask app context (so `FLASK_APP=wsgi:app` is set or implied).

> Every command is **idempotent** unless otherwise noted — safe to re-run on every deploy.

### Pointing the CLI at a specific environment

Each environment has its own code release, its own Python venv, and its own database. A `flask` command points at an environment when all three line up: the `python` binary you invoke comes from that env's venv, `FLASK_APP` resolves to that env's checkout, and the env vars (notably `DATABASE_URL` and `FLASK_ENV_PROFILE`) point at that env's database.

#### Local development (single env on your laptop)

There is only one environment on a dev box — the one your local `.venv` and `.env` (or shell env) describe. From the repo root:

```bash
source .venv/bin/activate
export FLASK_APP=wsgi:app
flask user list            # or any other command in this section
```

Default DB is the SQLite file at `instance/dev.db`; set `DATABASE_URL` in your shell or `.env` to point at a local Postgres instead.

#### Remote environments (testing / staging / production)

The three deployed environments live on the deploy host under `/opt/consulting-site/<env>/`. Each has its own `current` symlink to the active release, its own `.venv/` inside that release, and its own `shared/env/app.env` with the env-specific `DATABASE_URL`, `SECRET_KEY`, and `FLASK_ENV_PROFILE`.

A `flask` command points at a deployed environment when **all three** line up:

1. `python` comes from the release's `.venv/` (not the local dev venv — pinned deps differ).
2. `FLASK_APP` (or `--app`) resolves to that release's `wsgi.py`.
3. The shell has the env's `DATABASE_URL`, `FLASK_ENV_PROFILE`, and `SECRET_KEY` exported — sourced from `<env>/shared/env/app.env`. **Without these, `BaseConfig` falls back to the local SQLite file at `instance/dev.db` and the command will fail with `sqlite3.OperationalError: unable to open database file` (or worse, silently hit the wrong DB).**

`deploy_release.sh` sources `app.env` for its own process during the deploy, but **that does NOT carry into a fresh interactive shell** — the env vars are lost the moment that script exits. You have to source it yourself on every manual invocation. The complete, working pattern:

```bash
# As the deploy user on the deploy host:
ENV=testing                                  # or staging | production
ENV_FILE="/opt/consulting-site/${ENV}/shared/env/app.env"
APP_DIR="/opt/consulting-site/${ENV}/current"

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a           # export DATABASE_URL + FLASK_ENV_PROFILE + SECRET_KEY

cd "$APP_DIR"
FLASK_APP=wsgi:app .venv/bin/flask client apply-branding --all
```

That works from a shell already running as `deploy`. If you're SSHed in as a different user and need to switch, wrap it in `sudo -u deploy -H bash -lc '…'` (the `-l` gives you a login shell so `PATH` and `HOME` are what the deploy user expects). End-to-end example for inviting a portal user from a fresh SSH session:

```bash
sudo -u deploy -H bash -lc '
  ENV=testing
  ENV_FILE="/opt/consulting-site/${ENV}/shared/env/app.env"
  APP_DIR="/opt/consulting-site/${ENV}/current"

  set -a; source "$ENV_FILE"; set +a
  cd "$APP_DIR" &&
  echo "FLASK_ENV_PROFILE=$FLASK_ENV_PROFILE" &&
  echo "DATABASE_URL=$DATABASE_URL" &&
  FLASK_APP=wsgi:app .venv/bin/flask user invite \
    --email drifterbot@psifunction.com \
    --client drift-and-anchor
'
```

The two `echo`s confirm `app.env` was sourced before any DB-touching command runs — if either comes back empty, stop and re-check `app.env` rather than retrying blind. Swap `ENV=testing` for `staging` or `production` as needed; the rest is parameterised.

> **Common failure mode.** If you skip `source "$ENV_FILE"` and just `cd` into `current/` + run `flask`, you'll get `sqlite3.OperationalError: unable to open database file` because SQLAlchemy falls back to the default SQLite path with no parent directory in the release dir. That's the symptom of "I pointed at the right release but the wrong database."

> **Why not just `source` the local `.venv` and run `flask`?** Two reasons. First, the local venv has whatever Python and pip versions you happened to install, which can drift from the release's pinned deps — running through the release venv guarantees parity with what the live app is using. Second, the local shell has whatever env vars are in scope, which almost certainly do not match the deployed environment's `DATABASE_URL` / `SECRET_KEY` / `FLASK_ENV_PROFILE`. Pointing at the release venv + that env's `app.env` removes both ambiguities at once.

> **Always double-check before running mutating commands against `production`.** Read the release's `REVISION` file and echo the resolved config first to confirm you're pointed where you think you are:
>
> ```bash
> ENV=production
> cat "/opt/consulting-site/${ENV}/current/REVISION"
> sudo -u deploy -H bash -lc '
>   ENV_FILE="/opt/consulting-site/${ENV}/shared/env/app.env"
>   APP_DIR="/opt/consulting-site/${ENV}/current"
>   set -a; source "$ENV_FILE"; set +a
>   cd "$APP_DIR" &&
>   echo "FLASK_ENV_PROFILE=$FLASK_ENV_PROFILE" &&
>   echo "DATABASE_URL=$DATABASE_URL" &&
>   FLASK_APP=wsgi:app .venv/bin/flask client list
> '
> ```

### `flask user …` — manage portal users

#### `flask user invite`

Send a registration invite to a new portal user. Creates the client org if it does not exist yet, mints a fresh invite token, and prints the invite URL.

| Option | Required | Default | Description |
|---|---|---|---|
| `--email` | yes | — | Email address to invite (lowercased automatically). |
| `--client` | yes | — | Client slug (e.g. `ctai`). Created if missing. |
| `--client-name` | no | `<slug>` title-cased | Display name when creating the client. |
| `--hours` | no | `72` | Invite expiry in hours. |

Example:

```bash
flask user invite --email catherine@drift-and-anchor.com \
                  --client drift-and-anchor \
                  --client-name "Drift & Anchor" \
                  --hours 72
```

#### `flask user list`

List all portal users with their email, display name, client, and status (`active` / `invited` / `inactive`). No options.

```bash
flask user list
```

#### `flask user make-admin`

Grant admin privileges to an existing portal user.

| Option | Required | Description |
|---|---|---|
| `--email` | yes | Email of the user to promote. |

```bash
flask user make-admin --email quinn@psifunction.com
```

#### `flask user deactivate`

Deactivate a portal user — revokes access and clears any outstanding invite or reset tokens. The user row is preserved (use `make-admin` and direct DB writes to undo).

| Option | Required | Description |
|---|---|---|
| `--email` | yes | Email of the user to deactivate. |

```bash
flask user deactivate --email former@client.com
```

#### `flask user reset-password`

Generate a password-reset link for an existing user. The link is printed to stdout and not sent anywhere — copy it into your out-of-band channel of choice.

| Option | Required | Default | Description |
|---|---|---|---|
| `--email` | yes | — | Email of the user. |
| `--hours` | no | `24` | Reset token expiry in hours. |

```bash
flask user reset-password --email catherine@drift-and-anchor.com --hours 24
```

### `flask client …` — manage client organizations

#### `flask client create`

Create a new client organization row. Fails if the slug already exists.

| Option | Required | Default | Description |
|---|---|---|---|
| `--slug` | yes | — | URL slug (e.g. `ctai`, `acme`, `drift-and-anchor`). |
| `--name` | yes | — | Display name. |
| `--primary` | no | `None` | Primary hex color (e.g. `#2B4C6F`). |
| `--accent` | no | `None` | Accent hex color (e.g. `#C4956A`). |
| `--logo` | no | `None` | Logo URL. |
| `--banner` | no | `None` | Banner image URL. |
| `--tagline` | no | `None` | Short welcome tagline. |
| `--font-url` | no | `None` | Google Fonts CSS URL. |
| `--font-display` | no | `None` | Display `font-family` value. |

```bash
flask client create --slug acme --name "ACME Corporation" \
                    --primary "#D7282F" --accent "#1A1A1A" \
                    --tagline "Purveyors of fine products since 1949."
```

#### `flask client list`

List all client organizations with name, slug, active flag, and primary/accent colors. No options.

```bash
flask client list
```

#### `flask client update`

Update one or more fields on an existing client. Pass only the options you want to change; omitted options are left as-is. Refuses to operate if the slug is unknown.

| Option | Required | Default | Description |
|---|---|---|---|
| `--slug` | yes | — | Client slug to update. |
| `--name` | no | `None` | New display name. |
| `--primary` | no | `None` | Primary hex color. |
| `--accent` | no | `None` | Accent hex color. |
| `--logo` | no | `None` | Logo URL. |
| `--banner` | no | `None` | Banner image URL. |
| `--tagline` | no | `None` | Short welcome tagline. |
| `--font-url` | no | `None` | Google Fonts CSS URL. |
| `--font-display` | no | `None` | Display `font-family` value. |

```bash
flask client update --slug acme --tagline "New tagline text"
```

#### `flask client apply-branding`

Apply the known-good branding profile from `BRANDING_PROFILES` (the dict at the top of `app/cli.py`) to one or all clients. Creates the `Client` row if missing, then upserts branding fields in place. **Safe to run on every deploy** — idempotent, only writes when a value changed.

| Option | Required | Description |
|---|---|---|
| `--slug` | one of these | Client slug to apply. Omit and pass `--all` for the full set. |
| `--all` | one of these | Apply every profile in `BRANDING_PROFILES`. |

Exit codes: `0` on success, `1` if the slug has no profile, `2` if neither `--slug` nor `--all` was provided.

```bash
flask client apply-branding --slug ctai
flask client apply-branding --all   # what deploy_release.sh runs
```

#### `flask client seed-acme-demo`

Seed the ACME showcase demo user (`demo@acme.com`). Idempotent — re-running on a registered user does **not** rotate the password unless asked. Ensures the ACME client row exists via `BRANDING_PROFILES['acme']` first.

| Option | Required | Default | Description |
|---|---|---|---|
| `--password` | no | env / generated | Password to set for the demo user. Wins over env / generated. |
| `--display-name` | no | `ACME Demo` | Display name for the user. |
| `--reset-password` | no | off | Force password regeneration even when the user is already registered. Ignored when `--password` is also provided. |

Password resolution order:

1. `--password` CLI flag (always used if provided).
2. `ACME_DEMO_PASSWORD` env var (only when the user is unregistered or `--reset-password` was passed).
3. Randomly generated 16-char password (printed once) — same gating as #2.

```bash
flask client seed-acme-demo
ACME_DEMO_PASSWORD='correct-horse-battery-staple' flask client seed-acme-demo
flask client seed-acme-demo --reset-password   # rotate creds
```

#### `flask client seed-acme-resources`

Seed the ACME showcase `ClientResource` rows (engagement / deliverables / tools). Idempotent — re-running upserts by `(client_id, title)`. No options.

```bash
flask client seed-acme-resources
```

#### `flask client seed-drift-and-anchor-resources`

Seed the Drift & Anchor `ClientResource` rows (engagement / asset / application / general). Idempotent — re-running upserts by `(client_id, title)`. Also cleans up stale placeholder rows (`Project Workspace`, `User Guides`) if they exist. No options.

```bash
flask client seed-drift-and-anchor-resources
```

#### `flask client seed-drift-and-anchor-invite`

Provision Catherine's invite on the Drift & Anchor portal. Creates `catherine@drift-and-anchor.com` as a non-admin, active, *unregistered* user and mints a fresh invite token; the full invite URL is printed to stdout. Idempotent — re-running keeps the existing token unless `--rotate` is passed (so deploy-time re-seeds do not invalidate a still-valid invite link mid-acceptance).

| Option | Required | Default | Description |
|---|---|---|---|
| `--rotate` | no | off | Force regeneration of the invite token even if one already exists. |

```bash
flask client seed-drift-and-anchor-invite
flask client seed-drift-and-anchor-invite --rotate
```

### `flask resource …` — manage client resources

Resources are dashboard cards — guides, tools, external links — keyed to a client and a category.

#### `flask resource add`

Add a resource to a client portal.

| Option | Required | Default | Description |
|---|---|---|---|
| `--client` | yes | — | Client slug (e.g. `acme`). |
| `--title` | yes | — | Resource display title. |
| `--category` | yes | — | One of `document`, `backlog`, `application`, `guide` (case-insensitive). |
| `--url` | no | `None` | External URL. |
| `--file` | no | `None` | Static file path (relative to `app/static/`). |
| `--order` | no | `0` | Sort order within category. |

```bash
flask resource add --client acme --title "Engagement Charter" \
                   --category document --url https://psifunction.com/... \
                   --order 10
```

#### `flask resource remove`

Remove a resource by `(client, title)`. Fails if the client slug is unknown; prints a warning if no matching row exists.

| Option | Required | Description |
|---|---|---|
| `--client` | yes | Client slug. |
| `--title` | yes | Resource title to remove. |

```bash
flask resource remove --client acme --title "Engagement Charter"
```

#### `flask resource list`

List client resources. Filter to one client with `--client`; output is grouped by client, then category, then sort order.

| Option | Required | Default | Description |
|---|---|---|---|
| `--client` | no | `None` | Filter to a single client slug. |

```bash
flask resource list
flask resource list --client drift-and-anchor
```

### Standalone seeders

These are top-level commands (not under a group). Both are idempotent.

#### `flask seed-taxonomy`

Upsert the canonical taxonomy tags (vertical / function / technology) from `TAXONOMY_AXES` in `app/cli.py`. Match key is the slug derived from the label. Must be run before `flask seed-work-demo` if any tags are missing — the work seeder will skip entries whose tags have not been seeded yet. No options.

```bash
flask seed-taxonomy
```

#### `flask seed-work-demo`

Upsert the public-safe `WorkItem` rows for the home-page showcase (CTAI / TruRender, Global Arts Live, Havarti Risk). Match key is the title. Resolves tag labels against `TaxonomyTag` rows — run `flask seed-taxonomy` first if needed. No options.

```bash
flask seed-work-demo
```

### Deploy-time composition

`deploy/scripts/deploy_release.sh` runs the following after `flask db upgrade`:

```bash
flask client apply-branding --all
flask client seed-acme-demo
flask client seed-acme-resources
```

`deploy/scripts/db_migrate.sh` additionally exposes opt-in `SEED_*` env flags for the rest:

```bash
SEED_ACME_DEMO=1   flask client seed-acme-demo + flask client seed-acme-resources
SEED_TAXONOMY=1    flask seed-taxonomy
SEED_WORK_DEMO=1   flask seed-work-demo
```
