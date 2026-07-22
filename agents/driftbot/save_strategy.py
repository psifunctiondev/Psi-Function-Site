"""
Save strategy — pluggable destination for audit outputs.

Two strategies today:
    - LocalPickupStrategy: writes to a local pickup dir for review.
    - DriveSaveStrategy: pushes the Slides spec into the
      `BrandSight Client Output/` Drive folder via the Slides + Drive
      APIs.

Selected via ``DRIFTERBOT_SAVE_STRATEGY`` env var.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agents.driftbot.runner import AuditDraft

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type — one shape for all strategies
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SaveResult:
    """What every SaveStrategy.save() returns.

    Attributes:
        location:   Human-readable reference (a Path for local, a Drive
                    URL or presentation URI for Drive). Used in logs
                    and the worker status message.
        presentation_id:  Google Slides presentation ID, if applicable.
                          None for non-Slides strategies.
        web_url:    Edit URL on docs.google.com, if applicable.
    """

    location: str | Path
    presentation_id: str | None = None
    web_url: str | None = None


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class SaveStrategy(ABC):
    """Pluggable destination for audit drafts."""

    @abstractmethod
    def save(self, draft: AuditDraft, slides_spec: dict) -> SaveResult:
        """Persist the audit to the destination."""


# ---------------------------------------------------------------------------
# Local pickup (unchanged behavior; only the return shape changed)
# ---------------------------------------------------------------------------


class LocalPickupStrategy(SaveStrategy):
    """Writes to a local pickup dir for human review.

    Default ``/tmp/drifterbot-pickup/<client-slug>-<audit_id>-<date>/``.
    Folder naming matches the convention Quinn locked in:
    ``clients/<name>-<audit_id>-<date>/`` — adapted to local as flat
    (no top-level ``clients/`` prefix needed for local pickup).
    """

    def __init__(self, root: Path = None) -> None:
        self.root = root or Path('/tmp/drifterbot-pickup')

    def save(self, draft: AuditDraft, slides_spec: dict) -> SaveResult:
        client_slug = draft.client.id  # already slugified upstream
        date_str = datetime.now(UTC).strftime('%Y-%m-%d')
        run_dir = self.root / f"{client_slug}-{draft.audit_id}-{date_str}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Write Slides spec JSON
        (run_dir / 'slides-spec.json').write_text(
            json.dumps(slides_spec, indent=2), encoding='utf-8',
        )

        # Write Markdown preview for human eye-balling
        from agents.driftbot.runner import render_audit_draft
        (run_dir / 'audit-draft.md').write_text(
            render_audit_draft(draft), encoding='utf-8',
        )

        return SaveResult(location=run_dir)


# ---------------------------------------------------------------------------
# Drive save strategy
# ---------------------------------------------------------------------------


# Default folder is the "BrandSight Client Output" subfolder inside the
# "DrifterBot" Shared Drive. Override via BRANDSIGHT_OUTPUT_FOLDER_ID env
# var. See portal-integration-spec.md §13.4 for topology.
DEFAULT_OUTPUT_FOLDER_ID = '1rrVimH-UB3qn0FJ0rBuZ9FoTTydSMdIS'


def _build_drive_filename(draft: AuditDraft) -> str:
    """{Client Name} - Competitive Audit - {YYYY-MM-DD-HH}

    Timestamp is sourced from ``draft.generated_at`` so the filename
    is deterministic per draft, not per process invocation — same-day
    duplicate drafts don't clobber each other, and re-running a build
    of an already-saved audit produces the same filename (idempotent).
    Hyphens match the era-agnostic convention in the rest of D&A
    filenames.

    Accepts both ISO-8601 (``2026-07-21T09:00:00Z`` — used by tests
    and the spec) and the legacy space-separated format produced by
    ``run_audit()`` (``2026-07-21 09 UTC``).
    """
    raw = draft.generated_at.strip()
    # ISO-8601: replace trailing Z with explicit UTC offset for fromisoformat
    iso = raw.replace('Z', '+00:00') if raw.endswith('Z') else raw
    try:
        ts = datetime.fromisoformat(iso).strftime('%Y-%m-%d-%H')
    except ValueError:
        # Legacy format: 'YYYY-MM-DD HH UTC' — split on whitespace
        try:
            date_part = raw.split()[0]
            hour_part = raw.split()[1]
            ts = f"{date_part}-{hour_part}"
        except (IndexError, ValueError):
            # Last-resort fallback: today's UTC date/hour. Avoids crashing
            # on malformed input but logs nothing here — caller should
            # validate generated_at shape upstream.
            ts = datetime.now(UTC).strftime('%Y-%m-%d-%H')
    return f"{draft.client.name} - Competitive Audit - {ts}"


def _build_drive_url(presentation_id: str) -> str:
    return f"https://docs.google.com/presentation/d/{presentation_id}/edit"


class DriveSaveStrategy(SaveStrategy):
    """Pushes the audit slides into the D&A BrandSight Output Drive folder
    via the Google Slides + Drive APIs (Path A-corrected: native Slides
    in Drive, no on-disk artifact).

    Workflow:
        1. JWT grant against the service-account JSON at
           ``DRIFTERBOT_SERVICE_ACCOUNT_JSON_PATH``, impersonating
           the workspace user ``subject=`` so the created
           presentation is owned by D&A, not the service
           account.
        2. POST ``/v1/presentations`` with ``{"title":  ..}``.
        3. POST ``/v1/presentations/{id}:batchUpdate`` to insert the
           slides + elements.
        4. PATCH ``/drive/v3/files/{id}?addParents=<folder_id>
           &removeParents=<prior>`` (with name + description in body).
           This atomically: renames, moves, and updates description —
           no orphan in My Drive.

    Environment:
        DRIFTERBOT_SERVICE_ACCOUNT_JSON_PATH:  path to
                                   service-account JSON key (default
                                   ``/opt/.../secrets/
                                   drifterbot-slidemaker.json``).
        DRIFTERBOT_SUBJECT:        workspace user to impersonate
                                   (e.g. ``drifterbot@drift-and-anchor.com``).
        BRANDSIGHT_OUTPUT_FOLDER_ID: Drive folder ID for the "DrifterBot"
                                     Shared Drive → "BrandSight Client
                                     Output" subfolder. Defaults to
                                     ``1rrVimH-UB3qn0FJ0rBuZ9FoTTydSMdIS``
                                     per portal-spec §13.4.
        DRIFTERBOT_BRAND_TEMPLATE_ID: Drive file ID of the D&A brand
                                     template (in BrandSight Input
                                     folder). When set, every audit
                                     deck is created FROM this template
                                     via ``sourcePresentationId``,
                                     inheriting masters/layouts/theme.
                                     Defaults to the live template ID
                                     from
                                     ``agents/driftbot/layout_catalog.py``.
                                     Set to empty string to disable
                                     template reuse and build blank.
    """

    def __init__(
        self,
        *,
        service_account_json_path: Path | None = None,
        subject: str | None = None,
        output_folder_id: str | None = None,
        brand_template_id: str | None = None,
        slides_client=None,  # dependency injection seam for tests
    ) -> None:
        self.service_account_json_path = (
            service_account_json_path
            or Path(
                os.environ.get(
                    'DRIFTERBOT_SERVICE_ACCOUNT_JSON_PATH',
                    '/opt/consulting-site/production/shared/secrets/'
                    'drifterbot-slidemaker.json',
                )
            )
        )
        self.subject = subject or os.environ.get('DRIFTERBOT_SUBJECT', '')
        self.output_folder_id = (
            output_folder_id
            or os.environ.get('BRANDSIGHT_OUTPUT_FOLDER_ID')
            or DEFAULT_OUTPUT_FOLDER_ID
        )
        # Brand template ID — kwarg wins over env wins over default.
        # Lazy import to avoid loading layout_catalog at module import.
        from agents.driftbot.layout_catalog import DEFAULT_BRAND_TEMPLATE_ID
        env_template = os.environ.get('DRIFTERBOT_BRAND_TEMPLATE_ID')
        if brand_template_id is not None:
            # Explicit kwarg takes precedence — including explicit
            # None to force blank. (Empty-string kwarg treated as
            # "disable" to match env semantics.)
            self.brand_template_id = (
                brand_template_id if brand_template_id != ''
                else None
            )
        elif env_template == '':
            # Explicit empty string in env disables template reuse
            # (force blank) — useful for debugging 'why does this
            # look wrong?' without commenting out code.
            self.brand_template_id = None
        elif env_template is not None:
            self.brand_template_id = env_template
        else:
            self.brand_template_id = DEFAULT_BRAND_TEMPLATE_ID
        # Lazy import + dependency injection so tests can swap a fake.
        if slides_client is None:
            from agents.driftbot.slides_client import SlidesClient
            self._slides_client = SlidesClient(
                service_account_json_path=self.service_account_json_path,
                subject=self.subject,
            )
        else:
            self._slides_client = slides_client

    def save(self, draft: AuditDraft, slides_spec: dict) -> SaveResult:
        if not self.subject:
            raise RuntimeError(
                'DriveSaveStrategy: no subject configured '
                '(set DRIFTERBOT_SUBJECT — the workspace user to '
                'impersonate for presentation ownership)'
            )

        filename = _build_drive_filename(draft)
        # Slides API takes title == filename without extension.
        title = filename

        # Step 1+2: create + batchUpdate. If create fails outright
        # we have no orphan to clean up. If create succeeds but
        # batchUpdate fails, the empty presentation is orphaned and
        # we delete it before surfacing the error.
        presentation_id: str | None = None
        try:
            presentation_id = self._slides_client.create_presentation(
                title=title,
                slides_spec=slides_spec,
                source_presentation_id=self.brand_template_id,
            )
        except Exception:
            logger.exception(
                'DriveSaveStrategy: create_presentation failed for '
                'audit_id=%s client=%s — no artifact yet, nothing to '
                'clean up',
                draft.audit_id, draft.client.id,
            )
            raise

        # If create_presentation succeeded but raised partway through
        # (e.g. batchUpdate failed after presentations.create already
        # landed), it returns no presentation_id. Treat any partial
        # state as needing cleanup.
        if presentation_id is None:
            logger.error(
                'DriveSaveStrategy: create_presentation returned '
                'None for audit_id=%s client=%s',
                draft.audit_id, draft.client.id,
            )
            raise RuntimeError(
                'SlidesClient.create_presentation returned no id '
                '(create may have partially succeeded — check '
                'workspace user Drive for orphan)'
            )

        # Step 3: move into target folder. On any failure, delete
        # the presentation to prevent leaving an orphan in the
        # impersonated user's My Drive.
        try:
            web_url = self._slides_client.move_to_folder(
                presentation_id=presentation_id,
                folder_id=self.output_folder_id,
                name=filename,
            )
        except Exception:
            logger.exception(
                'DriveSaveStrategy: move_to_folder failed for '
                'audit_id=%s client=%s — orphan presentation '
                'id=%s in workspace user Drive; cleaning up',
                draft.audit_id, draft.client.id, presentation_id,
            )
            try:
                self._slides_client.delete_file(presentation_id)
                logger.info(
                    'DriveSaveStrategy: cleaned up orphan '
                    'presentation_id=%s audit_id=%s',
                    presentation_id, draft.audit_id,
                )
            except Exception:
                logger.exception(
                    'DriveSaveStrategy: cleanup-orphan FAILED for '
                    'presentation_id=%s — manual cleanup needed '
                    '(/tmp/cleanup_orphan.py)',
                    presentation_id,
                )
            # Re-raise the original error (not the cleanup failure).
            raise

        logger.info(
            'DriveSaveStrategy: saved presentation_id=%s url=%s '
            'folder_id=%s client=%s audit_id=%s',
            presentation_id, web_url, self.output_folder_id,
            draft.client.id, draft.audit_id,
        )
        return SaveResult(
            location=f'https://drive.google.com/drive/folders/{self.output_folder_id}',
            presentation_id=presentation_id,
            web_url=web_url,
        )
# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_save_strategy() -> SaveStrategy:
    """Return the active save strategy based on env var."""
    name = os.environ.get('DRIFTERBOT_SAVE_STRATEGY', 'local_pickup')
    if name == 'local_pickup':
        return LocalPickupStrategy()
    if name == 'drive':
        return DriveSaveStrategy()
    raise ValueError(f"unknown save strategy: {name!r}")


def save_audit(draft: AuditDraft, slides_spec: dict, request_id: int) -> SaveResult:
    """Convenience entry point used by the worker."""
    return get_save_strategy().save(draft, slides_spec)
