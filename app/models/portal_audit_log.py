"""PortalAuditLog — internal audit trail of portal-driven OP mutations.

Every successful portal mutation (status change, reorder) writes one
row to this table BEFORE posting the human-readable journal comment
to OpenProject. The journal comment is what clients see in OP;
``PortalAuditLog`` is Psi Function's internal record.

Per the 2026-04-24 spec §"New model: PortalAuditLog":

    id, user_id, client_id, op_project_id, op_work_package_id,
    action ("status_change" | "reorder"),
    before_value, after_value,
    op_response_code, op_response_error,
    created_at

Schema notes:

  * ``user_id`` / ``client_id`` are nullable so the audit row
    survives deletion of the actor (admin "who did this" lookups
    shouldn't break when an old user is removed).
  * ``op_project_id`` / ``op_work_package_id`` are nullable for the
    same reason on the OP side.
  * ``action`` is the only NOT-NULL string column — every audit row
    must carry one of the two spec-defined actions.
  * ``created_at`` is server-defaulted to now() so the cron / script
    path doesn't have to thread a clock.
  * Indexes on (op_work_package_id), (client_id), (created_at) —
    admin queries by client + by recency are the common ops ask.
"""

from __future__ import annotations

from app.extensions import db


class PortalAuditLog(db.Model):
    """One row per successful portal-driven OP mutation."""

    __tablename__ = 'portal_audit_log'

    # Action enum values — pinned at the class level so typos at the
    # call site are caught by Python (not silently inserted as a
    # misspelled string). Tests pin these as part of the contract.
    ACTION_STATUS_CHANGE = 'status_change'
    ACTION_REORDER = 'reorder'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey('user.id'), nullable=True,
    )
    client_id = db.Column(
        db.Integer, db.ForeignKey('client.id'), nullable=True,
    )
    op_project_id = db.Column(db.Integer, nullable=True)
    op_work_package_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(32), nullable=False)
    # before_value / after_value are free-form strings: status names
    # for status_change, "1"/"2"/etc. for reorder. Kept as strings (not
    # JSON) because each action has a known simple shape and string
    # columns are cheaper to index if we ever need a value lookup.
    before_value = db.Column(db.String(255), nullable=True)
    after_value = db.Column(db.String(255), nullable=True)
    # OP's response code + an optional error message (e.g. from a 409).
    # Always populated — even 200s get 200 here so a "what did OP
    # respond with" query is one column.
    op_response_code = db.Column(db.Integer, nullable=True)
    op_response_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime, server_default=db.func.now(), nullable=False,
    )

    __table_args__ = (
        db.Index('ix_portal_audit_log_op_wp', 'op_work_package_id'),
        db.Index('ix_portal_audit_log_client', 'client_id'),
        db.Index('ix_portal_audit_log_created_at', 'created_at'),
    )

    def __repr__(self) -> str:
        return (
            f'<PortalAuditLog {self.id} action={self.action!r} '
            f'wp={self.op_work_package_id} by user={self.user_id}>'
        )
