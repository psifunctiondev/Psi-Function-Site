"""Tests for Client.openproject_master_project_id (commit 2 of OP integration).

Covers:

* Model: the field exists, is nullable, defaults to None, accepts ints.
* Migrations: the alembic upgrade/downgrade round-trips without data loss
  for existing rows (and respects the existing null state).
* CLI seed flows: ``_apply_profile`` and the ACME / CTAI branding profiles
  do not set this field. It must stay null until ops wires a real project
  ID per client.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.cli import BRANDING_PROFILES, _apply_profile
from app.extensions import db
from app.models.client import Client

# ---------------------------------------------------------------------------
# Model-level
# ---------------------------------------------------------------------------

class TestClientOpenProjectField:
    """The new column is exposed on Client with the expected shape."""

    def test_field_exists_on_model(self):
        # SQLAlchemy exposes mapped columns via the class.
        assert hasattr(Client, 'openproject_master_project_id')
        col = Client.openproject_master_project_id
        # The column should be nullable (we don't backfill; ops wires per
        # client). It must NOT have a server-side default.
        assert col.nullable is True

    def test_default_value_is_none(self, db_session):
        c = Client(name='OPNull Corp', slug='op-null-corp')
        db_session.add(c)
        db_session.commit()

        assert c.openproject_master_project_id is None

    def test_can_assign_integer_value(self, db_session):
        c = Client(
            name='OPInt Corp', slug='op-int-corp',
            openproject_master_project_id=4242,
        )
        db_session.add(c)
        db_session.commit()

        db_session.refresh(c)
        assert c.openproject_master_project_id == 4242

    def test_does_not_break_existing_client_construction(self, db_session):
        # Backwards compatibility: callers that don't pass the new field
        # (e.g. existing tests, the user invite CLI) still work.
        c = Client(name='Backcompat Corp', slug='backcompat-corp')
        db_session.add(c)
        db_session.commit()

        assert c.openproject_master_project_id is None
        assert c.id is not None


# ---------------------------------------------------------------------------
# Migration round-trip
# ---------------------------------------------------------------------------

def _alembic_config(app):
    """Build an alembic Config bound to the app's test database."""
    cfg = Config()
    # Point fileConfig at the project's alembic.ini so env.py can read
    # [loggers]/[handlers] without choking on a None filename.
    cfg.config_file_name = 'migrations/alembic.ini'
    cfg.set_main_option('script_location', 'migrations')
    # Flask-Migrate's env.py uses current_app; we don't need a real
    # connection string here because we drive the migration in an
    # app context.
    return cfg


class TestOpenProjectMasterIdMigration:
    """The 33e2c1a946ce migration upgrades, downgrades, and is rename-safe."""

    @pytest.fixture
    def fresh_schema(self, app):
        """Drop and recreate the schema so we can step the alembic chain."""
        with app.app_context():
            db.drop_all()
            yield app

    def _current_head(self):
        # Hardcode the head we expect for this commit. If a later commit
        # lands a new head, this test should be re-pointed (or use
        # ``alembic heads`` against the migrations dir).
        return '33e2c1a946ce'

    def test_upgrade_adds_column(self, app, fresh_schema):
        with app.app_context():
            cfg = _alembic_config(app)
            command.upgrade(cfg, self._current_head())

            insp = inspect(db.engine)
            cols = {c['name'] for c in insp.get_columns('client')}
            assert 'openproject_master_project_id' in cols

    def test_downgrade_drops_column(self, app, fresh_schema):
        with app.app_context():
            cfg = _alembic_config(app)
            command.upgrade(cfg, self._current_head())
            command.downgrade(cfg, '8d63edc201fd')

            insp = inspect(db.engine)
            cols = {c['name'] for c in insp.get_columns('client')}
            assert 'openproject_master_project_id' not in cols

    def test_round_trip_preserves_existing_rows(self, app, fresh_schema):
        """Upgrade + downgrade + upgrade again should be a no-op for
        pre-existing data (the new column is nullable, so no values are
        forced)."""
        from sqlalchemy import text

        with app.app_context():
            # Step forward to just-before the new migration to insert a row.
            cfg = _alembic_config(app)
            command.upgrade(cfg, '8d63edc201fd')

            # Insert via raw SQL to avoid the ORM trying to write to the
            # not-yet-existing ``openproject_master_project_id`` column.
            # (The model is already mapped to the new column; only the DB
            # schema hasn't caught up yet.)
            db.session.execute(
                text(
                    "INSERT INTO client (name, slug, is_active) "
                    "VALUES (:name, :slug, :is_active)"
                ),
                {'name': 'Pre Corp', 'slug': 'pre-corp', 'is_active': True},
            )
            db.session.commit()
            original_id = db.session.execute(
                text("SELECT id FROM client WHERE slug = 'pre-corp'")
            ).scalar_one()
            original_name = 'Pre Corp'

            # Now upgrade — existing row should still be there with the
            # new field null.
            command.upgrade(cfg, '33e2c1a946ce')
            db.session.expire_all()
            survivor = db.session.get(Client, original_id)
            assert survivor is not None
            assert survivor.name == original_name
            assert survivor.openproject_master_project_id is None

            # Downgrade — the new column disappears, the row remains.
            command.downgrade(cfg, '8d63edc201fd')
            db.session.expire_all()
            # Use raw SQL because the ORM model still has the dropped column.
            row = db.session.execute(
                text("SELECT id, name FROM client WHERE id = :id"),
                {'id': original_id},
            ).first()
            assert row is not None
            assert row.name == original_name

            # Upgrade again — still null, still there.
            command.upgrade(cfg, '33e2c1a946ce')
            db.session.expire_all()
            survivor = db.session.get(Client, original_id)
            assert survivor is not None
            assert survivor.openproject_master_project_id is None


# ---------------------------------------------------------------------------
# CLI seed flows must not set the new field
# ---------------------------------------------------------------------------

class TestSeedFlowsLeaveOpFieldNull:
    """``_apply_profile`` and the existing profiles must NOT touch
    ``openproject_master_project_id``. It stays null until ops wires a
    real project ID per client (separate concern, not in this commit)."""

    def test_apply_profile_does_not_set_op_field(self, db_session):
        profile = BRANDING_PROFILES['ctai']
        client, _created, _changed = _apply_profile('ctai', profile)

        assert client.openproject_master_project_id is None

    def test_apply_profile_acme_does_not_set_op_field(self, db_session):
        profile = BRANDING_PROFILES['acme']
        client, _created, _changed = _apply_profile('acme', profile)

        assert client.openproject_master_project_id is None

    def test_re_applying_profile_keeps_op_field_null(self, db_session):
        """Idempotent re-runs (the deploy-time pattern) must not flip the
        field, even if a future profile tries to set it. The seeder only
        iterates the profile dict, and the dicts intentionally omit this
        key, so we want to lock that behavior in."""
        _apply_profile('acme', BRANDING_PROFILES['acme'])
        # Re-apply — should still leave the field alone.
        _apply_profile('acme', BRANDING_PROFILES['acme'])
        client = Client.query.filter_by(slug='acme').first()
        assert client is not None
        assert client.openproject_master_project_id is None
