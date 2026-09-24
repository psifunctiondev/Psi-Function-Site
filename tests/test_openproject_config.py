"""Unit tests for the OpenProject config helper (``current_op_client``).

The portal talks to OpenProject via two env vars:

* ``OPENPROJECT_URL``     — instance root, e.g. ``https://op.example.com:5443``
* ``OPENPROJECT_API_KEY`` — service-account API key (used for writes)

``current_op_client()`` returns a singleton-style client when both env
vars are set. When either is missing, it raises ``OpenProjectConfigError``
with a message that names the missing vars — so the operator sees a
clear failure rather than a stack trace.

The helper is deliberately a thin env-reader; tests pin:
* Both unset -> OpenProjectConfigError naming BOTH vars
* Only URL set -> OpenProjectConfigError naming OPENPROJECT_API_KEY
* Only KEY set -> OpenProjectConfigError naming OPENPROJECT_URL
* Both set -> returns OpenProjectClient with the configured URL + KEY
* URL gets a trailing-slash strip (consistent with OpenProjectClient.__init__)
"""

from __future__ import annotations

import pytest

from app.services.openproject_config import (
    OpenProjectConfigError,
    current_op_client,
)


def test_current_op_client_raises_when_both_env_vars_missing(monkeypatch):
    monkeypatch.delenv("OPENPROJECT_URL", raising=False)
    monkeypatch.delenv("OPENPROJECT_API_KEY", raising=False)
    with pytest.raises(OpenProjectConfigError) as exc:
        current_op_client()
    msg = str(exc.value)
    assert "OPENPROJECT_URL" in msg
    assert "OPENPROJECT_API_KEY" in msg


def test_current_op_client_raises_when_only_url_set(monkeypatch):
    monkeypatch.setenv("OPENPROJECT_URL", "https://op.example.com")
    monkeypatch.delenv("OPENPROJECT_API_KEY", raising=False)
    with pytest.raises(OpenProjectConfigError) as exc:
        current_op_client()
    assert "OPENPROJECT_API_KEY" in str(exc.value)


def test_current_op_client_raises_when_only_key_set(monkeypatch):
    monkeypatch.delenv("OPENPROJECT_URL", raising=False)
    monkeypatch.setenv("OPENPROJECT_API_KEY", "secret-key")
    with pytest.raises(OpenProjectConfigError) as exc:
        current_op_client()
    assert "OPENPROJECT_URL" in str(exc.value)


def test_current_op_client_returns_client_when_both_set(monkeypatch):
    monkeypatch.setenv("OPENPROJECT_URL", "https://op.example.com")
    monkeypatch.setenv("OPENPROJECT_API_KEY", "secret-key")
    client = current_op_client()
    from app.services.openproject import OpenProjectClient
    assert isinstance(client, OpenProjectClient)
    assert client.base_url == "https://op.example.com"
    # API key is sent as the apikey basic-auth header; verify by checking
    # that _auth_header is a Basic header (Base64 of "apikey:secret-key").
    import base64
    expected = base64.b64encode(b"apikey:secret-key").decode()
    assert client._auth_header == f"Basic {expected}"


def test_current_op_client_strips_trailing_slash(monkeypatch):
    """``OPENPROJECT_URL`` may or may not have a trailing slash — the
    client should normalize. Mirrors OpenProjectClient.__init__ behavior
    but is re-pinned here so a future refactor can't silently break it."""
    monkeypatch.setenv("OPENPROJECT_URL", "https://op.example.com/")
    monkeypatch.setenv("OPENPROJECT_API_KEY", "k")
    client = current_op_client()
    assert client.base_url == "https://op.example.com"


def test_current_op_client_treats_blank_env_as_missing(monkeypatch):
    """A blank OPENPROJECT_URL or OPENPROJECT_API_KEY (operator typed the
    name but left the value empty) must behave the same as missing —
    surface a config error, not a downstream auth failure."""
    monkeypatch.setenv("OPENPROJECT_URL", "")
    monkeypatch.setenv("OPENPROJECT_API_KEY", "")
    with pytest.raises(OpenProjectConfigError):
        current_op_client()
