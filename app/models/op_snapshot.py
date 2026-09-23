"""OpenProject snapshot model — daily cache of story-point distribution.

The portal's Progress tab renders a stacked bar chart over weeks of
story points, bucketed by status. Hitting OpenProject for this on every
render would be slow + costly + breach OP rate limits on busy days.
Instead the daily snapshot cron walks each active client's master
project + direct children, computes the current status distribution
(sum of ``storyPoints`` per status name), and writes one
:class:`OpProjectSnapshot` row per project per day.

The Progress tab then reads ONLY from this table — no live OP calls
on render. A backfill CLI (commit 4d) can reconstruct historical
snapshots from OP journals the first time a project is "seen" by the
cron (so an existing project doesn't render an empty chart for the
first ~8 weeks after launch).

Idempotency: the (project_op_id, snapshot_date) tuple is unique. A
re-run on the same day updates the existing row in place rather than
creating duplicates.
"""

from __future__ import annotations

from datetime import date, datetime

from app.extensions import db


class OpProjectSnapshot(db.Model):
    """A single day's story-point distribution for one OP project.

    Rows are upserted by ``(project_op_id, snapshot_date)`` — re-running
    the cron on the same day updates the existing row in place.

    ``story_points_by_status_json`` stores ``{status_name: sp_sum}``
    as JSON text so the schema doesn't need to grow when OP instances
    have custom statuses. Status names are strings (the canonical
    STATUS_ORDER list in app/services/openproject.py) so the Progress
    tab can sort them deterministically.

    ``work_package_count`` is a convenience aggregate — the chart
    doesn't render it directly today, but the dashboard card / future
    "% complete" callouts may. Captured at the same time as the
    distribution so we don't pay an extra fetch.
    """

    __tablename__ = 'op_project_snapshot'

    id = db.Column(db.Integer, primary_key=True)
    project_op_id = db.Column(db.Integer, nullable=False, index=True)
    snapshot_date = db.Column(db.Date, nullable=False, index=True)
    # {status_name: sp_sum} JSON — see module docstring
    story_points_by_status_json = db.Column(
        db.Text, nullable=False, default='{}',
    )
    work_package_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(
        db.DateTime, server_default=db.func.now(), nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        onupdate=db.func.now(),
        nullable=False,
    )

    __table_args__ = (
        db.UniqueConstraint(
            'project_op_id', 'snapshot_date',
            name='uq_op_project_snapshot_project_date',
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return (
            f'<OpProjectSnapshot project_op_id={self.project_op_id} '
            f'snapshot_date={self.snapshot_date} count={self.work_package_count}>'
        )

    @property
    def distribution(self) -> dict[str, int]:
        """Return the deserialized ``{status_name: sp_sum}`` distribution."""
        import json

        if not self.story_points_by_status_json:
            return {}
        try:
            parsed = json.loads(self.story_points_by_status_json)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @classmethod
    def for_project_on_date(
        cls, project_op_id: int, day: date,
    ) -> 'OpProjectSnapshot | None':
        """Look up the snapshot for a (project, day) pair, or None."""
        return cls.query.filter_by(
            project_op_id=project_op_id, snapshot_date=day,
        ).first()
