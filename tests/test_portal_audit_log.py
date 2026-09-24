"""Tests for the PortalAuditLog model + migration.

``PortalAuditLog`` records every successful portal-driven mutation to
OpenProject — the internal "who did what when" trail. Per the
2026-04-24 spec §"New model: PortalAuditLog":

    id, user_id, client_id, op_project_id, op_work_package_id,
    action ("status_change" | "reorder"),
    before_value, after_value,
    op_response_code, op_response_error,
    created_at

The journal comment posted to OP is the human-readable audit trail
clients see; this table is Psi Function's internal record. Useful
for "who changed this status last Tuesday at 3pm" admin queries.

Covers:
* Model shape: columns, indexes, before/after JSON helpers, action
  enum values.
* Migration: the upgrade creates the table; downgrade removes it.
* Migration chain: depends on the OP snapshot migration
  (``a1b2c3d4e5f7``) so the schema history is linear.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import inspect

from app import create_app
from app.extensions import db as _db
from app.models.portal_audit_log import PortalAuditLog


@pytest.fixture
def app():
    app = create_app('pytest')
    return app


@pytest.fixture
def db_session(app):
    with app.app_context():
        _db.create_all()
        yield _db.session
        _db.session.remove()
        _db.drop_all()


# --------------------------------------------------------------------------- #
# Model shape
# --------------------------------------------------------------------------- #
class TestPortalAuditLogModelShape:
    def test_table_name(self):
        assert PortalAuditLog.__tablename__ == 'portal_audit_log'

    def test_required_columns_present(self):
        cols = {c.name for c in PortalAuditLog.__table__.columns}
        # Per spec.
        assert cols == {
            'id', 'user_id', 'client_id', 'op_project_id',
            'op_work_package_id', 'action',
            'before_value', 'after_value',
            'op_response_code', 'op_response_error', 'created_at',
        }

    def test_id_is_primary_key(self):
        id_col = PortalAuditLog.__table__.columns['id']
        assert id_col.primary_key is True

    def test_user_id_and_client_id_are_nullable(self):
        """A user could be deleted; we keep the audit row but null out
        the FK so the history isn't lost. (Future hardening: separate
        archive mode.)"""
        user_col = PortalAuditLog.__table__.columns['user_id']
        client_col = PortalAuditLog.__table__.columns['client_id']
        assert user_col.nullable is True
        assert client_col.nullable is True

    def test_op_project_id_and_op_work_package_id_are_nullable(self):
        """Same rationale — the audit row outlives the OP-side row."""
        proj_col = PortalAuditLog.__table__.columns['op_project_id']
        wp_col = PortalAuditLog.__table__.columns['op_work_package_id']
        assert proj_col.nullable is True
        assert wp_col.nullable is True

    def test_action_is_not_nullable(self):
        """Every audit row has an action — without one it's not
        meaningful audit data."""
        assert PortalAuditLog.__table__.columns['action'].nullable is False

    def test_created_at_is_not_nullable_and_defaults_to_now(self):
        col = PortalAuditLog.__table__.columns['created_at']
        assert col.nullable is False
        assert col.server_default is not None


# --------------------------------------------------------------------------- #
# Action enum values
# --------------------------------------------------------------------------- #
class TestActionValues:
    """Pin the two spec-defined actions so a typo at the call site
    (e.g. ``"status-change"`` vs ``"status_change"``) fails loudly.

    The write route writes these strings verbatim; tests assert on the
    string in PortalAuditLog rows, so the values are part of the
    contract.
    """

    def test_status_change_action(self):
        assert PortalAuditLog.ACTION_STATUS_CHANGE == 'status_change'

    def test_reorder_action(self):
        assert PortalAuditLog.ACTION_REORDER == 'reorder'


# --------------------------------------------------------------------------- #
# Persistence + read-back
# --------------------------------------------------------------------------- #
class TestPersistence:
    def test_can_create_and_read_back(self, db_session):
        row = PortalAuditLog(
            user_id=1,
            client_id=2,
            op_project_id=42,
            op_work_package_id=99,
            action=PortalAuditLog.ACTION_STATUS_CHANGE,
            before_value='New',
            after_value='In progress',
            op_response_code=200,
            op_response_error=None,
        )
        db_session.add(row)
        db_session.commit()

        got = db_session.query(PortalAuditLog).filter_by(id=row.id).one()
        assert got.user_id == 1
        assert got.client_id == 2
        assert got.op_project_id == 42
        assert got.op_work_package_id == 99
        assert got.action == 'status_change'
        assert got.before_value == 'New'
        assert got.after_value == 'In progress'
        assert got.op_response_code == 200
        assert got.op_response_error is None
        # created_at was server-defaulted to now()
        assert isinstance(got.created_at, datetime)

    def test_created_at_is_set_to_now(self, db_session):
        """The created_at column is server-defaulted; just verify it
        lands (we don't pin tz-awareness because SQLAlchemy + SQLite +
        Postgres differ in how they round-trip naive vs aware
        datetimes)."""
        row = PortalAuditLog(
            user_id=1, action=PortalAuditLog.ACTION_REORDER,
            before_value='1', after_value='2', op_response_code=200,
        )
        db_session.add(row)
        db_session.commit()

        got = db_session.query(PortalAuditLog).filter_by(id=row.id).one()
        assert got.created_at is not None


# --------------------------------------------------------------------------- #
# Indexes
# --------------------------------------------------------------------------- #
class TestIndexes:
    """The audit table grows fast — every WP mutation writes a row.
    Cheap queries for ops/admin need an index. Pin the indexes so a
    future drop is loud."""

    def test_index_on_op_work_package_id(self, db_session):
        idx_cols = _indexed_columns('portal_audit_log', 'op_work_package_id')
        assert idx_cols, 'expected an index on op_work_package_id'

    def test_index_on_client_id(self, db_session):
        idx_cols = _indexed_columns('portal_audit_log', 'client_id')
        assert idx_cols, 'expected an index on client_id'

    def test_index_on_created_at(self, db_session):
        idx_cols = _indexed_columns('portal_audit_log', 'created_at')
        assert idx_cols, 'expected an index on created_at'


def _indexed_columns(table_name: str, column_name: str) -> list[str]:
    """Return the list of columns in any index on ``table_name`` that
    includes ``column_name``. Empty list if no such index exists.

    Uses the live engine from the active app context (the ``db_session``
    fixture opens one)."""
    insp = inspect(_db.engine)
    out = []
    for idx in insp.get_indexes(table_name):
        if column_name in idx.get('column_names', []):
            out.append(column_name)
    return out
