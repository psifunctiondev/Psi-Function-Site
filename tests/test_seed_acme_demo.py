"""Tests for `flask client seed-acme-demo`.

The seeder must:
  * create the ACME client row (via BRANDING_PROFILES) if missing,
  * create demo@acme.com as a non-admin, active, registered user,
  * be idempotent on re-run,
  * never auto-promote the demo user to admin,
  * honor --password > ACME_DEMO_PASSWORD env > random fallback,
  * not rotate an existing password unless --password is given.
"""

import re

from click.testing import CliRunner

from app.cli import ACME_DEMO_EMAIL, client_cli
from app.models.client import Client
from app.models.user import User


def _invoke(app, args, env=None):
    """Run the seed-acme-demo command inside the test app context."""
    runner = CliRunner(env=env)
    with app.app_context():
        return runner.invoke(client_cli, ['seed-acme-demo', *args])


class TestSeedAcmeDemo:

    def test_creates_client_and_demo_user(self, app, db_session):
        """First run creates the ACME client and demo user from scratch."""
        assert Client.query.filter_by(slug='acme').first() is None
        assert User.query.filter_by(email=ACME_DEMO_EMAIL).first() is None

        result = _invoke(app, ['--password', 'hunter2hunter2'])

        assert result.exit_code == 0, result.output
        client = Client.query.filter_by(slug='acme').first()
        assert client is not None
        assert client.name  # populated from BRANDING_PROFILES['acme']

        user = User.query.filter_by(email=ACME_DEMO_EMAIL).first()
        assert user is not None
        assert user.client_id == client.id
        assert user.is_admin is False
        assert user.is_active_user is True
        assert user.is_registered is True
        assert user.check_password('hunter2hunter2') is True

    def test_is_idempotent(self, app, db_session):
        """Running twice does not duplicate rows or rotate the password."""
        _invoke(app, ['--password', 'first-pass-1234'])
        # Second run with NO --password must not change the password.
        result = _invoke(app, [])

        assert result.exit_code == 0, result.output
        users = User.query.filter_by(email=ACME_DEMO_EMAIL).all()
        assert len(users) == 1
        assert users[0].check_password('first-pass-1234') is True
        clients = Client.query.filter_by(slug='acme').all()
        assert len(clients) == 1

    def test_explicit_password_rotates(self, app, db_session):
        """An explicit --password on a re-run does rotate the password."""
        _invoke(app, ['--password', 'old-password-12'])
        result = _invoke(app, ['--password', 'new-password-12'])

        assert result.exit_code == 0, result.output
        user = User.query.filter_by(email=ACME_DEMO_EMAIL).first()
        assert user.check_password('new-password-12') is True
        assert user.check_password('old-password-12') is False

    def test_env_password_used_when_not_registered(self, app, db_session):
        """ACME_DEMO_PASSWORD env var is used when no flag is passed."""
        result = _invoke(
            app, [], env={'ACME_DEMO_PASSWORD': 'env-supplied-pw1'},
        )

        assert result.exit_code == 0, result.output
        user = User.query.filter_by(email=ACME_DEMO_EMAIL).first()
        assert user.check_password('env-supplied-pw1') is True

    def test_random_password_fallback_is_printed(self, app, db_session):
        """With no flag and no env var, a random password is generated + shown."""
        result = _invoke(app, [])

        assert result.exit_code == 0, result.output
        user = User.query.filter_by(email=ACME_DEMO_EMAIL).first()
        assert user.is_registered is True
        # The CLI should print the generated password exactly once.
        assert 'Generated password' in result.output
        match = re.search(r'^\s{4}(\S+)\s*$', result.output, re.MULTILINE)
        assert match is not None, f'no generated password line in:\n{result.output}'
        generated = match.group(1)
        assert user.check_password(generated) is True

    def test_demo_user_never_promoted_to_admin(self, app, db_session):
        """If somehow demo user got is_admin=True, re-seeding must un-set it."""
        # First seed.
        _invoke(app, ['--password', 'pw-aaaaaaaaaaaaa'])
        user = User.query.filter_by(email=ACME_DEMO_EMAIL).first()
        user.is_admin = True
        db_session.commit()

        result = _invoke(app, [])

        assert result.exit_code == 0, result.output
        user = User.query.filter_by(email=ACME_DEMO_EMAIL).first()
        assert user.is_admin is False

    def test_reactivates_disabled_demo_user(self, app, db_session):
        """A disabled demo user is re-activated on re-seed."""
        _invoke(app, ['--password', 'pw-bbbbbbbbbbbbb'])
        user = User.query.filter_by(email=ACME_DEMO_EMAIL).first()
        user.is_active_user = False
        db_session.commit()

        result = _invoke(app, [])

        assert result.exit_code == 0, result.output
        user = User.query.filter_by(email=ACME_DEMO_EMAIL).first()
        assert user.is_active_user is True
