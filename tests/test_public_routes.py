def test_home(client):
    response = client.get("/")
    assert response.status_code == 200

def test_about(client):
    response = client.get("/about")
    assert response.status_code == 200

def test_homepage_includes_assets(client):
    resp = client.get("/")
    html = resp.data.decode()

    assert "/static/dist/assets/app.css" in html
    assert "app.js" in html
    
def test_homepage_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200