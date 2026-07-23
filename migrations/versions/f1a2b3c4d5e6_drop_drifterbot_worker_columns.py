"""Drop DrifterBot worker columns from competitive_audit_submission

Revision ID: f1a2b3c4d5e6
Revises: d2e3f4a5b6c7
Create Date: 2026-07-23 18:55:00.000000

Companion migration to PR #71 (chore/revert-driftbot-portal-worker,
the 24-revert chain that abandoned the portal-DB intake +
worker-as-daemon architecture on Psi-Function-Site in favor of
email intake from the brandsight repo).

What happened
-------------
The revert chain deleted:

  - agents/driftbot/  (the worker package)
  - migrations/versions/e3f4a5b6c7d8_extend_competitive_audit_submission_for_worker.py
    (the migration that added the worker-output columns)

After the revert, alembic's head is d2e3f4a5b6c7 (the rename
migration). But the testing/staging/production databases had
e3f4a5b6c7d8 recorded as their applied head — and the four
worker columns it added are still present in the schema.

When the next flask db upgrade runs against any of those DBs,
alembic tries to find e3f4a5b6c7d8 in the codebase to walk
forward from it, can't, and fails with:

    ERROR [flask_migrate] Error: Can't locate revision identified
    by 'e3f4a5b6c7d8'

This migration resolves that by:

  1. Dropping the four worker-output columns (audit_id,
     error_message, started_at, completed_at) — none have any
     remaining readers since app/models/competitive_audit.py no
     longer declares them, and the worker that wrote them is gone.

  2. Becoming the new alembic head, down-revving to
     d2e3f4a5b6c7. Running flask db upgrade against any existing
     DB records this revision in alembic_version and clears the
     orphan reference to e3f4a5b6c7d8.

Deploy-time bridge
------------------
Because e3f4a5b6c7d8 was deleted from the codebase, alembic
cannot find it in the migration graph to walk forward from it.
deploy_release.sh runs a flask db stamp d2e3f4a5b6c7 BEFORE
flask db upgrade, which rewrites alembic_version to the
pre-existing head; the upgrade then runs cleanly.

Data safety
-----------
All four columns were nullable and only ever written by the
DrifterBot worker, which has been removed. Existing rows have
NULL in all four columns. Dropping them is a no-op against any
data.

The competitive_audit_submission rows themselves are preserved —
the portal's R1 audit-request form route
(portal.drift_and_anchor_competitive_audit) still exists and
still writes the base columns. Submissions continue to land in
the DB with status='submitted'; they just don't get processed
until the brandsight email-intake pipeline is wired up to read
them via DATABASE_URL.

Refs: PR #71, brandsight PR #4 (companion rebase), the
2026-07-23 Drift & Anchor pivot from portal-DB to email intake.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade():
    """Drop the four DrifterBot worker columns from
    competitive_audit_submission.

    Uses plain op.drop_column rather than batch_alter_table
    because the columns being dropped were added in the (now-
    deleted) e3f4a5b6c7d8 migration. SQLite's batch mode tries
    to recreate the table from a snapshot of the current schema
    and fails to find columns that weren't introduced via
    batch_alter_table in the same migration. Direct op.drop_column
    works on both PostgreSQL (the production engine) and SQLite
    (the test engine).
    """
    op.drop_column('competitive_audit_submission', 'completed_at')
    op.drop_column('competitive_audit_submission', 'started_at')
    op.drop_column('competitive_audit_submission', 'error_message')
    op.drop_column('competitive_audit_submission', 'audit_id')


def downgrade():
    """Re-add the four DrifterBot worker columns.

    Mirrors e3f4a5b6c7d8 upgrade() exactly. Used only by
    flask db downgrade; no live deploy path calls this.
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
