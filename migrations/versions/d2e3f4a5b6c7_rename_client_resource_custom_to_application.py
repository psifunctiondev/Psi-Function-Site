"""Rename ClientResource.category 'custom' to 'application'

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-25 20:55:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    """Rewrite category='custom' rows to 'application'.

    Currently a no-op (no seed populates that key — the existing
    seeder uses 'engagement' / 'asset' / 'general'). Shipping the
    rewrite anyway so prod stays clean if any legacy 'custom' rows
    surface and so the test pinned in test_competitive_audit.py has
    something real to exercise.
    """
    op.execute(
        "UPDATE client_resource "
        "SET category = 'application' "
        "WHERE category = 'custom'"
    )


def downgrade():
    op.execute(
        "UPDATE client_resource "
        "SET category = 'custom' "
        "WHERE category = 'application'"
    )
