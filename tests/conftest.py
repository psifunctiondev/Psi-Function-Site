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
