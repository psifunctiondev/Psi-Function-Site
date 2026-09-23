"""Tests for OpProjectSnapshot model + the migration that creates it.

Covers:

* Model shape: columns, unique constraint, indexes, JSON distribution
  helper.
* Idempotency: re-saving with the same (project_op_id, snapshot_date)
  updates the row in place rather than creating duplicates.
* Migration: the upgrade creates the table; downgrade removes it; the
  upgrade + downgrade + upgrade round-trip is a no-op.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.extensions import db
from app.models.op_snapshot import OpProjectSnapshot


# --------------------------------------------------------------------------- #
# Helpers — same pattern as tests/test_client_openproject_master_id.py
# --------------------------------------------------------------------------- #
def _alembic_config(app):
    cfg = Config()
    cfg.config_file_name = 'migrations/alembic.ini'
    cfg.set_main_option('script_location', 'migrations')
    cfg.set_main_option('sqlalchemy.url', app.config['SQLALCHEMY_DATABASE_URI'])
    return cfg


# --------------------------------------------------------------------------- #
# Model shape
# --------------------------------------------------------------------------- #
class TestOpProjectSnapshotModel:

    def test_columns_present(self):
        assert hasattr(OpProjectSnapshot, 'id')
        assert hasattr(OpProjectSnapshot, 'project_op_id')
        assert hasattr(OpProjectSnapshot, 'snapshot_date')
        assert hasattr(OpProjectSnapshot, 'story_points_by_status_json')
        assert hasattr(OpProjectSnapshot, 'work_package_count')
        assert hasattr(OpProjectSnapshot, 'created_at')
        assert hasattr(OpProjectSnapshot, 'updated_at')

    def test_distribution_property_parses_json(self, db_session):
        snap = OpProjectSnapshot(
            project_op_id=42,
            snapshot_date=date(2026, 9, 22),
            story_points_by_status_json=json.dumps({
                'New': 3, 'In progress': 8, 'Completed': 5,
            }),
            work_package_count=6,
        )
        db_session.add(snap)
        db_session.commit()

        # Re-fetch to read the value the DB stored.
        fetched = OpProjectSnapshot.for_project_on_date(42, date(2026, 9, 22))
        assert fetched is not None
        assert fetched.distribution == {
            'New': 3, 'In progress': 8, 'Completed': 5,
        }
        assert fetched.work_package_count == 6

    def test_distribution_handles_empty_and_garbage_json(self, db_session):
        # Empty string -> empty dict (the column default).
        snap = OpProjectSnapshot(
            project_op_id=42,
            snapshot_date=date(2026, 9, 23),
            story_points_by_status_json='',
            work_package_count=0,
        )
        db_session.add(snap)
        db_session.commit()
        fetched = OpProjectSnapshot.for_project_on_date(42, date(2026, 9, 23))
        assert fetched.distribution == {}

        # Garbage JSON -> empty dict (defensive — don't raise).
        snap.story_points_by_status_json = 'not-json'
        db_session.commit()
        fetched = OpProjectSnapshot.for_project_on_date(42, date(2026, 9, 23))
        assert fetched.distribution == {}

    def test_for_project_on_date_returns_none_when_missing(self, db_session):
        assert OpProjectSnapshot.for_project_on_date(
            999, date(2026, 1, 1),
        ) is None

    def test_unique_constraint_on_project_date_pair(self, db_session):
        """The (project_op_id, snapshot_date) unique constraint prevents
        duplicate rows for the same day — the cron relies on this for
        idempotent re-runs.
        """
        from sqlalchemy.exc import IntegrityError

        first = OpProjectSnapshot(
            project_op_id=42,
            snapshot_date=date(2026, 9, 22),
            story_points_by_status_json='{}',
            work_package_count=0,
        )
        db_session.add(first)
        db_session.commit()

        with pytest.raises(IntegrityError):
            db_session.add(OpProjectSnapshot(
                project_op_id=42,
                snapshot_date=date(2026, 9, 22),  # same pair
                story_points_by_status_json='{}',
                work_package_count=0,
            ))
            db_session.commit()
        db_session.rollback()

    def test_upsert_pattern_used_by_cron(self, db_session):
        """The cron uses this pattern: look up by (project, date); if
        found, update in place; else insert. Test the round-trip.
        """
        existing = OpProjectSnapshot(
            project_op_id=42,
            snapshot_date=date(2026, 9, 22),
            story_points_by_status_json='{"New": 1}',
            work_package_count=1,
        )
        db_session.add(existing)
        db_session.commit()
        first_id = existing.id

        # Re-run "today's cron" — same date, updated counts.
        snap = OpProjectSnapshot.for_project_on_date(42, date(2026, 9, 22))
        snap.work_package_count = 5
        snap.story_points_by_status_json = '{"New": 4, "In progress": 1}'
        db_session.commit()

        # Same row, updated values.
        all_rows = OpProjectSnapshot.query.filter_by(
            project_op_id=42, snapshot_date=date(2026, 9, 22),
        ).all()
        assert len(all_rows) == 1
        assert all_rows[0].id == first_id
        assert all_rows[0].work_package_count == 5
        assert all_rows[0].distribution == {'New': 4, 'In progress': 1}


# --------------------------------------------------------------------------- #
# Migration upgrade / downgrade
# --------------------------------------------------------------------------- #
class TestOpSnapshotMigration:

    HEAD = 'a1b2c3d4e5f7'  # this commit's revision id
    PREV = '33e2c1a946ce'    # parent revision

    @pytest.fixture
    def fresh_schema(self, app):
        with app.app_context():
            db.drop_all()
        yield app

    def test_upgrade_creates_table(self, app, fresh_schema):
        with app.app_context():
            cfg = _alembic_config(app)
            command.upgrade(cfg, self.HEAD)

            insp = inspect(db.engine)
            assert 'op_project_snapshot' in insp.get_table_names()
            cols = {c['name'] for c in insp.get_columns('op_project_snapshot')}
            assert {'id', 'project_op_id', 'snapshot_date',
                    'story_points_by_status_json', 'work_package_count',
                    'created_at', 'updated_at'} <= cols

            # Unique constraint present.
            uqs = {uc['name'] for uc in insp.get_unique_constraints(
                'op_project_snapshot',
            )}
            assert 'uq_op_project_snapshot_project_date' in uqs

    def test_downgrade_drops_table(self, app, fresh_schema):
        with app.app_context():
            cfg = _alembic_config(app)
            command.upgrade(cfg, self.HEAD)
            command.downgrade(cfg, self.PREV)

            insp = inspect(db.engine)
            assert 'op_project_snapshot' not in insp.get_table_names()

    def test_round_trip_is_noop(self, app, fresh_schema):
        """upgrade -> downgrade -> upgrade should leave the schema
        identical and not lose the indexes."""
        with app.app_context():
            cfg = _alembic_config(app)
            command.upgrade(cfg, self.HEAD)
            command.downgrade(cfg, self.PREV)
            command.upgrade(cfg, self.HEAD)

            insp = inspect(db.engine)
            assert 'op_project_snapshot' in insp.get_table_names()
            indexes = {ix['name'] for ix in insp.get_indexes('op_project_snapshot')}
            # Both indexes recreated on second upgrade.
            assert 'ix_op_project_snapshot_project_op_id' in indexes
            assert 'ix_op_project_snapshot_snapshot_date' in indexes
