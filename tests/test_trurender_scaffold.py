"""Tests for the TruRender portal scaffold (R1).

R1 ships the route stubs + templates + service stub only. These tests lock in:
- both routes are ``@login_required`` (anonymous -> /p/login)
- both routes enforce the CTAI-only access check:
    * CTAI users can reach the overview + new-project placeholder
    * site admins can reach them on any slug
    * users from a non-CTAI client get 403
- the overview template renders with the expected CTA box link
- the new-project template renders without crashing
- the service stub raises :class:`TruRenderNotConfigured` (so callers can
  catch it cleanly in R2)

R2 will add tests for the wired-up service module + form submission.
"""

import pytest

from app.models.client import Client
from app.services import trurender
from app.services.trurender import TruRenderNotConfigured

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctai_client(db_session):
    """A CTAI client — the only client allowed to enter TruRender.

    Mirrors the BRANDING_PROFILES['ctai'] row so palette/font assertions
    in the template tests reflect what the dashboard already exercises
    against the real CTAI client.
    """
    c = Client(
        slug='ctai',
        name='Catherine Truman Architects',
        primary_color='#FA6202',
        accent_color='#878787',
        tagline='Modernizing New England Home Design',
        logo_url='/static/images/ctai-logo.svg',
        font_url=(
            'https://fonts.googleapis.com/css2?'
            'family=Special+Gothic&display=swap'
        ),
        font_display="'Special Gothic', sans-serif",
        is_active=True,
    )
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def other_client(db_session):
    """A non-CTAI client — its members must NOT reach TruRender."""
    c = Client(slug='other', name='Other Corp', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def ctai_user(db_session, ctai_client):
    from app.models.user import User
    user = User(
        email='ctai@example.com',
        display_name='CTAI User',
        is_admin=False,
        client_id=ctai_client.id,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def other_user(db_session, other_client):
    from app.models.user import User
    user = User(
        email='other@example.com',
        display_name='Other User',
        is_admin=False,
        client_id=other_client.id,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


def _login(http_client, email, password):
    return http_client.post('/p/login', data={
        'action': 'login',
        'email': email,
        'password': password,
    })


# ---------------------------------------------------------------------------
# Auth gates
# ---------------------------------------------------------------------------

def test_overview_requires_login(app):
    http = app.test_client()
    resp = http.get('/p/ctai/trurender/', follow_redirects=False)
    assert resp.status_code == 302
    assert '/p/login' in resp.headers.get('Location', '')


def test_new_project_requires_login(app):
    http = app.test_client()
    resp = http.get('/p/ctai/trurender/new', follow_redirects=False)
    assert resp.status_code == 302
    assert '/p/login' in resp.headers.get('Location', '')


# ---------------------------------------------------------------------------
# CTAI access check
# ---------------------------------------------------------------------------

def test_ctai_user_can_reach_overview(app, client, ctai_user):
    _login(client, 'ctai@example.com', 'password123')
    resp = client.get('/p/ctai/trurender/', follow_redirects=False)
    assert resp.status_code == 200


def test_ctai_user_can_reach_new_project(app, client, ctai_user):
    _login(client, 'ctai@example.com', 'password123')
    resp = client.get('/p/ctai/trurender/new', follow_redirects=False)
    assert resp.status_code == 200


def test_admin_can_reach_overview_for_any_slug(app, client, db_session, admin_user, ctai_client):
    _login(client, 'admin@test.com', 'adminpass123')
    resp = client.get('/p/ctai/trurender/', follow_redirects=False)
    assert resp.status_code == 200


def test_admin_can_reach_new_project_for_any_slug(app, client, db_session, admin_user, ctai_client):
    _login(client, 'admin@test.com', 'adminpass123')
    resp = client.get('/p/ctai/trurender/new', follow_redirects=False)
    assert resp.status_code == 200


def test_non_ctai_user_blocked_from_overview(app, client, db_session, other_user, ctai_client):
    _login(client, 'other@example.com', 'password123')
    resp = client.get('/p/ctai/trurender/', follow_redirects=False)
    assert resp.status_code == 403


def test_non_ctai_user_blocked_from_new_project(app, client, db_session, other_user, ctai_client):
    _login(client, 'other@example.com', 'password123')
    resp = client.get('/p/ctai/trurender/new', follow_redirects=False)
    assert resp.status_code == 403


def test_ctai_user_blocked_from_other_client_trurender(
    app, client, db_session, ctai_user, other_client,
):
    """A CTAI user trying to open TruRender under another client's slug
    must be blocked — TruRender is CTAI-specific, not a per-client product.
    """
    _login(client, 'ctai@example.com', 'password123')
    resp = client.get('/p/other/trurender/', follow_redirects=False)
    assert resp.status_code == 403


def test_unknown_slug_returns_404(app, client, ctai_user):
    _login(client, 'ctai@example.com', 'password123')
    resp = client.get('/p/nope/trurender/', follow_redirects=False)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Template content
# ---------------------------------------------------------------------------

def test_overview_renders_cta_link_to_new_project(app, client, ctai_user):
    _login(client, 'ctai@example.com', 'password123')
    resp = client.get('/p/ctai/trurender/', follow_redirects=False)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'TruRender Overview' in body
    # CTA box link to the placeholder route
    assert '/p/ctai/trurender/new' in body
    assert '+ New Rendering to Photograph Transform Project' in body


def test_new_project_renders_placeholder_copy(app, client, ctai_user):
    _login(client, 'ctai@example.com', 'password123')
    resp = client.get('/p/ctai/trurender/new', follow_redirects=False)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Coming in R2' in body
    # Round-2 Config C is the proven winner per TruRender Technical Reference.
    assert 'Config C' in body


def test_overview_extends_base_with_ctai_palette(app, client, ctai_user):
    """Overview must extend base.html and inject the same client CSS vars
    the dashboard uses, so the Special-Gothic + coral palette carries
    through to the sub-page.
    """
    _login(client, 'ctai@example.com', 'password123')
    resp = client.get('/p/ctai/trurender/', follow_redirects=False)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '--client-primary: #FA6202' in body
    assert '--client-accent: #878787' in body
    assert "Special Gothic" in body
    # portal.css is linked
    assert 'portal.css' in body


# ---------------------------------------------------------------------------
# Service stub
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('func_name', [
    'list_jobs', 'get_job', 'create_job', 'submit_job', 'cancel_job',
])
def test_service_stub_functions_raise_not_implemented(func_name):
    """Every public function on the service stub raises
    :class:`TruRenderNotConfigured` so callers can catch it cleanly in R2.
    """
    func = getattr(trurender, func_name)
    with pytest.raises(TruRenderNotConfigured):
        func()


def test_trurender_not_configured_is_not_implemented():
    """The placeholder exception type must subclass NotImplementedError so
    existing 500-handling code that catches NotImplementedError keeps
    working.
    """
    assert issubclass(TruRenderNotConfigured, NotImplementedError)
