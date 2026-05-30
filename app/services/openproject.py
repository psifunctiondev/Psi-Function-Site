"""OpenProject API v3 client.

A thin, dependency-free wrapper over the OpenProject REST API (v3) used by the
Psi Function client portal. Uses ``urllib`` from the standard library so no new
HTTP dependency is introduced.

All network I/O funnels through :meth:`OpenProjectClient._request`, which is the
single seam tests mock. Higher-level methods stay pure request-shaping +
response-parsing logic.

Error mapping (see :func:`_raise_for_status`):
    * 401 / 403  -> :class:`OpenProjectAuthError`
    * 404        -> :class:`OpenProjectNotFound`
    * 409        -> :class:`OpenProjectConcurrencyError`
    * 422        -> :class:`OpenProjectValidationError`
    * other 4xx/5xx -> :class:`OpenProjectError`
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

__all__ = [
    "OpenProjectClient",
    "OpenProjectError",
    "OpenProjectAuthError",
    "OpenProjectNotFound",
    "OpenProjectConcurrencyError",
    "OpenProjectValidationError",
    "STATUS_ORDER",
]

# Canonical left-to-right status ordering for the Status kanban (Phase 1).
# Any statuses present in the instance but not listed here are appended in
# the order the API returns them. See spec "Status & column ordering".
STATUS_ORDER = ["New", "Ready", "In progress", "Completed", "Deployed"]

# Pagination safety cap: 10 pages * 100 = 1000 work packages. Plenty for now.
_MAX_PAGES = 10
_DEFAULT_PAGE_SIZE = 100
_DEFAULT_TIMEOUT = 30


class OpenProjectError(Exception):
    """Base class for all OpenProject client errors.

    ``status`` is the HTTP status code (or ``None`` for transport failures).
    ``body`` is the parsed JSON error body when available, else ``None``.
    """

    def __init__(self, message: str, *, status: int | None = None, body: dict | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


class OpenProjectAuthError(OpenProjectError):
    """401 / 403 — bad or insufficient credentials."""


class OpenProjectNotFound(OpenProjectError):
    """404 — resource does not exist."""


class OpenProjectConcurrencyError(OpenProjectError):
    """409 — lockVersion conflict; someone else edited the resource."""


class OpenProjectValidationError(OpenProjectError):
    """422 — request body failed OpenProject validation."""


def _raise_for_status(status: int, body: dict | None, *, url: str) -> None:
    """Map a non-2xx HTTP status to the appropriate exception."""
    if 200 <= status < 300:
        return
    msg = _extract_message(body) or f"OpenProject request to {url} failed"
    if status in (401, 403):
        raise OpenProjectAuthError(msg, status=status, body=body)
    if status == 404:
        raise OpenProjectNotFound(msg, status=status, body=body)
    if status == 409:
        raise OpenProjectConcurrencyError(msg, status=status, body=body)
    if status == 422:
        raise OpenProjectValidationError(msg, status=status, body=body)
    raise OpenProjectError(msg, status=status, body=body)


def _extract_message(body: dict | None) -> str | None:
    """Pull a human-readable message out of an OpenProject error body."""
    if not isinstance(body, dict):
        return None
    # OpenProject error bodies use {"_type":"Error","message":"...","_embedded":{"errors":[...]}}
    if body.get("message"):
        return str(body["message"])
    embedded = body.get("_embedded", {})
    errors = embedded.get("errors") if isinstance(embedded, dict) else None
    if isinstance(errors, list) and errors:
        msgs = [e.get("message") for e in errors if isinstance(e, dict) and e.get("message")]
        if msgs:
            return "; ".join(str(m) for m in msgs)
    return None


class OpenProjectClient:
    """Client for the OpenProject API v3.

    Parameters
    ----------
    base_url:
        Instance root, e.g. ``https://openproject.example.com:5443``. The
        ``/api/v3`` prefix is appended internally; pass the bare host root.
    api_key:
        OpenProject API key. Sent via HTTP Basic as ``apikey:<key>``.
    timeout:
        Per-request socket timeout in seconds.
    """

    def __init__(self, base_url: str, api_key: str, *, timeout: int = _DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/api/v3"
        self.api_key = api_key
        self.timeout = timeout
        token = base64.b64encode(f"apikey:{api_key}".encode()).decode()
        self._auth_header = f"Basic {token}"

    # ------------------------------------------------------------------ #
    # Transport — the single mocked seam.
    # ------------------------------------------------------------------ #
    def _request(self, method: str, path: str, *, params: dict | None = None,
                 body: dict | None = None) -> dict:
        """Perform an HTTP request against the API and return the parsed JSON.

        ``path`` is relative to ``/api/v3`` (leading slash optional).
        Raises an ``OpenProject*`` error on any non-2xx status or transport
        failure.
        """
        url = self.api_base + ("" if path.startswith("/") else "/") + path
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        data = None
        headers = {"Authorization": self._auth_header, "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                parsed = json.loads(raw) if raw else {}
                parsed_dict = parsed if isinstance(parsed, dict) else None
                _raise_for_status(resp.status, parsed_dict, url=url)
                return parsed
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            parsed = None
            if raw:
                try:
                    parsed = json.loads(raw)
                except (ValueError, json.JSONDecodeError):
                    parsed = None
            _raise_for_status(exc.code, parsed if isinstance(parsed, dict) else None, url=url)
            # _raise_for_status always raises for non-2xx; this is unreachable.
            raise OpenProjectError(f"Unexpected HTTPError {exc.code}", status=exc.code) from exc
        except urllib.error.URLError as exc:
            raise OpenProjectError(f"Transport error contacting {url}: {exc.reason}") from exc

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get_project(self, project_id: int) -> dict:
        return self._request("GET", f"/projects/{project_id}")

    def get_child_projects(self, parent_id: int) -> list[dict]:
        """Return direct child projects of ``parent_id`` (one level deep)."""
        filters = json.dumps([{"parent": {"operator": "=", "values": [str(parent_id)]}}])
        result = self._request("GET", "/projects", params={"filters": filters, "pageSize": 100})
        return _elements(result)

    def get_work_packages(
        self,
        project_id: int,
        *,
        types: list[str] | None = None,
        statuses: list[str] | None = None,
        include_terminal: bool = True,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> list[dict]:
        """Return work packages for a project, following pagination.

        ``types`` / ``statuses`` filter by name (matched against the linked
        resource title). ``include_terminal`` is accepted for caller intent;
        terminal-status filtering is applied client-side by callers that need
        it since OpenProject's terminal flag lives on the status resource.
        """
        filters: list[dict] = []
        if types:
            filters.append({"type": {"operator": "=", "values": types}})
        if statuses:
            filters.append({"status": {"operator": "=", "values": statuses}})

        collected: list[dict] = []
        offset = 1
        for _ in range(_MAX_PAGES):
            params: dict = {"offset": offset, "pageSize": page_size}
            if filters:
                params["filters"] = json.dumps(filters)
            result = self._request("GET", f"/projects/{project_id}/work_packages", params=params)
            page = _elements(result)
            collected.extend(page)
            total = result.get("total", 0)
            if offset * page_size >= total or not page:
                break
            offset += 1
        return collected

    def get_work_package(self, wp_id: int) -> dict:
        return self._request("GET", f"/work_packages/{wp_id}")

    def get_statuses(self) -> list[dict]:
        return _elements(self._request("GET", "/statuses", params={"pageSize": 100}))

    def get_priorities(self) -> list[dict]:
        return _elements(self._request("GET", "/priorities", params={"pageSize": 100}))

    def get_version(self, version_id: int) -> dict:
        return self._request("GET", f"/versions/{version_id}")

    def get_work_package_journals(self, wp_id: int) -> list[dict]:
        """Return the activity/journal entries for a work package (backfill)."""
        return _elements(self._request("GET", f"/work_packages/{wp_id}/activities",
                                       params={"pageSize": 100}))

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def update_work_package_status(self, wp_id: int, status_id: int, lock_version: int) -> dict:
        body = {
            "lockVersion": lock_version,
            "_links": {"status": {"href": f"/api/v3/statuses/{status_id}"}},
        }
        return self._request("PATCH", f"/work_packages/{wp_id}", body=body)

    def update_work_package_priority_order(
        self, wp_id: int, new_position: int, lock_version: int
    ) -> dict:
        """Reorder a work package within its project.

        NOTE: OpenProject's exact reorder mechanics are confirmed via spike at
        the top of commit 5 before this is wired to the portal. The ``position``
        field shape below is provisional and may change after that spike.
        """
        body = {"lockVersion": lock_version, "position": new_position}
        return self._request("PATCH", f"/work_packages/{wp_id}", body=body)

    def post_work_package_comment(self, wp_id: int, raw_markdown: str) -> dict:
        body = {"comment": {"raw": raw_markdown}}
        return self._request("POST", f"/work_packages/{wp_id}/activities", body=body)


def _elements(collection: dict) -> list[dict]:
    """Extract ``_embedded.elements`` from an OpenProject collection response."""
    if not isinstance(collection, dict):
        return []
    embedded = collection.get("_embedded", {})
    if not isinstance(embedded, dict):
        return []
    elements = embedded.get("elements", [])
    return elements if isinstance(elements, list) else []
