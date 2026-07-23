"""DrifterBot audit request — portal submission for competitive audits."""

import json

from app.extensions import db


class AuditRequest(db.Model):
    """A portal-submitted request for DrifterBot to run a competitive audit.

    Submitted from the Drift & Anchor portal at
    ``/p/drift-and-anchor/request-audit/`` and picked up by the
    DrifterBot worker (see ``agents/drifterbot/worker.py`` in the
    brandsight repo). Lifecycle states move
    ``pending -> running -> completed`` (or ``failed``).

    Audit-target config is stored as JSON blobs (``_json`` columns)
    rather than relational rows so the schema stays flat for the
    single-client D&A soft-launch. If other clients adopt the same
    flow, promote to proper relational tables at that point — the
    JSON shape is the contract the worker expects.
    """

    __tablename__ = 'audit_request'

    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    ALL_STATUSES = (STATUS_PENDING, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED)

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    requested_at = db.Column(
        db.DateTime, server_default=db.func.now(), nullable=False,
    )

    # Audit-target config
    client_name = db.Column(db.String(255), nullable=False)
    client_category = db.Column(db.String(255), nullable=False)
    competitor_list_json = db.Column(db.Text, nullable=False)
    audience_list_json = db.Column(db.Text, nullable=False)
    positioning_inputs_json = db.Column(db.Text, nullable=True)
    social_scans_json = db.Column(db.Text, nullable=False)
    context_drive_links_json = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Lifecycle
    status = db.Column(db.String(32), nullable=False, default='pending')
    audit_id = db.Column(db.String(32), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime, server_default=db.func.now(), onupdate=db.func.now(),
    )

    # Relationships
    client = db.relationship('Client', back_populates='audit_requests')
    requested_by = db.relationship('User')

    # --- JSON blob deserializers ----------------------------------------
    # Kept as @property helpers (no caching) — the data is small and
    # these are only hit on the form's "recent requests" list and the
    # worker pickup path. If a future page needs to enumerate hundreds
    # of rows, switch to a JSON column type at the DB level.

    @property
    def competitor_list(self):
        return json.loads(self.competitor_list_json or '[]')

    @property
    def audience_list(self):
        return json.loads(self.audience_list_json or '[]')

    @property
    def social_scans(self):
        return json.loads(self.social_scans_json or '[]')

    @property
    def positioning_inputs(self):
        return json.loads(self.positioning_inputs_json or '{}')

    @property
    def context_drive_links(self):
        return json.loads(self.context_drive_links_json or '[]')

    def __repr__(self):
        return f'<AuditRequest {self.id} client={self.client_id} status={self.status}>'
