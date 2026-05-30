"""Unit tests for the OpenProject API v3 client.

Two layers of mocking:

* **Method-level** — patch ``OpenProjectClient._request`` to assert request
  shaping (method, path, params, body) and response parsing for each public
  method. No HTTP touched.
* **Transport-level** — patch ``urllib.request.urlopen`` to drive the real
  ``_request`` -> ``_raise_for_status`` path and verify the full error-mapping
  hierarchy (401/403/404/409/422/other/transport).
"""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
from unittest import mock

import pytest

from app.services.openproject import (
    STATUS_ORDER,
    OpenProjectAuthError,
    OpenProjectClient,
    OpenProjectConcurrencyError,
    OpenProjectError,
    OpenProjectNotFound,
    OpenProjectValidationError,
)

BASE_URL = "https://op.example.com:5443"
API_KEY = "test-key"


@pytest.fixture
def client():
    return OpenProjectClient(BASE_URL, API_KEY)


def _collection(elements, total=None):
    return {
        "_type": "Collection",
        "total": total if total is not None else len(elements),
        "_embedded": {"elements": elements},
    }


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #
def test_base_url_is_stripped_and_api_base_built():
    c = OpenProjectClient(BASE_URL + "/", API_KEY)
    assert c.base_url == BASE_URL
    assert c.api_base == BASE_URL + "/api/v3"


def test_auth_header_is_basic_apikey():
    import base64

    c = OpenProjectClient(BASE_URL, "secret")
    expected = "Basic " + base64.b64encode(b"apikey:secret").decode()
    assert c._auth_header == expected


def test_status_order_constant():
    assert STATUS_ORDER[0] == "New"
    assert STATUS_ORDER[-1] == "Deployed"


# --------------------------------------------------------------------------- #
# Read methods — request shaping + parsing (mock _request)
# --------------------------------------------------------------------------- #
def test_get_project(client):
    with mock.patch.object(client, "_request", return_value={"id": 7, "name": "Master"}) as m:
        out = client.get_project(7)
    m.assert_called_once_with("GET", "/projects/7")
    assert out["id"] == 7


def test_get_child_projects_builds_parent_filter(client):
    payload = _collection([{"id": 8}, {"id": 9}])
    with mock.patch.object(client, "_request", return_value=payload) as m:
        out = client.get_child_projects(7)
    args, kwargs = m.call_args
    assert args[0] == "GET"
    assert args[1] == "/projects"
    filters = json.loads(kwargs["params"]["filters"])
    assert filters[0]["parent"]["values"] == ["7"]
    assert [p["id"] for p in out] == [8, 9]


def test_get_work_packages_single_page(client):
    payload = _collection([{"id": 1}, {"id": 2}], total=2)
    with mock.patch.object(client, "_request", return_value=payload) as m:
        out = client.get_work_packages(7, page_size=100)
    assert len(out) == 2
    assert m.call_count == 1


def test_get_work_packages_follows_pagination(client):
    page1 = _collection([{"id": i} for i in range(100)], total=150)
    page2 = _collection([{"id": i} for i in range(100, 150)], total=150)
    with mock.patch.object(client, "_request", side_effect=[page1, page2]) as m:
        out = client.get_work_packages(7, page_size=100)
    assert len(out) == 150
    assert m.call_count == 2
    # second call uses offset=2
    assert m.call_args_list[1].kwargs["params"]["offset"] == 2


def test_get_work_packages_applies_type_and_status_filters(client):
    payload = _collection([], total=0)
    with mock.patch.object(client, "_request", return_value=payload) as m:
        client.get_work_packages(7, types=["User story"], statuses=["New"])
    filters = json.loads(m.call_args.kwargs["params"]["filters"])
    keys = {next(iter(f)) for f in filters}
    assert keys == {"type", "status"}


def test_get_work_packages_pagination_cap(client):
    # Always returns a full page claiming a huge total -> must stop at 10 pages.
    full = _collection([{"id": 0}] * 100, total=10_000)
    with mock.patch.object(client, "_request", return_value=full) as m:
        client.get_work_packages(7, page_size=100)
    assert m.call_count == 10


def test_get_work_package(client):
    with mock.patch.object(client, "_request", return_value={"id": 42}) as m:
        out = client.get_work_package(42)
    m.assert_called_once_with("GET", "/work_packages/42")
    assert out["id"] == 42


def test_get_statuses_unwraps_elements(client):
    payload = _collection([{"id": 1, "name": "New"}])
    with mock.patch.object(client, "_request", return_value=payload):
        out = client.get_statuses()
    assert out == [{"id": 1, "name": "New"}]


def test_get_priorities_unwraps_elements(client):
    payload = _collection([{"id": 1, "name": "Normal"}])
    with mock.patch.object(client, "_request", return_value=payload):
        assert client.get_priorities()[0]["name"] == "Normal"


def test_get_version(client):
    with mock.patch.object(client, "_request", return_value={"id": 3}) as m:
        client.get_version(3)
    m.assert_called_once_with("GET", "/versions/3")


def test_get_work_package_journals(client):
    payload = _collection([{"id": 1, "_type": "Activity"}])
    with mock.patch.object(client, "_request", return_value=payload) as m:
        out = client.get_work_package_journals(42)
    m.assert_called_once_with("GET", "/work_packages/42/activities", params={"pageSize": 100})
    assert len(out) == 1


# --------------------------------------------------------------------------- #
# Write methods — body shaping
# --------------------------------------------------------------------------- #
def test_update_work_package_status_body(client):
    with mock.patch.object(client, "_request", return_value={"id": 42}) as m:
        client.update_work_package_status(42, status_id=5, lock_version=3)
    args, kwargs = m.call_args
    assert args == ("PATCH", "/work_packages/42")
    body = kwargs["body"]
    assert body["lockVersion"] == 3
    assert body["_links"]["status"]["href"] == "/api/v3/statuses/5"


def test_update_work_package_priority_order_body(client):
    with mock.patch.object(client, "_request", return_value={"id": 42}) as m:
        client.update_work_package_priority_order(42, new_position=2, lock_version=4)
    body = m.call_args.kwargs["body"]
    assert body["lockVersion"] == 4
    assert body["position"] == 2


def test_post_work_package_comment_body(client):
    with mock.patch.object(client, "_request", return_value={"id": 1}) as m:
        client.post_work_package_comment(42, "Changed via Psi Function portal by a@b.com (5)")
    args, kwargs = m.call_args
    assert args == ("POST", "/work_packages/42/activities")
    assert kwargs["body"]["comment"]["raw"].startswith("Changed via Psi Function portal")


# --------------------------------------------------------------------------- #
# Transport + error mapping — drive real _request via fake urlopen
# --------------------------------------------------------------------------- #
class _FakeResponse(io.BytesIO):
    def __init__(self, status, payload):
        super().__init__(json.dumps(payload).encode() if payload is not None else b"")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _http_error(code, payload):
    body = json.dumps(payload).encode() if payload is not None else b""
    return urllib.error.HTTPError(
        url="https://op.example.com:5443/api/v3/x",
        code=code,
        msg="err",
        hdrs=email.message.Message(),
        fp=io.BytesIO(body),
    )


def test_request_success_returns_parsed_json(client):
    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(200, {"id": 99})):
        out = client._request("GET", "/projects/99")
    assert out == {"id": 99}


def test_request_success_empty_body(client):
    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(204, None)):
        out = client._request("DELETE", "/x")
    assert out == {}


def test_request_sends_auth_and_json_body(client):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["auth"] = req.headers.get("Authorization")
        captured["body"] = req.data
        return _FakeResponse(200, {"ok": True})

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client._request("PATCH", "/work_packages/1", body={"lockVersion": 2})
    assert captured["method"] == "PATCH"
    assert captured["auth"].startswith("Basic ")
    assert json.loads(captured["body"]) == {"lockVersion": 2}
    assert captured["url"].endswith("/api/v3/work_packages/1")


@pytest.mark.parametrize(
    "code,exc",
    [
        (401, OpenProjectAuthError),
        (403, OpenProjectAuthError),
        (404, OpenProjectNotFound),
        (409, OpenProjectConcurrencyError),
        (422, OpenProjectValidationError),
        (500, OpenProjectError),
        (400, OpenProjectError),
    ],
)
def test_error_mapping(client, code, exc):
    err = _http_error(code, {"_type": "Error", "message": f"boom {code}"})
    with mock.patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(exc) as ei:
            client._request("GET", "/x")
    assert ei.value.status == code
    assert "boom" in str(ei.value)


def test_validation_error_preserves_body(client):
    payload = {
        "_type": "Error",
        "message": "Multiple field errors",
        "_embedded": {"errors": [{"message": "Subject can't be blank"}]},
    }
    err = _http_error(422, payload)
    with mock.patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(OpenProjectValidationError) as ei:
            client._request("PATCH", "/work_packages/1", body={})
    assert ei.value.body == payload


def test_embedded_errors_message_extraction(client):
    payload = {
        "_type": "Error",
        "_embedded": {"errors": [{"message": "A"}, {"message": "B"}]},
    }
    err = _http_error(422, payload)
    with mock.patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(OpenProjectValidationError) as ei:
            client._request("GET", "/x")
    assert "A" in str(ei.value) and "B" in str(ei.value)


def test_transport_error_wrapped(client):
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("conn refused")):
        with pytest.raises(OpenProjectError) as ei:
            client._request("GET", "/x")
    assert ei.value.status is None
    assert "Transport error" in str(ei.value)


def test_non_2xx_in_urlopen_body_maps(client):
    # Some servers return a non-2xx status on a normal response object rather
    # than raising HTTPError; _raise_for_status must still fire.
    with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(404, {"message": "gone"})):
        with pytest.raises(OpenProjectNotFound):
            client._request("GET", "/x")
