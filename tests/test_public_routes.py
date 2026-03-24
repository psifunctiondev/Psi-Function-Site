def test_home(client):
    response = client.get("/")
    assert response.status_code == 200

def test_about(client):
    response = client.get("/about")
    assert response.status_code == 200

def test_homepage_includes_assets(client):
    resp = client.get("/")
    html = resp.data.decode()

    # CSS assets
    assert 'href="/static/css/complete_design_tokens.css"' in html
    assert 'href="/static/css/site.css"' in html

    # JS asset
    assert 'src="/static/js/app.js"' in html

    # Fonts (external dependency)
    assert "fonts.googleapis.com" in html

def test_homepage_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
