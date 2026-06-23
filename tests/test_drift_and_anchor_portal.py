"""Tests for the Drift & Anchor client portal scaffold (R1).

R1 ships the route + template + theming + seed commands for the new
Drift & Anchor client. These tests lock in:

- the BRANDING_PROFILES entry pins the exact client row (name, slug,
  theming, tagline) per Quinn's brief
- the ``/p/drift-and-anchor/`` route is ``@login_required`` (anonymous
  -> /p/login) and the access check matches the dashboard rule
  (own-client user OR admin)
- the landing template renders without throwing and surfaces the
  brand-story hero copy + the services split + the engagement
  placeholder
- the resource seeder creates the initial rows idempotently
- the invite seeder creates the Catherine user + a valid invite
  token (idempotent on re-run, --rotate forces a fresh token)
- the service stub raises :class:`DriftAndAnchorNotConfigured` so
  callers can catch it cleanly in R2

R2 will add tests for the wired-up service module + the engagement
timeline render path.
"""

import re

import pytest
from click.testing import CliRunner

from app.cli import (
    BRANDING_PROFILES,
    DRIFT_AND_ANCHOR_INVITE_EMAIL,
    DRIFT_AND_ANCHOR_INVITE_NAME,
    DRIFT_AND_ANCHOR_RESOURCES,
    client_cli,
)
from app.models.client import Client, ClientResource
from app.models.user import User
from app.services import drift_and_anchor
from app.services.drift_and_anchor import DriftAndAnchorNotConfigured

# ---------------------------------------------------------------------------
# Constants — pin the brief to code so it can't drift.
# ---------------------------------------------------------------------------

EXPECTED_BRANDING = {
    'name': 'Drift & Anchor',
    'slug': 'drift-and-anchor',
    'primary_color': '#160E33',
    'accent_color': '#C9A66B',
    'logo_max_height': '5rem',
    'tagline': 'Brand Strategy and Storytelling Consultancy',
    'font_display': '"DM Serif Display", serif',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _invoke(app, args):
    """Run a client_cli subcommand inside the test app context."""
    runner = CliRunner()
    with app.app_context():
        return runner.invoke(client_cli, args)


def _login(http_client, email, password):
    return http_client.post('/p/login', data={
        'action': 'login',
        'email': email,
        'password': password,
    })


# ---------------------------------------------------------------------------
# Branding profile — pins the brief to BRANDING_PROFILES so deploy-time
# apply-branding --all produces exactly the right client row.
# ---------------------------------------------------------------------------

class TestBrandingProfile:

    def test_drift_and_anchor_profile_exists(self):
        assert 'drift-and-anchor' in BRANDING_PROFILES

    def test_drift_and_anchor_uses_hyphenated_slug(self):
        # Brief is explicit: hyphens matter to the client.
        assert BRANDING_PROFILES['drift-and-anchor']['slug'] == 'drift-and-anchor'

    def test_drift_and_anchor_branding_values(self):
        profile = BRANDING_PROFILES['drift-and-anchor']
        for field, expected in EXPECTED_BRANDING.items():
            assert profile.get(field) == expected, (
                f'BRANDING_PROFILES["drift-and-anchor"][{field!r}] '
                f'is {profile.get(field)!r}, expected {expected!r}'
            )

    def test_drift_and_anchor_logo_url_set(self):
        # Squarespace CDN URL — must be present so the eyebrow logo
        # renders without a broken-image placeholder.
        profile = BRANDING_PROFILES['drift-and-anchor']
        assert profile.get('logo_url', '').startswith('https://')
        assert 'squarespace-cdn.com' in profile['logo_url']
        assert 'DA_logo2.png' in profile['logo_url']

    def test_drift_and_anchor_banner_url_set(self):
        # Stormy seascape banner — used as the hero image on the landing.
        profile = BRANDING_PROFILES['drift-and-anchor']
        assert 'D%26A_social-share' in profile.get('banner_url', '')
        assert 'squarespace' in profile['banner_url']

    def test_drift_and_anchor_font_url_is_google_fonts(self):
        profile = BRANDING_PROFILES['drift-and-anchor']
        assert 'fonts.googleapis.com' in profile.get('font_url', '')


# ---------------------------------------------------------------------------
# Client row — apply-branding creates it with the expected theming.
# ---------------------------------------------------------------------------

class TestDriftAndAnchorClientRow:

    def test_apply_branding_creates_client(self, app, db_session):
        result = _invoke(app, ['apply-branding', '--slug', 'drift-and-anchor'])
        assert result.exit_code == 0, result.output

        client = Client.query.filter_by(slug='drift-and-anchor').first()
        assert client is not None
        assert client.name == 'Drift & Anchor'
        assert client.is_active is True
        assert client.primary_color == '#160E33'
        assert client.accent_color == '#C9A66B'
        assert client.tagline == 'Brand Strategy and Storytelling Consultancy'
        assert client.font_display == '"DM Serif Display", serif'
        assert client.logo_max_height == '5rem'

    def test_apply_branding_all_includes_drift_and_anchor(self, app, db_session):
        # The deploy script runs `apply-branding --all` — Drift & Anchor
        # must be picked up by that call so the client row ships on
        # every release.
        result = _invoke(app, ['apply-branding', '--all'])
        assert result.exit_code == 0, result.output
        assert Client.query.filter_by(slug='drift-and-anchor').first() is not None

    def test_apply_branding_is_idempotent(self, app, db_session):
        _invoke(app, ['apply-branding', '--slug', 'drift-and-anchor'])
        # Second run: no change, no error.
        result = _invoke(app, ['apply-branding', '--slug', 'drift-and-anchor'])
        assert result.exit_code == 0, result.output
        assert result.output.strip().endswith('Unchanged: Drift & Anchor [drift-and-anchor]'), (
            f'expected "Unchanged" line, got: {result.output!r}'
        )


# ---------------------------------------------------------------------------
# Auth gate on the landing route
# ---------------------------------------------------------------------------

class TestDriftAndAnchorRouteAuth:

    def test_route_requires_login(self, app):
        http = app.test_client()
        resp = http.get('/p/drift-and-anchor/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/p/login' in resp.headers.get('Location', '')

    def test_route_404s_for_wrong_slug_segment(self, app, client, admin_user):
        # The route literal is `/p/drift-and-anchor/` so any other slug
        # in the URL should 404, not pass through to a 500.
        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.get('/p/other-client/', follow_redirects=False)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Access control — own-client user OR admin
# ---------------------------------------------------------------------------

@pytest.fixture
def drift_and_anchor_client(db_session):
    """A Drift & Anchor client row matching the BRANDING_PROFILES entry."""
    c = Client(
        slug='drift-and-anchor',
        name='Drift & Anchor',
        primary_color='#160E33',
        accent_color='#C9A66B',
        tagline='Brand Strategy and Storytelling Consultancy',
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


@pytest.fixture
def drift_and_anchor_user(db_session, drift_and_anchor_client):
    from app.models.user import User
    user = User(
        email='catherine@drift-and-anchor.com',
        display_name='Catherine Sheehan',
        is_admin=False,
        client_id=drift_and_anchor_client.id,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def other_client(db_session):
    c = Client(slug='acme', name='ACME', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def other_user(db_session, other_client):
    from app.models.user import User
    user = User(
        email='acme-user@example.com',
        display_name='ACME User',
        is_admin=False,
        client_id=other_client.id,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


class TestDriftAndAnchorRouteAccess:

    def test_own_client_user_can_reach_landing(
        self, app, client, drift_and_anchor_user,
    ):
        _login(client, 'catherine@drift-and-anchor.com', 'password123')
        resp = client.get('/p/drift-and-anchor/', follow_redirects=False)
        assert resp.status_code == 200

    def test_admin_can_reach_landing(
        self, app, client, admin_user, drift_and_anchor_client,
    ):
        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.get('/p/drift-and-anchor/', follow_redirects=False)
        assert resp.status_code == 200

    def test_other_client_user_blocked(
        self, app, client, other_user, drift_and_anchor_client,
    ):
        _login(client, 'acme-user@example.com', 'password123')
        resp = client.get('/p/drift-and-anchor/', follow_redirects=False)
        assert resp.status_code == 403

    def test_unknown_slug_404s(
        self, app, client, admin_user,
    ):
        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.get('/p/no-such-client/', follow_redirects=False)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Template content — brand story + services split + engagement hub
# ---------------------------------------------------------------------------

class TestDriftAndAnchorTemplate:

    def _get_landing_html(self, client, user):
        _login(client, 'catherine@drift-and-anchor.com', 'password123')
        resp = client.get('/p/drift-and-anchor/', follow_redirects=False)
        assert resp.status_code == 200
        return resp.get_data(as_text=True)

    def test_renders_without_throwing(
        self, app, client, drift_and_anchor_user,
    ):
        html = self._get_landing_html(client, drift_and_anchor_user)
        assert html  # non-empty body

    def test_hero_copy_present(
        self, app, client, drift_and_anchor_user,
    ):
        html = self._get_landing_html(client, drift_and_anchor_user)
        # Hero line, verbatim from the brief.
        assert 'Your brand is everything. And nothing without the right story.' in html
        # Brand story body — first 80 chars as a fingerprint.
        assert 'Stories do what facts and logic cannot' in html
        assert 'Drift &amp; Anchor' in html or 'Drift & Anchor' in html

    def test_services_split_present(
        self, app, client, drift_and_anchor_user,
    ):
        html = self._get_landing_html(client, drift_and_anchor_user)
        assert 'Our Services' in html
        # Strategy column
        assert 'Strategy' in html
        assert 'Brand Strategy' in html
        assert 'Research' in html
        assert 'Messaging Strategy' in html
        # Creative column
        assert 'Creative' in html
        assert 'Campaign Development' in html
        assert 'Brand Design' in html

    def test_engagement_placeholder_present(
        self, app, client, drift_and_anchor_user,
    ):
        html = self._get_landing_html(client, drift_and_anchor_user)
        # Mirrors the CTAI "Coming in R2" pattern.
        assert 'Engagement hub' in html
        assert 'coming soon' in html

    def test_themed_palette_in_css(
        self, app, client, drift_and_anchor_user,
    ):
        html = self._get_landing_html(client, drift_and_anchor_user)
        # CSS variables on :root — same shape the dashboard uses.
        assert '--client-primary: #160E33' in html
        assert '--client-accent: #C9A66B' in html
        # 8px radius chosen for the brand's editorial-rounded feel.
        assert '--client-radius: 8px' in html
        # Display font from Google Fonts.
        assert 'DM Serif Display' in html
        # portal.css is linked.
        assert 'portal.css' in html

    def test_logo_and_banner_render(
        self, app, client, drift_and_anchor_user,
    ):
        html = self._get_landing_html(client, drift_and_anchor_user)
        # Eyebrow logo from the BRANDING_PROFILES logo_url.
        assert 'https://example.com/da-logo.png' in html
        # Banner from the BRANDING_PROFILES banner_url.
        assert 'https://example.com/da-banner.jpg' in html
        # portal-page class wraps the body (light-locked block).
        assert 'portal-page' in html
        # Scope class so Drift & Anchor-specific CSS can't bleed.
        assert 'drift-and-anchor' in html

    def test_back_to_portal_link(
        self, app, client, drift_and_anchor_user,
    ):
        html = self._get_landing_html(client, drift_and_anchor_user)
        # The welcome row links back to the standard dashboard.
        assert '/p/drift-and-anchor' in html
        assert 'Back to portal' in html


# ---------------------------------------------------------------------------
# Resource seeder — `flask client seed-drift-and-anchor-resources`
# ---------------------------------------------------------------------------

class TestSeedDriftAndAnchorResources:

    def test_creates_all_seed_rows(self, app, db_session):
        result = _invoke(app, ['seed-drift-and-anchor-resources'])
        assert result.exit_code == 0, result.output

        client = Client.query.filter_by(slug='drift-and-anchor').first()
        assert client is not None
        rows = ClientResource.query.filter_by(client_id=client.id).all()
        assert len(rows) == len(DRIFT_AND_ANCHOR_RESOURCES)

        seeded_titles = {r.title for r in rows}
        expected_titles = {e['title'] for e in DRIFT_AND_ANCHOR_RESOURCES}
        assert seeded_titles == expected_titles

    def test_uses_known_categories(self, app, db_session):
        _invoke(app, ['seed-drift-and-anchor-resources'])
        client = Client.query.filter_by(slug='drift-and-anchor').first()
        rows = ClientResource.query.filter_by(client_id=client.id).all()
        for r in rows:
            assert r.category in ClientResource.CATEGORIES, (
                f'resource {r.title!r} has unknown category {r.category!r}'
            )

    def test_all_rows_visible_by_default(self, app, db_session):
        _invoke(app, ['seed-drift-and-anchor-resources'])
        client = Client.query.filter_by(slug='drift-and-anchor').first()
        rows = ClientResource.query.filter_by(client_id=client.id).all()
        for r in rows:
            assert r.is_visible is True

    def test_is_idempotent(self, app, db_session):
        _invoke(app, ['seed-drift-and-anchor-resources'])
        first_count = ClientResource.query.count()
        result = _invoke(app, ['seed-drift-and-anchor-resources'])
        assert result.exit_code == 0, result.output
        assert ClientResource.query.count() == first_count
        assert 'unchanged' in result.output

    def test_creates_client_if_missing(self, app, db_session):
        # The seeder also creates the client row when absent (via the
        # branding profile) so it can be run in isolation.
        assert Client.query.filter_by(slug='drift-and-anchor').first() is None
        result = _invoke(app, ['seed-drift-and-anchor-resources'])
        assert result.exit_code == 0, result.output
        assert Client.query.filter_by(slug='drift-and-anchor').first() is not None

    def test_engagement_oversight_resource_present(self, app, db_session):
        # The brief lists this row first (sort_order 10) — pin it so a
        # future refactor of the seed payload doesn't silently drop it.
        _invoke(app, ['seed-drift-and-anchor-resources'])
        client = Client.query.filter_by(slug='drift-and-anchor').first()
        row = ClientResource.query.filter_by(
            client_id=client.id, title='Engagement Overview',
        ).first()
        assert row is not None
        assert row.category == 'engagement'
        assert row.sort_order == 10
        assert row.is_visible is True


# ---------------------------------------------------------------------------
# Invite seeder — `flask client seed-drift-and-anchor-invite`
# ---------------------------------------------------------------------------

class TestSeedDriftAndAnchorInvite:

    def test_creates_catherine_with_fresh_invite(self, app, db_session):
        result = _invoke(app, ['seed-drift-and-anchor-invite'])
        assert result.exit_code == 0, result.output

        client = Client.query.filter_by(slug='drift-and-anchor').first()
        assert client is not None

        user = User.query.filter_by(email=DRIFT_AND_ANCHOR_INVITE_EMAIL).first()
        assert user is not None
        assert user.display_name == DRIFT_AND_ANCHOR_INVITE_NAME
        assert user.client_id == client.id
        assert user.is_active_user is True
        assert user.is_admin is False
        assert user.is_registered is False  # password_hash is None
        assert user.invite_token is not None
        assert user.invite_expires is not None
        assert user.is_invite_valid is True

    def test_prints_token_and_invite_url(self, app, db_session):
        result = _invoke(app, ['seed-drift-and-anchor-invite'])
        assert result.exit_code == 0, result.output

        user = User.query.filter_by(email=DRIFT_AND_ANCHOR_INVITE_EMAIL).first()
        # CLI output must surface the token + URL so Quinn can hand off
        # the invite link before AgentMail is wired.
        assert user.invite_token in result.output
        assert '/p/login?mode=register&token=' in result.output
        assert user.invite_token in result.output.split('Invite URL:')[-1]

    def test_is_idempotent_without_rotate(self, app, db_session):
        _invoke(app, ['seed-drift-and-anchor-invite'])
        first = User.query.filter_by(email=DRIFT_AND_ANCHOR_INVITE_EMAIL).first()
        first_token = first.invite_token

        # Re-run WITHOUT --rotate. The existing valid token must
        # persist — burning it on every deploy would invalidate the
        # invite link mid-acceptance.
        result = _invoke(app, ['seed-drift-and-anchor-invite'])
        assert result.exit_code == 0, result.output

        second = User.query.filter_by(email=DRIFT_AND_ANCHOR_INVITE_EMAIL).first()
        assert second.invite_token == first_token
        assert 'unchanged' in result.output

    def test_rotate_forces_fresh_token(self, app, db_session):
        _invoke(app, ['seed-drift-and-anchor-invite'])
        first = User.query.filter_by(email=DRIFT_AND_ANCHOR_INVITE_EMAIL).first()
        first_token = first.invite_token

        result = _invoke(app, ['seed-drift-and-anchor-invite', '--rotate'])
        assert result.exit_code == 0, result.output

        # Expire the test session's identity map so we re-read from the
        # DB rather than the cached pre-rotate user object. The CLI
        # commands each run in their own app context, so without
        # expire_all the second query returns the same Python object
        # that the first CLI run produced.
        db_session.expire_all()
        second = User.query.filter_by(email=DRIFT_AND_ANCHOR_INVITE_EMAIL).first()
        assert second.invite_token is not None
        assert second.invite_token != first_token
        assert 'rotated' in result.output

    def test_rotates_token_when_existing_is_expired(self, app, db_session):
        from datetime import UTC, datetime, timedelta
        _invoke(app, ['seed-drift-and-anchor-invite'])
        user = User.query.filter_by(email=DRIFT_AND_ANCHOR_INVITE_EMAIL).first()
        user.invite_expires = datetime.now(UTC) - timedelta(hours=1)
        db_session.commit()
        original_token = user.invite_token

        result = _invoke(app, ['seed-drift-and-anchor-invite'])
        assert result.exit_code == 0, result.output

        db_session.expire_all()
        user = User.query.filter_by(email=DRIFT_AND_ANCHOR_INVITE_EMAIL).first()
        # An expired token must be refreshed on re-run, even without
        # --rotate, so the invite flow doesn't strand Catherine.
        assert user.invite_token != original_token
        assert user.is_invite_valid is True

    def test_catherine_never_promoted_to_admin(self, app, db_session):
        _invoke(app, ['seed-drift-and-anchor-invite'])
        user = User.query.filter_by(email=DRIFT_AND_ANCHOR_INVITE_EMAIL).first()
        user.is_admin = True
        db_session.commit()

        result = _invoke(app, ['seed-drift-and-anchor-invite'])
        assert result.exit_code == 0, result.output
        user = User.query.filter_by(email=DRIFT_AND_ANCHOR_INVITE_EMAIL).first()
        assert user.is_admin is False

    def test_email_matches_brief_exactly(self, app, db_session):
        # Pin the email — the invite URL flows from this.
        _invoke(app, ['seed-drift-and-anchor-invite'])
        assert User.query.filter_by(
            email='catherine@drift-and-anchor.com',
        ).first() is not None

    def test_invite_token_is_url_safe(self, app, db_session):
        # Same shape as test_models.py — the token must round-trip
        # through a URL without escaping.
        _invoke(app, ['seed-drift-and-anchor-invite'])
        user = User.query.filter_by(email=DRIFT_AND_ANCHOR_INVITE_EMAIL).first()
        assert re.fullmatch(r'[A-Za-z0-9_-]+', user.invite_token)


# ---------------------------------------------------------------------------
# Service stub — every public function raises DriftAndAnchorNotConfigured
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('func_name', [
    'list_engagement_milestones',
    'get_case_studies',
    'list_openproject_projects',
    'list_mkdocs_guides',
    'get_contact_routes',
])
def test_service_stub_functions_raise_not_implemented(func_name):
    """Every public function on the service stub raises
    :class:`DriftAndAnchorNotConfigured` so callers can catch it
    cleanly in R2.
    """
    func = getattr(drift_and_anchor, func_name)
    with pytest.raises(DriftAndAnchorNotConfigured):
        func()


def test_drift_and_anchor_not_configured_is_not_implemented():
    """The placeholder exception type must subclass NotImplementedError
    so existing 500-handling code that catches NotImplementedError
    keeps working.
    """
    assert issubclass(DriftAndAnchorNotConfigured, NotImplementedError)
