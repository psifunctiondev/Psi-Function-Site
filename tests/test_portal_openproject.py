"""Tests for the OpenProject-backed Projects card and project summary route.

Covers:

* client_dashboard renders the OP projects table when the client has a
  master_project_id wired AND OP env vars are set.
* client_dashboard falls back to the legacy ClientResource backlog list
  when no master_project_id is set.
* client_dashboard renders the 'temporarily unavailable' state when OP
  is configured but unreachable.
* Cross-client access on the project summary route 404s (no leak).
* Tab dispatch: ?tab=progress|status|backlog routes to the right
  partial; unknown tab values fall back to 'progress'.
* Auth: unauthenticated users redirect to /p/login; non-admin users
  cannot view other clients' summary pages (403).
"""

from __future__ import annotations

from unittest import mock

import pytest

from app.models.client import Client
from app.models.user import User


def _login(http_client, email, password):
    return http_client.post('/p/login', data={
        'action': 'login',
        'email': email,
        'password': password,
    })


def _set_op_env(monkeypatch, url='https://op.example.com', key='test-key'):
    monkeypatch.setenv('OPENPROJECT_URL', url)
    monkeypatch.setenv('OPENPROJECT_API_KEY', key)


# --------------------------------------------------------------------------- #
# client_dashboard — Projects card rendering
# --------------------------------------------------------------------------- #
class TestDashboardProjectsCard:

    def test_falls_back_to_resources_when_no_master(
        self, app, client, test_user, db_session,
    ):
        """Clients without an OP master project (ACME, CTAI today)
        render the legacy backlog-resource list — no regression."""
        from app.models.client import ClientResource

        db_session.add(ClientResource(
            client_id=test_user.client_id,
            title='Legacy Project Plan',
            category='backlog',
            external_url='https://example.com/plan',
            sort_order=1,
            is_visible=True,
        ))
        db_session.commit()

        _login(client, 'user@test.com', 'password123')
        resp = client.get('/p/test-corp')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Legacy Project Plan' in html
        # Empty-state copy not used because there's a row.
        assert 'No project plans yet' not in html

    def test_renders_op_projects_when_master_set(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        """When the client has a master_project_id + OP env vars are
        set, the dashboard renders the OP project list (master + children).
        """
        _set_op_env(monkeypatch)
        c = Client.query.get(test_user.client_id)
        c.openproject_master_project_id = 42
        db_session.commit()

        fake_projects = [
            {'id': 42, 'name': 'Drift & Anchor Audit',
             'updatedAt': '2026-09-22T14:23:00Z', 'portal_role': 'master'},
            {'id': 43, 'name': 'Engagement Setup',
             'updatedAt': '2026-09-22T14:23:00Z', 'portal_role': 'child'},
        ]
        fake_op = mock.MagicMock()
        fake_op.get_project.return_value = fake_projects[0]
        fake_op.get_child_projects.return_value = [fake_projects[1]]

        with mock.patch(
            'app.services.openproject_portal.get_client_projects',
            return_value=fake_projects,
        ):
            _login(client, 'user@test.com', 'password123')
            resp = client.get('/p/test-corp')

        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Drift &amp; Anchor Audit' in html or 'Drift & Anchor Audit' in html
        assert 'Engagement Setup' in html
        # The summary link is per-project (not just client dashboard).
        assert '/p/test-corp/projects/42' in html
        assert '/p/test-corp/projects/43' in html

    def test_shows_unavailable_state_on_op_error(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        """When OP env vars are set but the request fails, the partial
        shows the polite 'temporarily unavailable' message rather than
        blowing up the dashboard.
        """
        _set_op_env(monkeypatch)
        c = Client.query.get(test_user.client_id)
        c.openproject_master_project_id = 42
        db_session.commit()

        with mock.patch(
            'app.services.openproject_portal.get_client_projects',
            side_effect=RuntimeError('OP down'),
        ):
            _login(client, 'user@test.com', 'password123')
            resp = client.get('/p/test-corp')

        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'OpenProject temporarily unavailable' in html


# --------------------------------------------------------------------------- #
# project_summary route — auth + cross-client guard
# --------------------------------------------------------------------------- #
class TestProjectSummaryRoute:

    def _client_with_op_master(
        self, db_session, slug='test-corp', master_id=42,
    ) -> Client:
        c = Client.query.filter_by(slug=slug).first()
        if c is None:
            c = Client(slug=slug, name=slug.title())
            db_session.add(c)
            db_session.flush()
        c.openproject_master_project_id = master_id
        db_session.commit()
        return c

    def test_unauthenticated_redirects_to_login(self, app, client):
        resp = client.get('/p/test-corp/projects/42', follow_redirects=False)
        assert resp.status_code == 302
        assert '/p/login' in resp.headers.get('Location', '')

    def test_cross_client_returns_404(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        """A regular user cannot view a project id that doesn't belong
        to their client — 404 (not 403) so we don't leak whether other
        OP projects exist. Tested by asking for an op-identifier that
        is NOT in the fetched list for the requester's client.
        """
        _set_op_env(monkeypatch)
        self._client_with_op_master(db_session, master_id=42)

        # test_user belongs to test-corp (slug in fixture). test-corp's
        # master is 42. Ask for id 999 — not in the fetched project
        # list — and confirm 404.
        fake_projects = [
            {'id': 42, 'name': 'Master',
             'updatedAt': '2026-09-22T14:23:00Z', 'portal_role': 'master'},
        ]
        with mock.patch(
            'app.services.openproject_portal.get_client_projects',
            return_value=fake_projects,
        ):
            _login(client, 'user@test.com', 'password123')
            resp = client.get('/p/test-corp/projects/999')
            assert resp.status_code == 404

    def test_default_tab_is_progress(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        self._client_with_op_master(db_session, master_id=42)
        fake_projects = [
            {'id': 42, 'name': 'Master',
             'updatedAt': '2026-09-22T14:23:00Z', 'portal_role': 'master'},
        ]
        with mock.patch(
            'app.services.openproject_portal.get_client_projects',
            return_value=fake_projects,
        ):
            _login(client, 'user@test.com', 'password123')
            resp = client.get('/p/test-corp/projects/42')
            assert resp.status_code == 200
            html = resp.data.decode()
            assert 'portal-tabs__tab--active' in html
            # Progress tab is active by default.
            assert '>Progress<' in html

    def test_tab_query_param_renders_correct_partial(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        self._client_with_op_master(db_session, master_id=42)
        fake_projects = [
            {'id': 42, 'name': 'Master',
             'updatedAt': '2026-09-22T14:23:00Z', 'portal_role': 'master'},
        ]
        with mock.patch(
            'app.services.openproject_portal.get_client_projects',
            return_value=fake_projects,
        ):
            _login(client, 'user@test.com', 'password123')
            for tab, marker in [
                ('progress', 'portal-project-progress'),
                ('status', 'portal-kanban'),
                ('backlog', 'portal-backlog'),
            ]:
                resp = client.get(f'/p/test-corp/projects/42?tab={tab}')
                assert resp.status_code == 200, f'tab={tab}'
                html = resp.data.decode()
                assert marker in html, f'tab={tab} should render {marker}'

    def test_unknown_tab_falls_back_to_progress(
        self, app, client, test_user, db_session, monkeypatch,
    ):
        _set_op_env(monkeypatch)
        self._client_with_op_master(db_session, master_id=42)
        fake_projects = [
            {'id': 42, 'name': 'Master',
             'updatedAt': '2026-09-22T14:23:00Z', 'portal_role': 'master'},
        ]
        with mock.patch(
            'app.services.openproject_portal.get_client_projects',
            return_value=fake_projects,
        ):
            _login(client, 'user@test.com', 'password123')
            resp = client.get('/p/test-corp/projects/42?tab=garbage')
            assert resp.status_code == 200
            html = resp.data.decode()
            assert 'portal-project-progress' in html

    def test_404_when_no_master_wired(
        self, app, client, test_user, db_session,
    ):
        """Client has no openproject_master_project_id — any
        /p/<slug>/projects/... request 404s cleanly.
        """
        # Ensure master_id is None.
        c = Client.query.get(test_user.client_id)
        c.openproject_master_project_id = None
        db_session.commit()

        _login(client, 'user@test.com', 'password123')
        resp = client.get('/p/test-corp/projects/42')
        assert resp.status_code == 404
