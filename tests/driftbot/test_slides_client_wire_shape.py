"""
Wire-shape tests for SlidesClient.move_to_folder.

The unit tests in test_drive_save_strategy.py mock at the SlidesClient
boundary and never verify the actual HTTP request shape. These tests
use a FakeTransport on httpx so we can read the actual URL + params +
body that get sent to Google. They catch anything that "looks
plausible on read-through" but doesn't actually do what the Drive v3
API expects.

Specifically: Drive ``files.patch`` for parent changes requires
``addParents`` + ``removeParents`` *query* parameters — not body
fields. We read the file's current parents first, then PATCH with
both. The wire-shape bug that bit Path A v1 was that
move_to_folder() shipped with a TODO comment noting this exact
requirement but only sent name+description in body. The file was
renamed but never moved. This file would have caught it.

The wire-shape test for files.export (B2) was replaced when we
pivoted B2 → A-corrected; if we re-add .pptx export later we'll
need to restore the export test too.
"""

from __future__ import annotations

import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from agents.driftbot.slides_client import (
    DriveAuthError,
    DriveFolderAccessError,
    SlidesClient,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _generate_rsa_pem() -> str:
    """Throwaway RSA key for JWT signing in tests. Never sent anywhere."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode('utf-8')


@pytest.fixture
def fake_sa_key(tmp_path):
    sa = {
        'client_email': 'fake@fake-project.iam.gserviceaccount.com',
        'private_key_id': 'fake-kid',
        'token_uri': 'https://oauth2.googleapis.com/token',
        'private_key': _generate_rsa_pem(),
    }
    p = tmp_path / 'sa.json'
    p.write_text(json.dumps(sa))
    return p


@pytest.fixture
def client(fake_sa_key):
    """SlidesClient with a MockTransport that handles token grants and
    lets each test set handlers for subsequent requests in order.
    """
    state = {'handlers': []}

    def combined_handler(request: httpx.Request) -> httpx.Response:
        # Token grant — return a fake bearer (first request)
        if 'oauth2.googleapis.com/token' in str(request.url):
            return httpx.Response(
                200,
                content=json.dumps(
                    {'access_token': '***', 'expires_in': 3600}
                ).encode(),
            )
        # Otherwise, pull next handler from the queue
        if not state['handlers']:
            raise AssertionError(
                'SlidesClient made an unexpected request to '
                f'{request.url} — did the test wire all expected calls?'
            )
        h = state['handlers'].pop(0)
        return h(request)

    http = httpx.Client(
        transport=httpx.MockTransport(combined_handler), timeout=30.0,
    )
    c = SlidesClient(
        service_account_json_path=fake_sa_key,
        subject='drifterbot@drift-and-anchor.com',
        _http_client=http,
    )
    c.set_next_handlers = lambda hs: state.update(handlers=hs)
    return c


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


def test_move_to_folder_uses_addparents_removeparents_query_params(client):
    """The wire-shape bug: Drive parent changes need addParents +
    removeParents in QUERY params, not body fields. Verify the request
    shape so future regressions are caught.
    """
    requests = []

    def get_handler(request: httpx.Request) -> httpx.Response:
        requests.append(('GET', request))
        return httpx.Response(
            200,
            content=json.dumps(
                {'id': 'PRES-1234', 'parents': ['OLD-PARENT-1', 'OLD-PARENT-2']}
            ).encode(),
        )

    def patch_handler(request: httpx.Request) -> httpx.Response:
        requests.append(('PATCH', request))
        return httpx.Response(
            200,
            content=json.dumps({
                'id': 'PRES-1234',
                'name': 'New Name',
                'webViewLink': 'https://docs.google.com/presentation/d/PRES-1234/edit',
            }).encode(),
        )

    client.set_next_handlers([get_handler, patch_handler])
    web_url = client.move_to_folder(
        presentation_id='PRES-1234',
        folder_id='FOLDER-TARGET',
        name='New Name',
    )

    assert web_url == (
        'https://docs.google.com/presentation/d/PRES-1234/edit'
    )
    assert len(requests) == 2
    # First: GET to read current parents
    method_get, req_get = requests[0]
    assert method_get == 'GET'
    assert '/drive/v3/files/PRES-1234' in str(req_get.url)
    # fields=id,parents URL-encoded as fields=id%2Cparents
    assert 'fields=id,parents' in str(req_get.url) or \
        'fields=id%2Cparents' in str(req_get.url)

    # Second: PATCH with addParents + removeParents in QUERY, body has name
    method_patch, req_patch = requests[1]
    assert method_patch == 'PATCH'
    url = str(req_patch.url)
    assert '/drive/v3/files/PRES-1234' in url
    # The crux: addParents + removeParents in query, NOT body
    assert 'addParents=FOLDER-TARGET' in url
    assert 'removeParents=OLD-PARENT-1%2COLD-PARENT-2' in url or \
        'removeParents=OLD-PARENT-1,OLD-PARENT-2' in url
    # Body still has name + description
    body = json.loads(req_patch.content.decode())
    assert body['name'] == 'New Name'
    assert 'description' in body
    # Critically: body should NOT contain addParents / removeParents
    assert 'addParents' not in body
    assert 'removeParents' not in body
    assert 'parents' not in body  # parents in body is silently ignored by Drive v3


def test_move_to_folder_returns_web_view_link(client):
    def get_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps({'id': 'PRES-A', 'parents': []}).encode(),
        )

    def patch_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps({
                'id': 'PRES-A',
                'name': 'N',
                'webViewLink': 'https://docs.google.com/presentation/d/PRES-A/edit',
            }).encode(),
        )

    client.set_next_handlers([get_handler, patch_handler])
    result = client.move_to_folder('PRES-A', 'F-B', 'N')
    assert isinstance(result, str)
    assert result.endswith('/edit')


def test_move_to_folder_handles_no_prior_parents(client):
    """When GET returns no parents (fresh create), removeParents stays empty."""
    def get_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps({'id': 'PRES-B', 'parents': []}).encode(),
        )

    def patch_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps({
                'id': 'PRES-B', 'name': 'N',
                'webViewLink': 'https://docs.google.com/presentation/d/PRES-B/edit',
            }).encode(),
        )

    client.set_next_handlers([get_handler, patch_handler])
    # Should not raise even with empty current parents
    web = client.move_to_folder('PRES-B', 'FOLDER', 'N')
    assert 'PRES-B' in web


def test_move_to_folder_raises_403_on_folder_access_denied(client):
    def get_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps({'id': 'PRES-C', 'parents': []}).encode(),
        )

    def patch_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=b'permission denied')

    client.set_next_handlers([get_handler, patch_handler])
    with pytest.raises(DriveFolderAccessError, match='cannot modify files'):
        client.move_to_folder('PRES-C', 'FOLDER', 'N')


def test_move_to_folder_raises_drive_auth_on_500(client):
    def get_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps({'id': 'PRES-D', 'parents': []}).encode(),
        )

    def patch_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b'{"error":{"message":"oops"}}')

    client.set_next_handlers([get_handler, patch_handler])
    with pytest.raises(DriveFolderAccessError, match='files.patch failed'):
        client.move_to_folder('PRES-D', 'FOLDER', 'N')


def test_move_to_folder_raises_drive_folder_access_on_get_404(client):
    """If the GET itself fails (file vanished), DriveFolderAccessError is raised."""
    def get_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b'not found')

    client.set_next_handlers([get_handler])
    with pytest.raises(DriveFolderAccessError, match='files.get .pre-move. failed'):
        client.move_to_folder('PRES-E', 'FOLDER', 'N')


# ------------------------------------------------------------------
# delete_file — cleanup-on-failure helper
# ------------------------------------------------------------------


def test_delete_file_uses_delete_method_with_supports_alldrives(client):
    """Wire shape for cleanup: DELETE method, supportsAllDrives=true
    query param. Catches future regressions if the cleanup path
    diverges from create/move.
    """
    requests = []

    def delete_handler(request: httpx.Request) -> httpx.Response:
        requests.append(('DELETE', request))
        return httpx.Response(204, content=b'')

    client.set_next_handlers([delete_handler])
    client.delete_file('PRES-CLEANUP')

    assert len(requests) == 1
    method, req = requests[0]
    assert method == 'DELETE'
    assert '/drive/v3/files/PRES-CLEANUP' in str(req.url)
    assert 'supportsAllDrives=true' in str(req.url)


def test_delete_file_swallows_404(client):
    """An already-gone file shouldn't fail the cleanup path."""
    def delete_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b'not found')

    client.set_next_handlers([delete_handler])
    # Should NOT raise
    client.delete_file('PRES-GONE', swallow_404=True)


def test_delete_file_raises_on_500(client):
    """Server errors should raise so caller can decide to retry or log."""
    def delete_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b'{"error":{"message":"oops"}}')

    client.set_next_handlers([delete_handler])
    with pytest.raises(DriveAuthError, match='files.delete failed'):
        client.delete_file('PRES-DEAD', swallow_404=True)


def test_delete_file_404_unswallowed_raises(client):
    """If swallow_404=False, a 404 is a real error (caller wants to know)."""
    def delete_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b'gone')

    client.set_next_handlers([delete_handler])
    with pytest.raises(DriveAuthError, match='files.delete failed'):
        client.delete_file('PRES-GONE', swallow_404=False)


def test_delete_file_204_is_success(client):
    """Both 200 and 204 are valid Drive success responses."""
    for code in (200, 204):
        def delete_handler(request: httpx.Request, code=code) -> httpx.Response:
            return httpx.Response(code, content=b'')

        client.set_next_handlers([delete_handler])
        client.delete_file(f'PRES-{code}')  # should not raise


# ------------------------------------------------------------------
# create_presentation — PR #59 wire-shape assertions
# ------------------------------------------------------------------
# Per PR #59, ``SlidesClient.create_presentation()`` sends
# ``sourcePresentationId`` in the POST body when a brand template
# is configured. This makes the new presentation inherit the D&A
# brand template's masters, layouts, theme, and fonts. Without it,
# the deck reverts to the Google default master and the visual
# brand collapses.
#
# These wire-shape tests would have caught the bug where Quinn said
# "the deck doesn't look like the reference" — the Slides call
# silently fell through to the default master because the
# sourcePresentationId field was never sent.


def test_create_presentation_sends_source_presentation_id_in_body(client):
    """Wire-shape regression test: when ``source_presentation_id`` is
    passed, it MUST be in the POST body, not as a query param, and
    NOT inside a nested ``presentation`` field. The Slides API
    rejects anything else with 400.
    """
    requests = []

    def create_handler(request: httpx.Request) -> httpx.Response:
        requests.append(('POST', request))
        return httpx.Response(
            200,
            content=json.dumps(
                {'presentationId': 'PRES-NEW-1234'}
            ).encode(),
        )

    # No batchUpdate requests needed; we exercise just the create step.
    client.set_next_handlers([create_handler])
    pid = client.create_presentation(
        title='Acme - Competitive Audit - 2026-07-21',
        slides_spec={'slides': []},  # empty → no batchUpdate
        source_presentation_id='TEMPLATE-BRAND-XYZ',
    )

    assert pid == 'PRES-NEW-1234'
    assert len(requests) == 1
    method, req = requests[0]
    assert method == 'POST'
    assert str(req.url).startswith('https://slides.googleapis.com/v1/presentations')
    # The body MUST contain sourcePresentationId at the top level.
    body = json.loads(req.content.decode())
    assert body['title'] == 'Acme - Competitive Audit - 2026-07-21'
    assert body['sourcePresentationId'] == 'TEMPLATE-BRAND-XYZ'
    # And NOT inside any nested field (Slides API ignores nested keys).
    assert 'presentation' not in body
    assert 'presentationId' not in body


def test_create_presentation_omits_source_presentation_id_when_none(client):
    """Wire-shape: when ``source_presentation_id`` is None (legacy
    behavior), the body should NOT contain ``sourcePresentationId``
    at all — sending null/empty would still be valid but is
    unnecessary and might confuse future readers. Regression: the
    field must be OMITTED, not set to None.
    """
    requests = []

    def create_handler(request: httpx.Request) -> httpx.Response:
        requests.append(('POST', request))
        return httpx.Response(
            200,
            content=json.dumps({'presentationId': 'PRES-LEGACY'}).encode(),
        )

    client.set_next_handlers([create_handler])
    pid = client.create_presentation(
        title='Blank Deck',
        slides_spec={'slides': []},
        source_presentation_id=None,
    )

    assert pid == 'PRES-LEGACY'
    body = json.loads(requests[0][1].content.decode())
    assert 'sourcePresentationId' not in body
    # Only title should be set.
    assert body == {'title': 'Blank Deck'}


def test_create_presentation_with_template_triggers_batch_update_with_template_layouts(client):
    """End-to-end shape: create-from-template then batchUpdate. Each
    slide's ``slideLayoutReference`` should use ``layoutObjectId``
    from the template (resolved via ``layout_catalog``), NOT
    ``predefinedLayout``. This is what selects the D&A custom
    layouts instead of the built-in ones with the same name.
    """
    from agents.driftbot.layout_catalog import LAYOUT_IDS, LayoutName

    requests = []

    def create_handler(request: httpx.Request) -> httpx.Response:
        requests.append(('CREATE', request))
        return httpx.Response(
            200,
            content=json.dumps({'presentationId': 'PRES-TEMPL'}).encode(),
        )

    def batch_update_handler(request: httpx.Request) -> httpx.Response:
        requests.append(('BATCH', request))
        # Return 200 with empty replies so client doesn't fail.
        return httpx.Response(
            200,
            content=json.dumps({'replies': []}).encode(),
        )

    client.set_next_handlers([create_handler, batch_update_handler])
    pid = client.create_presentation(
        title='Templated Deck',
        slides_spec={'slides': [
            {'slideId': 'slide-1', 'layout': LayoutName.TITLE.value,
             'elements': [{'type': 'text', 'placeholder': 'TITLE', 'text': 'X'}]},
            {'slideId': 'slide-2', 'layout': LayoutName.TITLE_AND_BODY.value,
             'elements': [{'type': 'text', 'placeholder': 'BODY', 'text': 'Y'}]},
        ]},
        source_presentation_id='TEMPLATE-ID',
    )
    assert pid == 'PRES-TEMPL'
    assert len(requests) == 2

    # 1. Create body has sourcePresentationId at the top level.
    create_body = json.loads(requests[0][1].content.decode())
    assert create_body['sourcePresentationId'] == 'TEMPLATE-ID'

    # 2. BatchUpdate body has createSlide requests with layoutObjectId.
    batch_body = json.loads(requests[1][1].content.decode())
    requests_list = batch_body['requests']
    create_slide_reqs = [r for r in requests_list if 'createSlide' in r]
    assert len(create_slide_reqs) == 2
    assert create_slide_reqs[0]['createSlide']['slideLayoutReference']['layoutObjectId'] == LAYOUT_IDS['TITLE']  # noqa: E501
    assert create_slide_reqs[1]['createSlide']['slideLayoutReference']['layoutObjectId'] == LAYOUT_IDS['TITLE_AND_BODY']  # noqa: E501
    # Critically: NO predefinedLayout anywhere (would silently fall
    # back to Google built-ins with the same name).
    for r in create_slide_reqs:
        assert 'predefinedLayout' not in r['createSlide']['slideLayoutReference']
