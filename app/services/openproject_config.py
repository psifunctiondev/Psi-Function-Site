"""OpenProject configuration helper.

The portal talks to OpenProject via two env vars (per the kickoff spec
2026-04-24):

* ``OPENPROJECT_URL``     — instance root, e.g. ``https://op.example.com:5443``
* ``OPENPROJECT_API_KEY`` — service-account API key (used for writes)

``current_op_client()`` returns an :class:`OpenProjectClient` when both
env vars are set. When either is missing (or blank), it raises
:class:`OpenProjectConfigError` with a message that names the missing
vars — operators see a clear failure rather than a stack trace.

The helper is deliberately a thin env-reader. A singleton is not used
because Flask ``current_app`` is the right dependency for the
process-wide app context — and tests can monkeypatch ``os.environ`` to
control what each test sees.
"""

from __future__ import annotations

import os

from .openproject import OpenProjectClient

__all__ = ["current_op_client", "OpenProjectConfigError"]


class OpenProjectConfigError(RuntimeError):
    """Raised when ``OPENPROJECT_URL`` / ``OPENPROJECT_API_KEY`` are not set.

    Surfaces a clear, actionable message that names the missing vars so
    operators don't have to dig through stack traces to find the env
    gap. Distinguishes this from auth failures (which are OpenProject's
    401/403 response).
    """


def current_op_client() -> OpenProjectClient:
    """Return an :class:`OpenProjectClient` configured from env vars.

    Reads ``OPENPROJECT_URL`` and ``OPENPROJECT_API_KEY`` from
    ``os.environ``. Both must be present and non-blank. Raises
    :class:`OpenProjectConfigError` listing every missing var.

    The client's ``base_url`` is normalized (trailing slash stripped)
    to match :class:`OpenProjectClient`'s own contract — pinned by the
    config-helper test so a future refactor can't break the contract
    silently.
    """
    url = (os.environ.get("OPENPROJECT_URL") or "").strip()
    api_key = (os.environ.get("OPENPROJECT_API_KEY") or "").strip()

    missing = []
    if not url:
        missing.append("OPENPROJECT_URL")
    if not api_key:
        missing.append("OPENPROJECT_API_KEY")
    if missing:
        raise OpenProjectConfigError(
            "OpenProject client not configured: missing env var(s): "
            + ", ".join(missing)
            + ". Set both OPENPROJECT_URL and OPENPROJECT_API_KEY to "
            + "enable portal writes."
        )
    return OpenProjectClient(url, api_key)
