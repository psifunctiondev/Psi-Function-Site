# Drift & Anchor Client Portal — R1 Runbook

The Drift & Anchor client portal is a real (non-showcase) tenant for
the brand-strategy consultancy founded by Catherine Sheehan. R1
ships the brand-story-driven landing page, the initial dashboard
resources, and the invite provisioning for Catherine — the minimum
viable surface so the portal isn't empty on first sign-in.

This runbook covers R1. R2/R3 will fill in the engagement timeline,
the OpenProject embed, the MkDocs guide index, and the case-study
reels (see the engagement card on the landing for the R2/R3 plan).

---

## What R1 ships

| Layer | Artifact | Source |
|-------|----------|--------|
| Branding | `clients` row, slug `drift-and-anchor`, deep-navy/warm-gold palette, DM Serif Display, stormy-seascape banner | `BRANDING_PROFILES['drift-and-anchor']` in `app/cli.py` |
| Landing | Brand-story hero + Our Services split (Strategy/Creative) + engagement-hub placeholder | `app/templates/portal/drift_and_anchor.html` |
| Route | `GET /p/drift-and-anchor/` — login-required, own-client-or-admin access | `app/blueprints/portal/routes.py` |
| Resources | 6 `client_resources` rows across `engagement` / `asset` / `backlog` / `guide` / `general` | `flask client seed-drift-and-anchor-resources` |
| Invite | `catherine@drift-and-anchor.com`, non-admin, active, unregistered, fresh invite token printed | `flask client seed-drift-and-anchor-invite` |
| Service stub | `app/services/drift_and_anchor.py` with R2-shaped function surface | placeholder raises `DriftAndAnchorNotConfigured` |
| Deploy hook | Branding re-applied on every release via `apply-branding --all` | `deploy/scripts/deploy_release.sh` |

The Drift & Anchor resources and invite seeders are **not** wired
into the deploy script by default — they're one-off bring-up
commands. Re-run them as needed; both are idempotent.

---

## Brand values (locked from the brief)

- **name:** `Drift & Anchor`
- **slug:** `drift-and-anchor` (hyphens, intentional)
- **primary:** `#160E33` (deep navy/purple — the brand's only true color)
- **accent:** `#C9A66B` (warm gold — Quinn may shift to monochromatic later)
- **font_display:** `"DM Serif Display", serif`
- **logo_max_height:** `5rem` (horizontal wordmark with the anchor mark)
- **tagline:** `Brand Strategy and Storytelling Consultancy`
- **radius:** `8px` (soft-but-editorial; softer than the default radius-lg)

Logo, banner, and font URLs are pinned in `BRANDING_PROFILES['drift-and-anchor']`
in `app/cli.py`. They are CDN-hosted on Squarespace and Google Fonts.

---

## Bring-up (local)

From a clean local checkout with the venv active and the database
migrated:

```bash
flask client apply-branding --slug drift-and-anchor
flask client seed-drift-and-anchor-resources
flask client seed-drift-and-anchor-invite
```

`seed-drift-and-anchor-invite` prints the invite URL — copy it and
hand it to Catherine (or wire AgentMail when that lands). The
token is fresh and valid for 72 hours.

```text
Created invite user: catherine@drift-and-anchor.com → Drift & Anchor
Invite token: generated
Token value: <urlsafe-token>
Invite URL: https://psifunction.com/p/login?mode=register&token=<urlsafe-token>
```

All three commands are idempotent. Re-running
`seed-drift-and-anchor-resources` syncs drifted fields without
duplicating rows. Re-running `seed-drift-and-anchor-invite`
**does not** rotate the token unless `--rotate` is passed — this
guards against burning the invite link out from under Catherine
on a deploy-time re-seed.

---

## Bring-up (deploy)

The release script re-applies every known-good branding profile on
every deploy, so `apply-branding --all` is enough to ship the
Drift & Anchor branding on the next release.

The resource and invite seeders are **not** in the deploy script —
they're one-off bring-up commands. The reason: the invite token
must remain stable across deploys (or Catherine loses the link
mid-acceptance), and the resources are seeded once at bring-up,
not continuously like the ACME demo data.

If a future release needs to re-seed Drift & Anchor resources,
run `flask client seed-drift-and-anchor-resources` on the host.
The seeder is idempotent — re-runs sync fields, not duplicate
rows.

---

## Resource categories

Drift & Anchor uses the standard `ClientResource.CATEGORIES` keys:

- `engagement` — "Engagement & Process" — Engagement Overview, Services & Approach
- `asset` — "Assets & Deliverables" — Featured Case Studies
- `backlog` — "Project Backlog" — Project Workspace (OpenProject mirror, coming in R2)
- `guide` — "User Guides" — MkDocs-hosted strategy frameworks
- `general` — "General" — Contact card

All six seeded rows have `is_visible=True` and `external_url='#'`
as a placeholder so the dashboard renders the link without 404ing.
Real destinations land in follow-up commits.

---

## Teardown

Drift & Anchor lives in three tables:

```sql
DELETE FROM client_resources WHERE client_id = (SELECT id FROM clients WHERE slug='drift-and-anchor');
DELETE FROM users           WHERE email = 'catherine@drift-and-anchor.com';
DELETE FROM clients         WHERE slug = 'drift-and-anchor';
```

Order matters (resources → user → client) because of FK constraints.
After teardown, `flask client apply-branding --slug drift-and-anchor`
will recreate the client row from `BRANDING_PROFILES`; running both
seeders again restores R1 in full.

---

## Tests

- `tests/test_drift_and_anchor_portal.py::TestBrandingProfile` — pins the
  brand values from this runbook to `BRANDING_PROFILES`.
- `tests/test_drift_and_anchor_portal.py::TestDriftAndAnchorClientRow` —
  covers `apply-branding --slug drift-and-anchor` (and `--all`).
- `tests/test_drift_and_anchor_portal.py::TestDriftAndAnchorRouteAuth`
  + `TestDriftAndAnchorRouteAccess` — covers the `/p/drift-and-anchor/`
  auth gate and access check.
- `tests/test_drift_and_anchor_portal.py::TestDriftAndAnchorTemplate` —
  covers the brand-story hero, services split, engagement hub,
  theming, and back-to-portal link.
- `tests/test_drift_and_anchor_portal.py::TestSeedDriftAndAnchorResources` —
  covers the resource seeder (idempotency, all rows visible, known
  categories).
- `tests/test_drift_and_anchor_portal.py::TestSeedDriftAndAnchorInvite` —
  covers the invite seeder (idempotency, --rotate, expired-token
  refresh, no admin promotion).
- `tests/test_drift_and_anchor_portal.py::test_service_stub_*` —
  covers the R2 service stub raising
  `DriftAndAnchorNotConfigured`.

---

## Known limitations / future phases

- R1 ships a placeholder engagement hub. R2 replaces it with the
  live timeline, OpenProject workspace embed, and contact handoff.
  R3 layers in the MkDocs guide index and case-study reels.
- The invite email is not sent automatically — the invite URL
  must be hand-delivered (or wired to AgentMail in a follow-up
  commit).
- The resources' `external_url` is `'#'` until the real links
  (OpenProject workspace URL, MkDocs guide index URL, case-study
  asset URLs) are confirmed with Catherine.
- The Drift & Anchor landing route is hard-coded to
  `/p/drift-and-anchor/` and does not accept other slugs. If the
  brand ever gets a second slug, the route and the BRANDING_PROFILES
  key need to stay in sync.
