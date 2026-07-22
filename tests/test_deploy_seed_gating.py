"""Tests for the deploy-script seed gating.

The deploy scripts (deploy/scripts/deploy_release.sh and
deploy/scripts/db_migrate.sh) expose opt-in env knobs for the
per-client seed flows. This test pins which knobs exist and which
flask commands each one triggers, so a refactor that drops a knob or
typos a command name is caught at PR time.

This is the same pattern used for test_competitive_audit.py's
TestSlice9SecurityHeadersCsp — read the script as text and pin
strings. Shellcheck + a smoke run is the only real verification;
in-pytest this catches accidental drops / typos.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_RELEASE = (
    REPO_ROOT / "deploy" / "scripts" / "deploy_release.sh"
)
DB_MIGRATE = REPO_ROOT / "deploy" / "scripts" / "db_migrate.sh"
INSTALL_NGINX = (
    REPO_ROOT / "deploy" / "scripts" / "install_nginx_site.sh"
)
SNIPPETS_DIR = REPO_ROOT / "deploy" / "nginx" / "snippets"


class TestDeployReleaseDriftAndAnchorGating:
    """deploy_release.sh must run the Drift & Anchor seeders when
    SEED_DRIFT_AND_ANCHOR=1, and skip them with a log line when it
    isn't set. Mirrors the SEED_ACME_DEMO=1 pattern."""

    def test_script_exists(self):
        assert DEPLOY_RELEASE.exists()

    def test_seeds_drift_and_anchor_resources_when_enabled(self):
        text = DEPLOY_RELEASE.read_text()
        # The env-var check must be SEED_DRIFT_AND_ANCHOR.
        assert 'SEED_DRIFT_AND_ANCHOR:-0}' in text, (
            "deploy_release.sh missing SEED_DRIFT_AND_ANCHOR env check"
        )
        # Both seeder commands must appear inside the enabled branch.
        # Look for them within the gated block — we just check they're
        # in the script at all and gated on the env var.
        assert "seed-drift-and-anchor-resources" in text
        assert "seed-drift-and-anchor-invite" in text

    def test_logs_skip_when_disabled(self):
        text = DEPLOY_RELEASE.read_text()
        # The "skip" branch should mention the env var name so an
        # operator reading the deploy log knows how to enable it.
        assert "Skipping Drift & Anchor seed" in text
        assert "SEED_DRIFT_AND_ANCHOR=1" in text

    def test_seeds_run_after_branding(self):
        # The D&A seed block must sit AFTER the apply-branding step so
        # the client row exists when the seeders run. apply-branding
        # creates the client via _apply_profile; seed-drift-and-anchor
        # *also* calls _apply_profile internally, but the ordering
        # is the same as ACME — branding first, then seed.
        text = DEPLOY_RELEASE.read_text()
        branding_pos = text.find("apply-branding --all")
        dna_pos = text.find("seed-drift-and-anchor-resources")
        acme_pos = text.find("seed-acme-resources")
        assert branding_pos != -1
        assert dna_pos != -1
        assert acme_pos != -1
        assert branding_pos < dna_pos, (
            "Drift & Anchor seed must run after apply-branding"
        )
        assert acme_pos < dna_pos, (
            "ACME seed currently runs before Drift & Anchor seed in "
            "deploy_release.sh — that's fine for ordering but if you "
            "ever rearrange, keep ACME first to preserve the log flow."
        )


class TestDbMigrateDriftAndAnchorGating:
    """db_migrate.sh must expose SEED_DRIFT_AND_ANCHOR as an opt-in
    env knob and must include it in the --with-seeds all-knobs set."""

    def test_script_exists(self):
        assert DB_MIGRATE.exists()

    def test_help_text_documents_new_knob(self):
        text = DB_MIGRATE.read_text()
        assert "SEED_DRIFT_AND_ANCHOR=1" in text, (
            "db_migrate.sh help text missing SEED_DRIFT_AND_ANCHOR=1"
        )

    def test_with_seeds_enables_new_knob(self):
        # --with-seeds sets SEED_ACME_DEMO, SEED_TAXONOMY, SEED_WORK_DEMO.
        # After the new wiring it must also set SEED_DRIFT_AND_ANCHOR.
        text = DB_MIGRATE.read_text()
        # Locate the --with-seeds block: it's the `if [ "$WITH_SEEDS" -eq 1 ]`
        # followed by a sequence of `export SEED_*=1` lines.
        with_seeds_idx = text.find('WITH_SEEDS" -eq 1 ]')
        assert with_seeds_idx != -1
        block = text[with_seeds_idx: with_seeds_idx + 400]
        assert "SEED_DRIFT_AND_ANCHOR=1" in block, (
            "--with-seeds block does not export SEED_DRIFT_AND_ANCHOR=1"
        )

    def test_runs_seeds_when_enabled(self):
        text = DB_MIGRATE.read_text()
        assert (
            "flask client seed-drift-and-anchor-resources" in text
        ), "db_migrate.sh does not call seed-drift-and-anchor-resources"
        assert (
            "flask client seed-drift-and-anchor-invite" in text
        ), "db_migrate.sh does not call seed-drift-and-anchor-invite"

    def test_logs_skip_when_disabled(self):
        text = DB_MIGRATE.read_text()
        assert "Drift & Anchor seed skipped" in text
        assert "SEED_DRIFT_AND_ANCHOR=1" in text


# ---------------------------------------------------------------------------
# Slice 10 — install_nginx_site.sh snippet sync + deploy_release.sh wiring
# ---------------------------------------------------------------------------


class TestInstallNginxSiteScript:
    """The install_nginx_site.sh script must copy the snippets
    directory contents to /etc/nginx/snippets/ on every invocation,
    not just the main site conf. The 2026-07-22 incident was caused
    by this gap."""

    def test_script_exists(self):
        assert INSTALL_NGINX.exists()

    def test_accepts_testing_env(self):
        # The original script only accepted staging|production. The
        # deploy flow runs for testing too, so the script must accept
        # it. Find the case statement and assert testing is in the
        # valid arm.
        text = INSTALL_NGINX.read_text()
        case_start = text.find("case")
        case_end = text.find("esac")
        assert case_start != -1 and case_end != -1
        case_block = text[case_start:case_end]
        # The valid arm must list testing|staging|production.
        assert "testing|staging|production" in case_block
        # The default arm (`*)`) must NOT list testing.
        default_arm = case_block[case_block.rfind("*)"):]
        assert "testing" not in default_arm

    def test_copies_snippet_files(self):
        # The script must call `install -m 0644` for each .conf file
        # in the snippets dir, and the destination must be
        # /etc/nginx/snippets/. This is the core fix.
        text = INSTALL_NGINX.read_text()
        assert "/etc/nginx/snippets" in text
        assert "install -m 0644" in text
        # The snippet glob must pull from the source snippets dir.
        assert "deploy/nginx/snippets" in text or "nginx/snippets/*.conf" in text

    def test_creates_destination_dir_if_missing(self):
        # If /etc/nginx/snippets doesn't exist on a fresh droplet,
        # the script must create it. install -d is the standard idiom.
        text = INSTALL_NGINX.read_text()
        assert "install -d" in text
        assert "0755" in text  # sane perms on the snippets dir

    def test_validates_and_reloads_nginx(self):
        # The script must validate with nginx -t and reload on success.
        # These are the final two steps and the contract for "deploy
        # finished, nginx is serving the new config".
        text = INSTALL_NGINX.read_text()
        assert "nginx -t" in text
        assert "systemctl reload nginx" in text

    def test_snippet_dir_has_expected_files(self):
        # Sanity check on the source tree: the snippets dir must
        # contain at least security-headers.conf and
        # hardening-common.conf. If a refactor renames or moves
        # them, this catches it.
        assert (SNIPPETS_DIR / "security-headers.conf").exists()
        assert (SNIPPETS_DIR / "hardening-common.conf").exists()


class TestDeployReleaseCallsInstallNginx:
    """deploy_release.sh must invoke install_nginx_site.sh so the
    snippet file sync happens on every deploy, not just on
    provisioning. The call sits after `flask db upgrade` and before
    the seed flows, with a `|| log WARN` so a failed install doesn't
    block the deploy."""

    def test_calls_install_nginx_after_migrations(self):
        text = DEPLOY_RELEASE.read_text()
        # Find the migrations block and the install_nginx call, then
        # assert the install_nginx call sits AFTER the migrations.
        migrations_pos = text.find("flask db upgrade")
        install_pos = text.find("install_nginx_site.sh")
        assert migrations_pos != -1
        assert install_pos != -1
        assert migrations_pos < install_pos, (
            "install_nginx_site.sh must run after flask db upgrade"
        )

    def test_warns_on_failure_does_not_abort(self):
        # The install call must be guarded with `|| log "WARN..."` so
        # a transient nginx issue doesn't break the deploy. The
        # pattern mirrors the apply-branding guard above it.
        text = DEPLOY_RELEASE.read_text()
        # Locate the install block. Use a search that finds the
        # `sudo bash` invocation and asserts the `||` follows within
        # the next 200 chars.
        install_idx = text.find("install_nginx_site.sh")
        assert install_idx != -1
        block = text[install_idx: install_idx + 400]
        assert "||" in block, "install_nginx_site.sh call must be guarded with ||"
        assert "WARN" in block, "|| branch must log a WARN"
        # And the guard must NOT be at the deploy level (i.e. we
        # should NOT have `set -e` removed around the call).
        assert "set -Eeuo pipefail" in text  # sanity: strict mode still on

    def test_uses_source_dir_path(self):
        # The script must call install_nginx_site.sh from
        # $SOURCE_DIR (the rsynced source tree), not from the
        # current release dir. That way the call works during the
        # release symlink switch.
        text = DEPLOY_RELEASE.read_text()
        # The literal "$SOURCE_DIR/deploy/scripts/install_nginx_site.sh"
        # should appear in the call.
        assert (
            "$SOURCE_DIR/deploy/scripts/install_nginx_site.sh" in text
        ), "install_nginx_site.sh must be invoked from $SOURCE_DIR"

    def test_deploy_release_already_restarts_gunicorn(self):
        # The gunicorn-restart gap Quinn hit (manual seed => stale
        # workers => page doesn't show new rows) is already covered
        # by the unconditional restart at the end of deploy_release.sh.
        # This test pins that contract so a refactor doesn't drop it.
        text = DEPLOY_RELEASE.read_text()
        assert "systemctl restart \"$SERVICE_NAME\"" in text, (
            "deploy_release.sh must restart the systemd service on every deploy"
        )

    def test_readme_documents_snippet_sync(self):
        # README has a section explaining the snippet sync + the
        # manual-seed restart note. If a docs refactor drops either
        # paragraph, this catches it.
        readme = (REPO_ROOT / "README.md").read_text()
        assert "Nginx site + snippet sync" in readme
        assert (
            "deploy/scripts/install_nginx_site.sh" in readme
        ), "README must reference the install_nginx_site.sh script"
        assert (
            "Manual seed flows need a manual worker restart" in readme
        ), "README must warn about the manual-seed / stale-worker gap"
