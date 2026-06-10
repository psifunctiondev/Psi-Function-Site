"""
tests/test_admin_work_items.py

Light coverage for the /admin/work-items authoring routes:
  - auth required (unauthenticated -> 302 to login)
  - non-admin user is forbidden (403)
  - admin can list, create, edit, and delete WorkItems
  - tag M2M assignment round-trips through create + edit
  - quick-toggle visible flips the flag
"""

from app.models.client import Client
from app.models.taxonomy import TaxonomyTag, WorkItem


def _login(http_client, email, password):
    return http_client.post('/p/login', data={
        'action': 'login',
        'email': email,
        'password': password,
    })


# ---------------------------------------------------------------------------
# Auth gates
# ---------------------------------------------------------------------------

def test_work_items_list_redirects_unauthenticated(app, client):
    resp = client.get('/admin/work-items/', follow_redirects=False)
    assert resp.status_code == 302
    assert '/p/login' in resp.headers.get('Location', '')


def test_work_items_list_forbidden_for_regular_user(app, client, test_user):
    _login(client, 'user@test.com', 'password123')
    resp = client.get('/admin/work-items/')
    assert resp.status_code == 403


def test_work_items_list_loads_for_admin(app, client, admin_user, db_session):
    _login(client, 'admin@test.com', 'adminpass123')
    resp = client.get('/admin/work-items/')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'Work Items' in html


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_work_item_persists_tags(app, client, admin_user, db_session):
    """POST /admin/work-items/new/ should create a row and write tag links."""
    v = TaxonomyTag(axis='vertical', label='Healthcare',
                    slug='healthcare', sort_order=0)
    t = TaxonomyTag(axis='technology', label='LLM Apps',
                    slug='llm-apps', sort_order=0)
    db_session.add_all([v, t])
    db_session.commit()

    _login(client, 'admin@test.com', 'adminpass123')
    resp = client.post('/admin/work-items/new/', data={
        'title': 'Hospital Workflow Bot',
        'description': 'A bot that triages incoming referrals.',
        'is_projected': '1',
        'is_visible': '1',
        'sort_order': '5',
        'tag_ids': [str(v.id), str(t.id)],
    }, follow_redirects=False)

    # Success -> redirect to list view.
    assert resp.status_code == 302
    assert '/admin/work-items' in resp.headers.get('Location', '')

    item = WorkItem.query.filter_by(title='Hospital Workflow Bot').one()
    assert item.is_projected is True
    assert item.is_visible is True
    assert item.sort_order == 5
    tag_axes = {tag.axis for tag in item.tags}
    assert tag_axes == {'vertical', 'technology'}


def test_create_work_item_validates_required_fields(
    app, client, admin_user, db_session,
):
    _login(client, 'admin@test.com', 'adminpass123')
    # No title, no description -> re-render form, not 302.
    resp = client.post('/admin/work-items/new/', data={
        'title': '',
        'description': '',
    })
    assert resp.status_code == 200
    assert WorkItem.query.count() == 0


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------

def test_edit_work_item_updates_tags(app, client, admin_user, db_session):
    v = TaxonomyTag(axis='vertical', label='Retail',
                    slug='retail', sort_order=0)
    f = TaxonomyTag(axis='function', label='Marketing',
                    slug='marketing', sort_order=0)
    db_session.add_all([v, f])
    db_session.commit()

    item = WorkItem(
        title='Old Title', description='Old desc.',
        sort_order=0, is_visible=True, is_projected=False,
    )
    item.tags = [v]
    db_session.add(item)
    db_session.commit()
    item_id = item.id

    _login(client, 'admin@test.com', 'adminpass123')
    resp = client.post(
        f'/admin/work-items/{item_id}/edit/',
        data={
            'title': 'New Title',
            'description': 'Updated description.',
            'is_projected': '',
            'is_visible': '1',
            'sort_order': '2',
            'tag_ids': [str(f.id)],   # drop vertical, add function
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    refreshed = WorkItem.query.get(item_id)
    assert refreshed.title == 'New Title'
    assert refreshed.is_projected is False
    assert refreshed.sort_order == 2
    assert {t.id for t in refreshed.tags} == {f.id}


# ---------------------------------------------------------------------------
# Delete + toggle-visible
# ---------------------------------------------------------------------------

def test_delete_work_item(app, client, admin_user, db_session):
    item = WorkItem(
        title='Doomed', description='Bye.',
        sort_order=0, is_visible=True, is_projected=False,
    )
    db_session.add(item)
    db_session.commit()
    item_id = item.id

    _login(client, 'admin@test.com', 'adminpass123')
    resp = client.post(
        f'/admin/work-items/{item_id}/delete/',
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert WorkItem.query.get(item_id) is None


def test_toggle_visible_flips_flag(app, client, admin_user, db_session):
    item = WorkItem(
        title='Toggle', description='Me.',
        sort_order=0, is_visible=True, is_projected=False,
    )
    db_session.add(item)
    db_session.commit()
    item_id = item.id

    _login(client, 'admin@test.com', 'adminpass123')
    resp = client.post(
        f'/admin/work-items/{item_id}/toggle-visible/',
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert WorkItem.query.get(item_id).is_visible is False

    # Second toggle brings it back.
    client.post(f'/admin/work-items/{item_id}/toggle-visible/')
    assert WorkItem.query.get(item_id).is_visible is True


# ---------------------------------------------------------------------------
# Optional client link
# ---------------------------------------------------------------------------

def test_create_with_client_link(app, client, admin_user, db_session):
    c = Client(name='ACME Co', slug='acme')
    db_session.add(c)
    db_session.commit()

    _login(client, 'admin@test.com', 'adminpass123')
    resp = client.post('/admin/work-items/new/', data={
        'title': 'ACME Engagement',
        'description': 'A project for ACME.',
        'client_id': str(c.id),
        'is_visible': '1',
        'sort_order': '0',
    }, follow_redirects=False)
    assert resp.status_code == 302

    item = WorkItem.query.filter_by(title='ACME Engagement').one()
    assert item.client_id == c.id
