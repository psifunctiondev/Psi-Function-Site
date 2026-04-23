"""
tests/test_portal.py
Tests for the client portal routes (dashboard, admin, legacy redirects).
"""

from app.extensions import db as _db
from app.models.client import Client, ClientResource
from app.models.user import User


def _login(http_client, email, password):
    """Helper to log in via the auth route."""
    return http_client.post('/p/login', data={
        'action': 'login',
        'email': email,
        'password': password,
    })


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------

def test_dashboard_redirects_unauthenticated(app, db_session):
    http = app.test_client()
    resp = http.get('/p/dashboard', follow_redirects=False)
    assert resp.status_code == 302
    assert '/p/login' in resp.headers.get('Location', '')


# ---------------------------------------------------------------------------
# Authenticated user dashboard
# ---------------------------------------------------------------------------

def test_dashboard_redirects_to_client_slug(app, client, test_user):
    _login(client, 'user@test.com', 'password123')
    resp = client.get('/p/dashboard', follow_redirects=False)
    assert resp.status_code == 302
    assert '/p/test-corp' in resp.headers.get('Location', '')


def test_client_dashboard_loads(app, client, test_user):
    _login(client, 'user@test.com', 'password123')
    resp = client.get('/p/test-corp')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'Test Corp' in html


# ---------------------------------------------------------------------------
# Admin overview
# ---------------------------------------------------------------------------

def test_admin_accessible_by_admin(app, client, admin_user, db_session):
    # Admin needs at least one active client for the page to render
    c = Client(name='Admin Corp', slug='admin-corp')
    db_session.add(c)
    db_session.commit()

    _login(client, 'admin@test.com', 'adminpass123')
    resp = client.get('/p/admin')
    assert resp.status_code == 200


def test_admin_forbidden_for_regular_user(app, client, test_user):
    _login(client, 'user@test.com', 'password123')
    resp = client.get('/p/admin')
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Client dashboard — access control
# ---------------------------------------------------------------------------

def test_client_dashboard_forbidden_for_wrong_client(app, client, test_user, db_session):
    """A regular user cannot view another client's dashboard."""
    other = Client(name='Other Corp', slug='other-corp')
    db_session.add(other)
    db_session.commit()

    _login(client, 'user@test.com', 'password123')
    resp = client.get('/p/other-corp')
    assert resp.status_code == 403


def test_admin_can_view_any_client_dashboard(app, client, admin_user, db_session):
    """Admins can access any client's dashboard."""
    c = Client(name='Any Corp', slug='any-corp')
    db_session.add(c)
    db_session.commit()

    _login(client, 'admin@test.com', 'adminpass123')
    resp = client.get('/p/any-corp')
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Legacy redirects
# ---------------------------------------------------------------------------

def test_legacy_truview_redirect(client):
    resp = client.get('/clients/ctai/truview-guide', follow_redirects=False)
    assert resp.status_code == 301
    assert '/guides/ctai/truview/' in resp.headers.get('Location', '')


def test_legacy_trueview_redirect(client):
    resp = client.get('/clients/ctai/trueview-guide', follow_redirects=False)
    assert resp.status_code == 301
    assert '/guides/ctai/truview/' in resp.headers.get('Location', '')
