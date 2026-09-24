"""Portal-side write orchestration for OpenProject mutations.

This module owns the "every successful portal mutation does these four
things, in this order" contract for commit 5 of the OP integration:

    1. PATCH the work package via the typed ``OpenProjectClient``.
    2. POST a journal comment via the service-account token so clients
       see an audit trail in OpenProject itself.
    3. Write one row to ``PortalAuditLog`` — Psi Function's internal
       "who changed what when" record (the journal comment is the
       external one; this is the internal one).
    4. Invalidate the 60s read cache for the affected project.

Lock-version semantics: every PATCH carries ``lockVersion``; on a 409
OpenProject responds with ``OpenProjectConcurrencyError``. The helper
translates that into a structured ``WriteResult(success=False,
code='CONFLICT', message=...)`` so the route can return
``{ok: false, code: 'CONFLICT', ...}`` to the optimistic-UI JS without
catching exceptions at the route layer.

Journal-comment template (per kickoff rule #5 — exact format, no edits):

    Changed via Psi Function portal by <User.email> (<User.id>)

Cache invalidation: per the April spec, "Invalidated immediately after
any successful write for that project." We call
:meth:`cache_invalidate` after both PATCH + journal POST succeed. If
either fails we don't write the audit log either — the helper only
runs the journal + audit + invalidate trio on a fully successful PATCH.

Reorder mechanics: OpenProject's reorder API is provisional per the
commit-1 docstring on ``update_work_package_priority_order`` — the
``position`` integer is what OP interprets as the new sort position.
If OP rejects the reorder shape in production we re-spike; for v1 the
helper treats the response the same as a status change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.extensions import db
from app.models.portal_audit_log import PortalAuditLog
from app.services.openproject import (
    OpenProjectClient,
    OpenProjectConcurrencyError,
    OpenProjectError,
)
from app.services.openproject_cache import cache_invalidate
from app.services.openproject_config import (
    current_op_client,  # noqa: F401 — re-exported for test mock targets
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Status-name → status-id resolution
# --------------------------------------------------------------------------- #
def resolve_status_id(
    op_client: OpenProjectClient, status_name: str,
) -> int | None:
    """Return the OP status id for ``status_name``, or ``None`` if no match.

    Reads ``/api/v3/statuses`` (paginated) and matches by title. Returns
    ``None`` (rather than raising) when the OP instance doesn't define a
    status with that name — the route layer surfaces a 422 with a clear
    message rather than crashing.

    The fetch follows pagination — OP instances may carry more than the
    default page size. The result is not cached at this layer; the read
    cache in :mod:`app.services.openproject_cache` is invalidated after
    every write, so a re-fetch here is the safe behavior under load.
    """
    if not status_name:
        return None
    needle = status_name.strip()
    if not needle:
        return None

    statuses = op_client.get_statuses()
    for entry in statuses:
        if not isinstance(entry, dict):
            continue
        title = entry.get('name') or entry.get('title')
        if title == needle:
            sid = entry.get('id')
            if isinstance(sid, int):
                return sid
    return None


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass
class WriteResult:
    """Outcome of a portal-driven OP mutation.

    ``success=False`` results carry an error ``code`` the JS can branch
    on ('CONFLICT', 'NOT_FOUND', 'VALIDATION', 'CONFIG', 'TRANSPORT',
    'UNKNOWN') plus a human-readable ``message`` and the raw OP ``status``
    for ops debugging.
    """

    success: bool
    work_package: dict | None = None
    code: str | None = None
    message: str | None = None
    status: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render for the JSON the optimistic-UI JS consumes.

        Always returns ``ok`` (the boolean the JS keys off) and the
        WP payload on success. On failure, returns ``ok: false`` plus
        ``code`` + ``status`` (OP HTTP code if any). The ``message``
        is human-readable and safe to render in a flash banner.
        """
        if self.success:
            return {
                'ok': True,
                'workPackage': self.work_package or {},
            }
        return {
            'ok': False,
            'code': self.code or 'UNKNOWN',
            'message': self.message or 'OpenProject rejected the update.',
            'status': self.status,
        }


def _error_result(exc: OpenProjectError) -> WriteResult:
    """Translate an ``OpenProjectError`` into a structured ``WriteResult``."""
    if isinstance(exc, OpenProjectConcurrencyError):
        return WriteResult(
            success=False, code='CONFLICT',
            message=(
                'OpenProject rejected the change because someone else '
                'edited this work package first. Refresh and try again.'
            ),
            status=exc.status,
        )
    # OpenProjectNotFound → 404 (rare on PATCH but possible if WP was
    # deleted between the page render and the drag).
    name = type(exc).__name__
    if name == 'OpenProjectNotFound':
        return WriteResult(
            success=False, code='NOT_FOUND',
            message='Work package not found in OpenProject.',
            status=exc.status,
        )
    if name == 'OpenProjectValidationError':
        return WriteResult(
            success=False, code='VALIDATION',
            message=str(exc) or 'OpenProject rejected the request shape.',
            status=exc.status,
        )
    if name == 'OpenProjectAuthError':
        return WriteResult(
            success=False, code='CONFIG',
            message='OpenProject credentials invalid; contact Psi Function.',
            status=exc.status,
        )
    # Transport / 5xx / other
    return WriteResult(
        success=False, code='TRANSPORT',
        message=str(exc) or 'OpenProject unreachable.',
        status=exc.status,
    )


# --------------------------------------------------------------------------- #
# Journal-comment template — exact format per kickoff rule #5
# --------------------------------------------------------------------------- #
def _journal_comment(user) -> str:
    """Return the exact journal-comment body for a portal mutation.

    Per kickoff rule #5: ``Changed via Psi Function portal by
    <User.email> (<User.id>)``. No edits, no extra punctuation, no
    leading/trailing whitespace.
    """
    email = getattr(user, 'email', '') or 'unknown@unknown'
    user_id = getattr(user, 'id', '?')
    return f'Changed via Psi Function portal by {email} ({user_id})'


def _post_journal_comment(
    op_client: OpenProjectClient, wp_id: int, user,
) -> None:
    """Post the audit journal comment. Logs but doesn't raise on failure.

    A journal-comment POST failure shouldn't break the user-visible
    mutation — the WP is already updated in OP, the cache is about to
    be invalidated, the audit row is already written. We log loudly
    so ops can investigate, but the optimistic UI sees success.
    """
    try:
        op_client.post_work_package_comment(wp_id, _journal_comment(user))
    except OpenProjectError as exc:
        logger.warning(
            'journal comment POST failed wp=%s user=%s err=%s',
            wp_id, getattr(user, 'id', '?'), exc,
        )


def _write_audit_row(
    *,
    user, client_id: int | None,
    op_project_id: int, op_work_package_id: int,
    action: str, before_value: str | None,
    after_value: str | None,
    op_response_code: int | None,
    op_response_error: str | None,
) -> None:
    """Persist one PortalAuditLog row. Rolls back on DB error so the
    commit (which flushes the audit row alongside) stays consistent."""
    row = PortalAuditLog(
        user_id=getattr(user, 'id', None),
        client_id=client_id,
        op_project_id=op_project_id,
        op_work_package_id=op_work_package_id,
        action=action,
        before_value=before_value,
        after_value=after_value,
        op_response_code=op_response_code,
        op_response_error=op_response_error,
    )
    db.session.add(row)
    db.session.commit()


# --------------------------------------------------------------------------- #
# Public API — status change + reorder
# --------------------------------------------------------------------------- #
def change_work_package_status(
    op_client: OpenProjectClient,
    *,
    user,
    client_id: int | None,
    op_project_id: int,
    wp_id: int,
    target_status_name: str,
    lock_version: int,
    before_status_name: str | None = None,
) -> WriteResult:
    """Change a work package's status via the portal.

    Resolves ``target_status_name`` to an OP status id, PATCHes the WP,
    then runs the journal + audit + invalidate trio on success.

    Returns a structured :class:`WriteResult`. ``CONFLICT`` results
    are surfaced verbatim so the JS can show "OpenProject rejected
    the change because someone else edited this work package first"
    without custom message-mapping on the client.
    """
    status_id = resolve_status_id(op_client, target_status_name)
    if status_id is None:
        return WriteResult(
            success=False, code='VALIDATION',
            message=f'Unknown status: {target_status_name!r}',
        )

    try:
        wp = op_client.update_work_package_status(
            wp_id, status_id, lock_version,
        )
    except OpenProjectError as exc:
        return _error_result(exc)

    # Successful PATCH — post journal, write audit row, invalidate cache.
    _post_journal_comment(op_client, wp_id, user)
    try:
        _write_audit_row(
            user=user,
            client_id=client_id,
            op_project_id=op_project_id,
            op_work_package_id=wp_id,
            action=PortalAuditLog.ACTION_STATUS_CHANGE,
            before_value=before_status_name,
            after_value=target_status_name,
            op_response_code=200,
            op_response_error=None,
        )
    except Exception:  # noqa: BLE001
        logger.exception('audit row write failed wp=%s', wp_id)
    cache_invalidate(op_project_id)
    return WriteResult(success=True, work_package=wp)


def reorder_work_package(
    op_client: OpenProjectClient,
    *,
    user,
    client_id: int | None,
    op_project_id: int,
    wp_id: int,
    new_position: int,
    lock_version: int,
    before_position: int | None = None,
) -> WriteResult:
    """Move a work package to ``new_position`` within its project.

    OpenProject's reorder semantics are provisional — see the
    ``update_work_package_priority_order`` docstring on the client.
    The route layers pass ``new_position`` straight through; if OP
    rejects the shape in production we re-spike.

    Same audit + journal + cache trio as :func:`change_work_package_status`.
    """
    try:
        wp = op_client.update_work_package_priority_order(
            wp_id, new_position, lock_version,
        )
    except OpenProjectError as exc:
        return _error_result(exc)

    _post_journal_comment(op_client, wp_id, user)
    try:
        _write_audit_row(
            user=user,
            client_id=client_id,
            op_project_id=op_project_id,
            op_work_package_id=wp_id,
            action=PortalAuditLog.ACTION_REORDER,
            before_value=str(before_position) if before_position is not None else None,
            after_value=str(new_position),
            op_response_code=200,
            op_response_error=None,
        )
    except Exception:  # noqa: BLE001
        logger.exception('audit row write failed wp=%s', wp_id)
    cache_invalidate(op_project_id)
    return WriteResult(success=True, work_package=wp)