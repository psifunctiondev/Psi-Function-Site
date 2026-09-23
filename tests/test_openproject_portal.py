"""Unit tests for the OpenProject portal helper.

Covers:

* ``get_client_projects`` — returns master + children when master is
  set; ``[]`` when master_id is None; degrades gracefully on OP errors
  (no exception bubbles into the render path).
* ``status_distribution`` — sums ``storyPoints`` per status name.
* ``count_by_status`` — counts work packages per status name.
* ``order_statuses`` — sorts names by :data:`STATUS_ORDER`, preserves
  unknown names at the tail.
* ``percent_complete`` — returns int 0..100 for known statuses; ``None``
  when the distribution is empty.
* ``is_open_status`` — true for kanban-top + Blocked + Rejected.

All tests are method-level — no HTTP is touched, no fixtures beyond
stock ones.
"""

from __future__ import annotations

from unittest import mock

import pytest

from app.services.openproject import (
    KANBAN_STATUS_BOTTOM,
    KANBAN_STATUS_TOP,
    STATUS_ORDER,
    OpenProjectAuthError,
)
from app.services.openproject_portal import (
    count_by_status,
    get_client_projects,
    is_open_status,
    order_statuses,
    percent_complete,
    status_distribution,
)


# --------------------------------------------------------------------------- #
# Fixtures — minimal Client row + OpenProjectClient stub
# --------------------------------------------------------------------------- #
class _StubClient:
    """Just enough surface for ``get_client_projects`` to call."""

    def __init__(self, master=None, children=None, *, raise_on_master=None):
        self._master = master
        self._children = children
        self._raise_on_master = raise_on_master
        self.master_calls = 0
        self.children_calls = 0

    def get_project(self, project_id):
        self.master_calls += 1
        if self._raise_on_master is not None:
            raise self._raise_on_master
        return self._master

    def get_child_projects(self, parent_id):
        self.children_calls += 1
        return self._children


class _Client:
    """Bare-bones Client stand-in: only the attribute the helper reads."""

    def __init__(self, slug='acme', master_id=42):
        self.slug = slug
        self.openproject_master_project_id = master_id


def _wp(status_name, sp=None, wp_id=1):
    """Build a minimal work-package row.

    ``sp`` of ``None`` means the WP has no ``storyPoints`` set (the field
    is nullable on the OP side). Default ``sp=5`` keeps tests terse.
    """
    return {
        "id": wp_id,
        "storyPoints": sp if sp is not None else None,
        "_links": {"status": {"title": status_name}},
    }


# --------------------------------------------------------------------------- #
# get_client_projects
# --------------------------------------------------------------------------- #
class TestGetClientProjects:

    def test_returns_empty_when_no_master_configured(self):
        client = _Client(master_id=None)
        op = _StubClient()
        assert get_client_projects(client, op) == []
        assert op.master_calls == 0  # don't even hit OP

    def test_returns_master_and_children(self):
        client = _Client(master_id=42)
        master = {"id": 42, "name": "Master"}
        children = [
            {"id": 43, "name": "Child A"},
            {"id": 44, "name": "Child B"},
        ]
        op = _StubClient(master=master, children=children)
        out = get_client_projects(client, op)
        assert len(out) == 3
        assert out[0]["portal_role"] == "master"
        assert out[0]["name"] == "Master"
        assert out[1]["portal_role"] == "child"
        assert out[1]["name"] == "Child A"
        assert out[2]["portal_role"] == "child"
        assert out[2]["name"] == "Child B"

    def test_master_only_when_no_children(self):
        client = _Client(master_id=42)
        op = _StubClient(master={"id": 42, "name": "Master"}, children=[])
        out = get_client_projects(client, op)
        assert len(out) == 1
        assert out[0]["portal_role"] == "master"

    def test_returns_master_only_when_children_fetch_fails(self):
        """If master succeeds but children fails (e.g. transient OP 5xx),
        we still return the master — never an empty list when we have
        at least one good row. The dashboard partial can show 'master
        only' with an inline warning if it wants.
        """
        client = _Client(master_id=42)
        op = mock.MagicMock()
        op.get_project.return_value = {"id": 42, "name": "Master"}
        op.get_child_projects.side_effect = OpenProjectAuthError("nope")
        out = get_client_projects(client, op)
        assert len(out) == 1
        assert out[0]["portal_role"] == "master"

    def test_returns_empty_when_master_fetch_fails(self):
        """If even the master fails (auth, 404, transport), return []
        rather than raise — the render path handles empty gracefully.
        """
        client = _Client(master_id=42)
        op = _StubClient(raise_on_master=OpenProjectAuthError("nope"))
        assert get_client_projects(client, op) == []


# --------------------------------------------------------------------------- #
# status_distribution + count_by_status
# --------------------------------------------------------------------------- #
class TestStatusDistribution:

    def test_sums_story_points_by_status_name(self):
        wps = [
            _wp("New", sp=3),
            _wp("New", sp=5),
            _wp("In progress", sp=8),
            _wp("Completed", sp=2),
        ]
        assert status_distribution(wps) == {
            "New": 8,
            "In progress": 8,
            "Completed": 2,
        }

    def test_treats_null_story_points_as_zero(self):
        """Stories without storyPoints still count under their status,
        with 0 SP contribution — they show up in the distribution rather
        than disappearing.
        """
        wps = [
            _wp("New", sp=None),
            _wp("New", sp=5),
        ]
        assert status_distribution(wps) == {"New": 5}

    def test_returns_unknown_bucket_when_no_status_link(self):
        """Defensive: a WP without _links.status lands under 'Unknown'
        so it doesn't get silently dropped from the Progress chart.
        """
        wps = [{"id": 1, "storyPoints": 3, "_links": {}}]
        assert status_distribution(wps) == {"Unknown": 3}

    def test_empty_input_returns_empty_dict(self):
        assert status_distribution([]) == {}

    def test_count_by_status_returns_counts_not_points(self):
        wps = [
            _wp("New", sp=3),
            _wp("New", sp=5),
            _wp("Completed", sp=2),
        ]
        assert count_by_status(wps) == {"New": 2, "Completed": 1}


# --------------------------------------------------------------------------- #
# order_statuses
# --------------------------------------------------------------------------- #
class TestOrderStatuses:

    def test_orders_by_status_order(self):
        names = ["Completed", "New", "In progress"]
        assert order_statuses(names) == ["New", "In progress", "Completed"]

    def test_appends_unknown_names_at_tail(self):
        """Statuses the OP instance has that we don't list must still
        appear — appended in input order at the end.
        """
        names = ["Custom", "New", "ZZZ-Internal", "Ready"]
        out = order_statuses(names)
        # Known names come first in canonical order.
        assert out[:2] == ["New", "Ready"]
        # Unknowns appended in input order.
        assert out[2:] == ["Custom", "ZZZ-Internal"]

    def test_empty_input(self):
        assert order_statuses([]) == []

    def test_full_canonical_order_round_trip(self):
        assert order_statuses(STATUS_ORDER) == list(STATUS_ORDER)


# --------------------------------------------------------------------------- #
# percent_complete
# --------------------------------------------------------------------------- #
class TestPercentComplete:

    def test_none_for_empty_distribution(self):
        """Empty board must NOT show as 0% — None renders as '—'."""
        assert percent_complete({}) is None

    def test_zero_percent_when_only_unknown_statuses(self):
        """WPs with no status bucket land under 'Unknown'. They're
        counted in the total but contribute nothing to 'done', so the
        result is 0%. Not None — the distribution isn't empty.
        """
        assert percent_complete({"Unknown": 5}) == 0

    def test_zero_percent_when_all_in_open_states(self):
        assert percent_complete({"New": 5, "In progress": 3}) == 0

    def test_full_percent_when_all_done(self):
        assert percent_complete({"Completed": 5, "Deployed": 5}) == 100

    def test_partial_percent_rounds_to_int(self):
        # 3 done of 10 total = 30
        assert percent_complete({
            "Completed": 3,
            "New": 4,
            "In progress": 3,
        }) == 30

    def test_treats_only_completed_and_deployed_as_done(self):
        """Custom OP statuses named 'Done' / 'Shipped' should NOT count
        until the canonical mapping is updated — until then, only the
        two wireframe-named terminal statuses count.
        """
        # 'Shipped' has SP but isn't in DONE_STATUSES — 0% complete.
        assert percent_complete({"Shipped": 10}) == 0


# --------------------------------------------------------------------------- #
# is_open_status
# --------------------------------------------------------------------------- #
class TestIsOpenStatus:

    @pytest.mark.parametrize("name", list(KANBAN_STATUS_TOP) + ["Blocked", "Rejected"])
    def test_open_statuses(self, name):
        assert is_open_status(name) is True

    @pytest.mark.parametrize("name", ["Deployed", "Completed", "Unknown", "", None])
    def test_closed_or_invalid_statuses(self, name):
        assert is_open_status(name) is False

    def test_does_not_confuse_with_kanban_bottom_closed(self):
        """Done statuses (Deployed, Completed) are NOT 'open' for backlog
        purposes — they live on the kanban bottom row but don't show up
        in the prioritized backlog list.
        """
        assert is_open_status("Deployed") is False
        assert is_open_status("Completed") is False
