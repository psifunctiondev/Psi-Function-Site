import pytest

from app import create_app
from app.extensions import db as _db
from app.models.client import Client
from app.models.user import User


@pytest.fixture
def app():
    app = create_app('pytest')
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    """Create all tables for the test, yield the db session, then tear down."""
    with app.app_context():
        _db.create_all()
        yield _db.session
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def test_user(db_session):
    """A regular (non-admin) user linked to a test client."""
    c = Client(name='Test Corp', slug='test-corp')
    db_session.add(c)
    db_session.flush()

    user = User(
        email='user@test.com',
        display_name='Test User',
        is_admin=False,
        client_id=c.id,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_user(db_session):
    """An admin user (no client association)."""
    user = User(
        email='admin@test.com',
        display_name='Admin User',
        is_admin=True,
    )
    user.set_password('adminpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def drift_and_anchor_client(db_session):
    """A Drift & Anchor client row matching the BRANDING_PROFILES entry.

    Moved here from test_drift_and_anchor_portal.py so it can be shared
    across the portal tests AND the competitive-audit tests without
    duplicating the fixture definition.
    """
    c = Client(
        slug='drift-and-anchor',
        name='Drift & Anchor',
        primary_color='#160E33',
        accent_color='#C9A66B',
        tagline='Your brand is everything. And nothing without the right story.',
        logo_url='https://example.com/da-logo.png',
        banner_url='https://example.com/da-banner.jpg',
        font_url=(
            'https://fonts.googleapis.com/css2?'
            'family=DM+Serif+Display:ital,wght@0,400;1,400'
        ),
        font_display='"DM Serif Display", serif',
        logo_max_height='5rem',
        is_active=True,
    )
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture(autouse=True)
def _portal_writes_op_bridge(request, monkeypatch):
    """Auto-mock current_op_client + get_client_projects for portal write tests.

    Tests in test_portal_openproject_writes.py route OP writes through
    _resolve_op_project, which imports current_op_client from
    app.services.openproject_config. The test file's patches against
    app.services.openproject_writes.current_op_client (a re-export) miss
    the route's import, and get_client_projects is not always mocked, so
    the route aborts 404 against op.example.com. This fixture installs the
    missing mocks at the canonical paths. Tests that explicitly patch
    current_op_client at the right path or get_client_projects inside a
    `with` block take precedence (innermost wins).

    Skipped for the 503 env-missing tests so current_op_client keeps
    raising OpenProjectConfigError.
    """
    if 'test_portal_openproject_writes.py' not in str(request.fspath):
        return
    if 'returns_503_when_op_env_missing' in request.node.name:
        return

    from unittest import mock
    op = mock.MagicMock()
    op.get_statuses.return_value = [
        {'id': 1, 'name': 'New'},
        {'id': 3, 'name': 'In progress'},
        {'id': 7, 'name': 'Completed'},
    ]
    op.get_project.return_value = {'id': 42, 'name': 'Master'}
    op.get_work_package.return_value = {
        'id': 99, 'lockVersion': 1, 'position': 3,
        '_links': {'status': {'title': 'New'}},
    }
    op.update_work_package_status.return_value = {
        'id': 99, 'lockVersion': 2,
        '_links': {'status': {'title': 'In progress'}},
    }
    op.update_work_package_priority_order.return_value = {
        'id': 99, 'lockVersion': 2, 'position': 5,
    }
    op.post_work_package_comment.return_value = {'id': 1}
    monkeypatch.setattr(
        'app.services.openproject_config.current_op_client',
        lambda: op,
    )
    monkeypatch.setattr(
        'app.services.openproject_portal.get_client_projects',
        lambda client, op_client: [
            {'id': 42, 'name': 'Master', 'portal_role': 'master'}
        ],
    )
