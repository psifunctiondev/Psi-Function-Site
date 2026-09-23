"""Daily OpenProject snapshot worker.

Walks every active Client with a non-null ``openproject_master_project_id``
and writes one :class:`OpProjectSnapshot` row per project per day,
capturing:

* ``story_points_by_status_json`` — sum of ``storyPoints`` bucketed by
  status name (built-in OP field, no customField id needed per the
  field-mapping doc).
* ``work_package_count`` — total work packages in the project.

Idempotent per day: re-running for the same ``snapshot_date`` upserts
in place via :meth:`OpProjectSnapshot.for_project_on_date`.

Backfill (``backfill_snapshots_for_project``) reconstructs snapshots
from journals the first time a project is "seen". Operators trigger
this manually — it's NOT automatic, per the April spec ("Make backfill
a separate CLI command, not automatic — so ops controls cost").
"""

from __future__ import annotations

import json
import logging
from datetime import date

from app.extensions import db
from app.models.client import Client
from app.models.op_snapshot import OpProjectSnapshot
from app.services.openproject import OpenProjectClient
from app.services.openproject_portal import (
    count_by_status,
    status_distribution,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Single-project snapshot
# --------------------------------------------------------------------------- #
def snapshot_one_project(
    op_client: OpenProjectClient,
    project_op_id: int,
    day: date,
) -> OpProjectSnapshot | None:
    """Compute and persist today's snapshot for one project.

    Returns the upserted :class:`OpProjectSnapshot` row, or ``None``
    when the project has no work packages (we still write a row with
    count=0 + empty distribution so the Progress chart shows a flat
    line at SP=0 instead of a missing data point).

    On OP error (auth / 404 / transport), logs and returns ``None``
    without raising — the cron keeps going across clients.
    """
    work_packages = op_client.get_work_packages(project_op_id)
    distribution = status_distribution(work_packages)
    count = sum(count_by_status(work_packages).values())

    snap = OpProjectSnapshot.for_project_on_date(project_op_id, day)
    if snap is None:
        snap = OpProjectSnapshot(
            project_op_id=project_op_id,
            snapshot_date=day,
        )
        db.session.add(snap)
    snap.work_package_count = count
    snap.story_points_by_status_json = json.dumps(distribution)
    db.session.commit()
    logger.info(
        'snapshotted project=%s date=%s wps=%d statuses=%s',
        project_op_id, day, count, sorted(distribution),
    )
    return snap


# --------------------------------------------------------------------------- #
# Full-cron: walk every active client with a master project wired
# --------------------------------------------------------------------------- #
def run_snapshot_for_active_clients(
    op_client: OpenProjectClient,
    *,
    day: date | None = None,
) -> dict[str, int]:
    """Snapshot master + children for every active client.

    Returns ``{client_slug: project_count}`` so the CLI can summarize
    what it just did. ``day`` defaults to ``date.today()``.

    Clients without an OP master project id are skipped silently —
    they're under wiring. Clients whose OP fetch errors are logged
    and skipped, but the loop continues for other clients.
    """
    from app.services.openproject_portal import get_client_projects

    target_day = day or date.today()
    summary: dict[str, int] = {}

    clients = Client.query.filter(
        Client.is_active.is_(True),
        Client.openproject_master_project_id.isnot(None),
    ).all()

    for client in clients:
        try:
            projects = get_client_projects(client, op_client)
        except Exception:  # noqa: BLE001 — keep going across clients
            logger.exception(
                'snapshot: project fetch failed for client %s', client.slug,
            )
            summary[client.slug] = 0
            continue

        n = 0
        for project in projects:
            pid = project.get('id')
            if not isinstance(pid, int):
                continue
            try:
                snapshot_one_project(op_client, pid, target_day)
            except Exception:  # noqa: BLE001
                logger.exception(
                    'snapshot: write failed for project=%s client=%s',
                    pid, client.slug,
                )
                continue
            n += 1
        summary[client.slug] = n

    return summary


# --------------------------------------------------------------------------- #
# Backfill — reconstruct snapshots from journals
# --------------------------------------------------------------------------- #
def backfill_snapshots_for_project(
    op_client: OpenProjectClient,
    project_op_id: int,
    *,
    weeks: int = 8,
) -> int:
    """Walk the project's recent WPs and write one snapshot per week.

    For each WP in the project, look at its journals
    (``get_work_package_journals``) and reconstruct the status the WP
    was in at each weekly boundary going back ``weeks`` weeks. Then
    bucket story points per status per boundary and upsert an
    ``OpProjectSnapshot`` for that (project, boundary_date).

    Returns the number of snapshots written. ``weeks=8`` matches the
    Progress tab's default window.

    Per the April spec this is a separate, manually-triggered CLI
    command — NOT automatic. Ops runs it the first time a project is
    "seen" so an existing project doesn't render an empty chart for
    the first 8 weeks after launch.
    """
    from datetime import timedelta

    today = date.today()
    boundaries = [today - timedelta(weeks=w) for w in range(weeks)]

    wps = op_client.get_work_packages(project_op_id)
    if not wps:
        return 0

    written = 0
    for boundary in boundaries:
        # For each WP, the status it was in at the boundary is found
        # by looking at the journals: pick the latest activity whose
        # createdAt < boundary that changed the status. If no such
        # activity exists and the WP was created before the boundary,
        # assume the WP didn't exist yet (skip).
        distribution: dict[str, int] = {}
        for wp in wps:
            wp_id = wp.get('id')
            sp = wp.get('storyPoints') or 0
            try:
                sp = int(sp)
            except (TypeError, ValueError):
                sp = 0
            if not isinstance(wp_id, int) or sp <= 0:
                continue

            status_at_boundary = _status_at_boundary(
                op_client, wp_id, boundary,
            )
            if status_at_boundary is None:
                continue
            distribution[status_at_boundary] = distribution.get(
                status_at_boundary, 0,
            ) + sp

        snap = OpProjectSnapshot.for_project_on_date(project_op_id, boundary)
        if snap is None:
            snap = OpProjectSnapshot(
                project_op_id=project_op_id, snapshot_date=boundary,
            )
            db.session.add(snap)
        snap.story_points_by_status_json = json.dumps(distribution)
        snap.work_package_count = sum(
            1 for wp in wps if (wp.get('storyPoints') or 0)
        )
        db.session.commit()
        written += 1

    return written


def _status_at_boundary(
    op_client: OpenProjectClient,
    wp_id: int,
    boundary: date,
) -> str | None:
    """Return the WP's status at ``boundary`` (latest status-change
    activity strictly before ``boundary``), or None if unknown."""
    from app.services.openproject_cache import fingerprint
    from app.services.openproject_cache import cache_get, cache_set

    # Cache key on (wp_id, boundary_iso) so we don't refetch per WP.
    fp = fingerprint(wp_id, {'boundary': boundary.isoformat()})
    cached = cache_get(wp_id, fp)
    if cached is not None:
        return cached

    journals = op_client.get_work_package_journals(wp_id)
    # Find the latest activity whose createdAt < boundary that
    # mentions a status (we look for any activity row with a status
    # _links.newValue.href / title).
    latest_status = None
    latest_dt = None
    for activity in journals:
        created_at = activity.get('createdAt', '')
        if created_at[:10] >= boundary.isoformat():
            continue
        links = activity.get('_links') or {}
        new_value = links.get('newValue') or {}
        title = new_value.get('title')
        href = new_value.get('href') or ''
        if not title or '/statuses/' not in href:
            continue
        if latest_dt is None or created_at > latest_dt:
            latest_status = title
            latest_dt = created_at

    cache_set(wp_id, fp, latest_status)
    return latest_status
