"""Unit tests for OpenProjectClient.last_completed_date_for.

Per the field-mapping spec (status-details-op-field-mapping.md §"Completed
Date Derivation"): the function queries a work package's activity feed
filtered to status-change activities for the Completed status, sorted
descending by createdAt, and returns the createdAt of the LATEST matching
activity. The "latest" semantics handles the reopen-and-reclose case (a
story that briefly hit Completed then reopened; the second Completed is
the meaningful one).

These tests are method-level (patch ``_request``) so no HTTP is touched
and no fixture work beyond a stock client is needed.
"""

from __future__ import annotations

from unittest import mock

import pytest

from app.services.openproject import OpenProjectClient

BASE_URL = "https://op.example.com:5443"
API_KEY = "test-key"


@pytest.fixture
def client() -> OpenProjectClient:
    return OpenProjectClient(BASE_URL, API_KEY)


def _activity(activity_id: int, created_at: str, new_value_href: str) -> dict:
    """Build one OpenProject activity row (status-change shape)."""
    return {
        "id": activity_id,
        "type": "WorkPackageActivity",
        "createdAt": created_at,
        "_links": {
            "newValue": {"href": new_value_href},
            "oldValue": {"href": "/api/v3/statuses/3"},
            "self": {"href": f"/api/v3/activities/{activity_id}"},
        },
    }


def test_last_completed_date_returns_first_row_created_at(client):
    """With a non-empty activity list, return createdAt of the first row."""
    rows = [
        _activity(2, "2026-09-08T14:22:00Z", "/api/v3/statuses/7"),
    ]
    fake_resp = {
        "_type": "Collection",
        "total": 1,
        "_embedded": {"elements": rows},
    }
    with mock.patch.object(
        OpenProjectClient, "_request", return_value=fake_resp,
    ) as m_req:
        result = client.last_completed_date_for(
            wp_id=42, completed_status_id=7,
        )
    assert result == "2026-09-08T14:22:00Z"
    # Verify request shape: path, filter (newValue=Completed href), sort desc, pageSize=1
    m_req.assert_called_once()
    args, kwargs = m_req.call_args
    assert args == ("GET", "/work_packages/42/activities")
    params = kwargs["params"]
    # filters must reference /api/v3/statuses/<completed_status_id>
    import json as _json
    filters = _json.loads(params["filters"])
    assert filters == [{
        "newValue": {
            "operator": "=",
            "values": ["/api/v3/statuses/7"],
        },
    }]
    # sortBy descending by createdAt
    assert params["sortBy"] == _json.dumps([["createdAt", "desc"]])
    # pageSize 1 (we only need the latest)
    assert params["pageSize"] == 1


def test_last_completed_date_returns_none_when_no_activities(client):
    """Empty activity list => None (story never reached Completed)."""
    fake_resp = {
        "_type": "Collection",
        "total": 0,
        "_embedded": {"elements": []},
    }
    with mock.patch.object(
        OpenProjectClient, "_request", return_value=fake_resp,
    ):
        result = client.last_completed_date_for(
            wp_id=99, completed_status_id=7,
        )
    assert result is None


def test_last_completed_date_uses_first_row_when_multiple(client):
    """When multiple activities match, the FIRST row (after desc sort) is the
    latest completion. Caller has already requested pageSize=1, but this
    guards against a future caller passing pageSize=N."""
    rows = [
        _activity(5, "2026-09-15T10:00:00Z", "/api/v3/statuses/7"),  # latest
        _activity(2, "2026-09-08T14:22:00Z", "/api/v3/statuses/7"),
    ]
    fake_resp = {
        "_type": "Collection",
        "total": 2,
        "_embedded": {"elements": rows},
    }
    with mock.patch.object(
        OpenProjectClient, "_request", return_value=fake_resp,
    ):
        result = client.last_completed_date_for(
            wp_id=42, completed_status_id=7,
        )
    assert result == "2026-09-15T10:00:00Z"


def test_last_completed_date_handles_missing_elements_key(client):
    """Defensive: an OP collection without ``_embedded.elements`` should
    return None, not raise."""
    fake_resp = {"_type": "Collection", "total": 0}
    with mock.patch.object(
        OpenProjectClient, "_request", return_value=fake_resp,
    ):
        result = client.last_completed_date_for(
            wp_id=42, completed_status_id=7,
        )
    assert result is None
