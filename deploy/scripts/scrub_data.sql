-- scrub_data.sql — Scrub PII from a freshly-restored staging database.
--
-- Applied by deploy/scripts/copy_data.sh immediately after
-- `pg_restore` of the source dump into the target database.  Replaces
-- emails, display names, and password hashes in `user`; clears invite
-- and password-reset tokens; leaves `client`, `client_resource`,
-- `work_item`, and `taxonomy_tag` rows in place per the signed-off
-- PII-scrub spec (2026-06-30).
--
-- Contract with copy_data.sh:
--   - The script must pass a Werkzeug pbkdf2 hash via psql variable:
--       psql ... -v password_hash='pbkdf2:sha256:600000$<salt>$<digest>' -f scrub_data.sql
--     The hash is generated in the shell with:
--       python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('THE_PASSWORD', method='pbkdf2:sha256:600000'))"
--     matching the format User.set_password() produces (app/models/user.py).
--
-- Verification of the contract:
--   - All `user.password_hash` values after this script runs must begin
--     with the literal prefix `pbkdf2:sha256:600000$`.
--   - `app/models/user.py::User.check_password` accepts that exact format
--     via `werkzeug.security.check_password_hash` (verified 2026-07-08).
--
-- Why Option B (shell-computed hash) and not Option A (pgcrypto):
--   - pgcrypto is NOT enabled in this project's databases.  No
--     `CREATE EXTENSION pgcrypto` appears in migrations/versions/*.py,
--     and the staging/production roles are not granted superuser.
--   - Enabling pgcrypto just for staging would be a permanent schema
--     change to staging for a feature that should be ephemeral.  Better
--     to compute the hash in the shell where werkzeug is already a
--     Flask runtime dependency.
--
-- Out of scope this round (intentionally not scrubbed):
--   - work_item.description / client_resource.description (authored copy)
--   - session rows, CSRF tokens, flask_login remember-me cookies
--   - request IPs, user agents
--   - file upload content

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------
-- Preflight: required tables exist, password_hash was passed, looks like a
-- Werkzeug pbkdf2 hash.  Fail loudly before touching any rows.
-- ---------------------------------------------------------------------------

\echo [scrub_data] preflight: checking required tables...

do $$
begin
  if not exists (select 1 from information_schema.tables where table_name = 'user') then
    raise exception 'required table "user" is missing from the target database';
  end if;
  if not exists (select 1 from information_schema.tables where table_name = 'client') then
    raise exception 'required table "client" is missing from the target database';
  end if;
end
$$;

\echo [scrub_data] preflight: checking password_hash variable...

-- psql exposes substitution values via current_setting('...', true) when
-- the variable is set with -v.  We treat "missing or empty" as fatal.
do $$
declare
  ph text := current_setting('password_hash', true);
begin
  if ph is null or ph = '' then
    raise exception 'password_hash psql variable was not provided (pass it with -v password_hash=...)';
  end if;
  if ph !~ '^pbkdf2:sha256:' then
    raise exception 'password_hash does not look like a Werkzeug pbkdf2 hash (got prefix: %)', substring(ph from 1 for 32);
  end if;
end
$$;

\echo [scrub_data] preflight OK; scrubbing user table...

-- ---------------------------------------------------------------------------
-- 1) Replace PII columns on `user` rows.
--      email:          <client-slug>+user<n>@staging.psifunction.invalid  (n = user.id)
--      display_name:   'Staging User <n>'
--      password_hash:  per-run hash (same for all users in this restore)
--      invite_token, reset_token, invite_expires, reset_expires: NULL
--
-- A single UPDATE so the affected row count and timing are observable
-- in the deploy log.
-- ---------------------------------------------------------------------------

update "user" u
   set email          = lower(coalesce(
                          (select c.slug from client c where c.id = u.client_id),
                          'unknown'
                        )) || '+user' || u.id::text || '@staging.psifunction.invalid',
       display_name   = 'Staging User ' || u.id::text,
       password_hash  = current_setting('password_hash', true),
       invite_token   = null,
       reset_token    = null,
       invite_expires = null,
       reset_expires  = null;

\echo [scrub_data] user table scrubbed.

-- ---------------------------------------------------------------------------
-- 2) Explicitly preserved tables (no UPDATE here; documented for the
--    next reader).  Per the signed-off PII-scrub spec:
--      - client           (name, slug preserved; tenant routing needs slugs)
--      - client_resource  (title, description, external_url, file_path preserved)
--      - work_item        (title, description preserved; authored copy)
--      - taxonomy_tag     (shared vocabulary)
-- ---------------------------------------------------------------------------

\echo [scrub_data] preserved tables: client, client_resource, work_item, taxonomy_tag
\echo [scrub_data] done.
