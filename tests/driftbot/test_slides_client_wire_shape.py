"""
Wire-shape tests for SlidesClient.export_to_pptx.

The unit tests in test_drive_save_strategy.py mock at the SlidesClient
boundary and never verify the actual HTTP request shape. These tests
use a FakeTransport on httpx so we can read the actual URL + params
that get sent to Google. They catch anything that "looks plausible on
read-through" but doesn't actually do what the API expects.

Specifically: Drive ``files.export`` requires ``mimeType`` as a query
param (not a header, not a body field). Slide presentation ID goes
in the path. Easy to get wrong; tested here.

Author: Doxa — refactored 2026-07-21 from move_to_folder tests after
B2 architecture pivot (mount-based write replaces Drive parent-PATCH).
"""

from __future__ import annotations

import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from agents.driftbot.slides_client import (
    DriveAuthError,
    SlidesClient,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


FAKE_PPTX = b'PK\x03\x04\x14\x00\x00\x00\x00\x00FAKE-PPTX-CONTENT'


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
    """SlidesClient with a MockTransport that handles the token grant
    and lets each test set the handler for subsequent (export) requests.
    """
    state = {'next_handler': None}

    def combined_handler(request: httpx.Request) -> httpx.Response:
        # Token grant — return a fake bearer
        if 'oauth2.googleapis.com/token' in str(request.url):
            return httpx.Response(
                200,
                content=json.dumps(
                    {'access_token': 'fake-token', 'expires_in': 3600}
                ).encode(),
            )
        # Otherwise, defer to the test-supplied handler
        h = state['next_handler']
        if h is None:
            raise AssertionError(
                'SlidesClient made an extra request — '
                'did the test wire all expected calls?'
            )
        return h(request)

    http = httpx.Client(
        transport=httpx.MockTransport(combined_handler), timeout=30.0,
    )
    c = SlidesClient(
        service_account_json_path=fake_sa_key,
        subject='drifterbot@drift-and-anchor.com',
        _http_client=http,
    )
    c._set_export_handler = lambda handler: state.update(next_handler=handler)
    return c


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


def test_export_to_pptx_uses_correct_mime_in_query_param(client):
    received_url = []

    def handler(request: httpx.Request) -> httpx.Response:
        received_url.append(str(request.url))
        return httpx.Response(200, content=FAKE_PPTX)

    client._set_export_handler(handler)
    pptx_bytes = client.export_to_pptx('PRES-1234')

    assert pptx_bytes == FAKE_PPTX
    assert len(received_url) == 1, 'export_to_pptx made extra requests'
    url = received_url[0]
    assert '/drive/v3/files/PRES-1234/export' in url
    assert 'mimeType=' in url
    assert 'application' in url
    assert 'presentationml.presentation' in url


def test_export_to_pptx_returns_bytes(client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FAKE_PPTX)

    client._set_export_handler(handler)
    result = client.export_to_pptx('PRES-ABCD')
    assert isinstance(result, bytes)
    assert result == FAKE_PPTX


def test_export_to_pptx_raises_on_non_200(client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500, content=b'{"error":{"message":"server side"}}',
        )

    client._set_export_handler(handler)
    with pytest.raises(DriveAuthError, match='files.export failed'):
        client.export_to_pptx('PRES-XYZ')
