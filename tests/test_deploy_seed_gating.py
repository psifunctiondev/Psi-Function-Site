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
