"""Tests for the idempotent client branding profile seeder.

Covers `BRANDING_PROFILES` data shape and the `_apply_profile` helper
that powers `flask client apply-branding`.
"""

from app.cli import BRANDING_PROFILES, _apply_profile
from app.models.client import Client

EXPECTED_FIELDS = {
    'name',
    'primary_color',
    'accent_color',
    'logo_url',
    'tagline',
    'font_url',
    'font_display',
}


class TestBrandingProfiles:

    def test_ctai_profile_shape(self):
        """CTAI profile exists and covers every brand-relevant field."""
        assert 'ctai' in BRANDING_PROFILES
        profile = BRANDING_PROFILES['ctai']
        assert set(profile.keys()) == EXPECTED_FIELDS

    def test_ctai_profile_values(self):
        """Spot-check the key CTAI brand values."""
        profile = BRANDING_PROFILES['ctai']
        assert profile['name'] == 'Catherine Truman Architects'
        assert profile['primary_color'] == '#FA6202'
        assert profile['accent_color'] == '#878787'
        assert profile['logo_url'] == '/static/images/ctai-logo.svg'
        assert profile['tagline'] == 'Modernizing New England Home Design'

    def test_every_profile_has_name_and_colors(self):
        """Any future profile must at minimum provide a name and colors."""
        for slug, profile in BRANDING_PROFILES.items():
            assert profile.get('name'), f'{slug} missing name'
            assert profile.get('primary_color'), f'{slug} missing primary_color'
            assert profile.get('accent_color'), f'{slug} missing accent_color'


class TestApplyProfile:

    def test_creates_missing_client(self, db_session):
        """Applying a profile to a missing slug creates the Client row."""
        profile = BRANDING_PROFILES['ctai']
        assert Client.query.filter_by(slug='ctai').first() is None

        client, created, changed = _apply_profile('ctai', profile)

        assert created is True
        assert client.slug == 'ctai'
        assert client.name == profile['name']
        assert client.primary_color == profile['primary_color']
        assert client.tagline == profile['tagline']

    def test_updates_existing_client_fields(self, db_session):
        """An existing row is updated in place; unchanged fields stay put."""
        # Pre-existing row with stale branding
        stale = Client(
            slug='ctai',
            name='Stale Name',
            primary_color='#000000',
            accent_color='#888888',
            tagline='old tagline',
        )
        db_session.add(stale)
        db_session.commit()

        profile = BRANDING_PROFILES['ctai']
        client, created, changed = _apply_profile('ctai', profile)

        assert created is False
        assert client.name == profile['name']
        assert client.primary_color == profile['primary_color']
        assert client.tagline == profile['tagline']
        # At minimum name/primary_color/tagline should have flipped
        assert 'name' in changed
        assert 'primary_color' in changed
        assert 'tagline' in changed

    def test_idempotent_second_apply_is_no_op(self, db_session):
        """Second apply reports no changes (true idempotency)."""
        profile = BRANDING_PROFILES['ctai']
        _apply_profile('ctai', profile)

        client, created, changed = _apply_profile('ctai', profile)

        assert created is False
        assert changed == []
        assert client.slug == 'ctai'
