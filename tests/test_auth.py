"""
tests/test_auth.py
Tests for authentication routes (login, logout, protected access).
"""


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------

def test_login_page_returns_200(client):
    resp = client.get('/p/login')
    assert resp.status_code == 200


def test_login_page_contains_form(client):
    html = client.get('/p/login').data.decode()
    assert 'email' in html.lower()
    assert 'password' in html.lower()


# ---------------------------------------------------------------------------
# Login with valid credentials
# ---------------------------------------------------------------------------

def test_login_valid_credentials_redirects(app, client, test_user):
    resp = client.post('/p/login', data={
        'action': 'login',
        'email': 'user@test.com',
        'password': 'password123',
    }, follow_redirects=False)
    # Should redirect (302) to the dashboard
    assert resp.status_code == 302
    assert '/p/dashboard' in resp.headers.get('Location', '')


def test_login_valid_credentials_sets_session(app, client, test_user):
    # Login
    client.post('/p/login', data={
        'action': 'login',
        'email': 'user@test.com',
        'password': 'password123',
    })
    # Accessing dashboard should redirect to the client slug dashboard (not back to login)
    resp = client.get('/p/dashboard', follow_redirects=False)
    # Should redirect to /p/test-corp (the client slug), not to login
    location = resp.headers.get('Location', '')
    assert '/p/login' not in location


# ---------------------------------------------------------------------------
# Login with bad credentials
# ---------------------------------------------------------------------------

def test_login_wrong_password_redirects_to_login(app, client, test_user):
    resp = client.post('/p/login', data={
        'action': 'login',
        'email': 'user@test.com',
        'password': 'wrongpassword',
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert '/p/login' in resp.headers.get('Location', '')


def test_login_wrong_password_flashes_error(app, client, test_user):
    resp = client.post('/p/login', data={
        'action': 'login',
        'email': 'user@test.com',
        'password': 'wrongpassword',
    }, follow_redirects=True)
    html = resp.data.decode()
    assert 'Invalid email or password' in html


def test_login_nonexistent_email_redirects(app, client, test_user):
    resp = client.post('/p/login', data={
        'action': 'login',
        'email': 'nobody@test.com',
        'password': 'whatever',
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert '/p/login' in resp.headers.get('Location', '')


def test_login_nonexistent_email_flashes_error(app, client, test_user):
    resp = client.post('/p/login', data={
        'action': 'login',
        'email': 'nobody@test.com',
        'password': 'whatever',
    }, follow_redirects=True)
    html = resp.data.decode()
    assert 'Invalid email or password' in html


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

def test_logout_redirects_to_login(app, client, test_user):
    # Login first
    client.post('/p/login', data={
        'action': 'login',
        'email': 'user@test.com',
        'password': 'password123',
    })
    resp = client.get('/p/logout', follow_redirects=False)
    assert resp.status_code == 302
    assert '/p/login' in resp.headers.get('Location', '')


def test_logout_clears_session(app, client, test_user):
    # Login
    client.post('/p/login', data={
        'action': 'login',
        'email': 'user@test.com',
        'password': 'password123',
    })
    # Logout
    client.get('/p/logout')
    # Try to access protected page — should redirect to login
    resp = client.get('/p/dashboard', follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get('Location', '')
    assert '/p/login' in location


# ---------------------------------------------------------------------------
# Protected route requires login
# ---------------------------------------------------------------------------

def test_dashboard_requires_login(app, db_session):
    """Unauthenticated access to a protected route redirects to login."""
    test_client = app.test_client()
    resp = test_client.get('/p/dashboard', follow_redirects=False)
    assert resp.status_code == 302
    assert '/p/login' in resp.headers.get('Location', '')
