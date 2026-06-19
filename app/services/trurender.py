"""TruRender service — scaffold (R1).

The portal-side adapter for the TruRender render-to-photograph pipeline. The
remote pipeline itself lives at ``agents/tekton/modal/trurender_comfyui.py``
(deployed to Modal, ComfyUI + Flux.1-dev) — see
``SharedObsidian/TruRender Technical Reference.md`` for parameters and the
proven winning config.

This module is the seam where the portal talks to the pipeline. R1 only
defines the public surface so that templates and routes can import it; no
network I/O is wired yet. R2/R3 will fill in:

    * process flow shape (one render == one TruRenderJob row)
    * history list query
    * parameter exposure (denoise / canny / controlnet / cfg / steps / max_dim)
    * audit log (who kicked off which render, with what params)
    * Modal integration (upload source to signed URL, POST to /render,
      poll status, pull result back to ``instance/uploads/ctai/<job_id>/``)

Anything the UI imports today should be safe to call — it will raise
:class:`NotImplementedError` until the wiring lands.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "TruRenderNotConfigured",
    "list_jobs",
    "get_job",
    "create_job",
    "submit_job",
    "cancel_job",
]


class TruRenderNotConfigured(NotImplementedError):
    """Raised by the scaffold placeholder functions.

    Will be removed in R2 once the service module is wired up. Catch this in
    route code so the UI can show a friendly "coming soon" message instead of
    a 500.
    """


def list_jobs(*args: Any, **kwargs: Any) -> list[Any]:
    """Return jobs for a given client. R2: query ``TruRenderJob`` rows.

    R1 stub: raises :class:`TruRenderNotConfigured`. The portal overview page
    does not call this yet — the CTA box is the only interactive element in
    R1 — so it's safe to leave as a placeholder.
    """
    raise TruRenderNotConfigured(
        "TruRender service is scaffolded only; list_jobs lands in R2."
    )


def get_job(*args: Any, **kwargs: Any) -> Any:
    """Fetch a single job by id. R2: row lookup.

    R1 stub: raises :class:`TruRenderNotConfigured`.
    """
    raise TruRenderNotConfigured(
        "TruRender service is scaffolded only; get_job lands in R2."
    )


def create_job(*args: Any, **kwargs: Any) -> Any:
    """Persist a new job row in pending state. R2: insert + return id.

    R1 stub: raises :class:`TruRenderNotConfigured`.
    """
    raise TruRenderNotConfigured(
        "TruRender service is scaffolded only; create_job lands in R2."
    )


def submit_job(*args: Any, **kwargs: Any) -> Any:
    """Hand a pending job to the Modal ComfyUI pipeline. R2: HTTP POST + poll.

    R1 stub: raises :class:`TruRenderNotConfigured`.
    """
    raise TruRenderNotConfigured(
        "TruRender service is scaffolded only; submit_job lands in R2."
    )


def cancel_job(*args: Any, **kwargs: Any) -> Any:
    """Cancel an in-flight job. R2: signal Modal + mark row cancelled.

    R1 stub: raises :class:`TruRenderNotConfigured`.
    """
    raise TruRenderNotConfigured(
        "TruRender service is scaffolded only; cancel_job lands in R2."
    )
