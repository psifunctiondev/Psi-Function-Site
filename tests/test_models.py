"""
tests/test_models.py
Unit tests for User, Client, and ClientResource models.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.client import Client, ClientResource
from app.models.user import User

# ---------------------------------------------------------------------------
# User model — password hashing
# ---------------------------------------------------------------------------

class TestUserPassword:

    def test_set_and_check_password_correct(self, db_session):
        user = User(email='pw@test.com')
        user.set_password('s3cret!')
        db_session.add(user)
        db_session.commit()

        assert user.check_password('s3cret!') is True

    def test_check_password_wrong(self, db_session):
        user = User(email='pw2@test.com')
        user.set_password('s3cret!')
        db_session.add(user)
        db_session.commit()

        assert user.check_password('wrong') is False

    def test_check_password_no_hash(self, db_session):
        """Unregistered user (password_hash is None) should return False."""
        user = User(email='nohash@test.com')
        db_session.add(user)
        db_session.commit()

        assert user.check_password('anything') is False


# ---------------------------------------------------------------------------
# User model — invite tokens
# ---------------------------------------------------------------------------

class TestUserInviteToken:

    def test_generate_invite_token_sets_fields(self, db_session):
        user = User(email='invite@test.com')
        db_session.add(user)
        db_session.commit()

        token = user.generate_invite_token()
        assert token is not None
        assert user.invite_token == token
        assert user.invite_expires is not None

    def test_invite_token_is_url_safe_string(self, db_session):
        user = User(email='invite2@test.com')
        db_session.add(user)
        db_session.commit()

        token = user.generate_invite_token()
        # URL-safe base64 only uses A-Z, a-z, 0-9, -, _
        import re
        assert re.fullmatch(r'[A-Za-z0-9_-]+', token)

    def test_is_invite_valid_when_not_expired(self, db_session):
        user = User(email='valid@test.com')
        db_session.add(user)
        db_session.commit()
        user.generate_invite_token(expires_hours=72)

        assert user.is_invite_valid is True

    def test_is_invite_valid_when_expired(self, db_session):
        user = User(email='expired@test.com')
        db_session.add(user)
        db_session.commit()
        user.generate_invite_token()
        # Manually set expiry in the past
        user.invite_expires = datetime.now(UTC) - timedelta(hours=1)

        assert user.is_invite_valid is False

    def test_is_invite_valid_when_no_token(self, db_session):
        user = User(email='notoken@test.com')
        db_session.add(user)
        db_session.commit()

        assert user.is_invite_valid is False


# ---------------------------------------------------------------------------
# User model — reset tokens
# ---------------------------------------------------------------------------

class TestUserResetToken:

    def test_generate_reset_token_sets_fields(self, db_session):
        user = User(email='reset@test.com')
        db_session.add(user)
        db_session.commit()

        token = user.generate_reset_token()
        assert token is not None
        assert user.reset_token == token
        assert user.reset_expires is not None

    def test_reset_token_is_url_safe_string(self, db_session):
        user = User(email='reset2@test.com')
        db_session.add(user)
        db_session.commit()

        token = user.generate_reset_token()
        import re
        assert re.fullmatch(r'[A-Za-z0-9_-]+', token)

    def test_is_reset_valid_when_not_expired(self, db_session):
        user = User(email='resetv@test.com')
        db_session.add(user)
        db_session.commit()
        user.generate_reset_token(expires_hours=24)

        assert user.is_reset_valid is True

    def test_is_reset_valid_when_expired(self, db_session):
        user = User(email='resete@test.com')
        db_session.add(user)
        db_session.commit()
        user.generate_reset_token()
        user.reset_expires = datetime.now(UTC) - timedelta(hours=1)

        assert user.is_reset_valid is False

    def test_is_reset_valid_when_no_token(self, db_session):
        user = User(email='resetn@test.com')
        db_session.add(user)
        db_session.commit()

        assert user.is_reset_valid is False


# ---------------------------------------------------------------------------
# User model — properties and repr
# ---------------------------------------------------------------------------

class TestUserProperties:

    def test_is_registered_true(self, db_session):
        user = User(email='reg@test.com')
        user.set_password('pass1234')
        db_session.add(user)
        db_session.commit()

        assert user.is_registered is True

    def test_is_registered_false(self, db_session):
        user = User(email='unreg@test.com')
        db_session.add(user)
        db_session.commit()

        assert user.is_registered is False

    def test_repr(self, db_session):
        user = User(email='repr@test.com')
        db_session.add(user)
        db_session.commit()

        assert repr(user) == '<User repr@test.com>'


# ---------------------------------------------------------------------------
# Client model
# ---------------------------------------------------------------------------

class TestClient:

    def test_create_client(self, db_session):
        c = Client(name='Acme Inc', slug='acme')
        db_session.add(c)
        db_session.commit()

        assert c.id is not None
        assert c.name == 'Acme Inc'
        assert c.slug == 'acme'

    def test_slug_uniqueness(self, db_session):
        c1 = Client(name='Acme Inc', slug='acme-unique')
        db_session.add(c1)
        db_session.commit()

        c2 = Client(name='Acme LLC', slug='acme-unique')
        db_session.add(c2)
        with pytest.raises(Exception):  # noqa: B017
            db_session.commit()
        db_session.rollback()

    def test_repr(self, db_session):
        c = Client(name='Repr Corp', slug='repr-corp')
        db_session.add(c)
        db_session.commit()

        assert repr(c) == '<Client repr-corp>'

    def test_users_relationship(self, db_session):
        c = Client(name='Rel Corp', slug='rel-corp')
        db_session.add(c)
        db_session.flush()

        u = User(email='rel@test.com', client_id=c.id)
        db_session.add(u)
        db_session.commit()

        assert c.users.count() == 1
        assert c.users.first().email == 'rel@test.com'

    def test_resources_relationship(self, db_session):
        c = Client(name='Res Corp', slug='res-corp')
        db_session.add(c)
        db_session.flush()

        r = ClientResource(client_id=c.id, title='Doc A', category='general')
        db_session.add(r)
        db_session.commit()

        assert c.resources.count() == 1
        assert c.resources.first().title == 'Doc A'


# ---------------------------------------------------------------------------
# ClientResource model
# ---------------------------------------------------------------------------

class TestClientResource:

    def test_create_resource(self, db_session):
        c = Client(name='CR Corp', slug='cr-corp')
        db_session.add(c)
        db_session.flush()

        r = ClientResource(client_id=c.id, title='Test Resource', category='proposal')
        db_session.add(r)
        db_session.commit()

        assert r.id is not None
        assert r.title == 'Test Resource'
        assert r.category == 'proposal'

    def test_category_label_known(self, db_session):
        c = Client(name='CL Corp', slug='cl-corp')
        db_session.add(c)
        db_session.flush()

        r = ClientResource(client_id=c.id, title='Prop', category='proposal')
        db_session.add(r)
        db_session.commit()

        assert r.category_label == 'Documents'

    def test_category_label_unknown_fallback(self, db_session):
        c = Client(name='CF Corp', slug='cf-corp')
        db_session.add(c)
        db_session.flush()

        r = ClientResource(client_id=c.id, title='Misc', category='weird stuff')
        db_session.add(r)
        db_session.commit()

        assert r.category_label == 'Weird Stuff'

    def test_categories_dict_keys(self):
        expected_keys = {'proposal', 'backlog', 'guide', 'asset', 'invoice', 'custom', 'general'}
        assert set(ClientResource.CATEGORIES.keys()) == expected_keys

    def test_repr(self, db_session):
        c = Client(name='RR Corp', slug='rr-corp')
        db_session.add(c)
        db_session.flush()

        r = ClientResource(client_id=c.id, title='My Doc', category='guide')
        db_session.add(r)
        db_session.commit()

        assert repr(r) == '<ClientResource My Doc (guide)>'
