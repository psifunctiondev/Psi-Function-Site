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


# Default folder is `brandsight-output` per vaults/doxa/brandsight-mount-ids.md
# (the BrandSight Client Output subfolder). Override via env on droplet.
DEFAULT_OUTPUT_FOLDER_ID = '1rrVimH-UB3qn0FJ0rBuZ9FoTTydSMdIS'


def _build_drive_filename(draft: AuditDraft) -> str:
    """{Client Name} - Competitive Audit - {YYYY-MM-DD-HH}

    24h UTC so two audits same day don't collide; hyphens match the
    era-agnostic convention in the rest of D&A filenames.
    """
    ts = datetime.now(UTC).strftime('%Y-%m-%d-%H')
    return f"{draft.client.name} - Competitive Audit - {ts}"


def _build_drive_url(presentation_id: str) -> str:
    return f"https://docs.google.com/presentation/d/{presentation_id}/edit"


class DriveSaveStrategy(SaveStrategy):
    """Pushes the audit slides into the D&A BrandSight Output Drive folder.

    Workflow:
        1. JWT grant against ``DRIFTERBOT_SLIDEMAKER_JSON`` (service
           account), impersonating the workspace user ``subject=`` so
           the created presentation is owned by D&A, not the service
           account.
        2. POST ``/v1/presentations`` with ``{"title": <filename-without-
           ext>}`` — note this only sets the title; content goes in
           step 3.
        3. POST ``/v1/presentations/{id}:batchUpdate`` to insert the
           actual slides + elements from the spec.
        4. PATCH ``/drive/v3/files/{id}`` to set the *filename* (Drive
           UI uses filename, not Slides title) and ``parents`` to the
           output folder.
        5. Return a ``SaveResult`` with the presentation ID + edit URL.

    Environment:
        DRIFTERBOT_SA_JSON_PATH: path to service-account JSON key
                                  (default ``/opt/.../secrets/
                                  drifterbot-slidemaker.json``).
        DRIFTERBOT_SUBJECT:       workspace user to impersonate
                                  (e.g. ``drifterbot@drift-and-anchor.com``).
        DRANDSIGHT_OUTPUT_FOLDER_ID:  override the output folder ID;
                                       defaults to ``brandsight-output``.
        DRIFTERBOT_OUTPUT_FOLDER_ID:  fallback env var name if the
                                       spec above is wrong (not used by
                                       default — env alias kept for
                                       future flexibility).
    """

    def __init__(
        self,
        *,
        service_account_json_path: Path | None = None,
        subject: str | None = None,
        output_folder_id: str | None = None,
        slides_client=None,  # dependency injection seam for tests
    ) -> None:
        self.service_account_json_path = (
            service_account_json_path
            or Path(
                os.environ.get(
                    'DRIFTERBOT_SA_JSON_PATH',
                    '/opt/consulting-site/production/shared/secrets/'
                    'drifterbot-slidemaker.json',
                )
            )
        )
        self.subject = subject or os.environ.get('DRIFTERBOT_SUBJECT', '')
        self.output_folder_id = (
            output_folder_id
            or os.environ.get(
                'BRANDSIGHT_OUTPUT_FOLDER_ID',
                os.environ.get(
                    'DRIFTERBOT_OUTPUT_FOLDER_ID',
                    DEFAULT_OUTPUT_FOLDER_ID,
                ),
            )
        )
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
        if not self.output_folder_id:
            raise RuntimeError(
                'DriveSaveStrategy: no output folder configured '
                '(set BRANDSIGHT_OUTPUT_FOLDER_ID or pass output_folder_id=)'
            )
        if not self.subject:
            raise RuntimeError(
                'DriveSaveStrategy: no subject configured '
                '(set DRIFTERBOT_SUBJECT — the workspace user to '
                'impersonate for presentation ownership)'
            )

        filename = _build_drive_filename(draft)
        # Drive filenames omit the extension; Slides gets title == name.
        title = filename

        try:
            presentation_id = self._slides_client.create_presentation(
                title=title,
                slides_spec=slides_spec,
            )
            self._slides_client.move_to_folder(
                presentation_id=presentation_id,
                folder_id=self.output_folder_id,
                name=filename,
            )
        except Exception:
            logger.exception(
                'DriveSaveStrategy: failed for audit_id=%s client=%s',
                draft.audit_id, draft.client.id,
            )
            # If the presentation was created but the move failed, we
            # have an orphan in the workspace user's root — log loud,
            # re-raise. Worker treats any exception as fatal.
            raise

        web_url = _build_drive_url(presentation_id)
        logger.info(
            'DriveSaveStrategy: created presentation_id=%s url=%s '
            'client=%s audit_id=%s',
            presentation_id, web_url, draft.client.id, draft.audit_id,
        )
        return SaveResult(
            location=web_url,
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
