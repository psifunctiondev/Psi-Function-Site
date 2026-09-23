"""Portal-side helper for the OpenProject integration.

A thin layer over :mod:`app.services.openproject` that adds the portal's
specific read patterns:

* Walking a client's master + direct-child OpenProject projects.
* Status distributions (sum of story points bucketed by status name) for
  a project — used by the dashboard card, the project-summary
  Progress tab, and the daily snapshot cron.

This module is intentionally stateless and side-effect-free. The 60s
read cache lives in :mod:`app.services.openproject_cache` (commit 5);
this layer just reads through it.

Field lookups use the canonical field names from
``status-details-op-field-mapping.md``:

* ``customField4`` — methodos_sequence (sort key on the kanban / backlog)
* ``customField6`` — methodos_epic_number
* ``customField7`` — methodos_story_number
* ``storyPoints`` — built-in OP field (no customField id needed)
"""

from __future__ import annotations

import logging
from typing import Iterable

from app.services.openproject import (
    KANBAN_STATUS_BOTTOM,
    KANBAN_STATUS_TOP,
    STATUS_ORDER,
    OpenProjectClient,
    OpenProjectError,
)

logger = logging.getLogger(__name__)

# Status names that count as "open" (i.e. not yet shipped / archived)
# for the Backlog tab. Anything else is excluded from the prioritized
# list. This intentionally mirrors the kanban bottom-row + Rejected;
# terminal stories live outside the active backlog.
OPEN_STATUSES = set(KANBAN_STATUS_TOP) | {"Blocked", "Rejected"}

# Status names that count as "done" for %-complete math.
DONE_STATUSES = {"Deployed", "Completed"}


# --------------------------------------------------------------------------- #
# Project walks
# --------------------------------------------------------------------------- #
def get_client_projects(
    client,
    op_client: OpenProjectClient,
) -> list[dict]:
    """Return the master + direct-child OpenProject projects for a client.

    Returns ``[]`` if the client has no ``openproject_master_project_id``
    set (still under ops wiring). On OpenProject errors (auth, 404,
    transport) the function logs and returns ``[master]`` with whatever
    data we managed to read, or ``[]`` if even the master fetch failed
    — we never raise into the dashboard render path; the partial shows
    an inline error message instead.
    """
    master_id = getattr(client, 'openproject_master_project_id', None)
    if master_id is None:
        return []

    projects: list[dict] = []
    try:
        master = op_client.get_project(master_id)
    except OpenProjectError as exc:
        logger.warning(
            'OP master fetch failed for client %s (master_id=%s): %s',
            client.slug, master_id, exc,
        )
        return []

    projects.append(_with_role(master, role='master'))

    try:
        children = op_client.get_child_projects(master_id)
    except OpenProjectError as exc:
        logger.warning(
            'OP child fetch failed for client %s (master_id=%s): %s',
            client.slug, master_id, exc,
        )
        return projects

    for child in children:
        projects.append(_with_role(child, role='child'))
    return projects


def _with_role(project: dict, *, role: str) -> dict:
    """Return a shallow-copied project dict tagged with a display role.

    ``master`` rows render as the top-level client project;
    ``child`` rows are direct sub-projects. We attach the role to the
    dict so the template can distinguish without re-fetching.
    """
    out = dict(project)
    out['portal_role'] = role
    return out


# --------------------------------------------------------------------------- #
# Status distributions — used by Progress chart + Backlog tab
# --------------------------------------------------------------------------- #
def status_distribution(work_packages: Iterable[dict]) -> dict[str, int]:
    """Return ``{status_name: story_points_sum}`` for the given work packages.

    ``work_packages`` are the raw OP payload rows (the result of
    :meth:`OpenProjectClient.get_work_packages`). Stories without a
    ``storyPoints`` value contribute 0; stories without a status land
    under ``"Unknown"`` so they show up rather than vanish.

    Story points live on the ``storyPoints`` top-level field on the WP
    payload (a built-in OP field, no customField id needed). Status
    names come from ``_links.status.title``.
    """
    bucket: dict[str, int] = {}
    for wp in work_packages:
        sp = wp.get('storyPoints') or 0
        try:
            sp = int(sp)
        except (TypeError, ValueError):
            sp = 0
        status = _status_name(wp) or 'Unknown'
        bucket[status] = bucket.get(status, 0) + sp
    return bucket


def count_by_status(work_packages: Iterable[dict]) -> dict[str, int]:
    """Return ``{status_name: count}`` for the given work packages."""
    bucket: dict[str, int] = {}
    for wp in work_packages:
        status = _status_name(wp) or 'Unknown'
        bucket[status] = bucket.get(status, 0) + 1
    return bucket


def _status_name(wp: dict) -> str | None:
    links = wp.get('_links') or {}
    status_link = links.get('status') or {}
    return status_link.get('title')


# --------------------------------------------------------------------------- #
# Ordered projections — kanban + backlog both consume these
# --------------------------------------------------------------------------- #
def order_statuses(names: Iterable[str]) -> list[str]:
    """Return the names sorted by :data:`STATUS_ORDER`.

    Names not in the canonical order (e.g. extra statuses the OP
    instance has that we don't list) are appended in input order at the
    end so they don't disappear.
    """
    rank = {n: i for i, n in enumerate(STATUS_ORDER)}
    head = sorted([n for n in names if n in rank], key=lambda n: rank[n])
    tail = [n for n in names if n not in rank]
    return head + tail


def percent_complete(distribution: dict[str, int]) -> int | None:
    """Return an int percent (0..100) of story-point work that is done.

    Returns ``None`` when the distribution is empty (no work packages) —
    the template renders "—" instead of "0%" so an empty board doesn't
    look accidentally-finished.
    """
    total = sum(distribution.values())
    if total <= 0:
        return None
    done = sum(sp for status, sp in distribution.items() if status in DONE_STATUSES)
    return round(done * 100 / total)


def is_open_status(status_name: str | None) -> bool:
    """Whether a work package's status counts as part of the active backlog."""
    return bool(status_name) and status_name in OPEN_STATUSES
