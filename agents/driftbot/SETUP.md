# DrifterBot worker — local setup

Post Path-C (2026-07-16), the worker lives inside Psi-Function-Site
(`agents/driftbot/`) and ships with the web-app release. The release's
own venv is the only environment you need — no `pip install -e` of a
sibling repo, no `PYTHONPATH` gymnastics.

## One-time setup (Belel or droplet)

```bash
cd /path/to/Psi-Function-Site

# The release venv already has app.extensions.db and the
# CompetitiveAuditSubmission model installed (they're part of the
# web-app install). Verify the worker imports cleanly:
.venv/bin/python -c "from agents.driftbot.worker import CompetitiveAuditAdapter; print('OK')"

# Run the worker test suite
.venv/bin/pytest tests/driftbot/ -v
```

You should see all tests pass and the import check succeed.

## Running the worker locally

```bash
# Set the prod DB URL (Quinn will give you the actual value)
export DATABASE_URL='postgresql://...'

# Pick up all submitted rows (one-shot CLI mode)
.venv/bin/python -m agents.driftbot.worker

# Process a single row by ID (useful for retries / manual ops)
.venv/bin/python -c "from agents.driftbot.worker import run_one_audit_request; print(run_one_audit_request(42))"
```

## Cron wiring

The OpenClaw cron continues to fire the worker via SSH to the droplet,
where `consulting-site-drifterbot@<env>.service` (see
`deploy/systemd/`) runs it against the local Postgres. The cron
inherits `DATABASE_URL` from the gateway's env file
(`/Users/doxa/.openclaw/service-env/ai.openclaw.gateway.env`).

**Prereq:** Quinn needs to add `DATABASE_URL=postgresql://...` to
the gateway env file. Without it, the worker will fail at startup
with `RuntimeError: PSIFUNCTIONSITE_DATABASE_URL (or DATABASE_URL)
must be set.` — visible in the worker's stderr / journalctl.

## Why a single venv now?

The worker used to live in `brandsight/agents/drifterbot/` and imported
`app.models.audit_request` from Psi-Function-Site via `pip install -e`.
That coupling was awkward (two repos, one runtime) and β-3 deleted the
`audit_request` schema entirely in favour of
`CompetitiveAuditSubmission`. Path-C moves the worker into
Psi-Function-Site so the worker, the model, and the venv all live in
one repo and one release.