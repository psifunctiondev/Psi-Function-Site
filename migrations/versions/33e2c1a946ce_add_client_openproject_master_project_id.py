"""add client openproject_master_project_id

Revision ID: 33e2c1a946ce
Revises: 8d63edc201fd
Create Date: 2026-06-15 19:55:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '33e2c1a946ce'
down_revision = '8d63edc201fd'
branch_labels = None
depends_on = None


def upgrade():
    # Commit 2 of 6 of the OpenProject integration (per the 2026-04-24
    # expanded spec). Holds the integer ID of the master OpenProject project
    # for each Client. Nullable on purpose: ops wires the real project ID
    # per client after this migration lands. The field name intentionally
    # uses ``_master_`` because the spec calls out that the master project
    # can have direct child sub-projects discovered via the OP API at read
    # time (not stored here).
    op.add_column(
        'client',
        sa.Column('openproject_master_project_id', sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column('client', 'openproject_master_project_id')
