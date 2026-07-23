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
    via the rclone FUSE mount on the droplet.

    Workflow (B2 architecture — mount-based write):
        1. JWT grant against ``DRIFTERBOT_SLIDEMAKER_JSON`` (service
           account), impersonating the workspace user ``subject=`` so
           the created presentation is owned by D&A, not the service
           account.
        2. POST ``/v1/presentations`` with ``{"title": <filename-without-
           ext>}`` — note this only sets the title; content goes in
           step 3.
        3. POST ``/v1/presentations/{id}:batchUpdate`` to insert the
           actual slides + elements from the spec.
        4. GET ``/drive/v3/files/{id}/export?mimeType=...pptx`` to
           serialize the rendered Slides presentation into PPTX bytes
           (we don't write a Google-native file to disk — we want
           a real .pptx so rclone through the FUSE mount can serve
           it).
        5. Write bytes to ``BRANDSIGHT_OUTPUT_PATH/<sanitized-name>.pptx``
           — the rclone mount auto-propagates to the workspace
           Shared Drive "DrifterBot" → ``BrandSight Client Output/``.

    Environment:
        DRIFTERBOT_SA_JSON_PATH:      path to service-account JSON key
                                       (default ``/opt/.../secrets/
                                       drifterbot-slidemaker.json``).
        DRIFTERBOT_SUBJECT:            workspace user to impersonate
                                       (e.g. ``drifterbot@drift-and-anchor.com``).
        BRANDSIGHT_OUTPUT_PATH:        absolute filesystem path; the
                                       droplet's rclone mount
                                       (``/mnt/brandsight-output/``)
                                       makes writes auto-propagate to
                                       the workspace Shared Drive.
                                       Defaults to
                                       ``/mnt/brandsight-output``.
    """

    def __init__(
        self,
        *,
        service_account_json_path: Path | None = None,
        subject: str | None = None,
        output_path: Path | None = None,
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
        self.output_path = (
            output_path
            or Path(
                os.environ.get('BRANDSIGHT_OUTPUT_PATH', '/mnt/brandsight-output')
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
        if not self.subject:
            raise RuntimeError(
                'DriveSaveStrategy: no subject configured '
                '(set DRIFTERBOT_SUBJECT — the workspace user to '
                'impersonate for presentation ownership)'
            )

        filename = _build_drive_filename(draft)
        # Slides API takes title == filename without extension.
        title = filename
        # On-disk PPTX file gets a .pptx extension; mount strips it.
        on_disk_name = f"{filename}.pptx"

        try:
            presentation_id = self._slides_client.create_presentation(
                title=title,
                slides_spec=slides_spec,
            )
        except Exception:
            logger.exception(
                'DriveSaveStrategy: create_presentation failed for '
                'audit_id=%s client=%s — no on-disk artifact yet',
                draft.audit_id, draft.client.id,
            )
            raise

        try:
            pptx_bytes = self._slides_client.export_to_pptx(presentation_id)
        except Exception:
            # Orphan presentation exists in the workspace user's Drive
            # by this point. Log loudly; worker treats any exception
            # as fatal. (Future: cleanup PR deletes the orphan.)
            logger.exception(
                'DriveSaveStrategy: export_to_pptx failed for '
                'audit_id=%s client=%s — orphan presentation '
                'id=%s in workspace user Drive',
                draft.audit_id, draft.client.id, presentation_id,
            )
            raise

        # Write PPTX bytes through the rclone mount. mount handles
        # upload to the Shared Drive asynchronously.
        try:
            self.output_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.exception(
                'DriveSaveStrategy: mkdir failed for output_path=%s',
                self.output_path,
            )
            raise RuntimeError(
                f'cannot create output dir {self.output_path}: {exc}'
            ) from exc

        target = self.output_path / on_disk_name
        try:
            target.write_bytes(pptx_bytes)
        except OSError as exc:
            logger.exception(
                'DriveSaveStrategy: write failed for target=%s',
                target,
            )
            raise RuntimeError(
                f'cannot write pptx to {target}: {exc}'
            ) from exc

        web_url = _build_drive_url(presentation_id)
        logger.info(
            'DriveSaveStrategy: wrote pptx=%s presentation_id=%s url=%s '
            'client=%s audit_id=%s bytes=%d',
            target, presentation_id, web_url,
            draft.client.id, draft.audit_id, len(pptx_bytes),
        )
        return SaveResult(
            location=target,
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
