"""Unit tests for the portal-side OpenProject helper module.

``app/services/openproject_portal.py`` is the thin layer between the raw
``OpenProjectClient`` and the portal's render paths — it adds the
domain-specific patterns the routes need:

* Walking a client's master + direct-child projects (graceful fallback
  on OP errors so the dashboard still renders).
* Status distributions (story-point sums per status) for the Progress
  chart and snapshot cron.
* Count by status for the kanban column headers.
* Ordering statuses by the canonical ``STATUS_ORDER`` (with unknown
  statuses appended so they don't disappear).
* Percent-complete math for the dashboard card.
* The "is this status open?" check for the Backlog tab.

Tests are pure functions over raw OP payload dicts — no HTTP, no
database, no Flask app. The render-path integration is covered by the
route tests in ``tests/test_portal_openproject.py`` (commit 3b).
"""

from __future__ import annotations

from unittest import mock

import pytest

from app.services.openproject import (
    KANBAN_STATUS_BOTTOM,
    KANBAN_STATUS_TOP,
    STATUS_ORDER,
    OpenProjectNotFound,
)
from app.services.openproject import OpenProjectClient, OpenProjectError
from app.services.openproject_portal import (
    OPEN_STATUSES,
    DONE_STATUSES,
    count_by_status,
    get_client_projects,
    is_open_status,
    order_statuses,
    percent_complete,
    status_distribution,
)


# --------------------------------------------------------------------------- #
# Fixtures + helpers
# --------------------------------------------------------------------------- #
def _wp(status: str, story_points: int | None = None) -> dict:
    """Build a minimal work-package payload shape (the only fields the
    portal helpers read)."""
    return {
        "id": 1,
        "subject": f"WP in {status}",
        "storyPoints": story_points,
        "_links": {
            "status": {"href": f"/api/v3/statuses/{status}", "title": status},
        },
    }


def _project(pid: int, name: str) -> dict:
    """Minimal project payload (master or child shape from OP)."""
    return {
        "id": pid,
        "name": name,
        "_links": {"self": {"href": f"/api/v3/projects/{pid}"}},
    }


class _StubClient:
    """Bare-minimum stand-in for OpenProjectClient.

    Lets the test set ``master`` and ``children`` payloads and assert on
    which calls ``get_client_projects`` made. Raises if a method is
    called that the test didn't stub — easier to spot over-calls than
    using MagicMock defaults.
    """

    def __init__(self, master=None, children=None, master_error=None,
                 children_error=None):
        self.master = master
        self.children = children or []
        self.master_error = master_error
        self.children_error = children_error
        self.master_calls = 0
        self.children_calls = 0

    def get_project(self, pid):
        self.master_calls += 1
        if self.master_error is not None:
            raise self.master_error
        return self.master

    def get_child_projects(self, parent_id):
        self.children_calls += 1
        if self.children_error is not None:
            raise self.children_error
        return self.children


# --------------------------------------------------------------------------- #
# get_client_projects
# --------------------------------------------------------------------------- #
class _StubClientRow:
    """Mimic a Client row enough for ``getattr(client,
    'openproject_master_project_id', None)`` — the helper uses getattr
    rather than a typed accessor so it works with the SQLAlchemy model
    AND with test doubles.
    """
    def __init__(self, slug='test-client', master_id=None):
        self.slug = slug
        self.openproject_master_project_id = master_id


def test_get_client_projects_returns_empty_when_no_master_id():
    """If the Client row has no master project ID, return [] — no OP call."""
    client_row = _StubClientRow(master_id=None)
    stub = _StubClient()
    assert get_client_projects(client_row, stub) == []
    assert stub.master_calls == 0
    assert stub.children_calls == 0


def test_get_client_projects_returns_master_and_children():
    """Master + direct children, each tagged with their portal role."""
    client_row = _StubClientRow(master_id=100)
    master = _project(100, "Acme Master")
    children = [_project(101, "Build"), _project(102, "Marketing")]
    stub = _StubClient(master=master, children=children)

    projects = get_client_projects(client_row, stub)

    assert [p["id"] for p in projects] == [100, 101, 102]
    assert [p["portal_role"] for p in projects] == ["master", "child", "child"]
    assert stub.master_calls == 1
    assert stub.children_calls == 1


def test_get_client_projects_returns_master_only_when_children_fails():
    """A 404 on the children endpoint must NOT swallow the master — the
    dashboard should still show the master row, just without children."""
    client_row = _StubClientRow(master_id=100)
    master = _project(100, "Acme Master")
    stub = _StubClient(
        master=master,
        children_error=OpenProjectNotFound("missing"),
    )
    projects = get_client_projects(client_row, stub)
    assert len(projects) == 1
    assert projects[0]["id"] == 100
    assert projects[0]["portal_role"] == "master"


def test_get_client_projects_returns_empty_when_master_fails():
    """A 404 on the master endpoint means the whole client has no OP
    data — return [] so the dashboard renders the empty state, not a
    half-broken row."""
    client_row = _StubClientRow(master_id=100)
    stub = _StubClient(master_error=OpenProjectNotFound("gone"))
    assert get_client_projects(client_row, stub) == []


# --------------------------------------------------------------------------- #
# status_distribution
# --------------------------------------------------------------------------- #
def test_status_distribution_buckets_story_points_by_status():
    """SP per status, summed."""
    wps = [
        _wp("New", 3),
        _wp("New", 5),
        _wp("In progress", 8),
        _wp("Completed", 2),
    ]
    dist = status_distribution(wps)
    assert dist == {"New": 8, "In progress": 8, "Completed": 2}


def test_status_distribution_treats_missing_sp_as_zero():
    """A WP without storyPoints must not raise or skew the bucket — SP=0."""
    wps = [_wp("New", None), _wp("New", 3)]
    assert status_distribution(wps) == {"New": 3}


def test_status_distribution_handles_unparseable_sp_gracefully():
    """A WP with a non-int storyPoints (e.g. a stray string) must not
    raise into the dashboard render path."""
    wps = [_wp("New", "abc"), _wp("New", 4)]
    assert status_distribution(wps) == {"New": 4}


def test_status_distribution_groups_statusless_wps_under_unknown():
    """A WP with no status link still appears (under 'Unknown') rather
    than silently disappearing."""
    bare = {"id": 1, "subject": "orphan", "storyPoints": 2, "_links": {}}
    assert status_distribution([bare]) == {"Unknown": 2}


# --------------------------------------------------------------------------- #
# count_by_status
# --------------------------------------------------------------------------- #
def test_count_by_status_counts_per_status():
    """WP count (not SP) per status."""
    wps = [
        _wp("New"), _wp("New"), _wp("New"),
        _wp("In progress"), _wp("Completed"),
    ]
    assert count_by_status(wps) == {"New": 3, "In progress": 1, "Completed": 1}


def test_count_by_status_empty_when_no_wps():
    assert count_by_status([]) == {}


# --------------------------------------------------------------------------- #
# order_statuses
# --------------------------------------------------------------------------- #
def test_order_statuses_sorts_by_canonical_order():
    """Input in arbitrary order comes out in STATUS_ORDER sequence."""
    names = ["Completed", "New", "In progress", "Ready"]
    assert order_statuses(names) == ["New", "Ready", "In progress", "Completed"]


def test_order_statuses_appends_unknown_statuses_at_end():
    """A status present in OP but not in STATUS_ORDER (e.g. a custom
    workflow state) must not vanish — it gets appended in input order."""
    names = ["Custom A", "New", "Custom B", "Ready"]
    assert order_statuses(names) == ["New", "Ready", "Custom A", "Custom B"]


def test_order_statuses_handles_empty_input():
    assert order_statuses([]) == []


# --------------------------------------------------------------------------- #
# percent_complete
# --------------------------------------------------------------------------- #
def test_percent_complete_sums_done_statuses_over_total():
    """Done SP / total SP, rounded to nearest int."""
    dist = {"New": 10, "Completed": 30, "Deployed": 60}
    assert percent_complete(dist) == 90  # 90 of 100


def test_percent_complete_returns_none_for_empty_distribution():
    """Empty board shouldn't render '0%' (would look accidentally
    finished). Returns None so the template renders '—'."""
    assert percent_complete({}) is None


def test_percent_complete_returns_none_for_zero_total():
    """All-zero distribution (no SP anywhere) also returns None."""
    assert percent_complete({"New": 0, "Completed": 0}) is None


def test_percent_complete_uses_done_statuses_constant():
    """Pin: DONE_STATUSES drives the math. If someone renames the
    statuses in OP and updates DONE_STATUSES, this test reflects that."""
    # Sanity check the constant — guards against an accidental rename.
    assert DONE_STATUSES == {"Deployed", "Completed"}


# --------------------------------------------------------------------------- #
# is_open_status
# --------------------------------------------------------------------------- #
def test_open_statuses_constant_matches_kanban_top_plus_blocked_rejected():
    """The Backlog tab excludes terminal + deployed stories. The
    open-statuses set is the kanban top-row (active cycle) plus
    Blocked + Rejected (stuck but not terminal). Pin the constant so
    an accidental edit is loud."""
    assert OPEN_STATUSES == set(KANBAN_STATUS_TOP) | {"Blocked", "Rejected"}


@pytest.mark.parametrize("status", [
    "New", "Ready", "In progress", "In testing",
    "Blocked", "Rejected",
])
def test_is_open_status_true_for_active_statuses(status):
    """Active-cycle + stuck statuses are part of the backlog."""
    assert is_open_status(status) is True


@pytest.mark.parametrize("status", [
    "Completed", "Deployed",
])
def test_is_open_status_false_for_terminal_statuses(status):
    """Terminal statuses (Completed, Deployed) are not backlog."""
    assert is_open_status(status) is False


def test_is_open_status_false_for_none_and_empty_string():
    """Defensive: None and '' are NOT open (would otherwise silently
    include WPs whose status link couldn't be resolved)."""
    assert is_open_status(None) is False
    assert is_open_status("") is False


# --------------------------------------------------------------------------- #
# STATUS_ORDER cross-checks
# --------------------------------------------------------------------------- #
def test_status_order_contains_all_top_and_bottom_statuses():
    """The two kanban rows (TOP + BOTTOM) partition STATUS_ORDER — every
    entry must appear in exactly one of them."""
    partitioned = set(KANBAN_STATUS_TOP) | set(KANBAN_STATUS_BOTTOM)
    assert set(STATUS_ORDER) == partitioned
