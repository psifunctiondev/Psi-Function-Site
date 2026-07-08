# Deployment

This document covers the day-to-day deployment workflows for the Psi-Function-Site
(Flask + Jinja, hosted at psifunction.com) across its three environments —
`testing`, `staging`, and `production` — each backed by its own PostgreSQL
database on the deploy host (`/opt/consulting-site/<env>/`).

The deploy host runs the `deploy` user with passwordless `sudo` for the
`postgres` role and `systemctl` operations on `consulting-site@<env>`.
All workflows are `workflow_dispatch`-only; nothing auto-runs on a
schedule.

## Promotion flow at a glance

```
testing  (auto-deploys from main)
   │
   ▼  gh workflow run promote_staging.yml -f sha=<testing-sha>
staging
   │
   ▼  gh workflow run promote_production.yml -f sha=<staging-sha>
production
```

`deploy.yml` (push to `main` and `workflow_dispatch`) drives the
`testing` and direct-to-`staging` / `production` paths.  The
`promote_*` workflows are the safer "verified-this-is-actually-live"
promotions between environments.

## Staging Promotion

The [Promote to Staging workflow](../.github/workflows/promote_staging.yml)
copies the current testing revision into the staging environment after
Quinn has poked at it in testing and signed off.

**What it does.**  Checks out the exact commit SHA currently live in
`testing`, rsyncs the repo to `/opt/consulting-site/staging/source/`
on the deploy host, runs `deploy/scripts/deploy_release.sh staging <sha>`
(which builds a new release, links shared uploads/logs/tmp, runs
`flask db upgrade`, and atomically switches the `current` symlink), then
verifies the live revision matches the requested SHA and runs the public
smoke test against `https://staging.psifunction.com`.

**How to invoke it.**

```bash
# Get the SHA currently live in testing
ssh deploy@<host> 'cat /opt/consulting-site/testing/current/REVISION'

# Promote that SHA to staging
gh workflow run promote_staging.yml -f sha=<testing-sha>
```

The workflow uses the `staging` GitHub Environment for any required
approvals.

**After promotion.**  Smoke-tested staging should be hittable at
`https://staging.psifunction.com`.  Staging data is the residual state
from its last deploy, plus whatever the seed workflows wrote into it.
Quinn pokes at staging with that data until he's ready to promote.

**Code-only rollback.**  The [Promote to Production workflow](../.github/workflows/promote_production.yml)
is the normal "go to prod" path.  If a *code* release misbehaves and you
need to roll back *without* a fresh data copy, use
`deploy/scripts/rollback_release.sh staging` on the deploy host.  This
swaps the `current` symlink back to the previous release dir; it does
NOT touch the database.  For database rollback without re-seeding, see
[Restore From Backup](#restore-from-backup) below.

## Seed Staging From Production

The [Seed Staging From Production workflow](../.github/workflows/seed_staging_from_production.yml)
copies the **current production database** into staging and **scrubs all
PII** so Quinn can log in as a real user against realistic data without
leaking real customers.  It runs `deploy/scripts/copy_data.sh production staging copy`
on the deploy host, then verifies the resulting password file.

This is intentionally a separate workflow from `promote_staging.yml` —
Quinn's plan is to seed staging right before a code promotion so the
deploy runs against real-world data, and to re-seed whenever staging
drifts from production.

### What it does

1. Refuses to run if `source == target` (no-op guard).
2. Checks Alembic head compatibility: if staging is **behind** production
   it runs `flask db upgrade` on staging first (auto-fix the obvious);
   if the heads **diverge** (genuine branch divergence, not just
   behind/ahead) it ABORTS before any destructive step — this is a
   human-decision problem, not an automation one.
3. Dumps the production database with `pg_dump --format=custom` to
   `/opt/consulting-site/backups/`.
4. Generates a 20-character URL-safe random password for this run.
5. Drops and **recreates** the staging database, restores the dump into
   it, then applies `deploy/scripts/scrub_data.sql`.
6. Writes the password to `/opt/consulting-site/staging/.staging_password`
   with mode `600`, owned by `deploy:deploy`.
7. Echoes the password to stdout so the workflow can capture it for the
   run summary (with `::add-mask::` applied first to keep the literal
   out of public logs).

### How to invoke it

**GitHub UI.**  Actions → "Seed Staging From Production" → "Run workflow" →
set `target_environment=staging` → type the exact confirm string
`yes-copy-production-data-to-staging` into the confirm field → click the
green "Run workflow" button.

**GitHub CLI.**

```bash
gh workflow run seed_staging_from_production.yml \
  -f target_environment=staging \
  -f confirm=yes-copy-production-data-to-staging
```

The confirm string must match the literal `yes-copy-production-data-to-staging`
byte-for-byte.  The first workflow step validates this and fails before
any SSH side effect if it doesn't.

### Where the staging password lands

The generated password is **the same for every scrubbed user** in this
one restore.  It lands in two places:

1. **GitHub Actions run summary.**  The workflow writes it into a
   fenced code block at the top of `$GITHUB_STEP_SUMMARY`, after
   `::add-mask::` so the literal is replaced with `***` if it ever
   appears in another log line.  Only people with read access to the
   `staging` GitHub Environment can see the summary.
2. **On the deploy host.**  `/opt/consulting-site/staging/.staging_password`,
   mode `600`, owner `deploy:deploy`.  Read with:
   ```bash
   ssh deploy@<host> sudo cat /opt/consulting-site/staging/.staging_password
   ```

### Preserved vs scrubbed

The PII scrub follows the signed-off spec from 2026-06-30:

| Table            | Column(s)                                                         | Action                                          |
|------------------|-------------------------------------------------------------------|-------------------------------------------------|
| `user`           | `email`                                                           | `<client-slug>+user<n>@staging.psifunction.invalid` (n = user.id) |
| `user`           | `display_name`                                                    | `Staging User <n>`                              |
| `user`           | `password_hash`                                                   | Replaced with `pbkdf2:sha256:600000$…$…` hash of the per-run random password (same hash for all users) |
| `user`           | `invite_token`, `reset_token`, `invite_expires`, `reset_expires`  | `NULL`                                          |
| `client`         | `name`, `slug`                                                    | **PRESERVED** (tenant slugs like `ctai` needed for portal routing) |
| `client`         | `logo_url`, `banner_url`, `font_url`, `tagline`                   | **PRESERVED** (not PII)                         |
| `client_resource`| `title`, `description`, `external_url`, `file_path`               | **PRESERVED**                                   |
| `work_item`      | `title`, `description`                                            | **PRESERVED** (authored copy, useful in staging) |
| `taxonomy_tag`   | —                                                                 | **PRESERVED** (shared vocabulary)               |

**Out of scope this round** (explicitly NOT scrubbed):
`work_item.description` / `client_resource.description` deeper
anonymization, session rows, CSRF tokens, flask_login remember-me
cookies, request IPs, user agents, and file upload content.  If any of
those become a concern, the scrub is the right place to extend.

### Safety notes

- **Destructive.**  This WIPES staging state.  It is not a soft
  operation — it drops the staging database, recreates it from scratch,
  and restores the production dump.  The previous staging state cannot
  be recovered except from a backup.  The concurrency group
  `seed-staging` with `cancel-in-progress: false` ensures a second
  invocation will **wait** for the first to finish; it cannot be cut off
  mid-`pg_dump`.
- **Code-only rollback is separate.**  If you only want to roll back a
  *code* change without re-seeding data, use
  `deploy/scripts/rollback_release.sh staging` on the deploy host.  See
  the [Staging Promotion](#staging-promotion) section above.
- **Alembic safety guarantee.**  If staging's Alembic head is behind
  production's, the workflow auto-upgrades staging before the dump.
  If the heads **diverge** (e.g. an old branch with unmerged
  migrations), the script aborts before any destructive step with a
  clear "divergent heads" error — this is **Quinn-decision** territory
  and will not auto-merge or guess.
- **Confirm string.**  The literal `yes-copy-production-data-to-staging`
  must be typed exactly.  The first step is a pure-string check before
  any SSH side effect; typo or wrong-case fails the run immediately.

### Restore From Backup

`scripts/backup_postgres.sh` (run nightly on the deploy host via cron)
keeps the last 7 days of `pg_dump --format=custom` backups per
database in `/opt/consulting-site/backups/`, named
`psifunction_<env>_<YYYY-MM-DD>.dump`.  To roll staging back to a
specific point **without** re-seeding from production:

```bash
# On the deploy host
sudo -u postgres dropdb --if-exists psifunction_staging
sudo -u postgres createdb psifunction_staging
sudo -u postgres pg_restore --dbname=psifunction_staging \
  --no-owner --no-privileges \
  /opt/consulting-site/backups/psifunction_staging_<DATE>.dump
```

The same scrub step applies — re-run `deploy/scripts/scrub_data.sql`
against the restored DB before pointing any traffic at it.  The seed
workflow does both drop+restore+scrub atomically; a manual restore
should always be followed by a manual scrub.
