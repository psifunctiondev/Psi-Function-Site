# Deploy

Server-side deploy scripts and systemd unit files. The droplet layout
follows the standard Capistrano-style `current/`, `previous/`, `releases/`,
`shared/`, `source/` split, with three environments (`testing`, `staging`,
`production`) routed by nginx.

## Rollout

Release promotion is driven by `.github/workflows/promote_production.yml`
which rsyncs the chosen commit to `/opt/consulting-site/production/source/`
on the droplet and runs `deploy/scripts/deploy_release.sh`. Once a release
is in place, the `current` symlink flips and the running services pick up
the new code on their next tick.

## Systemd units

Two templated units ship from this directory:

- `systemd/consulting-site@.service` — gunicorn for the web app
  (`%i = testing|staging|production`). Long-lived, 3 workers.
- `systemd/consulting-site-drifterbot@.service` — DrifterBot worker
  (`%i = testing|staging|production`). Fire-and-exit, fired by cron on
  Belel via SSH.

Installers: `scripts/install_systemd_service.sh` (gunicorn) and
`scripts/install_driftbot.sh` (worker). Both are `--apply`-gated — by
default they print a `[DRY-RUN]` plan and exit 0; pass `--apply` to
actually install.

### When to re-run the installer

The installers copy unit files from the release's `source/deploy/systemd/`
into `/etc/systemd/system/` and run `systemctl daemon-reload`. The release
pipeline only updates `source/` — it never touches `/etc/systemd/system/`.

**Re-run `install_driftbot.sh` only when the unit file itself changes
(e.g. `TimeoutStopSec`, `MemoryMax`, `Restart=`).** Worker code changes
ship with the next release and are picked up automatically on the next
cron tick. Same rule applies to `install_systemd_service.sh` for gunicorn
unit changes vs. app code changes.