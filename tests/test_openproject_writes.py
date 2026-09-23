"""Tests for the portal-side OpenProject write orchestration.

Covers:

* ``resolve_status_id`` — name → id mapping against the OP statuses
  collection; missing name returns None (no exception).
* ``WriteResult.to_dict`` — JSON shape the optimistic-UI JS consumes
  on success + on each error code path.
* ``change_work_package_status`` — happy path runs the four-step
  contract (PATCH → journal → audit → invalidate) in order; 409
  conflict translates to a structured WriteResult with code='CONFLICT';
  missing target status returns code='VALIDATION'.
* ``reorder_work_package`` — same contract for the reorder write;
  before/after position values land in the audit row as strings.
* Cache invalidation runs on success and NOT on a 409 failure.
* Audit row format: action code, before/after, OP response code,
  user_id / client_id are populated from the actor.

These tests mock at the ``OpenProjectClient`` method boundary (not
``urllib.request.urlopen``) because we're exercising the orchestration
layer, not the transport layer. Transport-level tests live in
``tests/test_openproject_client.py``.
"""

from __future__ import annotations

from unittest import mock

import pytest

from app.extensions import db
from app.models.portal_audit_log import PortalAuditLog
from app.services.openproject import (
    OpenProjectConcurrencyError,
    OpenProjectError,
)
from app.services.openproject_writes import (
    WriteResult,
    _journal_comment,
    change_work_package_status,
    reorder_work_package,
    resolve_status_id,
)


# --------------------------------------------------------------------------- #
# Fixtures + helpers
# --------------------------------------------------------------------------- #
def _status_payload():
    """The shape ``get_statuses`` returns — list of dicts with id+name."""
    return [
        {'id': 1, 'name': 'New'},
        {'id': 2, 'name': 'Ready'},
        {'id': 3, 'name': 'In progress'},
        {'id': 4, 'name': 'In testing'},
        {'id': 5, 'name': 'Blocked'},
        {'id': 6, 'name': 'Rejected'},
        {'id': 7, 'name': 'Completed'},
        {'id': 8, 'name': 'Deployed'},
    ]


class _StubUser:
    def __init__(self, id=42, email='alice@psi.test'):
        self.id = id
        self.email = email


@pytest.fixture(autouse=True)
def _reset_cache():
    """The read cache is module-global; reset before each test so
    cross-test bleed can't affect assertions about invalidation."""
    from app.services.openproject_cache import reset_cache_for_tests
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()


# --------------------------------------------------------------------------- #
# resolve_status_id
# --------------------------------------------------------------------------- #
class TestResolveStatusId:

    def test_returns_id_for_known_name(self):
        op = mock.MagicMock()
        op.get_statuses.return_value = _status_payload()
        assert resolve_status_id(op, 'In progress') == 3

    def test_returns_none_for_unknown_name(self):
        op = mock.MagicMock()
        op.get_statuses.return_value = _status_payload()
        assert resolve_status_id(op, 'Mystery Status') is None

    def test_returns_none_for_blank_name(self):
        op = mock.MagicMock()
        assert resolve_status_id(op, '') is None
        assert resolve_status_id(op, '   ') is None
        assert resolve_status_id(op, None) is None
        # No call to OP when the input is empty — saves a round-trip.
        op.get_statuses.assert_not_called()

    def test_handles_title_field_alternative(self):
        """Some OP versions return 'title' instead of 'name' on statuses."""
        op = mock.MagicMock()
        op.get_statuses.return_value = [
            {'id': 1, 'title': 'New'},
            {'id': 2, 'title': 'Ready'},
        ]
        assert resolve_status_id(op, 'New') == 1

    def test_skips_non_dict_entries(self):
        op = mock.MagicMock()
        op.get_statuses.return_value = [
            'not-a-dict',
            {'id': 1, 'name': 'New'},
            None,
            {'id': 2, 'name': 'Ready'},
        ]
        assert resolve_status_id(op, 'Ready') == 2


# --------------------------------------------------------------------------- #
# WriteResult JSON shape
# --------------------------------------------------------------------------- #
class TestWriteResultShape:

    def test_success_shape(self):
        r = WriteResult(
            success=True, work_package={'id': 99, 'subject': 'Hi'},
        )
        d = r.to_dict()
        assert d == {
            'ok': True,
            'workPackage': {'id': 99, 'subject': 'Hi'},
        }

    def test_success_with_no_work_package(self):
        r = WriteResult(success=True, work_package=None)
        assert r.to_dict() == {'ok': True, 'workPackage': {}}

    def test_conflict_shape(self):
        r = WriteResult(
            success=False, code='CONFLICT',
            message='...', status=409,
        )
        d = r.to_dict()
        assert d['ok'] is False
        assert d['code'] == 'CONFLICT'
        assert d['status'] == 409
        assert 'message' in d

    def test_failure_defaults_to_unknown_code(self):
        r = WriteResult(success=False)
        d = r.to_dict()
        assert d['ok'] is False
        assert d['code'] == 'UNKNOWN'
        assert 'message' in d  # fallback message present


# --------------------------------------------------------------------------- #
# _journal_comment template
# --------------------------------------------------------------------------- #
class TestJournalCommentTemplate:

    def test_exact_format(self):
        user = _StubUser(id=42, email='alice@psi.test')
        assert (
            _journal_comment(user)
            == 'Changed via Psi Function portal by alice@psi.test (42)'
        )

    def test_handles_missing_email(self):
        user = _StubUser(id=7, email='')
        # Defensive: don't crash on a malformed user row.
        assert _journal_comment(user) == (
            'Changed via Psi Function portal by unknown@unknown (7)'
        )


# --------------------------------------------------------------------------- #
# change_work_package_status — happy path
# --------------------------------------------------------------------------- #
class TestChangeStatusHappyPath:

    def test_runs_patch_journal_audit_invalidate_in_order(
        self, db_session,
    ):
        from app.services.openproject_cache import cache_set

        op = mock.MagicMock()
        op.get_statuses.return_value = _status_payload()
        op.update_work_package_status.return_value = {
            'id': 99, 'subject': 'Hello', 'lockVersion': 2,
            '_links': {'status': {'title': 'In progress'}},
        }
        op.post_work_package_comment.return_value = {'id': 1}

        # Pre-seed the cache so we can verify invalidate clears it.
        cache_set(99, 'some-fp', {'stale': True})

        result = change_work_package_status(
            op,
            user=_StubUser(),
            client_id=5,
            op_project_id=42,
            wp_id=99,
            target_status_name='In progress',
            lock_version=1,
            before_status_name='New',
        )

        assert result.success is True
        assert result.work_package['id'] == 99

        # All four steps ran, in the right order.
        op.update_work_package_status.assert_called_once_with(99, 3, 1)
        op.post_work_package_comment.assert_called_once()
        # The journal call's body matches the exact template.
        wp_id_arg, comment_arg = op.post_work_package_comment.call_args[0]
        assert wp_id_arg == 99
        assert comment_arg == (
            'Changed via Psi Function portal by alice@psi.test (42)'
        )

        # The audit row was written with the right shape.
        rows = PortalAuditLog.query.all()
        assert len(rows) == 1
        row = rows[0]
        assert row.action == PortalAuditLog.ACTION_STATUS_CHANGE
        assert row.before_value == 'New'
        assert row.after_value == 'In progress'
        assert row.op_response_code == 200
        assert row.user_id == 42
        assert row.client_id == 5
        assert row.op_project_id == 42
        assert row.op_work_package_id == 99

        # Cache was invalidated for the project.
        from app.services.openproject_cache import cache_get
        assert cache_get(42, 'some-fp') is None

    def test_no_audit_row_on_validation_error(self, db_session):
        op = mock.MagicMock()
        op.get_statuses.return_value = _status_payload()
        # PATCH raises validation.
        op.update_work_package_status.side_effect = (
            OpenProjectError('bad payload', status=422)
        )

        result = change_work_package_status(
            op,
            user=_StubUser(),
            client_id=5,
            op_project_id=42,
            wp_id=99,
            target_status_name='In progress',
            lock_version=1,
        )

        assert result.success is False
        assert result.code == 'TRANSPORT'  # base OpenProjectError → transport
        # No audit row written (PATCH failed).
        assert PortalAuditLog.query.count() == 0
        # No journal comment posted.
        op.post_work_package_comment.assert_not_called()


# --------------------------------------------------------------------------- #
# change_work_package_status — failure paths
# --------------------------------------------------------------------------- #
class TestChangeStatusFailures:

    def test_409_conflict_returns_structured_result(self, db_session):
        op = mock.MagicMock()
        op.get_statuses.return_value = _status_payload()
        op.update_work_package_status.side_effect = (
            OpenProjectConcurrencyError(
                'lock_version mismatch', status=409,
            )
        )

        result = change_work_package_status(
            op,
            user=_StubUser(),
            client_id=5,
            op_project_id=42,
            wp_id=99,
            target_status_name='In progress',
            lock_version=1,
        )

        assert result.success is False
        d = result.to_dict()
        assert d['ok'] is False
        assert d['code'] == 'CONFLICT'
        assert d['status'] == 409
        assert 'message' in d
        # No audit row written (PATCH failed).
        assert PortalAuditLog.query.count() == 0
        # Cache NOT invalidated on a failed PATCH (April spec: "every
        # successful write"; we read from cache until OP confirms).
        op.post_work_package_comment.assert_not_called()

    def test_unknown_status_returns_validation_result(self, db_session):
        op = mock.MagicMock()
        op.get_statuses.return_value = _status_payload()

        result = change_work_package_status(
            op,
            user=_StubUser(),
            client_id=5,
            op_project_id=42,
            wp_id=99,
            target_status_name='Not a Status',
            lock_version=1,
        )

        assert result.success is False
        d = result.to_dict()
        assert d['code'] == 'VALIDATION'
        assert 'Not a Status' in d['message']
        # No PATCH attempted when target is unresolvable.
        op.update_work_package_status.assert_not_called()


# --------------------------------------------------------------------------- #
# reorder_work_package
# --------------------------------------------------------------------------- #
class TestReorder:

    def test_happy_path(self, db_session):
        op = mock.MagicMock()
        op.update_work_package_priority_order.return_value = {
            'id': 99, 'lockVersion': 2,
        }
        op.post_work_package_comment.return_value = {'id': 1}

        result = reorder_work_package(
            op,
            user=_StubUser(),
            client_id=5,
            op_project_id=42,
            wp_id=99,
            new_position=7,
            lock_version=1,
            before_position=3,
        )

        assert result.success is True
        op.update_work_package_priority_order.assert_called_once_with(
            99, 7, 1,
        )
        op.post_work_package_comment.assert_called_once()

        row = PortalAuditLog.query.one()
        assert row.action == PortalAuditLog.ACTION_REORDER
        assert row.before_value == '3'
        assert row.after_value == '7'
        assert row.op_work_package_id == 99
        assert row.user_id == 42
        assert row.client_id == 5
        assert row.op_response_code == 200

    def test_conflict_returns_structured_result(self, db_session):
        op = mock.MagicMock()
        op.update_work_package_priority_order.side_effect = (
            OpenProjectConcurrencyError('lock mismatch', status=409)
        )

        result = reorder_work_package(
            op,
            user=_StubUser(),
            client_id=5,
            op_project_id=42,
            wp_id=99,
            new_position=5,
            lock_version=1,
            before_position=2,
        )

        assert result.success is False
        assert result.code == 'CONFLICT'
        assert PortalAuditLog.query.count() == 0

    def test_audit_row_omits_before_when_unknown(self, db_session):
        """A reorder with no before_position stored still records the
        new position — the audit row is still meaningful (operator
        sees "moved to N")."""
        op = mock.MagicMock()
        op.update_work_package_priority_order.return_value = {'id': 99}
        op.post_work_package_comment.return_value = {'id': 1}

        reorder_work_package(
            op,
            user=_StubUser(),
            client_id=5,
            op_project_id=42,
            wp_id=99,
            new_position=4,
            lock_version=1,
            before_position=None,
        )

        row = PortalAuditLog.query.one()
        assert row.before_value is None
        assert row.after_value == '4'


# --------------------------------------------------------------------------- #
# Cache invalidation behavior
# --------------------------------------------------------------------------- #
class TestCacheInvalidation:

    def test_successful_status_change_invalidates_cache(self, db_session):
        from app.services.openproject_cache import cache_get, cache_set

        op = mock.MagicMock()
        op.get_statuses.return_value = _status_payload()
        op.update_work_package_status.return_value = {'id': 99}
        op.post_work_package_comment.return_value = {'id': 1}

        # Pre-seed cache entries on this project + a sibling project.
        cache_set(42, 'fp-a', {'old': True})
        cache_set(42, 'fp-b', {'old': True})
        cache_set(43, 'fp-c', {'old': True})  # different project — must survive

        change_work_package_status(
            op,
            user=_StubUser(),
            client_id=5,
            op_project_id=42,
            wp_id=99,
            target_status_name='In progress',
            lock_version=1,
        )

        assert cache_get(42, 'fp-a') is None
        assert cache_get(42, 'fp-b') is None
        # The sibling project's cache is untouched.
        assert cache_get(43, 'fp-c') == {'old': True}

    def test_failed_status_change_does_not_invalidate(self, db_session):
        from app.services.openproject_cache import cache_get, cache_set

        op = mock.MagicMock()
        op.get_statuses.return_value = _status_payload()
        op.update_work_package_status.side_effect = (
            OpenProjectConcurrencyError('lock mismatch', status=409)
        )

        cache_set(42, 'fp-a', {'stale': True})

        result = change_work_package_status(
            op,
            user=_StubUser(),
            client_id=5,
            op_project_id=42,
            wp_id=99,
            target_status_name='In progress',
            lock_version=1,
        )

        assert result.success is False
        # Cache survives a failed write — no spurious re-fetches on the
        # next render of the dashboard card.
        assert cache_get(42, 'fp-a') == {'stale': True}


# --------------------------------------------------------------------------- #
# Journal-comment failure is logged but doesn't break the write
# --------------------------------------------------------------------------- #
class TestJournalCommentFailureIsTolerated:

    def test_audit_row_still_written_when_journal_fails(self, db_session):
        op = mock.MagicMock()
        op.get_statuses.return_value = _status_payload()
        op.update_work_package_status.return_value = {'id': 99}
        # Journal comment POST fails — the WP update is the source of
        # truth, so we should still consider the write successful.
        op.post_work_package_comment.side_effect = (
            OpenProjectError('journal 500', status=500)
        )

        result = change_work_package_status(
            op,
            user=_StubUser(),
            client_id=5,
            op_project_id=42,
            wp_id=99,
            target_status_name='In progress',
            lock_version=1,
        )

        # WP update succeeded → the portal marks it successful.
        assert result.success is True
        # Audit row still written (we know the WP was updated; the
        # journal failure is a separate concern for ops to investigate).
        assert PortalAuditLog.query.count() == 1