"""add portal_audit_log table

Commit 5 of the OP integration (per the 2026-09-22 kickoff).

Internal audit trail of every portal-driven OP mutation. The
human-readable journal comment posted to OP is the client-facing audit
record; this table is Psi Function's internal record for "who changed
what when" admin queries.

Schema notes mirror app/models/portal_audit_log.py: user_id / client_id
/ op_*_id are nullable so audit rows survive deletions; action is the
sole NOT-NULL string; created_at is server-defaulted. Indexes on
(op_work_package_id), (client_id), (created_at) serve the common ops
queries.

Revision chains from the OP snapshot migration (a1b2c3d4e5f7, commit
4) so the schema history is linear. If the snapshot migration's id
changes at commit time, rebase this migration to match.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b1c2d3e4f5a6'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'portal_audit_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'user_id', sa.Integer(),
            sa.ForeignKey('user.id'), nullable=True,
        ),
        sa.Column(
            'client_id', sa.Integer(),
            sa.ForeignKey('client.id'), nullable=True,
        ),
        sa.Column('op_project_id', sa.Integer(), nullable=True),
        sa.Column('op_work_package_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=32), nullable=False),
        sa.Column('before_value', sa.String(length=255), nullable=True),
        sa.Column('after_value', sa.String(length=255), nullable=True),
        sa.Column('op_response_code', sa.Integer(), nullable=True),
        sa.Column('op_response_error', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        'ix_portal_audit_log_op_wp',
        'portal_audit_log', ['op_work_package_id'],
    )
    op.create_index(
        'ix_portal_audit_log_client',
        'portal_audit_log', ['client_id'],
    )
    op.create_index(
        'ix_portal_audit_log_created_at',
        'portal_audit_log', ['created_at'],
    )


def downgrade():
    op.drop_index('ix_portal_audit_log_created_at', 'portal_audit_log')
    op.drop_index('ix_portal_audit_log_client', 'portal_audit_log')
    op.drop_index('ix_portal_audit_log_op_wp', 'portal_audit_log')
    op.drop_table('portal_audit_log')
