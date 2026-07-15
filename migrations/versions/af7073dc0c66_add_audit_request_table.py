"""add audit_request table for DrifterBot portal submissions

Revision ID: af7073dc0c66
Revises: 8d63edc201fd
Create Date: 2026-07-15

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'af7073dc0c66'
down_revision = '8d63edc201fd'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'audit_request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),

        # Submitter + portal context
        sa.Column('requested_by_user_id', sa.Integer(), nullable=False),
        sa.Column('requested_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('(CURRENT_TIMESTAMP)')),

        # Audit-target config (JSON blobs — keeps schema flat + future-proof)
        sa.Column('client_name', sa.String(length=255), nullable=False),
        sa.Column('client_category', sa.String(length=255), nullable=False),
        sa.Column('competitor_list_json', sa.Text(), nullable=False),
        sa.Column('audience_list_json', sa.Text(), nullable=False),
        sa.Column('positioning_inputs_json', sa.Text(), nullable=True),
        sa.Column('social_scans_json', sa.Text(), nullable=False),
        sa.Column('context_drive_links_json', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),

        # Lifecycle
        sa.Column('status', sa.String(length=32), nullable=False,
                  server_default='pending'),
        sa.Column('audit_id', sa.String(length=32), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),

        # Audit timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('(CURRENT_TIMESTAMP)'),
                  onupdate=sa.text('(CURRENT_TIMESTAMP)')),

        sa.ForeignKeyConstraint(['client_id'], ['client.id']),
        sa.ForeignKeyConstraint(['requested_by_user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('audit_request', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_audit_request_status'),
            ['status'], unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_audit_request_client_id'),
            ['client_id'], unique=False,
        )


def downgrade():
    with op.batch_alter_table('audit_request', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_request_client_id'))
        batch_op.drop_index(batch_op.f('ix_audit_request_status'))
    op.drop_table('audit_request')
