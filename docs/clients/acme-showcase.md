# ACME Showcase Client — Phase 0 Runbook

The ACME client is a fictional, public-safe showcase tenant used to
demonstrate the Psi Function client portal end-to-end without exposing
any real engagement. It exists in the same `clients` table as live
clients, but is fully bootstrapped from code (branding profile + CLI
seeders), so it can be torn down and rebuilt at any time.

This runbook covers Phase 0 — the minimum viable showcase.

---

## What Phase 0 ships

| Layer | Artifact | Source |
|-------|----------|--------|
| Branding | `clients` row, slug `acme`, ochre/sand palette, Bungee Inline display font, tagline | `BRANDING_PROFILES['acme']` in `app/cli.py` |
| Demo user | `demo@acme.com`, non-admin, active, registered, password printed once | `flask client seed-acme-demo` |
| Resources | 6 `client_resources` rows across `engagement` / `deliverables` / `tools` categories | `flask client seed-acme-resources` |
| Deploy hook | All three above re-applied on every release when `SEED_ACME_DEMO=1` | `deploy/scripts/deploy_release.sh` |

---

## Bring-up (local)

From a clean local checkout with the venv active and the database
migrated:

```bash
flask client apply-branding --slug acme
flask client seed-acme-demo
flask client seed-acme-resources
```

Then visit the portal as `demo@acme.com` (the seeder prints the
generated password the first time it runs; subsequent runs skip
password generation unless you pass `--reset-password`).

All three commands are idempotent. Re-running `seed-acme-demo` or
`seed-acme-resources` syncs drifted fields (description, category,
url, sort_order, profile attrs) without duplicating rows.

---

## Bring-up (deploy)

The release script re-applies every known-good branding profile on
every deploy. To additionally seed the ACME demo data on deploy, set:

```bash
export SEED_ACME_DEMO=1
```

in the deploy environment file. The hook is best-effort: a failure
in either seed command is logged but does not block the release.

To stop seeding on deploy, unset `SEED_ACME_DEMO` (or set to `0`)
and the next deploy will skip the seed step. Existing rows are
left in place — there is no automatic teardown.

---

## Resource categories

Phase 0 introduces three new `ClientResource.CATEGORIES` keys for
the showcase narrative:

- `engagement` — "Engagement & Process" — the SOW, the
  Discover→Blueprint→Construct→Realize doc.
- `deliverables` — "Deliverables" — the higher-order umbrella for
  what we shipped (an asset-level bucket already exists; this is
  for the showcase's narrative grouping).
- `tools` — "Tools & Dashboards" — links into OpenProject,
  dashboards, etc.

Existing legacy keys (`proposal`, `backlog`, `guide`, `asset`,
`invoice`, `custom`, `general`) are preserved verbatim for
backward compatibility. `category` is a free-form 64-char string
with no DB CHECK constraint, so adding keys requires no migration.

---

## Teardown

The showcase data lives in two tables:

```sql
DELETE FROM client_resources WHERE client_id = (SELECT id FROM clients WHERE slug='acme');
DELETE FROM users           WHERE email = 'demo@acme.com';
DELETE FROM clients         WHERE slug = 'acme';
```

Order matters (resources → user → client) because of FK constraints.
After teardown, `flask client apply-branding --slug acme` will
recreate the client row from `BRANDING_PROFILES`; running both
seeders again restores Phase 0 in full.

---

## Tests

- `tests/test_branding_profiles.py` — covers `apply-branding --slug acme`.
- `tests/test_seed_acme_demo.py` — covers the demo-user seeder.
- `tests/test_seed_acme_resources.py` — covers the resource seeder
  and the new category keys.
- `tests/test_models.py::TestClientResource::test_categories_dict_keys`
  — asserts both legacy and showcase key sets are present.

---

## Known limitations / future phases

- Phase 0 does not back the ACME client with an OpenProject project
  (per design — the `openproject_project_id` field is intentionally
  null for showcase tenants).
- The showcase resources are static. A future phase may template
  them per-client for new-engagement bring-up.
- The demo password is printed once on first seed and never logged.
  If lost, re-run `seed-acme-demo --reset-password`.
