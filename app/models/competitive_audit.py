"""Competitive Audit submission model.

A competitive audit is a client-driven intake: the user captures
identifying info for their own org (client_name) plus 0-4 competitors
(each with optional brand name, mandatory home URL, and a 4-channel
toggle for which social surfaces the downstream back-end should
include).

R1 ships the data capture + history + edit/fork flows only. The
status column exists for R2 (back-end processing pipeline) but the UI
does not flip it; submissions land as 'submitted' and stay there.

Design notes:

  - form_data is JSON. Empty competitor sub-cards are stored as ``None``,
    not as empty dicts — keeps the shape predictable for the downstream
    pipeline.
  - forked_from_id lets R2 render "this audit was duplicated from <id>"
    and lets the back-end dedupe downstream. Nullable + indexed so the
    history-list query (filter_by forked_from_id) stays cheap.
  - The composite (client_id, created_at) index serves the history
    list (``ORDER BY created_at DESC``) per-client.
"""

from app.extensions import db


class CompetitiveAuditSubmission(db.Model):
    """A captured competitive-audit request for a client.

    Belongs to exactly one :class:`~app.models.client.Client` (the org
    that submitted it). The author is the user who pressed Save; an
    admin can also submit on behalf of a client via the admin path
    (out of scope for R1).
    """

    __tablename__ = 'competitive_audit_submission'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(
        db.Integer,
        db.ForeignKey('client.id'),
        nullable=False,
    )
    author_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False,
    )
    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        onupdate=db.func.now(),
        nullable=False,
    )
    status = db.Column(
        db.String(32),
        nullable=False,
        default='submitted',
    )
    form_data = db.Column(db.JSON, nullable=False)
    forked_from_id = db.Column(
        db.Integer,
        db.ForeignKey('competitive_audit_submission.id'),
        nullable=True,
    )

    # Relationships
    client = db.relationship('Client', backref='competitive_audits')
    author = db.relationship('User', backref='competitive_audits')
    forked_from = db.relationship(
        'CompetitiveAuditSubmission',
        remote_side='CompetitiveAuditSubmission.id',
        backref='forks',
    )

    # Status constants. R1 UI never transitions out of 'submitted';
    # R2 will add 'processing' / 'complete' flows.
    STATUS_SUBMITTED = 'submitted'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETE = 'complete'
    STATUSES = (STATUS_SUBMITTED, STATUS_PROCESSING, STATUS_COMPLETE)

    # Composite index serves the history-list query path
    # (filter by client_id, ORDER BY created_at DESC) and the
    # fork-graph lookup (filter by forked_from_id).
    __table_args__ = (
        db.Index(
            'ix_competitive_audit_submission_client_created',
            'client_id',
            'created_at',
        ),
        db.Index(
            'ix_competitive_audit_submission_forked_from',
            'forked_from_id',
        ),
    )

    @property
    def status_chip_class(self):
        """CSS chip class keyed off the status string.

        Centralised here so the template stays markup-clean and so
        adding a new status only touches this property + the STATUSES
        tuple.
        """
        return {
            self.STATUS_SUBMITTED: 'status-chip--neutral',
            self.STATUS_PROCESSING: 'status-chip--accent',
            self.STATUS_COMPLETE: 'status-chip--success',
        }.get(self.status, 'status-chip--neutral')

    def __repr__(self):
        return (
            f'<CompetitiveAuditSubmission {self.id} '
            f'client={self.client_id} status={self.status}>'
        )
