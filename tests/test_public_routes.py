"""
tests/test_public_routes.py
Smoke tests for all public-facing routes.

Coverage:
  - All routes return HTTP 200
  - Key content is present in rendered HTML
  - Critical interactive elements (service panels, contact links) are intact
"""


# ---------------------------------------------------------------------------
# Route availability
# ---------------------------------------------------------------------------

def test_home(client, db_session):
    # db_session creates tables; the home route queries WorkItem.
    assert client.get("/").status_code == 200

def test_home_also_accessible_at_slash_home(client, db_session):
    assert client.get("/home").status_code == 200

def test_about(client):
    assert client.get("/about").status_code == 200

def test_services(client):
    assert client.get("/services").status_code == 200

def test_contact(client):
    assert client.get("/contact").status_code == 200


# ---------------------------------------------------------------------------
# Home page content
# ---------------------------------------------------------------------------

def test_home_renders_key_content(client, db_session):
    html = client.get("/").data.decode()
    assert "Psi Function" in html
    assert "Strategic technology" in html


# ---------------------------------------------------------------------------
# About page content
# ---------------------------------------------------------------------------

def test_about_renders_key_content(client):
    html = client.get("/about").data.decode()
    assert "Quinn Moore" in html
    assert "Psi Function" in html
    assert "Inspiration" in html
    assert "Leadership" in html


# ---------------------------------------------------------------------------
# Services page content
# ---------------------------------------------------------------------------

def test_services_renders_all_panels(client):
    """Every service must have a corresponding detail panel in the DOM.
    This catches the case where a selector card and its panel get out of sync."""
    html = client.get("/services").data.decode()
    panels = [
        "panel-fractional-cto",
        "panel-discovery",
        "panel-blueprint",
        "panel-construct",
        "panel-realize",
        "panel-project-management",
    ]
    for panel_id in panels:
        assert f'id="{panel_id}"' in html, f"Missing detail panel: #{panel_id}"

def test_services_renders_all_selector_cards(client):
    """Every selector card button must be present."""
    html = client.get("/services").data.decode()
    services = [
        "fractional-cto",
        "discovery",
        "blueprint",
        "construct",
        "realize",
        "project-management",
    ]
    for service in services:
        assert f'data-service="{service}"' in html, \
            f"Missing selector card: data-service={service}"

def test_services_panels_and_cards_match(client):
    """The set of data-service values and panel ids must be identical —
    no orphaned cards and no unreachable panels."""
    import re
    html = client.get("/services").data.decode()

    cards  = set(re.findall(r'data-service="([^"]+)"', html))
    panels = set(re.findall(r'id="panel-([^"]+)"', html))

    # Remove the placeholder which has no corresponding card
    panels.discard("placeholder")

    assert cards == panels, (
        f"Mismatch between selector cards and detail panels.\n"
        f"  Cards without panels: {cards - panels}\n"
        f"  Panels without cards: {panels - cards}"
    )


# ---------------------------------------------------------------------------
# Contact page content
# ---------------------------------------------------------------------------

def test_contact_renders_mailto(client):
    html = client.get("/contact").data.decode()
    assert "mailto:info@psifunction.com" in html

def test_contact_renders_linkedin(client):
    html = client.get("/contact").data.decode()
    assert "linkedin.com/company/psi-function-llc" in html

def test_contact_linkedin_opens_new_tab(client):
    """LinkedIn link must have target=_blank so it opens in a new tab."""
    html = client.get("/contact").data.decode()
    assert 'target="_blank"' in html

def test_contact_linkedin_has_noopener(client):
    """External _blank links must include rel=noopener for security."""
    html = client.get("/contact").data.decode()
    assert "noopener" in html
