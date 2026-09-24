"""add op_project_snapshot table

Commit 4 of the OP integration (per the 2026-09-22 kickoff).

The snapshot table is the read cache for the Progress tab stacked-bar
chart. Daily cron walks each active client's master project + direct
children, computes the status distribution (sum of storyPoints per
status name), and upserts one row per (project, day).

Schema:
  - project_op_id + snapshot_date are uniquely keyed so re-runs on
    the same day update in place (idempotent).
  - story_points_by_status_json is JSON text — {status_name: sp_sum}
    so the schema doesn't have to grow when OP instances add custom
    statuses.
  - work_package_count is a convenience aggregate (also captured by
    the cron; same fetch).
  - created_at + updated_at server-defaulted to now().
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f7'
down_revision = '33e2c1a946ce'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'op_project_snapshot',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_op_id', sa.Integer(), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column(
            'story_points_by_status_json',
            sa.Text(), nullable=False, server_default='{}',
        ),
        sa.Column(
            'work_package_count',
            sa.Integer(), nullable=False, server_default='0',
        ),
        sa.Column(
            'created_at',
            sa.DateTime(), server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            'project_op_id', 'snapshot_date',
            name='uq_op_project_snapshot_project_date',
        ),
    )
    op.create_index(
        'ix_op_project_snapshot_project_op_id',
        'op_project_snapshot', ['project_op_id'],
    )
    op.create_index(
        'ix_op_project_snapshot_snapshot_date',
        'op_project_snapshot', ['snapshot_date'],
    )


def downgrade():
    op.drop_index(
        'ix_op_project_snapshot_snapshot_date',
        table_name='op_project_snapshot',
    )
    op.drop_index(
        'ix_op_project_snapshot_project_op_id',
        table_name='op_project_snapshot',
    )
    op.drop_table('op_project_snapshot')
