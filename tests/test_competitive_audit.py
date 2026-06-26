"""Tests for the Drift & Anchor competitive-audit intake (R1).

R1 ships:
  - the CompetitiveAuditSubmission model
  - the M1 (table + indexes) and M2 (custom→application) Alembic
    migrations
  - the GET/POST route with ?edit, ?fork, and PRG redirect
  - the template (banner, scoped bold non-italic tagline, NO
    portal-welcome, first-visit card, 5-column grid, history list)
  - the DRIFT_AND_ANCHOR_RESOURCES seeder entry for the Applications
    card

These tests lock in:

  Model:
    - create / read / update round-trip
    - forked_from_id self-FK + backref 'forks'
    - status default + STATUSES enum + status_chip_class mapping
    - default form_data shape (empty slots stored as null)

  Auth:
    - not-logged-in → /p/login redirect
    - own-client D&A user can access
    - admin can access
    - other-client user → 403
    - cross-client ?edit=<id> → 404 (no existence leak)

  GET:
    - empty form renders the first-visit "+ Start New Audit" card
    - ?new=1 reveals the empty form
    - ?edit=<id> prefills form + highlights history row + sets
      submission_id hidden field
    - ?fork=<id> prefills form + sets forked_from_id hidden field,
      NOT submission_id
    - ?edit on a non-D&A row → 404

  POST:
    - missing client_name → flash error + re-render (status 200,
      user input preserved)
    - happy path: create + 302 redirect + correct form_data shape
    - edit in place: submission_id present → UPDATE, no new row
    - fork: forked_from_id present → CREATE new row with FK
    - empty competitor sub-card → stored as null (not {})

  Template:
    - banner block present
    - tagline "Competitive Audit Requests" rendered with
      page-scoped font-weight: 700 override and font-style: normal
    - NO portal-welcome block
    - "+ Start New Audit" first-visit card on empty render
    - form card class .competitive-audit-form-card has hover-suppress
    - 5-column grid renders with correct labels in correct order
    - history list renders

  Seeder:
    - DRIFT_AND_ANCHOR_RESOURCES now includes the competitive-audit
      entry pointing at the new route, in 'application' category,
      sort_order=10

  M2 migration:
    - creating a ClientResource with category='custom', running the
      migration, then reading it back returns 'application'
"""

import re

import pytest

from app.models.client import Client, ClientResource
from app.models.competitive_audit import CompetitiveAuditSubmission
from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(http_client, email, password):
    return http_client.post('/p/login', data={
        'action': 'login',
        'email': email,
        'password': password,
    })


def _make_admin(db_session):
    user = User(email='admin@test.com', is_admin=True)
    user.set_password('adminpass123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_drift_and_anchor_user(db_session, dna_client):
    user = User(
        email='catherine@drift-and-anchor.com',
        display_name='Catherine Sheehan',
        is_admin=False,
        client_id=dna_client.id,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_other_client_and_user(db_session):
    """A non-D&A client + user, used for cross-client 404 tests."""
    other = Client(slug='acme', name='ACME', is_active=True)
    db_session.add(other)
    db_session.flush()
    user = User(
        email='acme-user@example.com',
        display_name='ACME User',
        is_admin=False,
        client_id=other.id,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return other, user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin(db_session):
    return _make_admin(db_session)


@pytest.fixture
def dna_user(db_session, drift_and_anchor_client):
    return _make_drift_and_anchor_user(db_session, drift_and_anchor_client)


@pytest.fixture
def dna_other(db_session):
    return _make_other_client_and_user(db_session)


# ---------------------------------------------------------------------------
# Model — create / read / update / relationships / status
# ---------------------------------------------------------------------------

class TestCompetitiveAuditSubmissionModel:

    def _make_row(self, db_session, client, author, **kwargs):
        defaults = {
            'client_id': client.id,
            'author_id': author.id,
            'form_data': {'client_name': 'Acme', 'competitor_1': None,
                          'competitor_2': None, 'competitor_3': None,
                          'competitor_4': None},
        }
        defaults.update(kwargs)
        sub = CompetitiveAuditSubmission(**defaults)
        db_session.add(sub)
        db_session.commit()
        return sub

    def test_create_and_read_round_trip(self, db_session, drift_and_anchor_client,
                                         dna_user):
        sub = self._make_row(
            db_session, drift_and_anchor_client, dna_user,
            form_data={
                'client_name': 'Acme Co',
                'competitor_1': {
                    'brand_name': 'Beta',
                    'home_url': 'https://beta.com',
                    'include_socials': {
                        'x': True, 'facebook': False,
                        'instagram': False, 'youtube': False,
                    },
                },
                'competitor_2': None, 'competitor_3': None, 'competitor_4': None,
            },
        )
        db_session.refresh(sub)
        assert sub.id is not None
        assert sub.client_id == drift_and_anchor_client.id
        assert sub.author_id == dna_user.id
        assert sub.form_data['client_name'] == 'Acme Co'
        assert sub.form_data['competitor_1']['home_url'] == 'https://beta.com'
        assert sub.form_data['competitor_1']['include_socials']['x'] is True
        # Empty competitor slots stored as null.
        assert sub.form_data['competitor_2'] is None
        assert sub.form_data['competitor_3'] is None
        assert sub.form_data['competitor_4'] is None

    def test_status_defaults_to_submitted(self, db_session, drift_and_anchor_client,
                                          dna_user):
        sub = self._make_row(db_session, drift_and_anchor_client, dna_user)
        assert sub.status == CompetitiveAuditSubmission.STATUS_SUBMITTED

    def test_statuses_constant_lists_all_three(self):
        # R2 will use processing + complete; R1 UI never flips them.
        assert CompetitiveAuditSubmission.STATUSES == (
            'submitted', 'processing', 'complete',
        )

    def test_status_chip_class_mapping(self, db_session, drift_and_anchor_client,
                                       dna_user):
        sub = self._make_row(db_session, drift_and_anchor_client, dna_user)
        sub.status = 'submitted'
        assert sub.status_chip_class == 'status-chip--neutral'
        sub.status = 'processing'
        assert sub.status_chip_class == 'status-chip--accent'
        sub.status = 'complete'
        assert sub.status_chip_class == 'status-chip--success'
        # Unknown status → neutral fallback.
        sub.status = 'bogus'
        assert sub.status_chip_class == 'status-chip--neutral'

    def test_update_form_data_in_place(self, db_session, drift_and_anchor_client,
                                        dna_user):
        sub = self._make_row(
            db_session, drift_and_anchor_client, dna_user,
            form_data={'client_name': 'Original',
                       'competitor_1': None, 'competitor_2': None,
                       'competitor_3': None, 'competitor_4': None},
        )
        sub.form_data = {'client_name': 'Updated',
                         'competitor_1': None, 'competitor_2': None,
                         'competitor_3': None, 'competitor_4': None}
        db_session.commit()
        db_session.refresh(sub)
        assert sub.form_data['client_name'] == 'Updated'

    def test_forked_from_self_fk(self, db_session, drift_and_anchor_client,
                                 dna_user):
        original = self._make_row(db_session, drift_and_anchor_client, dna_user)
        fork = self._make_row(
            db_session, drift_and_anchor_client, dna_user,
            forked_from_id=original.id,
        )
        assert fork.forked_from_id == original.id
        # backref 'forks' surfaces the children.
        assert fork in original.forks
        assert fork.forked_from is original

    def test_forked_from_can_be_null(self, db_session, drift_and_anchor_client,
                                     dna_user):
        sub = self._make_row(db_session, drift_and_anchor_client, dna_user)
        assert sub.forked_from_id is None
        assert sub.forked_from is None
        assert sub.forks == []

    def test_default_form_data_shape_has_one_default_competitor_slot(
        self, db_session, drift_and_anchor_client, dna_user,
    ):
        # Slice 6 (Quinn items 3-5): the template renders ONE
        # competitor sub-card by default; the parser discovers
        # additional indices from submitted form keys. The
        # _EMPTY_FORM_DATA constant therefore only seeds index 1.
        empty = {
            'client_name': '',
            'competitor_1': None,
        }
        sub = self._make_row(
            db_session, drift_and_anchor_client, dna_user,
            form_data=empty,
        )
        db_session.refresh(sub)
        assert 'competitor_1' in sub.form_data
        assert sub.form_data['competitor_1'] is None
        # Slice 6: no hard-coded 2..4 nulls in the empty shape — the
        # parser only writes keys that were actually submitted.
        assert 'competitor_2' not in sub.form_data
        assert 'competitor_3' not in sub.form_data
        assert 'competitor_4' not in sub.form_data

    def test_client_relationship_backref(
        self, db_session, drift_and_anchor_client, dna_user,
    ):
        sub = self._make_row(db_session, drift_and_anchor_client, dna_user)
        assert sub.client is drift_and_anchor_client
        assert sub in drift_and_anchor_client.competitive_audits

    def test_author_relationship_backref(self, db_session, drift_and_anchor_client,
                                          dna_user):
        sub = self._make_row(db_session, drift_and_anchor_client, dna_user)
        assert sub.author is dna_user
        assert sub in dna_user.competitive_audits


# ---------------------------------------------------------------------------
# Auth gate on the route — not-logged-in / wrong-client / admin / own
# ---------------------------------------------------------------------------

class TestRouteAuth:

    def test_route_requires_login(self, app):
        http = app.test_client()
        resp = http.get(
            '/p/drift-and-anchor/competitive-audit/', follow_redirects=False,
        )
        assert resp.status_code == 302
        assert '/p/login' in resp.headers.get('Location', '')

    def test_route_404s_for_wrong_slug_segment(self, app, client, admin):
        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.get('/p/other-client/', follow_redirects=False)
        assert resp.status_code == 404

    def test_admin_can_reach(self, app, client, admin,
                             drift_and_anchor_client):
        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.get(
            '/p/drift-and-anchor/competitive-audit/', follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_own_client_user_can_reach(self, app, client, dna_user,
                                         drift_and_anchor_client):
        _login(client, 'catherine@drift-and-anchor.com', 'password123')
        resp = client.get(
            '/p/drift-and-anchor/competitive-audit/', follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_other_client_user_blocked_with_403(self, app, client, dna_other,
                                                  drift_and_anchor_client):
        _login(client, 'acme-user@example.com', 'password123')
        resp = client.get(
            '/p/drift-and-anchor/competitive-audit/', follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_inactive_dna_client_404s(self, app, client, admin,
                                       drift_and_anchor_client):
        # The route scopes on slug + is_active=True; flipping the bit
        # turns the lookup into a 404 even for admins.
        drift_and_anchor_client.is_active = False
        from app.extensions import db
        db.session.commit()
        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.get(
            '/p/drift-and-anchor/competitive-audit/', follow_redirects=False,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET — empty / ?new / ?edit / ?fork / cross-client 404
# ---------------------------------------------------------------------------

class TestRouteGet:

    def test_empty_render_shows_start_card(self, app, client, admin,
                                            drift_and_anchor_client):
        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.get(
            '/p/drift-and-anchor/competitive-audit/', follow_redirects=False,
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # First-visit card present; form NOT yet rendered.
        assert '+ Start New Audit' in body
        # The form submit button is the "Run Audit" — should be
        # absent on the first-visit card render.
        assert 'Run Audit' not in body
        # The "Save Audit" label was retired in slice 6 — must not
        # leak back into the page.
        assert 'Save Audit' not in body

    def test_new_query_param_reveals_empty_form(self, app, client, admin,
                                                  drift_and_anchor_client):
        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.get(
            '/p/drift-and-anchor/competitive-audit/?new=1',
            follow_redirects=False,
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Form is now visible: Run Audit button rendered.
        assert 'Run Audit' in body
        assert 'Save Audit' not in body
        # First-visit card is NOT also rendered — they're mutually
        # exclusive on this page.
        assert '+ Start New Audit' not in body
        # The client_name field is present and empty.
        assert 'name="client_name"' in body
        assert 'value=""' in body
        # Slice 7 item 2: the "Competitive Audit for Client:" label
        # above client_name was retired; only the input remains.
        assert 'Competitive Audit for Client:' not in body
        assert '>Brand Name:</label>' in body
        assert '>Brand Home Page URL:</label>' in body
        # Exactly ONE default competitor sub-card is rendered.
        # The default card carries data-competitive-audit-card; we
        # count those (not the JS literal that also mentions the
        # attribute name).
        # Exactly one server-rendered card carries the --main modifier
        # (column 2-5 span). Cloned cards don't. CSS comments and JS
        # selectors that mention these class names are out of scope;
        # we instead count a dedicated data attribute that ONLY appears
        # on the server-rendered default card.
        assert body.count('data-server-rendered="1"') == 1
        assert 'data-card-index="2"' not in body
        # The "Add" affordance is present (slice 6 item 4).
        assert 'data-competitive-audit-add' in body
        # Socials label uses the slice 6 (item 9) wording.
        assert '>Socials:</div>' in body
        assert 'Include Socials:' not in body

    def test_edit_prefills_form_and_sets_submission_id_hidden(
        self, app, client, admin, drift_and_anchor_client, dna_user,
    ):
        from app.extensions import db
        sub = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={
                'client_name': 'Edit Me',
                'competitor_1': {
                    'brand_name': 'X',
                    'home_url': 'https://x.com',
                    'include_socials': {
                        'x': True, 'facebook': True,
                        'instagram': False, 'youtube': False,
                    },
                },
                'competitor_2': None, 'competitor_3': None, 'competitor_4': None,
            },
        )
        db.session.add(sub)
        db.session.commit()

        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.get(
            f'/p/drift-and-anchor/competitive-audit/?edit={sub.id}',
            follow_redirects=False,
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Prefilled.
        assert 'value="Edit Me"' in body
        # Submission-id hidden present, forked_from_id NOT present.
        assert 'name="submission_id"' in body
        assert f'value="{sub.id}"' in body
        assert 'name="forked_from_id"' not in body
        # History row is highlighted.
        assert 'competitive-audit-history__row--highlight' in body

    def test_fork_prefills_form_and_sets_forked_from_id_hidden(
        self, app, client, admin, drift_and_anchor_client, dna_user,
    ):
        from app.extensions import db
        sub = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={
                'client_name': 'Fork Me',
                'competitor_1': None, 'competitor_2': None,
                'competitor_3': None, 'competitor_4': None,
            },
        )
        db.session.add(sub)
        db.session.commit()

        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.get(
            f'/p/drift-and-anchor/competitive-audit/?fork={sub.id}',
            follow_redirects=False,
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'value="Fork Me"' in body
        assert 'name="forked_from_id"' in body
        assert f'value="{sub.id}"' in body
        # Fork must NOT carry the submission_id hidden field — that
        # would update the source instead of creating a new row.
        assert 'name="submission_id"' not in body

    def test_edit_cross_client_id_404s(
        self, app, client, admin, drift_and_anchor_client, dna_user,
        dna_other,
    ):
        # Submission belongs to ACME — D&A user must not be able to
        # edit it via the D&A route. 404, NOT 403 (no existence leak).
        from app.extensions import db
        acme_client, _ = dna_other
        other_sub = CompetitiveAuditSubmission(
            client_id=acme_client.id,
            author_id=admin.id,
            form_data={'client_name': 'X',
                       'competitor_1': None, 'competitor_2': None,
                       'competitor_3': None, 'competitor_4': None},
        )
        db.session.add(other_sub)
        db.session.commit()

        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.get(
            f'/p/drift-and-anchor/competitive-audit/?edit={other_sub.id}',
            follow_redirects=False,
        )
        assert resp.status_code == 404

    def test_fork_cross_client_id_404s(
        self, app, client, admin, drift_and_anchor_client, dna_other,
    ):
        from app.extensions import db
        acme_client, _ = dna_other
        other_sub = CompetitiveAuditSubmission(
            client_id=acme_client.id,
            author_id=admin.id,
            form_data={'client_name': 'X',
                       'competitor_1': None, 'competitor_2': None,
                       'competitor_3': None, 'competitor_4': None},
        )
        db.session.add(other_sub)
        db.session.commit()

        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.get(
            f'/p/drift-and-anchor/competitive-audit/?fork={other_sub.id}',
            follow_redirects=False,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST — validation / create / update / fork
# ---------------------------------------------------------------------------

class TestRoutePost:

    def test_missing_client_name_returns_flash_and_preserves_input(
        self, app, client, admin, drift_and_anchor_client,
    ):
        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.post(
            '/p/drift-and-anchor/competitive-audit/',
            data={
                'client_name': '   ',
                'competitor_1_brand_name': 'Brand X',
                'competitor_1_home_url': 'https://x.com',
            },
            follow_redirects=False,
        )
        # 200 with the form re-rendered (NOT a redirect — the
        # validation must surface the error inline).
        assert resp.status_code == 200
        # No row should have been written.
        assert CompetitiveAuditSubmission.query.count() == 0
        with client.session_transaction() as sess:
            flashes = sess.get('_flashes', [])
            assert any('Client name is required' in str(f) for f in flashes)
        # User input is preserved — the brand_name field is still
        # populated so the user doesn't lose their work.
        body = resp.get_data(as_text=True)
        assert 'value="Brand X"' in body

    def test_happy_create_stores_full_shape(
        self, app, client, admin, drift_and_anchor_client, dna_user,
    ):
        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.post(
            '/p/drift-and-anchor/competitive-audit/',
            data={
                'client_name': 'Acme Co',
                'competitor_1_brand_name': 'Beta',
                'competitor_1_home_url': 'https://beta.com',
                'competitor_1_include_x': 'on',
                'competitor_1_include_facebook': 'on',
                # competitor_2..N not posted at all (slice 6: no
                # fixed cap on competitor sub-cards)
            },
            follow_redirects=False,
        )
        # PRG redirect.
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(
            '/p/drift-and-anchor/competitive-audit/',
        )

        sub = CompetitiveAuditSubmission.query.filter_by(
            client_id=drift_and_anchor_client.id,
        ).first()
        assert sub is not None
        assert sub.form_data['client_name'] == 'Acme Co'
        assert sub.form_data['competitor_1']['brand_name'] == 'Beta'
        assert sub.form_data['competitor_1']['home_url'] == 'https://beta.com'
        assert sub.form_data['competitor_1']['include_socials']['x'] is True
        assert sub.form_data['competitor_1']['include_socials']['facebook'] is True
        # Unticked toggles default to False (not True) on a populated
        # sub-card — the "default checked" only applies to UI initial
        # state, not to stored form_data.
        assert sub.form_data['competitor_1']['include_socials']['instagram'] is False
        assert sub.form_data['competitor_1']['include_socials']['youtube'] is False
        # Slice 6: the parser discovers competitor indices from the
        # form keys. Only competitor_1 was posted → form_data should
        # contain exactly that one key (no surprise competitor_2..4
        # null entries from a hard-coded 1..4 range).
        assert 'competitor_1' in sub.form_data
        assert 'competitor_2' not in sub.form_data
        assert 'competitor_3' not in sub.form_data
        assert 'competitor_4' not in sub.form_data
        # And defaults.
        assert sub.status == CompetitiveAuditSubmission.STATUS_SUBMITTED
        assert sub.forked_from_id is None
        assert sub.author_id == admin.id
        assert sub.client_id == drift_and_anchor_client.id

    def test_edit_in_place_updates_existing_row(
        self, app, client, admin, drift_and_anchor_client, dna_user,
    ):
        from app.extensions import db
        original = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={'client_name': 'Original',
                       'competitor_1': None, 'competitor_2': None,
                       'competitor_3': None, 'competitor_4': None},
        )
        db.session.add(original)
        db.session.commit()
        original_id = original.id

        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.post(
            '/p/drift-and-anchor/competitive-audit/',
            data={
                'submission_id': str(original_id),
                'client_name': 'Updated Name',
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

        # Same row, no new row, same id.
        assert CompetitiveAuditSubmission.query.count() == 1
        db.session.refresh(original)
        assert original.id == original_id
        assert original.form_data['client_name'] == 'Updated Name'

    def test_fork_creates_new_row_with_fk(
        self, app, client, admin, drift_and_anchor_client, dna_user,
    ):
        from app.extensions import db
        source = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={'client_name': 'Source',
                       'competitor_1': None, 'competitor_2': None,
                       'competitor_3': None, 'competitor_4': None},
        )
        db.session.add(source)
        db.session.commit()
        source_id = source.id

        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.post(
            '/p/drift-and-anchor/competitive-audit/',
            data={
                'forked_from_id': str(source_id),
                'client_name': 'Forked',
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

        # Two rows: source + fork, fork.forked_from_id = source.id.
        rows = (
            CompetitiveAuditSubmission.query
            .order_by(CompetitiveAuditSubmission.id)
            .all()
        )
        assert len(rows) == 2
        assert rows[0].id == source_id
        assert rows[0].forked_from_id is None
        assert rows[1].forked_from_id == source_id
        assert rows[1].form_data['client_name'] == 'Forked'

    def test_empty_subcard_stored_as_null_not_empty_dict(
        self, app, client, admin, drift_and_anchor_client,
    ):
        _login(client, 'admin@test.com', 'adminpass123')
        # brand_name AND home_url both blank for the extra
        # competitor sub-cards → null. Index 2..4 here stand in for
        # any "added via JS" sub-cards (slice 6 item 5: no cap).
        client.post(
            '/p/drift-and-anchor/competitive-audit/',
            data={
                'client_name': 'Tester',
                'competitor_1_brand_name': 'B1',
                'competitor_1_home_url': 'https://b1.com',
                'competitor_2_brand_name': '',
                'competitor_2_home_url': '',
                'competitor_3_brand_name': '',
                'competitor_3_home_url': '   ',
                'competitor_4_brand_name': '   ',
                'competitor_4_home_url': '',
            },
            follow_redirects=False,
        )

        sub = CompetitiveAuditSubmission.query.first()
        assert sub.form_data['competitor_2'] is None
        # Pure whitespace in either field still counts as empty.
        assert sub.form_data['competitor_3'] is None
        assert sub.form_data['competitor_4'] is None
        # Populated sub-card stores a real dict.
        assert isinstance(sub.form_data['competitor_1'], dict)
        assert sub.form_data['competitor_1']['brand_name'] == 'B1'

    def test_parser_discovers_arbitrary_competitor_indices(
        self, app, client, admin, drift_and_anchor_client,
    ):
        # Slice 6 (Quinn item 5: no upper bound on competitor sub-
        # cards): the parser discovers indices from the form keys,
        # so a submission with competitor_1..competitor_7 should
        # persist all of them.
        _login(client, 'admin@test.com', 'adminpass123')
        data = {'client_name': 'ManyComps'}
        for i in range(1, 8):
            data[f'competitor_{i}_brand_name'] = f'Brand {i}'
            data[f'competitor_{i}_home_url'] = f'https://b{i}.com'
        client.post(
            '/p/drift-and-anchor/competitive-audit/',
            data=data,
            follow_redirects=False,
        )
        sub = CompetitiveAuditSubmission.query.first()
        for i in range(1, 8):
            assert sub.form_data[f'competitor_{i}']['brand_name'] == f'Brand {i}'
            assert sub.form_data[f'competitor_{i}']['home_url'] == f'https://b{i}.com'
        # Nothing leaked past the submitted indices.
        assert 'competitor_8' not in sub.form_data
        assert 'competitor_0' not in sub.form_data

    def test_parser_skips_unsubmitted_indices(
        self, app, client, admin, drift_and_anchor_client,
    ):
        # Slice 6: if only competitor_3 is posted (e.g. the user
        # submitted a sparse form), the parser must NOT surprise-
        # create competitor_1 and competitor_2 entries — only the
        # posted index plus the always-present index 1 (per the
        # parser's "ensure 1 is present" rule) should be written.
        _login(client, 'admin@test.com', 'adminpass123')
        client.post(
            '/p/drift-and-anchor/competitive-audit/',
            data={
                'client_name': 'Sparse',
                'competitor_3_brand_name': 'C3',
                'competitor_3_home_url': 'https://c3.com',
            },
            follow_redirects=False,
        )
        sub = CompetitiveAuditSubmission.query.first()
        # Index 1 is empty → null (template renders it by default
        # even if user didn't fill it).
        assert sub.form_data['competitor_1'] is None
        # Index 2 was not posted and should not appear at all.
        assert 'competitor_2' not in sub.form_data
        # Index 3 is populated.
        assert sub.form_data['competitor_3']['brand_name'] == 'C3'

    def test_post_with_submission_id_cross_client_404s(
        self, app, client, admin, drift_and_anchor_client, dna_other,
    ):
        # Cross-client POST must also 404 — same leak-protection rule.
        from app.extensions import db
        acme_client, _ = dna_other
        other_sub = CompetitiveAuditSubmission(
            client_id=acme_client.id,
            author_id=admin.id,
            form_data={'client_name': 'X',
                       'competitor_1': None, 'competitor_2': None,
                       'competitor_3': None, 'competitor_4': None},
        )
        db.session.add(other_sub)
        db.session.commit()

        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.post(
            '/p/drift-and-anchor/competitive-audit/',
            data={'submission_id': str(other_sub.id),
                  'client_name': 'Hijack'},
            follow_redirects=False,
        )
        assert resp.status_code == 404
        # ACME row was NOT modified.
        db.session.refresh(other_sub)
        assert other_sub.form_data['client_name'] == 'X'

    def test_save_flash_appears_after_redirect(
        self, app, client, admin, drift_and_anchor_client,
    ):
        _login(client, 'admin@test.com', 'adminpass123')
        client.post(
            '/p/drift-and-anchor/competitive-audit/',
            data={'client_name': 'Flash Test'},
            follow_redirects=False,
        )
        # The next GET should surface the success flash.
        resp = client.get(
            '/p/drift-and-anchor/competitive-audit/', follow_redirects=False,
        )
        with client.session_transaction() as sess:
            flashes = sess.get('_flashes', [])
            assert any('Saved' in str(f) for f in flashes)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Template — chrome / 5-column grid / history list / CSS scope
# ---------------------------------------------------------------------------

class TestTemplate:

    def _get(self, client):
        _login(client, 'admin@test.com', 'adminpass123')
        resp = client.get(
            '/p/drift-and-anchor/competitive-audit/?new=1',
            follow_redirects=False,
        )
        assert resp.status_code == 200
        return resp.get_data(as_text=True)

    def test_banner_present(self, app, client, admin, drift_and_anchor_client):
        # Banner URL is set on the fixture (the d&a_client fixture).
        body = self._get(client)
        assert 'portal-banner' in body
        assert 'drift-and-anchor.com' in body or 'da-banner' in body

    def test_tagline_rendered_bold_and_non_italic(
        self, app, client, admin, drift_and_anchor_client,
    ):
        body = self._get(client)
        # Literal text.
        assert 'Competitive Audit Requests' in body
        # Page-scoped CSS override is in the <style> block.
        assert re.search(
            r'\.drift-and-anchor-competitive-audit\s+\.portal__tagline--hero',
            body,
        )
        # The override sets font-style: normal + font-weight: 700
        # within that scoped selector. Find the rule and check both
        # declarations live inside it.
        m = re.search(
            r'(\.drift-and-anchor-competitive-audit\s+\.portal__tagline--hero'
            r'\s*\{[^}]+\})',
            body,
        )
        assert m is not None, 'override rule not found'
        rule = m.group(1)
        assert 'font-style: normal' in rule
        assert 'font-weight: 700' in rule
        # Negative: the override must NOT be unscoped — assert there
        # is no `.portal__tagline--hero { font-style: normal ... }`
        # naked rule that would leak to the landing page.
        assert not re.search(
            r'^\s*\.portal__tagline--hero\s*\{[^}]*font-style:\s*normal',
            body,
            flags=re.MULTILINE,
        )

    def test_no_portal_welcome_block(
        self, app, client, admin, drift_and_anchor_client,
    ):
        body = self._get(client)
        # Spec: "NO portal-welcome block" on this page.
        assert 'portal-welcome' not in body
        assert 'Welcome,' not in body

    def test_first_visit_card_hidden_when_form_visible(
        self, app, client, admin, drift_and_anchor_client,
    ):
        body = self._get(client)
        # Form is visible → the start card is not.
        assert '+ Start New Audit' not in body

    def test_form_card_has_hover_suppress_class(
        self, app, client, admin, drift_and_anchor_client,
    ):
        body = self._get(client)
        assert 'competitive-audit-form-card' in body
        # Hover-suppress rule present and references the form-card class.
        assert re.search(
            r'\.competitive-audit-form-card:hover\s*\{[^}]*transform:\s*none',
            body,
        )

    def test_one_default_competitor_card_spanning_cols_2_to_5(
        self, app, client, admin, drift_and_anchor_client,
    ):
        body = self._get(client)
        # The 5-column grid wrapper still exists (column 1 = client,
        # columns 2-5 = the FIRST competitor sub-card).
        assert 'competitive-audit-grid' in body
        # Column 1 — client name. Slice 7 (item 2): the
        # "Competitive Audit for Client:" label was removed; only
        # the input remains. The label text must NOT render.
        assert 'Competitive Audit for Client:' not in body
        assert 'name="client_name"' in body
        # Exactly ONE competitor sub-card is server-rendered.
        # Count the dedicated data attribute on the server-rendered
        # default card (cloned cards don't carry it).
        assert body.count('data-server-rendered="1"') == 1
        # No card with index 2 is rendered — additional cards are
        # only added by the JS Add click.
        assert 'data-card-index="2"' not in body
        # The default card uses the span-2-to-5 class.
        assert 'competitive-audit-col--main' in body
        # The card carries the Add button affordance.
        assert 'data-competitive-audit-add' in body
        # Default card contains the standard labels and field names
        # for competitor index 1.
        assert 'Competitor 1' in body
        assert 'competitor_1_brand_name' in body
        # Slice 7 (item 3): "Competitor Brand Name:" → "Brand Name:"
        assert '>Brand Name:</label>' in body
        assert 'Competitor Brand Name:' not in body
        assert 'competitor_1_home_url' in body
        # Slice 7 (item 4): "Home Page URL:" → "Brand Home Page URL:".
        # Anchor to the literal `>Home Page URL:</label>` so we don't
        # false-positive on the substring "Home Page URL:" appearing
        # inside "Brand Home Page URL:".
        assert '>Brand Home Page URL:</label>' in body
        assert '>Home Page URL:</label>' not in body
        # Slice 6 (item 9): "Include Socials:" retired; only "Socials:"
        # is rendered now.
        assert '>Socials:</div>' in body
        assert 'Include Socials:' not in body
        # Slice 7 items 11-14: the socials label now sits in a
        # dedicated .competitive-audit-socials__label element, and
        # all four (label + checkbox) pairs sit on the SAME inline
        # row inside .competitive-audit-socials.
        assert 'competitive-audit-socials__label' in body
        # Slice 7 item 12: colons stripped from the checkbox labels
        # (X, Facebook, Instagram, YouTube); the "Socials:" label
        # itself keeps its colon.
        assert '>X</label>' in body
        assert '>Facebook</label>' in body
        assert '>Instagram</label>' in body
        assert '>YouTube</label>' in body
        assert '>X:</label>' not in body
        assert '>Facebook:</label>' not in body
        assert '>Instagram:</label>' not in body
        assert '>YouTube:</label>' not in body
        assert 'competitor_1_include_x' in body
        assert 'competitor_1_include_facebook' in body
        assert 'competitor_1_include_instagram' in body
        assert 'competitor_1_include_youtube' in body
        # Slice 7 items 5-6: brand_name + URL sit side-by-side inside
        # .competitive-audit-fields-grid. Same-line sanity: both
        # field names must appear inside that wrapper.
        fields_block = re.search(
            r'<div class="competitive-audit-fields-grid">(.*?)</div>\s*<!--',
            body, flags=re.S,
        )
        assert fields_block is not None, 'sub-grid wrapper not found'
        inner = fields_block.group(1)
        assert 'competitor_1_brand_name' in inner
        assert 'competitor_1_home_url' in inner
        # Slice 7 items 7-10: top-align declared in the CSS rule.
        assert re.search(
            r'\.competitive-audit-fields-grid\s+\.competitive-audit-row\s*\{'
            r'[^}]*align-items:\s*flex-start',
            body,
        )
        # Slice 7 item 13: .competitive-audit-social > label is no
        # longer font-weight: 700. Slice 6 had pinned it at 700 —
        # the rule must have dropped that.
        social_label_rule = re.search(
            r'\.competitive-audit-social\s*>\s*label\s*\{[^}]+\}',
            body,
        )
        assert social_label_rule is not None, 'social-label rule missing'
        assert 'font-weight: 400' in social_label_rule.group(0)
        assert 'font-weight: 700' not in social_label_rule.group(0)
        # The default card does NOT pre-render indices 2..4 — Quinn
        # (slice 6 items 3-5): single default card, more via JS Add.
        assert 'competitor_2_brand_name' not in body
        assert 'competitor_3_brand_name' not in body
        assert 'competitor_4_brand_name' not in body
        # Order check: brand_name comes before home_url within the
        # default card, and the fields block comes before the socials.
        first_card = body[body.find('Competitor 1'):body.find('data-competitive-audit-extra-cards')]
        assert first_card.find('>Brand Name:</label>') < first_card.find(
            '>Brand Home Page URL:</label>',
        )
        assert first_card.find('>Brand Home Page URL:</label>') < first_card.find(
            '>Socials:</div>',
        )

    def test_action_buttons_get_scoped_font_size_bump(
        self, app, client, admin, drift_and_anchor_client,
    ):
        # Slice 7 item 15: .competitive-audit-actions .btn gets a
        # scoped font-size override (~16px) so the primary CTA reads
        # stronger. The rule must exist; the override must NOT be on
        # a naked .btn selector (would leak globally).
        body = self._get(client)
        rule = re.search(
            r'\.competitive-audit-actions\s+\.btn\s*\{[^}]+\}',
            body,
        )
        assert rule is not None, 'scoped .competitive-audit-actions .btn rule missing'
        rule_body = rule.group(0)
        assert 'font-size' in rule_body
        # Page-scoped (not naked .btn): the selector must start with
        # .competitive-audit-actions. We already asserted that via the
        # regex match.
        # Negative: no naked `.btn { font-size: 16px ... }` or
        # `.btn { font-size: 1rem ... }` rule that would leak.
        assert not re.search(
            r'^\s*\.btn\s*\{[^}]*font-size:\s*(1rem|16px|17px)',
            body,
            flags=re.MULTILINE,
        )

    def test_social_toggles_default_checked_on_first_visit(
        self, app, client, admin, drift_and_anchor_client,
    ):
        body = self._get(client)
        # All four social toggle checkboxes rendered with `checked`.
        # On the empty form the form_data has no include_socials dict
        # at all, so the template falls back to the default-checked
        # branch (socials.get('x', True) etc.).
        for label in ('include_x', 'include_facebook', 'include_instagram',
                      'include_youtube'):
            # Find the first occurrence's enclosing checkbox.
            idx = body.find(f'name="competitor_1_{label}"')
            assert idx > -1
            snippet = body[idx:idx + 200]
            assert 'checked' in snippet

    def test_history_list_renders_rows_in_descending_order(
        self, app, client, admin, drift_and_anchor_client, dna_user,
    ):
        from datetime import UTC, datetime, timedelta

        from app.extensions import db
        older = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={'client_name': 'Older',
                       'competitor_1': None, 'competitor_2': None,
                       'competitor_3': None, 'competitor_4': None},
        )
        newer = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={'client_name': 'Newer',
                       'competitor_1': None, 'competitor_2': None,
                       'competitor_3': None, 'competitor_4': None},
        )
        db.session.add_all([older, newer])
        db.session.commit()
        # Backdate the older one so created_at differs.
        older.created_at = datetime.now(UTC) - timedelta(days=1)
        db_session = db.session
        db_session.commit()

        body = self._get(client)
        assert 'Past Submissions' in body
        assert 'Older' in body
        assert 'Newer' in body
        # Newer comes before Older in the rendered HTML.
        assert body.find('Newer') < body.find('Older')
        # Status chip class on each row.
        assert 'status-chip' in body
        assert 'status-chip--neutral' in body  # default is submitted
        # Edit + Duplicate actions on each row.
        assert f'?edit={older.id}' in body
        assert f'?fork={older.id}' in body


# ---------------------------------------------------------------------------
# Seeder — DRIFT_AND_ANCHOR_RESOURCES now contains the audit entry
# ---------------------------------------------------------------------------

class TestSeederIncludesCompetitiveAudit:

    def test_resource_list_contains_competitive_audit_entry(self):
        from app.cli import DRIFT_AND_ANCHOR_RESOURCES
        titles = [r['title'] for r in DRIFT_AND_ANCHOR_RESOURCES]
        assert 'Competitive Audit' in titles

    def test_competitive_audit_entry_points_at_the_route(self):
        from app.cli import DRIFT_AND_ANCHOR_RESOURCES
        entry = next(
            r for r in DRIFT_AND_ANCHOR_RESOURCES
            if r['title'] == 'Competitive Audit'
        )
        assert entry['external_url'] == '/p/drift-and-anchor/competitive-audit/'

    def test_competitive_audit_entry_is_application_category(self):
        from app.cli import DRIFT_AND_ANCHOR_RESOURCES
        entry = next(
            r for r in DRIFT_AND_ANCHOR_RESOURCES
            if r['title'] == 'Competitive Audit'
        )
        assert entry['category'] == 'application'
        # Sanity: 'application' is a known category on the model.
        assert 'application' in ClientResource.CATEGORIES

    def test_seeder_creates_competitive_audit_row(self, app, db_session):
        # The seeder is idempotent — running it surfaces the row.
        from click.testing import CliRunner

        from app.cli import client_cli
        runner = CliRunner()
        with app.app_context():
            result = runner.invoke(client_cli,
                                   ['seed-drift-and-anchor-resources'])
        assert result.exit_code == 0, result.output

        client = Client.query.filter_by(slug='drift-and-anchor').first()
        assert client is not None
        row = ClientResource.query.filter_by(
            client_id=client.id, title='Competitive Audit',
        ).first()
        assert row is not None
        assert row.category == 'application'
        assert row.external_url == '/p/drift-and-anchor/competitive-audit/'
        assert row.is_visible is True
        # sort_order within 'application' category — pin to 10 so the
        # Applications card on the landing lists this entry first.
        assert row.sort_order == 10


# ---------------------------------------------------------------------------
# M2 migration — ClientResource category 'custom' → 'application'
# ---------------------------------------------------------------------------

class TestMigrationRenameCustomToApplication:

    def test_migration_rewrites_custom_to_application(self, app, db_session):
        # Insert a legacy 'custom' row, then run the same SQL the
        # M2 migration runs (op.execute is a context-bound proxy that
        # can't be invoked outside Alembic's migration runner, so we
        # replicate the statement verbatim here to test the data
        # behavior end-to-end).
        from app.extensions import db
        client = Client.query.filter_by(slug='drift-and-anchor').first()
        if client is None:
            client = Client(slug='drift-and-anchor', name='Drift & Anchor',
                             is_active=True)
            db.session.add(client)
            db.session.flush()
        legacy = ClientResource(
            client_id=client.id,
            title='Legacy Custom Resource',
            category='custom',
            external_url='#',
            sort_order=999,
        )
        db.session.add(legacy)
        db.session.commit()
        legacy_id = legacy.id

        # Confirm the pre-migration state is 'custom'.
        assert ClientResource.query.get(legacy_id).category == 'custom'

        # Run the migration's UPDATE statement directly. Same SQL the
        # migration's upgrade() issues.
        db.session.execute(
            db.text(
                "UPDATE client_resource "
                "SET category = 'application' "
                "WHERE category = 'custom'"
            )
        )
        db.session.commit()
        db.session.expire_all()

        # Post-migration: 'application'.
        after = ClientResource.query.get(legacy_id)
        assert after.category == 'application'

    def test_migration_idempotent_on_clean_state(self, app, db_session):
        # Running the UPDATE twice on a DB with no 'custom' rows must
        # not fail (matches nothing the second time, but is a valid
        # no-op statement).
        from app.extensions import db
        sql = (
            "UPDATE client_resource "
            "SET category = 'application' "
            "WHERE category = 'custom'"
        )
        db.session.execute(db.text(sql))
        db.session.commit()
        db.session.execute(db.text(sql))  # second run is a no-op
        db.session.commit()

    def test_migration_target_column_set_in_docstring(self):
        # Pin the migration's intent — guards against accidental
        # rewrites that change the column.
        import inspect

        from migrations.versions.d2e3f4a5b6c7_rename_client_resource_custom_to_application import (
            upgrade,
        )
        src = inspect.getsource(upgrade)
        assert "category = 'application'" in src
        assert "WHERE category = 'custom'" in src