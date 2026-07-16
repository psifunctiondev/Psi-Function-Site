# DrifterBot worker — cron wiring

This document describes how to register the worker as an OpenClaw cron job.

## What the worker does

The worker picks up `competitive_audit_submission` rows in `submitted`
state from the Psi-Function-Site Postgres database, runs the DrifterBot
pipeline on each one, and writes the output via the active save strategy
(currently `LocalPickupStrategy` only).

Lifecycle:
```
submitted  ->  processing  ->  complete
                      \--> failed
```

The pickup query uses `SELECT ... FOR UPDATE SKIP LOCKED`, so two
overlapping worker invocations can't grab the same row.

## Pre-requisites

1. **Database URL** — set `PSIFUNCTIONSITE_DATABASE_URL` in the worker's
   environment. SQLAlchemy URL form:
   ```
   postgresql+psycopg://<user>:<pass>@<host>:<port>/<db>
   ```
   Recommendation: a read-replica or a staging-DB snapshot, NOT the
   production primary. The worker is read-mostly (only updates the
   `competitive_audit_submission` row it owns), so a replica is fine
   for the read side and the writes can route back to primary via
   PgBouncer or a separate write URL.

   Quinn: this needs your call on whether to give the worker prod,
   replica, or staging access. Default for first-launch: staging.
   Real answer depends on whether Catherine/Ryan need to see the
   recents table update in real-time (staging = no) vs. eventual
   (replica = yes).

2. **Python path** — the worker imports
   `app.models.competitive_audit.CompetitiveAuditSubmission` and
   `app.extensions.db`. The `agents.driftbot` package lives inside
   the `Psi-Function-Site` repo (post-β-3 move), so the worker runs
   directly from the release's venv with no `PYTHONPATH` gymnastics:
   ```
   /opt/consulting-site/<env>/current/.venv/bin/python -m agents.driftbot.worker
   ```
   See `deploy/systemd/consulting-site-drifterbot@.service` for the
   unit file Quinn uses to run it on the droplet.

## OpenClaw cron registration

Two options. Either one works; pick based on ops preference.

### Option A: Heartbeat extension (recommended for soft-launch)

Append the worker pickup to the existing heartbeat cron (`2eccf312`),
which already runs every 30 minutes on `tier/heartbeat` (gemma4:e4b).
The heartbeat model is fine for the pickup — it's mechanical DB I/O,
no LLM reasoning.

```json
{
  "name": "DrifterBot Audit Worker (heartbeat pickup)",
  "schedule": {
    "kind": "every",
    "everyMs": 300000,
    "anchorMs": 60000
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "Run `cd /opt/consulting-site/production/current && .venv/bin/python -m agents.driftbot.worker` and report any non-empty result. If empty, reply HEARTBEAT_OK.",
    "model": "litellm/tier/heartbeat",
    "timeoutSeconds": 180
  },
  "delivery": {
    "mode": "announce",
    "channel": "discord",
    "to": "channel:1519062495665324052"
  }
}
```

The worker's `main()` prints either `"worker: processed N request(s): [...]"`
or `"worker: no pending requests"`. The cron agentTurn prompt tells the
agent to only ping the channel if there's actual work, so quiet ticks
don't spam Discord.

### Option B: Standalone cron (recommended once Drive auth lands)

When Drive write is wired up and we want a tighter SLA on pickup
latency, register a standalone cron that runs more frequently:

```json
{
  "name": "DrifterBot Audit Worker (standalone)",
  "schedule": {
    "kind": "every",
    "everyMs": 60000,
    "anchorMs": 0
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "Run `cd /opt/consulting-site/production/current && .venv/bin/python -m agents.driftbot.worker`. Report result.",
    "model": "litellm/tier/heartbeat",
    "timeoutSeconds": 60
  }
}
```

Every minute pickup latency means Catherine/Ryan see "request received"
within ~60s of submitting, and the recents table flips to `running`
immediately. Better UX, but higher DB load (still trivial — one
`SELECT ... FOR UPDATE SKIP LOCKED` per minute).

## Model split

- **Pickup path** (the cron agentTurn that calls `main()`): `tier/heartbeat`
  (gemma4:e4b). Mechanical.
- **Audit run** (the `run_audit()` call inside `_run_one`): this is
  the LLM-shaped work. DrifterBot MVP's `runner.py` is stdlib-only,
  no LLM call yet — the executive summary, provocation chapters, and
  per-competitor cards are templated from the prompt files. When the
  runner graduates to calling an LLM (post-MVP), that call should
  route through `tier/smart` (or `tier/general` for cheaper drafts).
  The split is at the `run_audit()` boundary, not the worker
  boundary.

## Operational notes

- **Idempotency**: The pickup query is idempotent — re-running on an
  already-claimed row skips it (`status != submitted`). Safe to
  retrigger.
- **Failure mode**: rows in `failed` state stay in the table. The
  recents UI on the portal shows the `error_message` field. Quinn's
  call on whether to add a "retry" button on the portal — out of scope
  for MVP. For now: failed requests need manual cleanup via DB or
  the `run_one_audit_request(id)` entry point.
- **Timeout**: `run_audit()` is stdlib-only today and finishes in
  seconds. Once it grows an LLM call, the worker needs a timeout.
  Recommended: 10 minutes per row, hard-kill at the cron level
  (`timeoutSeconds: 600` in the cron payload above).
- **Concurrency**: Heartbeat cron runs sequentially. If two heartbeats
  ever overlap, `SKIP LOCKED` prevents double-processing. If you ever
  run two worker processes simultaneously, they coexist cleanly.

## Local testing

The integration smoke test (`tests/driftbot/test_smoke_worker.py`) runs
the worker end-to-end against an in-memory SQLite database with a
synthesized CompetitiveAuditSubmission row. Useful for verifying wiring
changes without needing the real DB up.

```bash
cd /path/to/Psi-Function-Site
.venv/bin/pytest tests/driftbot/test_smoke_worker.py -v
```

The test inserts a synthetic row, runs `run_one_audit_request(id)`,
and asserts:
- Status transitions `submitted → processing → complete`
- `audit_id` is set (8-char UUID per spec)
- `started_at` and `completed_at` are populated
- `LocalPickupStrategy` writes `slides-spec.json` + `audit-draft.md`
  to the run directory

## Future work (parked)

- DriveSaveStrategy when Drive auth lands
- Per-client filtering (currently D&A-only by route hard-coding; if
  another client adopts the flow, add a `client_slug` filter to the
  pickup query and gate the cron by deployment)
- Retry button on the portal for `failed` rows
- Notification email on completion (open question — Doxa only, or
  submitter + Doxa?)