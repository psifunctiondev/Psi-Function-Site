"""Extend competitive_audit_submission for DrifterBot worker output

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-07-16 13:30:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e3f4a5b6c7d8'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade():
    """Add four worker-output columns to competitive_audit_submission.

    - audit_id      : String(32)  — the worker's audit-run identifier
                                 (currently the 32-char draft slug
                                 produced by the runner; nullable
                                 until the worker claims the row)
    - error_message : Text        — populated when the worker fails;
                                 nullable on success
    - started_at    : DateTime    — set when the worker claims the row
    - completed_at  : DateTime    — set when the worker finishes
                                 (success OR failure)

    All four columns are nullable=True so existing rows (R1 surface
    only) survive the migration without backfill. The R2 worker
    writes them as it claims / completes each submission.
    """
    op.add_column(
        'competitive_audit_submission',
        sa.Column('audit_id', sa.String(length=32), nullable=True),
    )
    op.add_column(
        'competitive_audit_submission',
        sa.Column('error_message', sa.Text(), nullable=True),
    )
    op.add_column(
        'competitive_audit_submission',
        sa.Column('started_at', sa.DateTime(), nullable=True),
    )
    op.add_column(
        'competitive_audit_submission',
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    """Drop the four worker-output columns added in upgrade()."""
    op.drop_column('competitive_audit_submission', 'completed_at')
    op.drop_column('competitive_audit_submission', 'started_at')
    op.drop_column('competitive_audit_submission', 'error_message')
    op.drop_column('competitive_audit_submission', 'audit_id')
