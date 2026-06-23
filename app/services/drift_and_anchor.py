"""Drift & Anchor service — scaffold (R1).

Placeholder module for the Drift & Anchor client portal. R1 only defines
the public surface so templates and routes can import it; no real
behaviour is wired yet. R2/R3 will fill in the engagement-hub pieces
(OpenProject mirror, MkDocs guide index, contact routing, milestone
timeline) — see the engagement card on the landing page for the
shape that's coming.

Anything the UI imports today should be safe to call — it will raise
:class:`DriftAndAnchorNotConfigured` until the wiring lands.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "DriftAndAnchorNotConfigured",
    "list_engagement_milestones",
    "get_case_studies",
    "list_openproject_projects",
    "list_mkdocs_guides",
    "get_contact_routes",
]


class DriftAndAnchorNotConfigured(NotImplementedError):
    """Raised by the scaffold placeholder functions.

    Will be removed once the service module is wired up. Catch this in
    route code so the UI can show a friendly "coming soon" message
    instead of a 500.
    """


def list_engagement_milestones(*args: Any, **kwargs: Any) -> list[Any]:
    """Return the engagement milestone timeline.

    Stub: raises :class:`DriftAndAnchorNotConfigured`. The landing page
    does not call this yet — the engagement card is R1 placeholder copy.
    """
    raise DriftAndAnchorNotConfigured(
        "Drift & Anchor service is scaffolded only; "
        "list_engagement_milestones lands in R2."
    )


def get_case_studies(*args: Any, **kwargs: Any) -> list[Any]:
    """Return the featured case-study write-ups.

    Stub: raises :class:`DriftAndAnchorNotConfigured`. Will power the
    Featured Case Studies resource on the dashboard.
    """
    raise DriftAndAnchorNotConfigured(
        "Drift & Anchor service is scaffolded only; "
        "get_case_studies lands in R2."
    )


def list_openproject_projects(*args: Any, **kwargs: Any) -> list[Any]:
    """Return the OpenProject workspace projects for this client.

    Stub: raises :class:`DriftAndAnchorNotConfigured`. Will back the
    Project Workspace resource (live backlog read-through).
    """
    raise DriftAndAnchorNotConfigured(
        "Drift & Anchor service is scaffolded only; "
        "list_openproject_projects lands in R2."
    )


def list_mkdocs_guides(*args: Any, **kwargs: Any) -> list[Any]:
    """Return the MkDocs-hosted strategy frameworks / playbooks.

    Stub: raises :class:`DriftAndAnchorNotConfigured`. Will back the
    User Guides resource.
    """
    raise DriftAndAnchorNotConfigured(
        "Drift & Anchor service is scaffolded only; "
        "list_mkdocs_guides lands in R2."
    )


def get_contact_routes(*args: Any, **kwargs: Any) -> Any:
    """Return the contact / handoff routing config.

    Stub: raises :class:`DriftAndAnchorNotConfigured`. Will back the
    Contact resource and the ``Engagement hub`` card on the landing.
    """
    raise DriftAndAnchorNotConfigured(
        "Drift & Anchor service is scaffolded only; "
        "get_contact_routes lands in R2."
    )
