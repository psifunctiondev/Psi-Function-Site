"""add client logo_max_width

Revision ID: a1b2c3d4e5f6
Revises: 90c96eb9c0d6
Create Date: 2026-04-25

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '90c96eb9c0d6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('client', sa.Column('logo_max_width', sa.String(32), nullable=True))


def downgrade():
    op.drop_column('client', 'logo_max_width')
