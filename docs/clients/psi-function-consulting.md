# Psi Function Consulting — Client Portal Runbook (OpenProject Integration)

The OpenProject integration gives authenticated portal users a live
view of their engagement: a per-project summary page with three tabs
(Progress / Status / Backlog) plus drag-drop status changes and
backlog reordering that write through to OP via the service-account
token. This runbook covers bring-up, the daily snapshot cron, and
the backfill command.

This ships in commits 3-5 of the OP integration on
`feature/openproject-portal-pages`. See also:

- `client-portal-kanban.excalidraw` (vault, Obsidian) — UI spec for
  the kanban board.
- `client-portal-status-details.excalidraw` (vault) — per-story
  status details page.
- `status-details-op-field-mapping.md` (vault) — the binding
  contract between OP custom fields and the portal UI.

---

## What this integration ships

| Layer | Artifact | Source |
|-------|----------|--------|
| API client | `app/services/openproject.py` (9 read + 3 write methods, full error mapping) | commit 1 |
| Tenant wire-up | `Client.openproject_master_project_id` (nullable Int) + migration | commit 2 |
| Dashboard | "Projects" card on `/p/<slug>/` listing master + children | commit 3 |
| Project summary | `/p/<slug>/projects/<op-id>?tab=progress\|status\|backlog` | commit 3 |
| Snapshot model | `OpProjectSnapshot` + migration (`a1b2c3d4e5f7`) | commit 4 |
| Daily snapshot cron | `flask openproject snapshot` + `scripts/openproject_snapshot.py` | commit 4 |
| Backfill command | `flask openproject backfill-snapshots <project_id> [--weeks N]` | commit 4 |
| Audit log model | `PortalAuditLog` + migration (`b1c2d3e4f5a6`) | commit 5 |
| Write endpoints | `POST /api/portal/openproject/<op>/work_packages/<wp>/{status,reorder}` | commit 5 |
| Read cache | 60s TTL keyed on `(project_id, filter_fingerprint)`, invalidated on write | commit 5 |
| Drag-drop UI | SortableJS on Status + Backlog tabs (optimistic UI, flash on failure) | commit 5 |

---

## Bring-up (local)

```bash
# 1. Confirm the .env has the two OP env vars (see "Environment" below).
# 2. Apply migrations (the OP tables ship in commits 4 and 5).
. .venv/bin/activate && flask db upgrade

# 3. Wire a client's OP master project. The value is the OP project id
#    (numeric, e.g. 42). Edit in the DB or via the admin route.
UPDATE clients
SET openproject_master_project_id = 42
WHERE slug = 'psi-function-consulting';

# 4. Re-bundle the frontend so SortableJS gets picked up.
make assets

# 5. Smoke test the project summary page.
flask run
# Visit /p/psi-function-consulting/ — Projects card should now show
# the master + children from OP. Click any project → summary page
# with three tabs.
```

---

## Bring-up (deploy)

The release script picks up the new migrations automatically. The
`OPENPROJECT_URL` + `OPENPROJECT_API_KEY` env vars live in the deploy
environment file (alongside `DRIFTERBOT_SERVICE_ACCOUNT_JSON_PATH`,
`METHODOS_BOT_OP_API`, etc.). Set both before deploying this branch.

After deploy, wire any clients that have an OP master project:

```sql
UPDATE clients
SET openproject_master_project_id = <op_id>
WHERE slug = '<client-slug>';
```

Re-running the release script does NOT clobber existing wire-ups —
the `Client.openproject_master_project_id` field is hand-managed.

---

## Environment

| Var | Value source |
|-----|--------------|
| `OPENPROJECT_URL` | Production instance root, e.g. `https://openproject.example.com:5443` (no trailing slash). |
| `OPENPROJECT_API_KEY` | Service-account API key from the OP admin → Users → Service account user. **Do not reuse a human user's key** — the audit-trail journal comments record the service-account identity, not the human. |
| `OPENPROJECT_SNAPSHOT_HOUR_UTC` | Default `07:00`. Crontab fires the Belel wrapper at this hour UTC. |

Local secrets live in `instance/config.py` or a `.env` file loaded by
`python-dotenv`. The token VALUE for `METHODOS_BOT_OP_API` lives in
`~/.openclaw/.env` on Belel — copy the value, not the env var name.

---

## Daily snapshot cron

```bash
# Cron entry (run on Belel under the consult user):
0 7 * * * cd /opt/consulting-site/production/current && \
  /opt/consulting-site/production/current/.venv/bin/python \
  scripts/openproject_snapshot.py >> /var/log/openproject-snapshot.log 2>&1
```

The wrapper invokes `flask openproject snapshot` under the venv.
Exit code 0 = success; non-zero = ops should check the log.

For a one-off run:

```bash
flask openproject snapshot             # today
flask openproject snapshot --date 2026-09-15  # backfill a specific day
flask openproject snapshot --dry-run   # show what would run, no writes
```

For an existing project that has no snapshots yet (just wired up):

```bash
flask openproject backfill-snapshots 42 --weeks 8
```

This walks the project's recent work-package journals and
reconstructs the status distribution at each weekly boundary going
back N weeks, so the Progress chart doesn't show an empty bar for
the first 8 weeks after launch. **Not automatic** — ops runs this
once per new project so cost stays predictable.

---

## Read cache (60s TTL)

Reads against OP go through `app/services/openproject_cache.py`:

- Key: `(project_id, filter_fingerprint)` where the fingerprint is
  a stable hash of the filter dict.
- TTL: 60 seconds (pinned by `TTL_SECONDS`).
- Invalidation: every successful write to a project calls
  `cache_invalidate(project_id)` which drops every cached entry
  for that project. Cache survives failed writes (no spurious
  re-fetches on the next render after a 409).

The cache is a module-level dict protected by a `threading.Lock`.
Redis is intentionally out of scope — per the April spec, "Flask-
side,
use a small module-level dict with a lock; or cachetools.TTLCache.
No Redis yet."

---

## Audit log + journal comments

Every successful portal mutation writes:

1. **PortalAuditLog row** (`portal_audit_log` table) — Psi
   Function's internal "who changed what when" trail.
2. **Journal comment** on the OP work package (via
   `POST /api/v3/work_packages/:id/activities`) — what clients see
   in the OP UI itself.

The journal comment template is exact (no edits):

```
Changed via Psi Function portal by <User.email> (<User.id>)
```

If the journal POST fails after a successful WP update, the write is
still marked successful (the WP is the source of truth) but the
failure is logged so ops can investigate.

---

## Field mapping (binding contract)

Per `status-details-op-field-mapping.md`:

| UI | OP field | ID | Notes |
|---|---|---|---|
| Story number prefix `E##/S##` | `methodos_epic_number` + `methodos_story_number` | customField6, customField7 | Custom fields. |
| Kanban sort order | `methodos_sequence` | customField4 | Ascending; tie-break by `id`. |
| Story points | `storyPoints` | (built-in) | No customField id needed; reference by name. |
| Last completed date | derived from activity feed (latest status-change to "Completed") | — | See field-mapping doc §"Completed Date Derivation". |

**Anything not in this table should not be hardcoded** — request an
update to the field-mapping doc first.

---

## Tests

- `tests/test_openproject_client.py` — 31 tests covering the typed
  API client + error mapping.
- `tests/test_client_openproject_master_id.py` — 10 tests for the
  Client field + migration.
- `tests/test_openproject_config.py` — env-driven factory + config
  errors.
- `tests/test_openproject_cache.py` — fingerprint stability, TTL
  expiry, invalidation clears by project id only.
- `tests/test_openproject_portal.py` — project walk + status
  distribution + percent-complete helpers.
- `tests/test_openproject_last_completed.py` — journal-derived
  completed-date function.
- `tests/test_op_snapshot.py` — model + migration round-trip +
  unique constraint.
- `tests/test_openproject_snapshot.py` — daily worker + CLI (happy
  path, dry-run, missing env, idempotency).
- `tests/test_portal_audit_log.py` — model + migration + indexes +
  action enum pinning.
- `tests/test_portal_openproject.py` — Projects card render +
  summary route (auth, cross-client, tab dispatch).
- `tests/test_openproject_writes.py` — orchestration (status +
  reorder + journal + audit + cache).
- `tests/test_portal_openproject_writes.py` — route integration
  (auth, body validation, happy path, 409, missing config).

Run:

```bash
. .venv/bin/activate && pytest tests/test_openproject_*.py \
                                 tests/test_op_snapshot.py \
                                 tests/test_portal_audit_log.py \
                                 tests/test_portal_openproject*.py \
                                 tests/test_client_openproject_master_id.py
```

---

## Known limitations / future phases

- The drag-drop "ineligible status transitions" affordance (wireframe
  v0.4) — greying out illegal drops from one status to another — is
  not yet enforced. All column-to-column drops succeed at the JS
  layer; OP itself is the source of truth on whether a workflow
  transition is legal. Wireframe-side enforcement is a UI polish
  item.
- Real-time updates on the kanban are out of scope — Quinn's call
  (April prose, deferred). The page does NOT auto-refresh on
  another user's moves; user must reload or click "Refresh" once
  that affordance lands.
- The Backlog tab's "Target week" column shows `—` until the OP
  version end-date lookup lands (commit 7 candidate).
- Cache invalidation is per-process. A multi-worker gunicorn deploy
  with worker A invalidating after a write and worker B still
  holding the stale 60s entry is a known issue. Acceptable for v1 —
  Redis-backed cache is the structural fix when this matters.
- `update_work_package_priority_order` uses a provisional
  `position: <int>` body shape. If OP rejects it in production we
  re-spike the exact reorder payload before locking the route.