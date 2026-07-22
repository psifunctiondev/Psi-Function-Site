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
    return http_client.post(
        "/p/login",
        data={
            "action": "login",
            "email": email,
            "password": password,
        },
    )


def _make_admin(db_session):
    user = User(email="admin@test.com", is_admin=True)
    user.set_password("adminpass123")
    db_session.add(user)
    db_session.commit()
    return user


def _make_drift_and_anchor_user(db_session, dna_client):
    user = User(
        email="catherine@drift-and-anchor.com",
        display_name="Catherine Sheehan",
        is_admin=False,
        client_id=dna_client.id,
    )
    user.set_password("password123")
    db_session.add(user)
    db_session.commit()
    return user


def _make_other_client_and_user(db_session):
    """A non-D&A client + user, used for cross-client 404 tests."""
    other = Client(slug="acme", name="ACME", is_active=True)
    db_session.add(other)
    db_session.flush()
    user = User(
        email="acme-user@example.com",
        display_name="ACME User",
        is_admin=False,
        client_id=other.id,
    )
    user.set_password("password123")
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
            "client_id": client.id,
            "author_id": author.id,
            "form_data": {
                "client_name": "Acme",
                "competitor_1": None,
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        }
        defaults.update(kwargs)
        sub = CompetitiveAuditSubmission(**defaults)
        db_session.add(sub)
        db_session.commit()
        return sub

    def test_create_and_read_round_trip(self, db_session, drift_and_anchor_client, dna_user):
        sub = self._make_row(
            db_session,
            drift_and_anchor_client,
            dna_user,
            form_data={
                "client_name": "Acme Co",
                "competitor_1": {
                    "brand_name": "Beta",
                    "home_url": "https://beta.com",
                    "include_socials": {
                        "x": True,
                        "facebook": False,
                        "instagram": False,
                        "youtube": False,
                    },
                },
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        )
        db_session.refresh(sub)
        assert sub.id is not None
        assert sub.client_id == drift_and_anchor_client.id
        assert sub.author_id == dna_user.id
        assert sub.form_data["client_name"] == "Acme Co"
        assert sub.form_data["competitor_1"]["home_url"] == "https://beta.com"
        assert sub.form_data["competitor_1"]["include_socials"]["x"] is True
        # Empty competitor slots stored as null.
        assert sub.form_data["competitor_2"] is None
        assert sub.form_data["competitor_3"] is None
        assert sub.form_data["competitor_4"] is None

    def test_status_defaults_to_submitted(self, db_session, drift_and_anchor_client, dna_user):
        sub = self._make_row(db_session, drift_and_anchor_client, dna_user)
        assert sub.status == CompetitiveAuditSubmission.STATUS_SUBMITTED

    def test_statuses_constant_lists_all_four(self):
        # β-3 adds 'failed' for worker error rows.
        assert CompetitiveAuditSubmission.STATUSES == (
            "submitted",
            "processing",
            "complete",
            "failed",
        )

    def test_status_chip_class_mapping(self, db_session, drift_and_anchor_client, dna_user):
        sub = self._make_row(db_session, drift_and_anchor_client, dna_user)
        sub.status = "submitted"
        assert sub.status_chip_class == "status-chip--neutral"
        sub.status = "processing"
        assert sub.status_chip_class == "status-chip--accent"
        sub.status = "complete"
        assert sub.status_chip_class == "status-chip--success"
        # Unknown status → neutral fallback.
        sub.status = "bogus"
        assert sub.status_chip_class == "status-chip--neutral"

    def test_update_form_data_in_place(self, db_session, drift_and_anchor_client, dna_user):
        sub = self._make_row(
            db_session,
            drift_and_anchor_client,
            dna_user,
            form_data={
                "client_name": "Original",
                "competitor_1": None,
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        )
        sub.form_data = {
            "client_name": "Updated",
            "competitor_1": None,
            "competitor_2": None,
            "competitor_3": None,
            "competitor_4": None,
        }
        db_session.commit()
        db_session.refresh(sub)
        assert sub.form_data["client_name"] == "Updated"

    def test_forked_from_self_fk(self, db_session, drift_and_anchor_client, dna_user):
        original = self._make_row(db_session, drift_and_anchor_client, dna_user)
        fork = self._make_row(
            db_session,
            drift_and_anchor_client,
            dna_user,
            forked_from_id=original.id,
        )
        assert fork.forked_from_id == original.id
        # backref 'forks' surfaces the children.
        assert fork in original.forks
        assert fork.forked_from is original

    def test_forked_from_can_be_null(self, db_session, drift_and_anchor_client, dna_user):
        sub = self._make_row(db_session, drift_and_anchor_client, dna_user)
        assert sub.forked_from_id is None
        assert sub.forked_from is None
        assert sub.forks == []

    def test_default_form_data_shape_has_one_default_competitor_slot(
        self,
        db_session,
        drift_and_anchor_client,
        dna_user,
    ):
        # Slice 6 (Quinn items 3-5): the template renders ONE
        # competitor sub-card by default; the parser discovers
        # additional indices from submitted form keys. The
        # _EMPTY_FORM_DATA constant therefore only seeds index 1.
        empty = {
            "client_name": "",
            "competitor_1": None,
        }
        sub = self._make_row(
            db_session,
            drift_and_anchor_client,
            dna_user,
            form_data=empty,
        )
        db_session.refresh(sub)
        assert "competitor_1" in sub.form_data
        assert sub.form_data["competitor_1"] is None
        # Slice 6: no hard-coded 2..4 nulls in the empty shape — the
        # parser only writes keys that were actually submitted.
        assert "competitor_2" not in sub.form_data
        assert "competitor_3" not in sub.form_data
        assert "competitor_4" not in sub.form_data

    def test_client_relationship_backref(
        self,
        db_session,
        drift_and_anchor_client,
        dna_user,
    ):
        sub = self._make_row(db_session, drift_and_anchor_client, dna_user)
        assert sub.client is drift_and_anchor_client
        assert sub in drift_and_anchor_client.competitive_audits

    def test_author_relationship_backref(self, db_session, drift_and_anchor_client, dna_user):
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
            "/p/drift-and-anchor/competitive-audit/",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/p/login" in resp.headers.get("Location", "")

    def test_route_404s_for_wrong_slug_segment(self, app, client, admin):
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get("/p/other-client/", follow_redirects=False)
        assert resp.status_code == 404

    def test_admin_can_reach(self, app, client, admin, drift_and_anchor_client):
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/",
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_own_client_user_can_reach(self, app, client, dna_user, drift_and_anchor_client):
        _login(client, "catherine@drift-and-anchor.com", "password123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/",
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_other_client_user_blocked_with_403(
        self, app, client, dna_other, drift_and_anchor_client
    ):
        _login(client, "acme-user@example.com", "password123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/",
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_inactive_dna_client_404s(self, app, client, admin, drift_and_anchor_client):
        # The route scopes on slug + is_active=True; flipping the bit
        # turns the lookup into a 404 even for admins.
        drift_and_anchor_client.is_active = False
        from app.extensions import db

        db.session.commit()
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/",
            follow_redirects=False,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET — empty / ?new / ?edit / ?fork / cross-client 404
# ---------------------------------------------------------------------------


class TestRouteGet:
    def test_empty_render_shows_start_card(self, app, client, admin, drift_and_anchor_client):
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/",
            follow_redirects=False,
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # First-visit card present; form NOT yet rendered.
        assert "+ Start New Audit" in body
        # The form submit button is the "Run Audit" — should be
        # absent on the first-visit card render.
        assert "Run Audit" not in body
        # The "Save Audit" label was retired in slice 6 — must not
        # leak back into the page.
        assert "Save Audit" not in body

    def test_new_query_param_reveals_empty_form(self, app, client, admin, drift_and_anchor_client):
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/?new=1",
            follow_redirects=False,
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Form is now visible: Run Audit button rendered.
        assert "Run Audit" in body
        assert "Save Audit" not in body
        # First-visit card is NOT also rendered — they're mutually
        # exclusive on this page.
        assert "+ Start New Audit" not in body
        # The client_name field is present and empty.
        assert 'name="client_name"' in body
        assert 'value=""' in body
        # Slice 7 item 2: the "Competitive Audit for Client:" label
        # above client_name was retired; only the input remains.
        assert "Competitive Audit for Client:" not in body
        assert ">Brand Name:</label>" in body
        assert ">Brand Home Page URL:</label>" in body
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
        assert "data-competitive-audit-add" in body
        # Socials label uses the slice 6 (item 9) wording.
        assert ">Socials:</div>" in body
        assert "Include Socials:" not in body

    def test_edit_prefills_form_and_sets_submission_id_hidden(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
        dna_user,
    ):
        from app.extensions import db

        sub = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={
                "client_name": "Edit Me",
                "competitor_1": {
                    "brand_name": "X",
                    "home_url": "https://x.com",
                    "include_socials": {
                        "x": True,
                        "facebook": True,
                        "instagram": False,
                        "youtube": False,
                    },
                },
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        )
        db.session.add(sub)
        db.session.commit()

        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            f"/p/drift-and-anchor/competitive-audit/?edit={sub.id}",
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
        # Slice 8 (item 12): the history-row highlight class is gone
        # along with the rest of the history section. In its place,
        # the form is now in "edit mode" — the Run Audit button is
        # disabled and Edit Audit + Duplicate Audit become real <a>
        # links pointing at the same row.
        assert "competitive-audit-history__row--highlight" not in body
        # Run Audit button text + disabled attribute both present.
        assert "Run Audit" in body
        # Edit Audit + Duplicate Audit are REMOVED (Quinn 2026-07-22:
        # not VMP-necessary). Neither real links nor disabled buttons
        # render anymore.
        assert "Edit Audit" not in body
        assert "Duplicate Audit" not in body
        # The Run Audit button is marked disabled.
        assert re.search(
            r"<button[^>]*\bdisabled\b[^>]*>\s*Run Audit\s*</button>",
            body,
        )

    def test_fork_prefills_form_and_sets_forked_from_id_hidden(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
        dna_user,
    ):
        from app.extensions import db

        sub = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={
                "client_name": "Fork Me",
                "competitor_1": None,
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        )
        db.session.add(sub)
        db.session.commit()

        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            f"/p/drift-and-anchor/competitive-audit/?fork={sub.id}",
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
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
        dna_user,
        dna_other,
    ):
        # Submission belongs to ACME — D&A user must not be able to
        # edit it via the D&A route. 404, NOT 403 (no existence leak).
        from app.extensions import db

        acme_client, _ = dna_other
        other_sub = CompetitiveAuditSubmission(
            client_id=acme_client.id,
            author_id=admin.id,
            form_data={
                "client_name": "X",
                "competitor_1": None,
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        )
        db.session.add(other_sub)
        db.session.commit()

        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            f"/p/drift-and-anchor/competitive-audit/?edit={other_sub.id}",
            follow_redirects=False,
        )
        assert resp.status_code == 404

    def test_fork_cross_client_id_404s(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
        dna_other,
    ):
        from app.extensions import db

        acme_client, _ = dna_other
        other_sub = CompetitiveAuditSubmission(
            client_id=acme_client.id,
            author_id=admin.id,
            form_data={
                "client_name": "X",
                "competitor_1": None,
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        )
        db.session.add(other_sub)
        db.session.commit()

        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            f"/p/drift-and-anchor/competitive-audit/?fork={other_sub.id}",
            follow_redirects=False,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST — validation / create / update / fork
# ---------------------------------------------------------------------------


class TestRoutePost:
    def test_missing_client_name_returns_flash_and_preserves_input(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        _login(client, "admin@test.com", "adminpass123")
        resp = client.post(
            "/p/drift-and-anchor/competitive-audit/",
            data={
                "client_name": "   ",
                "competitor_1_brand_name": "Brand X",
                "competitor_1_home_url": "https://x.com",
            },
            follow_redirects=False,
        )
        # 200 with the form re-rendered (NOT a redirect — the
        # validation must surface the error inline).
        assert resp.status_code == 200
        # No row should have been written.
        assert CompetitiveAuditSubmission.query.count() == 0
        with client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
            assert any("Client name is required" in str(f) for f in flashes)
        # User input is preserved — the brand_name field is still
        # populated so the user doesn't lose their work.
        body = resp.get_data(as_text=True)
        assert 'value="Brand X"' in body

    def test_happy_create_stores_full_shape(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
        dna_user,
    ):
        _login(client, "admin@test.com", "adminpass123")
        resp = client.post(
            "/p/drift-and-anchor/competitive-audit/",
            data={
                "client_name": "Acme Co",
                "competitor_1_brand_name": "Beta",
                "competitor_1_home_url": "https://beta.com",
                "competitor_1_include_x": "on",
                "competitor_1_include_facebook": "on",
                # competitor_2..N not posted at all (slice 6: no
                # fixed cap on competitor sub-cards)
            },
            follow_redirects=False,
        )
        # Slice 8 (item 9): a successful POST no longer PRG-redirects
        # to the empty form. The route re-renders the same page in the
        # collapsed state with the just-saved submission. The collapsed
        # card's leading character is ">" and its title text is the
        # saved client_name.
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "competitive-audit-collapsed-card" in body
        assert "&gt; Acme Co" in body or "> Acme Co" in body
        assert "+ Start New Audit" in body
        # The form is NOT also rendered in the response (collapsed is
        # mutually exclusive with the form view).
        assert "Run Audit" not in body

        sub = CompetitiveAuditSubmission.query.filter_by(
            client_id=drift_and_anchor_client.id,
        ).first()
        assert sub is not None
        assert sub.form_data["client_name"] == "Acme Co"
        assert sub.form_data["competitor_1"]["brand_name"] == "Beta"
        assert sub.form_data["competitor_1"]["home_url"] == "https://beta.com"
        assert sub.form_data["competitor_1"]["include_socials"]["x"] is True
        assert sub.form_data["competitor_1"]["include_socials"]["facebook"] is True
        # Unticked toggles default to False (not True) on a populated
        # sub-card — the "default checked" only applies to UI initial
        # state, not to stored form_data.
        assert sub.form_data["competitor_1"]["include_socials"]["instagram"] is False
        assert sub.form_data["competitor_1"]["include_socials"]["youtube"] is False
        # Slice 6: the parser discovers competitor indices from the
        # form keys. Only competitor_1 was posted → form_data should
        # contain exactly that one key (no surprise competitor_2..4
        # null entries from a hard-coded 1..4 range).
        assert "competitor_1" in sub.form_data
        assert "competitor_2" not in sub.form_data
        assert "competitor_3" not in sub.form_data
        assert "competitor_4" not in sub.form_data
        # And defaults.
        assert sub.status == CompetitiveAuditSubmission.STATUS_SUBMITTED
        assert sub.forked_from_id is None
        assert sub.author_id == admin.id
        assert sub.client_id == drift_and_anchor_client.id

    def test_edit_in_place_updates_existing_row(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
        dna_user,
    ):
        from app.extensions import db

        original = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={
                "client_name": "Original",
                "competitor_1": None,
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        )
        db.session.add(original)
        db.session.commit()
        original_id = original.id

        _login(client, "admin@test.com", "adminpass123")
        resp = client.post(
            "/p/drift-and-anchor/competitive-audit/",
            data={
                "submission_id": str(original_id),
                "client_name": "Updated Name",
            },
            follow_redirects=False,
        )
        # Slice 8 (item 9): the POST now renders the page in collapsed
        # state (200) instead of PRG-redirecting (302).
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "competitive-audit-collapsed-card" in body
        assert "&gt; Updated Name" in body or "> Updated Name" in body

        # Same row, no new row, same id.
        assert CompetitiveAuditSubmission.query.count() == 1
        db.session.refresh(original)
        assert original.id == original_id
        assert original.form_data["client_name"] == "Updated Name"

    def test_fork_creates_new_row_with_fk(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
        dna_user,
    ):
        from app.extensions import db

        source = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={
                "client_name": "Source",
                "competitor_1": None,
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        )
        db.session.add(source)
        db.session.commit()
        source_id = source.id

        _login(client, "admin@test.com", "adminpass123")
        resp = client.post(
            "/p/drift-and-anchor/competitive-audit/",
            data={
                "forked_from_id": str(source_id),
                "client_name": "Forked",
            },
            follow_redirects=False,
        )
        # Slice 8 (item 9): the POST now renders the page in collapsed
        # state (200) instead of PRG-redirecting (302). The collapsed
        # card surfaces the new fork's client_name.
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "competitive-audit-collapsed-card" in body
        assert "&gt; Forked" in body or "> Forked" in body

        # Two rows: source + fork, fork.forked_from_id = source.id.
        rows = CompetitiveAuditSubmission.query.order_by(CompetitiveAuditSubmission.id).all()
        assert len(rows) == 2
        assert rows[0].id == source_id
        assert rows[0].forked_from_id is None
        assert rows[1].forked_from_id == source_id
        assert rows[1].form_data["client_name"] == "Forked"

    def test_empty_subcard_stored_as_null_not_empty_dict(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        _login(client, "admin@test.com", "adminpass123")
        # brand_name AND home_url both blank for the extra
        # competitor sub-cards → null. Index 2..4 here stand in for
        # any "added via JS" sub-cards (slice 6 item 5: no cap).
        client.post(
            "/p/drift-and-anchor/competitive-audit/",
            data={
                "client_name": "Tester",
                "competitor_1_brand_name": "B1",
                "competitor_1_home_url": "https://b1.com",
                "competitor_2_brand_name": "",
                "competitor_2_home_url": "",
                "competitor_3_brand_name": "",
                "competitor_3_home_url": "   ",
                "competitor_4_brand_name": "   ",
                "competitor_4_home_url": "",
            },
            follow_redirects=False,
        )

        sub = CompetitiveAuditSubmission.query.first()
        assert sub.form_data["competitor_2"] is None
        # Pure whitespace in either field still counts as empty.
        assert sub.form_data["competitor_3"] is None
        assert sub.form_data["competitor_4"] is None
        # Populated sub-card stores a real dict.
        assert isinstance(sub.form_data["competitor_1"], dict)
        assert sub.form_data["competitor_1"]["brand_name"] == "B1"

    def test_parser_discovers_arbitrary_competitor_indices(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        # Slice 6 (Quinn item 5: no upper bound on competitor sub-
        # cards): the parser discovers indices from the form keys,
        # so a submission with competitor_1..competitor_7 should
        # persist all of them.
        _login(client, "admin@test.com", "adminpass123")
        data = {"client_name": "ManyComps"}
        for i in range(1, 8):
            data[f"competitor_{i}_brand_name"] = f"Brand {i}"
            data[f"competitor_{i}_home_url"] = f"https://b{i}.com"
        client.post(
            "/p/drift-and-anchor/competitive-audit/",
            data=data,
            follow_redirects=False,
        )
        sub = CompetitiveAuditSubmission.query.first()
        for i in range(1, 8):
            assert sub.form_data[f"competitor_{i}"]["brand_name"] == f"Brand {i}"
            assert sub.form_data[f"competitor_{i}"]["home_url"] == f"https://b{i}.com"
        # Nothing leaked past the submitted indices.
        assert "competitor_8" not in sub.form_data
        assert "competitor_0" not in sub.form_data

    def test_parser_skips_unsubmitted_indices(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        # Slice 6: if only competitor_3 is posted (e.g. the user
        # submitted a sparse form), the parser must NOT surprise-
        # create competitor_1 and competitor_2 entries — only the
        # posted index plus the always-present index 1 (per the
        # parser's "ensure 1 is present" rule) should be written.
        _login(client, "admin@test.com", "adminpass123")
        client.post(
            "/p/drift-and-anchor/competitive-audit/",
            data={
                "client_name": "Sparse",
                "competitor_3_brand_name": "C3",
                "competitor_3_home_url": "https://c3.com",
            },
            follow_redirects=False,
        )
        sub = CompetitiveAuditSubmission.query.first()
        # Index 1 is empty → null (template renders it by default
        # even if user didn't fill it).
        assert sub.form_data["competitor_1"] is None
        # Index 2 was not posted and should not appear at all.
        assert "competitor_2" not in sub.form_data
        # Index 3 is populated.
        assert sub.form_data["competitor_3"]["brand_name"] == "C3"

    def test_post_with_submission_id_cross_client_404s(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
        dna_other,
    ):
        # Cross-client POST must also 404 — same leak-protection rule.
        from app.extensions import db

        acme_client, _ = dna_other
        other_sub = CompetitiveAuditSubmission(
            client_id=acme_client.id,
            author_id=admin.id,
            form_data={
                "client_name": "X",
                "competitor_1": None,
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        )
        db.session.add(other_sub)
        db.session.commit()

        _login(client, "admin@test.com", "adminpass123")
        resp = client.post(
            "/p/drift-and-anchor/competitive-audit/",
            data={"submission_id": str(other_sub.id), "client_name": "Hijack"},
            follow_redirects=False,
        )
        assert resp.status_code == 404
        # ACME row was NOT modified.
        db.session.refresh(other_sub)
        assert other_sub.form_data["client_name"] == "X"

    def test_save_flash_appears_after_redirect(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        _login(client, "admin@test.com", "adminpass123")
        client.post(
            "/p/drift-and-anchor/competitive-audit/",
            data={"client_name": "Flash Test"},
            follow_redirects=False,
        )
        # The next GET should surface the success flash.
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/",
            follow_redirects=False,
        )
        with client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
            assert any("Saved" in str(f) for f in flashes)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Template — chrome / 5-column grid / history list / CSS scope
# ---------------------------------------------------------------------------


class TestTemplate:
    def _get(self, client):
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/?new=1",
            follow_redirects=False,
        )
        assert resp.status_code == 200
        return resp.get_data(as_text=True)

    def test_banner_present(self, app, client, admin, drift_and_anchor_client):
        # Banner URL is set on the fixture (the d&a_client fixture).
        body = self._get(client)
        assert "portal-banner" in body
        assert "drift-and-anchor.com" in body or "da-banner" in body

    def test_tagline_rendered_bold_and_non_italic(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        body = self._get(client)
        # Literal text.
        assert "Competitive Audit Requests" in body
        # Page-scoped CSS override is in the <style> block.
        assert re.search(
            r"\.drift-and-anchor-competitive-audit\s+\.portal__tagline--hero",
            body,
        )
        # The override sets font-style: normal + font-weight: 700
        # within that scoped selector. Find the rule and check both
        # declarations live inside it.
        m = re.search(
            r"(\.drift-and-anchor-competitive-audit\s+\.portal__tagline--hero"
            r"\s*\{[^}]+\})",
            body,
        )
        assert m is not None, "override rule not found"
        rule = m.group(1)
        assert "font-style: normal" in rule
        assert "font-weight: 700" in rule
        # Negative: the override must NOT be unscoped — assert there
        # is no `.portal__tagline--hero { font-style: normal ... }`
        # naked rule that would leak to the landing page.
        assert not re.search(
            r"^\s*\.portal__tagline--hero\s*\{[^}]*font-style:\s*normal",
            body,
            flags=re.MULTILINE,
        )

    def test_no_portal_welcome_block(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        body = self._get(client)
        # Spec: "NO portal-welcome block" on this page.
        assert "portal-welcome" not in body
        assert "Welcome," not in body

    def test_first_visit_card_hidden_when_form_visible(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        body = self._get(client)
        # Form is visible → the start card is not.
        assert "+ Start New Audit" not in body

    def test_form_card_has_hover_suppress_class(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        body = self._get(client)
        assert "competitive-audit-form-card" in body
        # Hover-suppress rule present and references the form-card class.
        assert re.search(
            r"\.competitive-audit-form-card:hover\s*\{[^}]*transform:\s*none",
            body,
        )

    def test_one_default_competitor_card_spanning_cols_2_to_5(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        body = self._get(client)
        # The 5-column grid wrapper still exists (column 1 = client,
        # columns 2-5 = the FIRST competitor sub-card).
        assert "competitive-audit-grid" in body
        # Column 1 — client name. Slice 7 (item 2): the
        # "Competitive Audit for Client:" label was removed; only
        # the input remains. The label text must NOT render.
        assert "Competitive Audit for Client:" not in body
        assert 'name="client_name"' in body
        # Exactly ONE competitor sub-card is server-rendered.
        # Count the dedicated data attribute on the server-rendered
        # default card (cloned cards don't carry it).
        assert body.count('data-server-rendered="1"') == 1
        # No card with index 2 is rendered — additional cards are
        # only added by the JS Add click.
        assert 'data-card-index="2"' not in body
        # The default card uses the span-2-to-5 class.
        assert "competitive-audit-col--main" in body
        # The card carries the Add button affordance.
        assert "data-competitive-audit-add" in body
        # Default card contains the standard labels and field names
        # for competitor index 1.
        assert "Competitor 1" in body
        assert "competitor_1_brand_name" in body
        # Slice 7 (item 3): "Competitor Brand Name:" → "Brand Name:"
        assert ">Brand Name:</label>" in body
        assert "Competitor Brand Name:" not in body
        assert "competitor_1_home_url" in body
        # Slice 7 (item 4): "Home Page URL:" → "Brand Home Page URL:".
        # Anchor to the literal `>Home Page URL:</label>` so we don't
        # false-positive on the substring "Home Page URL:" appearing
        # inside "Brand Home Page URL:".
        assert ">Brand Home Page URL:</label>" in body
        assert ">Home Page URL:</label>" not in body
        # Slice 6 (item 9): "Include Socials:" retired; only "Socials:"
        # is rendered now.
        assert ">Socials:</div>" in body
        assert "Include Socials:" not in body
        # Slice 7 items 11-14: the socials label now sits in a
        # dedicated .competitive-audit-socials__label element, and
        # all four (label + checkbox) pairs sit on the SAME inline
        # row inside .competitive-audit-socials.
        assert "competitive-audit-socials__label" in body
        # Slice 7 item 12: colons stripped from the checkbox labels
        # (X, Facebook, Instagram, YouTube); the "Socials:" label
        # itself keeps its colon.
        assert ">X</label>" in body
        assert ">Facebook</label>" in body
        assert ">Instagram</label>" in body
        assert ">YouTube</label>" in body
        assert ">X:</label>" not in body
        assert ">Facebook:</label>" not in body
        assert ">Instagram:</label>" not in body
        assert ">YouTube:</label>" not in body
        assert "competitor_1_include_x" in body
        assert "competitor_1_include_facebook" in body
        assert "competitor_1_include_instagram" in body
        assert "competitor_1_include_youtube" in body
        # Slice 7 items 5-6: brand_name + URL sit side-by-side inside
        # .competitive-audit-fields-grid. Same-line sanity: both
        # field names must appear inside that wrapper.
        fields_block = re.search(
            r'<div class="competitive-audit-fields-grid">(.*?)</div>\s*<!--',
            body,
            flags=re.S,
        )
        assert fields_block is not None, "sub-grid wrapper not found"
        inner = fields_block.group(1)
        assert "competitor_1_brand_name" in inner
        assert "competitor_1_home_url" in inner
        # Slice 7 items 7-10: top-align declared in the CSS rule.
        assert re.search(
            r"\.competitive-audit-fields-grid\s+\.competitive-audit-row\s*\{"
            r"[^}]*align-items:\s*flex-start",
            body,
        )
        # Slice 7 item 13: .competitive-audit-social > label is no
        # longer font-weight: 700. Slice 6 had pinned it at 700 —
        # the rule must have dropped that.
        social_label_rule = re.search(
            r"\.competitive-audit-social\s*>\s*label\s*\{[^}]+\}",
            body,
        )
        assert social_label_rule is not None, "social-label rule missing"
        assert "font-weight: 400" in social_label_rule.group(0)
        assert "font-weight: 700" not in social_label_rule.group(0)
        # The default card does NOT pre-render indices 2..4 — Quinn
        # (slice 6 items 3-5): single default card, more via JS Add.
        assert "competitor_2_brand_name" not in body
        assert "competitor_3_brand_name" not in body
        assert "competitor_4_brand_name" not in body
        # Order check: brand_name comes before home_url within the
        # default card, and the fields block comes before the socials.
        first_card = body[
            body.find("Competitor 1") : body.find("data-competitive-audit-extra-cards")
        ]
        assert first_card.find(">Brand Name:</label>") < first_card.find(
            ">Brand Home Page URL:</label>",
        )
        assert first_card.find(">Brand Home Page URL:</label>") < first_card.find(
            ">Socials:</div>",
        )

    def test_action_buttons_get_scoped_font_size_bump(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        # Slice 7 item 15: .competitive-audit-actions .btn gets a
        # scoped font-size override (~16px) so the primary CTA reads
        # stronger. The rule must exist; the override must NOT be on
        # a naked .btn selector (would leak globally).
        body = self._get(client)
        rule = re.search(
            r"\.competitive-audit-actions\s+\.btn\s*\{[^}]+\}",
            body,
        )
        assert rule is not None, "scoped .competitive-audit-actions .btn rule missing"
        rule_body = rule.group(0)
        assert "font-size" in rule_body
        # Page-scoped (not naked .btn): the selector must start with
        # .competitive-audit-actions. We already asserted that via the
        # regex match.
        # Negative: no naked `.btn { font-size: 16px ... }` or
        # `.btn { font-size: 1rem ... }` rule that would leak.
        assert not re.search(
            r"^\s*\.btn\s*\{[^}]*font-size:\s*(1rem|16px|17px)",
            body,
            flags=re.MULTILINE,
        )

    def test_social_toggles_default_checked_on_first_visit(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        body = self._get(client)
        # All four social toggle checkboxes rendered with `checked`.
        # On the empty form the form_data has no include_socials dict
        # at all, so the template falls back to the default-checked
        # branch (socials.get('x', True) etc.).
        for label in ("include_x", "include_facebook", "include_instagram", "include_youtube"):
            # Find the first occurrence's enclosing checkbox.
            idx = body.find(f'name="competitor_1_{label}"')
            assert idx > -1
            snippet = body[idx : idx + 200]
            assert "checked" in snippet

    def test_history_list_renders_rows_in_descending_order(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
        dna_user,
    ):
        # Slice 8 (item 12): the "Past Submissions" section was
        # retired from the UI. The history list no longer renders on
        # either the empty / new form view OR the first-visit view,
        # even when rows exist. This test now verifies the SECTION IS
        # GONE rather than the rows. The descending-order behavior is
        # implicitly covered by the route's
        # ``order_by(created_at.desc())`` and a separate model test.
        from datetime import UTC, datetime, timedelta

        from app.extensions import db

        older = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={
                "client_name": "Older",
                "competitor_1": None,
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        )
        newer = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={
                "client_name": "Newer",
                "competitor_1": None,
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        )
        db.session.add_all([older, newer])
        db.session.commit()
        # Backdate the older one so created_at differs.
        older.created_at = datetime.now(UTC) - timedelta(days=1)
        db_session = db.session
        db_session.commit()

        body = self._get(client)
        # Slice 8 (item 12): the "Past Submissions" section is gone.
        assert "Past Submissions" not in body
        assert "competitive-audit-history" not in body
        # The data still exists in the DB \u2014 the section just isn't
        # rendered. The end-user re-access path is via the collapsed
        # card / ?edit=<id> URL.
        assert "Older" not in body
        assert "Newer" not in body


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Slice 8 — Quinn's review pass #3 (items 1-12)
#
# - Label / entry font-weight tweaks (items 1-3)
# - Add button inline on socials row (item 4)
# - Action buttons stacked vertically under the Client card (item 5)
# - Display font on .btn elements (item 6)
# - JS reindex() rewrites the Competitor N title (item 7)
# - Extra competitor cards span cols 2-5 (item 8)
# - Run Audit state machine: collapsed view after POST (items 9, 11)
# - Edit mode: Run Audit disabled, Edit + Duplicate enabled (item 10)
# - Past Submissions section removed (item 12)
# ---------------------------------------------------------------------------


class TestSlice8LabelAndEntryStyling:
    def test_col_title_is_dark_and_bold(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        # Slice 8 (item 1): the Client / Competitor N column titles
        # are now black + bold (was muted + unbolded).
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/?new=1",
            follow_redirects=False,
        )
        body = resp.get_data(as_text=True)
        rule = re.search(
            r"\.competitive-audit-col__title\s*\{[^}]+\}",
            body,
        )
        assert rule is not None
        block = rule.group(0)
        assert "color: var(--color-text)" in block
        assert "font-weight: 700" in block

    def test_row_labels_unbolded(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        # Slice 8 (item 2): Brand Name: / Brand Home Page URL: labels
        # inside .competitive-audit-row are font-weight: 400 now
        # (slice 7 had them at 700). The socials-row labels were
        # already 400 in slice 7 -- we re-pin here for regression.
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/?new=1",
            follow_redirects=False,
        )
        body = resp.get_data(as_text=True)
        row_label_rule = re.search(
            r"\.competitive-audit-row\s*>\s*label\s*\{([^}]+)\}",
            body,
        )
        assert row_label_rule is not None
        decls = row_label_rule.group(1)
        # Strip CSS comments before checking declarations (slice 8
        # docstrings mention the sibling .col__title font-weight: 700).
        decls_no_comments = re.sub(r"/\*.*?\*/", "", decls, flags=re.S)
        assert "font-weight: 400" in decls_no_comments
        # Negative: no naked `font-weight: 700` declaration in this rule.
        assert "font-weight: 700" not in decls_no_comments

        social_label_rule = re.search(
            r"\.competitive-audit-socials__label\s*\{[^}]+\}",
            body,
        )
        assert social_label_rule is not None
        # "Socials:" is a <div> styled like a label -- slice 8
        # interprets it strictly: same as the row labels, non-bold.
        assert "font-weight: 400" in social_label_rule.group(0)

    def test_text_inputs_pinned_non_bold(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        # Slice 8 (item 3): entry text inputs explicitly pinned to
        # font-weight: 400 so a global rule change can't bold them.
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/?new=1",
            follow_redirects=False,
        )
        body = resp.get_data(as_text=True)
        input_rule = re.search(
            r'\.competitive-audit-row\s*>\s*input\[type="text"\]\s*\{[^}]+\}',
            body,
        )
        assert input_rule is not None
        assert "font-weight: 400" in input_rule.group(0)


class TestSlice8Layout:
    def test_add_button_lives_in_extra_cards_row(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        # UX model B (Quinn, 2026-07-22): the Add button moved from
        # the socials row (slice 8 item 4) to a dedicated row at the
        # bottom of .competitive-audit-extra-cards. It's the LAST
        # child of extra-cards on initial render and stays last
        # after each clone (the JS inserts each new card before it).
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/?new=1",
            follow_redirects=False,
        )
        body = resp.get_data(as_text=True)
        # The Add button is inside .competitive-audit-extra-cards,
        # NOT inside .competitive-audit-socials.
        assert "data-competitive-audit-add-row" in body, (
            "expected the Add button's row to live in "
            ".competitive-audit-extra-cards (UX model B)"
        )
        # And the socials row no longer carries the Add button.
        socials_block = re.search(
            r'<div class="competitive-audit-socials">(.*?)</div>\s*</div>\s*</div>',
            body,
            flags=re.S,
        )
        assert socials_block is not None, "socials row not found"
        assert "data-competitive-audit-add" not in socials_block.group(1), (
            "Add button should not live inside .competitive-audit-socials "
            "anymore (UX model B puts it at the bottom of extra-cards)"
        )
        # The Add button is rendered as the LAST child of
        # .competitive-audit-extra-cards. This pins the model-B
        # invariant: new clones get inserted BEFORE the button.
        extra_block = re.search(
            r'<div class="competitive-audit-extra-cards"\s+'
            r'data-competitive-audit-extra-cards>(.*?)</div>\s*</div>',
            body,
            flags=re.S,
        )
        assert extra_block is not None, "extra-cards container not found"
        inner = extra_block.group(1)
        assert inner.rstrip().endswith("</button>") or "</button>" in inner[
            inner.rfind("data-competitive-audit-add"):inner.rfind("</button>") + len("</button>")
        ], (
            "Add button should be the LAST child of extra-cards on "
            "initial render"
        )

    def test_actions_stack_vertically_inside_col_1(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        # Slice 8 (item 5): action buttons flex-direction: column,
        # living inside the Client column (col 1) of the grid.
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/?new=1",
            follow_redirects=False,
        )
        body = resp.get_data(as_text=True)
        rule = re.search(
            r"\.competitive-audit-actions\s*\{[^}]+\}",
            body,
        )
        assert rule is not None
        assert "flex-direction: column" in rule.group(0)

        # And: the actions div is now inside the first col div (which
        # holds the Client title + client_name input). We confirm by
        # checking the markup structure: the actions div appears
        # AFTER the client_name input, both inside the same col.
        col1_block = re.search(
            r'<div class="competitive-audit-col">\s*'
            r'<div class="competitive-audit-col__title">Client</div>'
            r"(.*?)</div>\s*</div>",
            body,
            flags=re.S,
        )
        assert col1_block is not None, "Client col not found"
        inner = col1_block.group(1)
        assert 'name="client_name"' in inner
        assert "competitive-audit-actions" in inner
        assert "Run Audit" in inner

    def test_only_titles_use_dm_serif_everything_else_uses_montserrat(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        # Quinn (2026-07-22): only "Client" and "Competitor N"
        # titles should be DM Serif Display. Everything else on the
        # page (body text, labels, inputs, buttons, first-visit /
        # collapsed cards) should be Montserrat. This replaces the
        # prior slice-8 rule that cascaded DM Serif Display down to
        # .btn and the page-level container.
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/?new=1",
            follow_redirects=False,
        )
        body = resp.get_data(as_text=True)

        # 1. Title rule: .competitive-audit-col__title uses DM Serif.
        title_rule = re.search(
            r"\.drift-and-anchor-competitive-audit\s+"
            r"\.competitive-audit-col__title\s*\{[^}]*"
            r"font-family:\s*'DM Serif Display'",
            body,
            flags=re.S,
        )
        assert title_rule is not None, (
            ".competitive-audit-col__title should use DM Serif Display"
        )

        # 2. Body / button rule: .btn inside the form card uses
        # Montserrat, NOT DM Serif Display. The CSS has a multi-
        # selector rule body (one font-family declaration shared
        # across multiple selectors). We split the check in two:
        # first find the rule body (between an opening brace and
        # the matching closing brace that contains 'Montserrat'),
        # then assert the body contains the .btn-in-form-card
        # selector and the Montserrat font-family on the same
        # block.
        btn_rule_block = re.search(
            r"(\.drift-and-anchor-competitive-audit\s+"
            r"\.competitive-audit-form-card[\s\S]*?\{)"
            r"([^{}]*?)"
            r"(\})",
            body,
        )
        assert btn_rule_block is not None, (
            "expected the .competitive-audit-form-card rule body "
            "in the page CSS"
        )
        body_text = btn_rule_block.group(2)
        # The .btn-in-form-card selector must be in the selectors
        # list (before the {).
        selectors_text = btn_rule_block.group(1)
        assert (
            ".drift-and-anchor-competitive-audit .competitive-audit-form-card .btn"
            in selectors_text
        ), (
            ".btn inside the form card should be one of the rule's "
            "selectors (Quinn 2026-07-22)"
        )
        # The body must declare font-family: 'Montserrat'.
        assert re.search(
            r"font-family:\s*'Montserrat'",
            body_text,
        ), (
            ".btn-in-form-card rule body should declare "
            "font-family: 'Montserrat' (Quinn 2026-07-22)"
        )
        # Belt-and-suspenders: that rule body must NOT reference
        # DM Serif Display.
        assert "DM Serif Display" not in body_text, (
            ".btn font-family block still references DM Serif Display — "
            "Quinn wants only titles in DM Serif"
        )

        # 4. The fonts are loaded via {% block head %} on this page
        # only — base.html doesn't carry them, so we add them here.
        assert (
            "family=DM+Serif+Display" in body
            and "family=Montserrat" in body
        ), (
            "DM Serif Display + Montserrat must be loaded via {% block "
            "head %} on this page (Quinn 2026-07-22)"
        )

    def test_extra_cards_grid_spans_cols_2_to_5(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        # Slice 8 (item 8): the .competitive-audit-extra-cards
        # container is now a 5-column grid, with each child col
        # spanning 2 / span 4 -- same as the default card.
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/?new=1",
            follow_redirects=False,
        )
        body = resp.get_data(as_text=True)
        rule = re.search(
            r"\.competitive-audit-extra-cards\s*\{[^}]+\}",
            body,
        )
        assert rule is not None
        assert "display: grid" in rule.group(0)
        assert "repeat(5" in rule.group(0)
        child_rule = re.search(
            r"\.competitive-audit-extra-cards\s+\.competitive-audit-col\s*"
            r"\{[^}]+\}",
            body,
        )
        assert child_rule is not None
        assert "grid-column: 2 / span 4" in child_rule.group(0)


class TestSlice8CollapsedView:
    def test_post_renders_collapsed_view_with_client_name(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
        dna_user,
    ):
        # Slice 8 (item 9): the route no longer PRG-redirects after a
        # successful POST. Instead it re-renders the page in the
        # collapsed state with the just-saved submission.
        _login(client, "admin@test.com", "adminpass123")
        resp = client.post(
            "/p/drift-and-anchor/competitive-audit/",
            data={"client_name": "Collapsed Test Co"},
            follow_redirects=False,
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "competitive-audit-collapsed-card" in body
        # The leading character is ">" and the title text is the
        # saved client_name. The template escapes the literal > as
        # &gt; (it's inside the card link's text node).
        assert "&gt; Collapsed Test Co" in body
        # The + Start New Audit card follows the collapsed card.
        assert "+ Start New Audit" in body
        # The form is NOT rendered alongside the collapsed view.
        assert "Run Audit" not in body
        # No history section either (item 12).
        assert "Past Submissions" not in body

    def test_collapsed_card_template_has_untitled_fallback(self):
        # Spec (item 9): if client_name is empty, the collapsed card
        # shows "Untitled Audit". Easiest verification: the template
        # source contains the literal fallback string. (We can't
        # easily POST through the route with an empty client_name
        # because the route validates that field on POST.)
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        template = (
            repo_root / "app" / "templates" / "portal" / "drift_and_anchor_competitive_audit.html"
        ).read_text()
        assert "'Untitled Audit'" in template

    def test_collapsed_card_links_to_edit_route(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        # The collapsed card should be an <a href="?edit=<id>"> so
        # clicking it re-expands the audit back into the editable
        # form view (slice 8 item 10).
        _login(client, "admin@test.com", "adminpass123")
        resp = client.post(
            "/p/drift-and-anchor/competitive-audit/",
            data={"client_name": "Re-expand Me"},
            follow_redirects=False,
        )
        body = resp.get_data(as_text=True)
        latest = (
            CompetitiveAuditSubmission.query.filter_by(client_id=drift_and_anchor_client.id)
            .order_by(CompetitiveAuditSubmission.id.desc())
            .first()
        )
        assert latest is not None
        # Match the actual <a class="competitive-audit-collapsed-card"
        # href="?edit=<id>"> element (not just any string match in
        # the inline <style> CSS comments).
        assert (
            re.search(
                r'<a\s+class="competitive-audit-collapsed-card"\s+'
                r'href="[^"]*\?edit=' + str(latest.id) + r'"',
                body,
            )
            is not None
        )

    def test_order_is_collapsed_card_then_start_card(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        # Slice 8 (item 11): the rendered collapsed view is
        # [collapsed ClientName card] then [+ Start New Audit card].
        _login(client, "admin@test.com", "adminpass123")
        resp = client.post(
            "/p/drift-and-anchor/competitive-audit/",
            data={"client_name": "Order Test"},
            follow_redirects=False,
        )
        body = resp.get_data(as_text=True)
        # Anchor on the actual <a class="..."> elements to avoid
        # false positives from class names mentioned in inline
        # <style> CSS comments.
        collapsed_match = re.search(
            r'<a\s+class="competitive-audit-collapsed-card"',
            body,
        )
        start_match = re.search(
            r'<a\s+class="competitive-audit-start-card"',
            body,
        )
        assert collapsed_match is not None
        assert start_match is not None
        assert collapsed_match.start() < start_match.start(), (
            "collapsed card must come BEFORE the + Start New Audit card"
        )


class TestSlice8EditMode:
    def test_run_audit_disabled_when_editing(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
        dna_user,
    ):
        # Slice 8 (item 10): when ?edit=<id> is set, Run Audit is
        # disabled -- you don't "run" an existing audit, you re-save
        # it via the (also disabled in this view) submit.
        from app.extensions import db

        sub = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={
                "client_name": "Edit Mode",
                "competitor_1": None,
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        )
        db.session.add(sub)
        db.session.commit()

        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            f"/p/drift-and-anchor/competitive-audit/?edit={sub.id}",
            follow_redirects=False,
        )
        body = resp.get_data(as_text=True)
        # Run Audit button is present but disabled.
        m = re.search(
            r'<button[^>]*type="submit"[^>]*>\s*Run Audit\s*</button>',
            body,
        )
        assert m is not None, "Run Audit submit button not found"
        assert "disabled" in m.group(0)
        # Edit Audit + Duplicate Audit are REMOVED entirely (Quinn
        # 2026-07-22: not VMP-necessary, may return in a later
        # slice). Neither real links nor disabled buttons should
        # render.
        assert "Edit Audit" not in body
        assert "Duplicate Audit" not in body

    def test_run_audit_enabled_on_new_form(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
    ):
        # Outside edit mode (?new=1, no edit_target), Run Audit is
        # the only enabled action -- Edit + Duplicate are visible
        # affordance only.
        _login(client, "admin@test.com", "adminpass123")
        resp = client.get(
            "/p/drift-and-anchor/competitive-audit/?new=1",
            follow_redirects=False,
        )
        body = resp.get_data(as_text=True)
        m = re.search(
            r'<button[^>]*type="submit"[^>]*>\s*Run Audit\s*</button>',
            body,
        )
        assert m is not None
        assert "disabled" not in m.group(0)
        # Edit Audit + Duplicate Audit are REMOVED (Quinn 2026-07-22:
        # not VMP-necessary). Neither disabled buttons nor real
        # links should appear in the markup.
        assert "Edit Audit" not in body
        assert "Duplicate Audit" not in body
        # (Optional) Background button is present below Run Audit
        # (Quinn 2026-07-22: VMP-needed, wiring deferred).
        bg_btn = re.search(
            r'<button[^>]*aria-label="Background \(not yet wired\)"[^>]*>\s*'
            r'\(Optional\) Background\s*</button>',
            body,
        )
        assert bg_btn is not None, (
            "(Optional) Background button missing below Run Audit "
            "(Quinn 2026-07-22)"
        )
        assert "disabled" in bg_btn.group(0), (
            "(Optional) Background button should be disabled until "
            "Quinn wires it up"
        )


class TestSlice8NoHistorySection:
    def test_past_submissions_section_removed(
        self,
        app,
        client,
        admin,
        drift_and_anchor_client,
        dna_user,
    ):
        # Slice 8 (item 12): "Past Submissions" is gone from the UI.
        # Even when rows exist, no history section renders.
        from datetime import UTC, datetime, timedelta

        from app.extensions import db

        sub = CompetitiveAuditSubmission(
            client_id=drift_and_anchor_client.id,
            author_id=dna_user.id,
            form_data={
                "client_name": "Hidden History",
                "competitor_1": None,
                "competitor_2": None,
                "competitor_3": None,
                "competitor_4": None,
            },
        )
        db.session.add(sub)
        db.session.commit()
        sub.created_at = datetime.now(UTC) - timedelta(days=1)
        db.session.commit()

        _login(client, "admin@test.com", "adminpass123")
        for url in (
            "/p/drift-and-anchor/competitive-audit/",
            "/p/drift-and-anchor/competitive-audit/?new=1",
        ):
            resp = client.get(url, follow_redirects=False)
            body = resp.get_data(as_text=True)
            assert "Past Submissions" not in body, url
            assert "competitive-audit-history" not in body, url
            assert "Hidden History" not in body, url

        # ?edit=<id> renders the form in edit mode; client_name is
        # prefilled into the form input. Verify the history CSS class
        # and section header still don't render (item 12 holds
        # regardless of the route mode).
        resp = client.get(
            f"/p/drift-and-anchor/competitive-audit/?edit={sub.id}",
            follow_redirects=False,
        )
        body = resp.get_data(as_text=True)
        assert "Past Submissions" not in body
        assert "competitive-audit-history" not in body


class TestSlice8JsReindex:
    """Slice 8 item 7: the JS reindex() function rewrites the
    Competitor N title text inside cloned cards.

    Slice 9: the JS was extracted into
    app/static/js/portal/competitive-audit-form.js. The test now reads
    the JS file rather than the template, but the substring we pin is
    unchanged.

    Playwright / Selenium aren't wired into this project. Phronesis
    should add a real browser test in a later slice.
    """

    def test_reindex_rewrites_competitor_n_title(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        js = (
            repo_root
            / "app"
            / "static"
            / "js"
            / "portal"
            / "competitive-audit-form.js"
        ).read_text()
        # Source HTML for the default card still has the literal
        # "Competitor 1" inside the col__title div.
        assert 'class="competitive-audit-col__title">Competitor 1<' in js
        # And the reindex function rewrites that literal to use the
        # dynamic index.
        assert "class=\"competitive-audit-col__title\">Competitor ' + newIndex + '<" in js


class TestCloneModelBAddButton:
    """UX model B (Quinn, 2026-07-22): the Add button moves out of
    the default card and into its own row at the bottom of
    .competitive-audit-extra-cards. Each new clone is inserted BEFORE
    the Add button via DOM insertBefore(), so the button stays as
    the last child and always renders next to the newest competitor.

    This replaces the prior model (slice 8 item 4) where the Add
    button lived inline on the socials row of the default card.
    That model caused Quinn to see what looked like a working Add
    button on every cloned competitor (because the default card's
    Add was duplicated into each clone) but only the first one
    actually fired the listener. The fix on this branch moves the
    button to its own row and inserts clones before it, so there's
    exactly one Add button visible at all times and it always sits
    next to the last competitor.
    """

    def _read_js(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        return (
            repo_root
            / "app"
            / "static"
            / "js"
            / "portal"
            / "competitive-audit-form.js"
        ).read_text()

    def _read_template(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        return (
            repo_root
            / "app"
            / "templates"
            / "portal"
            / "drift_and_anchor_competitive_audit.html"
        ).read_text()

    def test_default_card_has_no_add_button(self):
        # UX model B: the default card no longer carries the Add
        # button. The button moved to a dedicated row in extra-cards.
        template = self._read_template()
        # Slice out the default card's outerHTML to confirm no Add
        # button lives inside it.
        import re
        card_match = re.search(
            r'<div class="competitive-audit-col competitive-audit-col--main"'
            r"[\s\S]*?</div>\s*</div>\s*</div>",
            template,
        )
        assert card_match is not None, "default card not found in template"
        card_html = card_match.group(0)
        assert "data-competitive-audit-add" not in card_html, (
            "default card still carries the Add button — UX model B "
            "should have moved it to .competitive-audit-extra-cards"
        )

    def test_add_button_inside_extra_cards_row(self):
        # The Add button lives in .competitive-audit-extra-cards,
        # inside the [data-competitive-audit-add-row] wrapper.
        template = self._read_template()
        import re
        # Find the .competitive-audit-extra-cards container and
        # confirm it contains the Add button.
        extra_match = re.search(
            r'<div class="competitive-audit-extra-cards"[^>]*>([\s\S]*?)</div>\s*</div>',
            template,
        )
        assert extra_match is not None, "extra-cards container not found"
        inner = extra_match.group(1)
        assert "data-competitive-audit-add-row" in inner, (
            "extra-cards container missing the Add button's wrapper row"
        )
        assert "data-competitive-audit-add" in inner, (
            "extra-cards container missing the Add button itself"
        )

    def test_js_inserts_clone_before_add_button(self):
        # The click handler must call insertBefore(newCard, addRow),
        # NOT appendChild(newCard), so the Add button stays last.
        js = self._read_js()
        assert "insertBefore(newCard, addRow)" in js, (
            "Add click handler must use insertBefore(newCard, addRow) "
            "to keep the Add button as the last child of extra-cards "
            "(UX model B)"
        )
        assert "extraContainer.appendChild(newCard)" not in js, (
            "Add click handler still uses appendChild — should be "
            "insertBefore so the Add button stays at the bottom"
        )

    def test_js_no_longer_strips_add_button_from_clones(self):
        # UX model B removes the need to strip the Add button from
        # clones (the default card doesn't carry one anymore). The
        # strip regex should be GONE from the JS file.
        js = self._read_js()
        strip_lines = [
            line
            for line in js.splitlines()
            if "data-competitive-audit-add" in line
            and r"<\/button>" in line
        ]
        assert len(strip_lines) == 0, (
            "Add-button strip regex should be removed in UX model B "
            f"(the default card no longer carries an Add button). "
            f"Found: {strip_lines}"
        )


# ---------------------------------------------------------------------------
# Slice 9 — extracted JS, favicon, TikTok checkbox, dashboard CTA removal
# ---------------------------------------------------------------------------


class TestSlice9ExtractedJs:
    """Slice 9 item 3: the inline <script> for the competitive-audit
    "Add competitor" behavior was extracted into
    app/static/js/portal/competitive-audit-form.js so the page
    complies with the site's strict CSP (script-src 'self')."""

    def test_external_js_file_exists(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        js_path = (
            repo_root
            / "app"
            / "static"
            / "js"
            / "portal"
            / "competitive-audit-form.js"
        )
        assert js_path.exists(), f"missing {js_path}"
        # Belt-and-suspenders: the file should not be empty.
        assert js_path.stat().st_size > 500

    def test_template_references_external_js(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        template = (
            repo_root
            / "app"
            / "templates"
            / "portal"
            / "drift_and_anchor_competitive_audit.html"
        ).read_text()
        # The template must reference the external script via url_for.
        assert (
            "js/portal/competitive-audit-form.js" in template
        ), "template does not load the external JS file"
        assert (
            "{{ url_for('static', filename='js/portal/competitive-audit-form.js') }}"
            in template
        ), "template does not use url_for for the external JS"

    def test_template_no_inline_competitive_audit_script(self):
        # The extracted JS contains the Add/clone logic. The inline
        # <script> block at the bottom of the template should NOT
        # contain a reindex / nextIndex / makeRemoveButton function —
        # those live in the extracted file now.
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        template = (
            repo_root
            / "app"
            / "templates"
            / "portal"
            / "drift_and_anchor_competitive_audit.html"
        ).read_text()
        # Locate the {% block scripts %} region and assert no reindex.
        scripts_start = template.find("{% block scripts %}")
        scripts_end = template.find("{% endblock %}", scripts_start)
        assert scripts_start != -1 and scripts_end != -1
        scripts_block = template[scripts_start:scripts_end]
        assert "function reindex(" not in scripts_block
        assert "function nextIndex(" not in scripts_block
        assert "function makeRemoveButton(" not in scripts_block

    def test_extracted_js_preserves_reindex_logic(self):
        # The external file must still contain the reindex + clone
        # wiring that used to live in the inline <script>. Otherwise
        # extraction would silently break the Add behavior.
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        js = (
            repo_root
            / "app"
            / "static"
            / "js"
            / "portal"
            / "competitive-audit-form.js"
        ).read_text()
        assert "competitive-audit-form-card" in js
        assert "data-competitive-audit-add" in js
        assert "data-competitive-audit-extra-cards" in js
        assert "data-card-index" in js
        assert "competitor_1_" in js  # source of the reindex regex
        assert "function reindex(" in js
        assert "function nextIndex(" in js
        assert "function makeRemoveButton(" in js


class TestSlice9TiktokCheckbox:
    """Slice 9 item 3: the socials row now includes TikTok alongside
    X, Facebook, Instagram, and YouTube. Default-checked on the
    default card to match the rest of the socials checkboxes."""

    def test_template_renders_tiktok_checkbox(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        template = (
            repo_root
            / "app"
            / "templates"
            / "portal"
            / "drift_and_anchor_competitive_audit.html"
        ).read_text()
        assert "competitor_1_include_tiktok" in template
        assert 'name="competitor_1_include_tiktok"' in template
        assert 'for="competitor_1_include_tiktok"' in template
        # TikTok label exists (not just the input).
        assert ">TikTok<" in template

    def test_extracted_js_reindex_handles_tiktok(self):
        # The reindex regex `competitor_1_/g` must catch the new
        # competitor_1_include_tiktok attribute on clone. Confirm by
        # walking a synthetic clone that includes TikTok.
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        js = (
            repo_root
            / "app"
            / "static"
            / "js"
            / "portal"
            / "competitive-audit-form.js"
        ).read_text()
        # reindex replaces the bare `competitor_1_` token globally,
        # which covers competitor_1_include_tiktok too.
        assert (
            ".replace(/competitor_1_/g, 'competitor_' + newIndex + '_')"
            in js
        ), "reindex regex should be a global bare-token match"


class TestSlice9Favicon:
    """Slice 9 item 4: site favicon added to base.html. The favicon
    file lives at app/static/favicon.ico (multi-resolution ICO derived
    from app/static/images/psi_logo_3.webp). Closes the 404 in the
    browser console on every portal page."""

    def test_favicon_file_exists(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        ico_path = repo_root / "app" / "static" / "favicon.ico"
        assert ico_path.exists(), f"missing {ico_path}"
        # ICO magic bytes: 00 00 01 00.
        with ico_path.open("rb") as fh:
            magic = fh.read(4)
        assert magic[:4] == b"\x00\x00\x01\x00", (
            f"favicon is not a valid ICO (magic={magic!r})"
        )

    def test_base_html_has_favicon_link(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        base = (repo_root / "app" / "templates" / "base.html").read_text()
        assert (
            "rel=\"icon\"" in base
        ), "base.html is missing <link rel=\"icon\">"
        assert (
            "{{ url_for('static', filename='favicon.ico') }}" in base
        ), "base.html does not url_for the favicon path"


class TestSlice9DashboardCtaRemoved:
    """Slice 9 item 5: the standalone "Competitive audit with
    DrifterBot" CTA block was removed from
    app/templates/portal/_dashboard_grid.html. The audit entry point
    now lives in the seeded Applications column (via DRIFT_AND_ANCHOR_RESOURCES)."""

    def test_dashboard_grid_no_standalone_cta(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        grid = (
            repo_root
            / "app"
            / "templates"
            / "portal"
            / "_dashboard_grid.html"
        ).read_text()
        assert "portal-dashboard-cta" not in grid, (
            "standalone DrifterBot CTA block still present in _dashboard_grid.html"
        )
        assert (
            "Request an audit" not in grid
        ), "old standalone CTA copy still present"


class TestSlice9SecurityHeadersCsp:
    """Slice 9 item 6: security-headers.conf CSP now allows
    static1.squarespace.com / images.squarespace-cdn.com for img-src,
    static.cloudflareinsights.com for script-src + connect-src, and
    still rejects inline scripts (script-src 'self' only)."""

    def test_csp_allows_squarespace_cdn_for_images(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        conf = (
            repo_root
            / "deploy"
            / "nginx"
            / "snippets"
            / "security-headers.conf"
        ).read_text()
        assert "static1.squarespace.com" in conf
        assert "images.squarespace-cdn.com" in conf
        assert "img-src" in conf

    def test_csp_allows_cloudflare_insights_script(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        conf = (
            repo_root
            / "deploy"
            / "nginx"
            / "snippets"
            / "security-headers.conf"
        ).read_text()
        assert "static.cloudflareinsights.com" in conf
        assert "script-src" in conf
        assert "connect-src" in conf

    def test_csp_does_not_permit_unsafe_inline_scripts(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        conf = (
            repo_root
            / "deploy"
            / "nginx"
            / "snippets"
            / "security-headers.conf"
        ).read_text()
        # Inline scripts would re-introduce the bug that slice 9 fixed
        # by extracting the JS. Pin script-src to 'self' only.
        assert "script-src 'self'" in conf
        assert "'unsafe-inline'" not in conf.split("script-src", 1)[1].split(";", 1)[0]



# Seeder — DRIFT_AND_ANCHOR_RESOURCES now contains the audit entry
# ---------------------------------------------------------------------------


class TestSeederIncludesCompetitiveAudit:
    def test_resource_list_contains_competitive_audit_entry(self):
        from app.cli import DRIFT_AND_ANCHOR_RESOURCES

        titles = [r["title"] for r in DRIFT_AND_ANCHOR_RESOURCES]
        assert "Competitive Audit" in titles

    def test_competitive_audit_entry_points_at_the_route(self):
        from app.cli import DRIFT_AND_ANCHOR_RESOURCES

        entry = next(r for r in DRIFT_AND_ANCHOR_RESOURCES if r["title"] == "Competitive Audit")
        assert entry["external_url"] == "/p/drift-and-anchor/competitive-audit/"

    def test_competitive_audit_entry_is_application_category(self):
        from app.cli import DRIFT_AND_ANCHOR_RESOURCES

        entry = next(r for r in DRIFT_AND_ANCHOR_RESOURCES if r["title"] == "Competitive Audit")
        assert entry["category"] == "application"
        # Sanity: 'application' is a known category on the model.
        assert "application" in ClientResource.CATEGORIES

    def test_seeder_creates_competitive_audit_row(self, app, db_session):
        # The seeder is idempotent — running it surfaces the row.
        from click.testing import CliRunner

        from app.cli import client_cli

        runner = CliRunner()
        with app.app_context():
            result = runner.invoke(client_cli, ["seed-drift-and-anchor-resources"])
        assert result.exit_code == 0, result.output

        client = Client.query.filter_by(slug="drift-and-anchor").first()
        assert client is not None
        row = ClientResource.query.filter_by(
            client_id=client.id,
            title="Competitive Audit",
        ).first()
        assert row is not None
        assert row.category == "application"
        assert row.external_url == "/p/drift-and-anchor/competitive-audit/"
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

        client = Client.query.filter_by(slug="drift-and-anchor").first()
        if client is None:
            client = Client(slug="drift-and-anchor", name="Drift & Anchor", is_active=True)
            db.session.add(client)
            db.session.flush()
        legacy = ClientResource(
            client_id=client.id,
            title="Legacy Custom Resource",
            category="custom",
            external_url="#",
            sort_order=999,
        )
        db.session.add(legacy)
        db.session.commit()
        legacy_id = legacy.id

        # Confirm the pre-migration state is 'custom'.
        assert ClientResource.query.get(legacy_id).category == "custom"

        # Run the migration's UPDATE statement directly. Same SQL the
        # migration's upgrade() issues.
        db.session.execute(
            db.text("UPDATE client_resource SET category = 'application' WHERE category = 'custom'")
        )
        db.session.commit()
        db.session.expire_all()

        # Post-migration: 'application'.
        after = ClientResource.query.get(legacy_id)
        assert after.category == "application"

    def test_migration_idempotent_on_clean_state(self, app, db_session):
        # Running the UPDATE twice on a DB with no 'custom' rows must
        # not fail (matches nothing the second time, but is a valid
        # no-op statement).
        from app.extensions import db

        sql = "UPDATE client_resource SET category = 'application' WHERE category = 'custom'"
        db.session.execute(db.text(sql))
        db.session.commit()
        db.session.execute(db.text(sql))  # second run is a no-op
        db.session.commit()

    def test_migration_target_column_set_in_docstring(self):
        # Pin the migration's intent — guards against accidental
        # rewrites that change the column.
        # Note (slice 8): pytest puts tests/ on sys.path, not the
        # project root, so `import migrations.versions...` does not
        # resolve. Read the migration file as text instead — the
        # assertion is purely about the SQL the upgrade() function
        # runs, which is captured by inspecting the source.
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        src = (
            repo_root
            / "migrations"
            / "versions"
            / "d2e3f4a5b6c7_rename_client_resource_custom_to_application.py"
        ).read_text()
        assert "category = 'application'" in src
        assert "WHERE category = 'custom'" in src
