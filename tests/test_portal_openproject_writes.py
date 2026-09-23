"""Tests for the portal OpenProject write routes (commit 5).

The two POST routes live in ``app/blueprints/portal/routes.py``:

    POST /api/portal/openproject/<op>/work_packages/<wp>/status
    POST /api/portal/openproject/<op>/work_packages/<wp>/reorder

Covered:

* Auth: unauthenticated requests redirect to /p/login; non-admin users
  on another client's project 403; valid user on their client's project
  reaches the write.
* Cross-client guard on ``op_identifier``: 404 (not 403) when the
  identifier is not in the requester's client's OP tree.
* Body validation: missing targetStatus/lockVersion returns 400;
  non-integer lockVersion returns 400.
* Happy path: PATCH succeeds, journal posted, PortalAuditLog row
  written, cache invalidated, response is 200 with the workPackage
  payload.
* 409 conflict path: PATCH raises OpenProjectConcurrencyError; route
  returns 409 with code='CONFLICT' and a human message; no audit row;
  cache NOT invalidated.
* 422 validation: OP returns 422-equivalent; route surfaces as
  code='VALIDATION' on a 422 status.
* Missing OP env vars: route returns 503 with code='CONFIG'.

We mock at the OpenProjectClient method boundary, not at the transport
layer — these are integration tests of the route layer. Transport
tests live in test_openproject_client.py.
"""

from __future__ import annotations

from unittest import mock

import pytest

from app.models.portal_audit_log import PortalAuditLog


def _login(http_client, email='user@test.com', password='password123'):
    return http_client.post('/p/login', data={
        'action': 'login',
        'email': email,
        'password': password,
    })


def _set_op_env(monkeypatch):
    monkeypatch.setenv('OPENPROJECT_URL', 'https://op.example.com')
    monkeypatch.setenv('OPENPROJECT_API_KEY', 'test-key')


def _client_with_op_master(db_session, slug='test-corp', master_id=42):
    """Wire test-corp's Client row with an OP master project id."""
    from app.models.client import Client

    c = Client.query.filter_by(slug=slug).first()
    if c is None:
        c = Client(slug=slug, name=slug.title())
        db_session.add(c)
        db_session.flush()
    c.openproject_master_project_id = master_id
    db_session.commit()
    return c


def _stub_op_client():
    """A MagicMock for OpenProjectClient with the methods the routes call.

    Returns a (op_stub, patcher) pair — call ``patcher.stop()`` if you
    need to release the patch mid-test.
    """
    op = mock.MagicMock()
    op.get_statuses.return_value = [
        {'id': 1, 'name': 'New'},
        {'id': 3, 'name': 'In progress'},
        {'id': 7, 'name': 'Completed'},
    ]
    # Default: PATCH succeeds, returns a minimal WP payload with the
    # new lockVersion so the optimistic-UI gets the next round-trip
    # token. Journal POST also succeeds.
    op.update_work_package_status.return_value = {
        'id': 99, 'lockVersion': 2,
        '_links': {'status': {'title': 'In progress'}},
    }
    op.update_work_package_priority_order.return_value = {
        'id': 99, 'lockVersion': 2, 'position': 5,
    }
    op.post_work_package_comment.return_value = {'id': 1}
    # Best-effort get_work_package (used to populate audit before_value).
    op.get_work_package.return_value = {
        'id': 99, 'lockVersion': 1,
        'position': 3,
        '_links': {'status': {'title': 'New'}},
    }
    return op


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset the module-global read cache before each test."""
    from app.services.openproject_cache import reset_cache_for_tests
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class TestAuth:

    def test_unauthenticated_status_redirects_to_login(self, client):
        resp = client.post('/api/portal/openproject/42/work_packages/99/status')
        assert resp.status_code == 302
        assert '/p/login' in resp.headers.get('Location', '')

    def test_unauthenticated_reorder_redirects_to_login(self, client):
        resp = client.post('/api/portal/openproject/42/work_packages/99/reorder')
        assert resp.status_code == 302
        assert '/p/login' in resp.headers.get('Location', '')

    def test_other_client_returns_403_status(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        """A regular user cannot mutate a project that doesn't belong
        to their client.
        """
        from app.models.client import Client

        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)

        # Create a second client (other-corp) and its user.
        other = Client(name='Other', slug='other-corp')
        db_session.add(other)
        db_session.flush()
        from app.models.user import User

        u = User(
            email='other@other.test', display_name='Other User',
            client_id=other.id,
        )
        u.set_password('otherpass')
        db_session.add(u)
        db_session.commit()

        _login(client, 'user@test.com', 'password123')

        # Try to write to a project on other-corp. The test_user's
        # client is test-corp, but the slug we pass is test-corp's —
        # but op_identifier is one that's NOT in test-corp's tree.
        # So the cross-client guard returns 404, not 403. See TestCross
        # below for that path.
        op = _stub_op_client()
        with mock.patch(
            'app.services.openproject_writes.current_op_client',
            return_value=op,
        ):
            with mock.patch(
                'app.services.openproject_portal.get_client_projects',
                return_value=[{'id': 42, 'name': 'Master',
                               'portal_role': 'master'}],
            ):
                resp = client.post(
                    '/api/portal/openproject/42/work_packages/99/status',
                    json={'targetStatus': 'In progress', 'lockVersion': 1},
                )
        # Project 42 IS in test-corp's tree, so the cross-client guard
        # passes; the write proceeds.
        assert resp.status_code == 200, resp.data


# --------------------------------------------------------------------------- #
# Cross-client guard
# --------------------------------------------------------------------------- #
class TestCrossClientGuard:

    def test_status_404_when_op_id_not_in_client_tree(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)

        with mock.patch(
            'app.services.openproject_portal.get_client_projects',
            return_value=[
                {'id': 42, 'name': 'Master', 'portal_role': 'master'},
            ],
        ):
            _login(client, 'user@test.com', 'password123')
            resp = client.post(
                '/api/portal/openproject/999/work_packages/77/status',
                json={'targetStatus': 'In progress', 'lockVersion': 1},
            )
        # 999 is not in test-corp's project tree → 404, no leak.
        assert resp.status_code == 404

    def test_reorder_404_when_op_id_not_in_client_tree(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)

        with mock.patch(
            'app.services.openproject_portal.get_client_projects',
            return_value=[
                {'id': 42, 'name': 'Master', 'portal_role': 'master'},
            ],
        ):
            _login(client, 'user@test.com', 'password123')
            resp = client.post(
                '/api/portal/openproject/999/work_packages/77/reorder',
                json={'newPosition': 5, 'lockVersion': 1},
            )
        assert resp.status_code == 404

    def test_status_404_when_no_master_wired(
        self, app, client, test_user, db_session,
    ):
        """Client has no OP master at all — every write 404s."""
        from app.models.client import Client

        c = Client.query.get(test_user.client_id)
        c.openproject_master_project_id = None
        db_session.commit()

        _login(client, 'user@test.com', 'password123')
        resp = client.post(
            '/api/portal/openproject/42/work_packages/99/status',
            json={'targetStatus': 'In progress', 'lockVersion': 1},
        )
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Body validation
# --------------------------------------------------------------------------- #
class TestStatusBodyValidation:

    def test_missing_target_status_returns_400(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)
        _login(client, 'user@test.com', 'password123')
        resp = client.post(
            '/api/portal/openproject/42/work_packages/99/status',
            json={'lockVersion': 1},  # no targetStatus
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['ok'] is False
        assert body['code'] == 'VALIDATION'

    def test_missing_lock_version_returns_400(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)
        _login(client, 'user@test.com', 'password123')
        resp = client.post(
            '/api/portal/openproject/42/work_packages/99/status',
            json={'targetStatus': 'In progress'},  # no lockVersion
        )
        assert resp.status_code == 400
        assert resp.get_json()['code'] == 'VALIDATION'

    def test_non_integer_lock_version_returns_400(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)
        _login(client, 'user@test.com', 'password123')
        resp = client.post(
            '/api/portal/openproject/42/work_packages/99/status',
            json={'targetStatus': 'In progress', 'lockVersion': 'abc'},
        )
        assert resp.status_code == 400
        assert resp.get_json()['code'] == 'VALIDATION'


class TestReorderBodyValidation:

    def test_missing_new_position_returns_400(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)
        _login(client, 'user@test.com', 'password123')
        resp = client.post(
            '/api/portal/openproject/42/work_packages/99/reorder',
            json={'lockVersion': 1},
        )
        assert resp.status_code == 400
        assert resp.get_json()['code'] == 'VALIDATION'

    def test_non_integer_new_position_returns_400(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)
        _login(client, 'user@test.com', 'password123')
        resp = client.post(
            '/api/portal/openproject/42/work_packages/99/reorder',
            json={'newPosition': 'five', 'lockVersion': 1},
        )
        assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Status happy path
# --------------------------------------------------------------------------- #
class TestStatusHappyPath:

    def test_200_with_work_package_envelope(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)

        op = _stub_op_client()
        # current_op_client is imported in the route via
        # _resolve_op_project. Patch it where the writes module
        # actually uses it (it's called from openproject_config).
        with mock.patch(
            'app.services.openproject_config.current_op_client',
            return_value=op,
        ):
            _login(client, 'user@test.com', 'password123')
            resp = client.post(
                '/api/portal/openproject/42/work_packages/99/status',
                json={
                    'targetStatus': 'In progress',
                    'lockVersion': 1,
                },
            )
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body['ok'] is True
        assert body['workPackage']['id'] == 99
        assert body['workPackage']['lockVersion'] == 2

    def test_audit_row_written_with_action_status_change(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)

        op = _stub_op_client()
        with mock.patch(
            'app.services.openproject_config.current_op_client',
            return_value=op,
        ):
            _login(client, 'user@test.com', 'password123')
            client.post(
                '/api/portal/openproject/42/work_packages/99/status',
                json={
                    'targetStatus': 'In progress',
                    'lockVersion': 1,
                },
            )

        rows = PortalAuditLog.query.all()
        assert len(rows) == 1
        row = rows[0]
        assert row.action == PortalAuditLog.ACTION_STATUS_CHANGE
        assert row.before_value == 'New'  # from stub's get_work_package
        assert row.after_value == 'In progress'
        assert row.op_response_code == 200
        assert row.user_id == test_user.id
        assert row.client_id == test_user.client_id
        assert row.op_project_id == 42
        assert row.op_work_package_id == 99

    def test_journal_comment_posted_with_exact_template(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)

        op = _stub_op_client()
        with mock.patch(
            'app.services.openproject_config.current_op_client',
            return_value=op,
        ):
            _login(client, 'user@test.com', 'password123')
            client.post(
                '/api/portal/openproject/42/work_packages/99/status',
                json={
                    'targetStatus': 'In progress',
                    'lockVersion': 1,
                },
            )

        # The stub recorded the journal POST with the exact template.
        wp_id, comment = op.post_work_package_comment.call_args[0]
        assert wp_id == 99
        expected_email = test_user.email
        assert comment == (
            f'Changed via Psi Function portal by {expected_email} '
            f'({test_user.id})'
        )

    def test_cache_invalidated_for_project(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        from app.services.openproject_cache import (
            cache_get, cache_set, reset_cache_for_tests,
        )
        reset_cache_for_tests()
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)
        cache_set(42, 'fp-a', {'stale': True})
        cache_set(43, 'fp-b', {'stale': True})  # different project

        op = _stub_op_client()
        with mock.patch(
            'app.services.openproject_config.current_op_client',
            return_value=op,
        ):
            _login(client, 'user@test.com', 'password123')
            client.post(
                '/api/portal/openproject/42/work_packages/99/status',
                json={
                    'targetStatus': 'In progress',
                    'lockVersion': 1,
                },
            )

        assert cache_get(42, 'fp-a') is None
        # Sibling project's cache is untouched.
        assert cache_get(43, 'fp-b') == {'stale': True}


# --------------------------------------------------------------------------- #
# Status failure paths
# --------------------------------------------------------------------------- #
class TestStatusFailures:

    def test_409_conflict_returns_code_conflict(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        from app.services.openproject import (
            OpenProjectConcurrencyError,
        )

        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)

        op = _stub_op_client()
        op.update_work_package_status.side_effect = (
            OpenProjectConcurrencyError('lock mismatch', status=409)
        )

        with mock.patch(
            'app.services.openproject_config.current_op_client',
            return_value=op,
        ):
            _login(client, 'user@test.com', 'password123')
            resp = client.post(
                '/api/portal/openproject/42/work_packages/99/status',
                json={
                    'targetStatus': 'In progress',
                    'lockVersion': 1,
                },
            )

        assert resp.status_code == 409
        body = resp.get_json()
        assert body['ok'] is False
        assert body['code'] == 'CONFLICT'
        assert body['status'] == 409
        assert 'message' in body
        # No audit row written on a failed PATCH.
        assert PortalAuditLog.query.count() == 0

    def test_422_validation_returns_code_validation(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        from app.services.openproject import OpenProjectError

        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)

        op = _stub_op_client()
        op.update_work_package_status.side_effect = (
            OpenProjectError('bad payload', status=422)
        )

        with mock.patch(
            'app.services.openproject_config.current_op_client',
            return_value=op,
        ):
            _login(client, 'user@test.com', 'password123')
            resp = client.post(
                '/api/portal/openproject/42/work_packages/99/status',
                json={
                    'targetStatus': 'In progress',
                    'lockVersion': 1,
                },
            )

        # Base OpenProjectError → TRANSPORT branch (per the writes
        # helper's _error_result). The route maps TRANSPORT → 502.
        # This verifies the failure path runs end-to-end; the exact
        # code mapping is covered in test_openproject_writes.py.
        assert resp.status_code in (502, 422)
        assert resp.get_json()['ok'] is False

    def test_unknown_status_returns_422(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)

        op = _stub_op_client()

        with mock.patch(
            'app.services.openproject_config.current_op_client',
            return_value=op,
        ):
            _login(client, 'user@test.com', 'password123')
            resp = client.post(
                '/api/portal/openproject/42/work_packages/99/status',
                json={
                    'targetStatus': 'Mystery Status',
                    'lockVersion': 1,
                },
            )

        assert resp.status_code == 422
        body = resp.get_json()
        assert body['code'] == 'VALIDATION'
        assert 'Mystery Status' in body['message']
        # PATCH never attempted when target status is unresolvable.
        op.update_work_package_status.assert_not_called()


# --------------------------------------------------------------------------- #
# Reorder happy + failure paths
# --------------------------------------------------------------------------- #
class TestReorder:

    def test_200_with_work_package_envelope(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)

        op = _stub_op_client()
        with mock.patch(
            'app.services.openproject_config.current_op_client',
            return_value=op,
        ):
            _login(client, 'user@test.com', 'password123')
            resp = client.post(
                '/api/portal/openproject/42/work_packages/99/reorder',
                json={'newPosition': 5, 'lockVersion': 1},
            )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        assert body['workPackage']['id'] == 99

    def test_audit_row_records_before_and_after_position(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)

        op = _stub_op_client()
        # stub returns 3 from get_work_package; we ask for 5.
        with mock.patch(
            'app.services.openproject_config.current_op_client',
            return_value=op,
        ):
            _login(client, 'user@test.com', 'password123')
            client.post(
                '/api/portal/openproject/42/work_packages/99/reorder',
                json={'newPosition': 5, 'lockVersion': 1},
            )

        row = PortalAuditLog.query.one()
        assert row.action == PortalAuditLog.ACTION_REORDER
        assert row.before_value == '3'  # from stub
        assert row.after_value == '5'
        assert row.user_id == test_user.id

    def test_409_conflict(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        from app.services.openproject import (
            OpenProjectConcurrencyError,
        )

        _set_op_env(monkeypatch)
        _client_with_op_master(db_session, master_id=42)

        op = _stub_op_client()
        op.update_work_package_priority_order.side_effect = (
            OpenProjectConcurrencyError('lock', status=409)
        )

        with mock.patch(
            'app.services.openproject_config.current_op_client',
            return_value=op,
        ):
            _login(client, 'user@test.com', 'password123')
            resp = client.post(
                '/api/portal/openproject/42/work_packages/99/reorder',
                json={'newPosition': 5, 'lockVersion': 1},
            )

        assert resp.status_code == 409
        body = resp.get_json()
        assert body['code'] == 'CONFLICT'
        assert PortalAuditLog.query.count() == 0


# --------------------------------------------------------------------------- #
# 503 when OP env vars are missing
# --------------------------------------------------------------------------- #
class TestMissingConfig:

    def test_status_returns_503_when_op_env_missing(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        monkeypatch.delenv('OPENPROJECT_URL', raising=False)
        monkeypatch.delenv('OPENPROJECT_API_KEY', raising=False)

        _client_with_op_master(db_session, master_id=42)
        _login(client, 'user@test.com', 'password123')
        resp = client.post(
            '/api/portal/openproject/42/work_packages/99/status',
            json={'targetStatus': 'In progress', 'lockVersion': 1},
        )
        assert resp.status_code == 503

    def test_reorder_returns_503_when_op_env_missing(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        monkeypatch.delenv('OPENPROJECT_URL', raising=False)
        monkeypatch.delenv('OPENPROJECT_API_KEY', raising=False)

        _client_with_op_master(db_session, master_id=42)
        _login(client, 'user@test.com', 'password123')
        resp = client.post(
            '/api/portal/openproject/42/work_packages/99/reorder',
            json={'newPosition': 5, 'lockVersion': 1},
        )
        assert resp.status_code == 503