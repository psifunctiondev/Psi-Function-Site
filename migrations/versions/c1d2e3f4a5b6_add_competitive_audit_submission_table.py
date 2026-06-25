"""Add competitive audit submission table

Revision ID: c1d2e3f4a5b6
Revises: 8d63edc201fd
Create Date: 2026-06-25 20:55:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c1d2e3f4a5b6'
down_revision = '8d63edc201fd'
branch_labels = None
depends_on = None


def upgrade():
    # competitive_audit_submission — captured intake for the
    # Drift & Anchor competitive-audit feature.
    #
    # form_data is JSON: nullable competitor sub-cards are stored as
    # nulls (not empty objects) so the downstream pipeline gets a
    # predictable shape.
    #
    # status defaults to 'submitted' (server-side); the R1 UI does not
    # flip it. R2 will introduce 'processing' / 'complete' transitions.
    #
    # Two indexes:
    #   - (client_id, created_at DESC) serves the per-client history list.
    #   - (forked_from_id) serves the fork-graph lookup.
    op.create_table(
        'competitive_audit_submission',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column(
            'status',
            sa.String(length=32),
            nullable=False,
            server_default='submitted',
        ),
        sa.Column('form_data', sa.JSON(), nullable=False),
        sa.Column('forked_from_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['author_id'], ['user.id'],
        ),
        sa.ForeignKeyConstraint(
            ['client_id'], ['client.id'],
        ),
        sa.ForeignKeyConstraint(
            ['forked_from_id'], ['competitive_audit_submission.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_competitive_audit_submission_client_created',
        'competitive_audit_submission',
        ['client_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'ix_competitive_audit_submission_forked_from',
        'competitive_audit_submission',
        ['forked_from_id'],
        unique=False,
    )


def downgrade():
    op.drop_index(
        'ix_competitive_audit_submission_forked_from',
        table_name='competitive_audit_submission',
    )
    op.drop_index(
        'ix_competitive_audit_submission_client_created',
        table_name='competitive_audit_submission',
    )
    op.drop_table('competitive_audit_submission')
