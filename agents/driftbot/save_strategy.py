"""
Save strategy — pluggable destination for audit outputs.

For now, only a local-filesystem strategy is implemented (writes to
/tmp/drifterbot-pickup/<audit_id>/). When Drive auth is sorted,
add a `DriveSaveStrategy` and select via `DRIFTERBOT_SAVE_STRATEGY`
env var.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

from agents.driftbot.runner import AuditDraft


class SaveStrategy(ABC):
    """Pluggable destination for audit drafts."""

    @abstractmethod
    def save(self, draft: AuditDraft, slides_spec: dict) -> Path:
        """Persist the audit to the destination. Return human-readable path."""


class LocalPickupStrategy(SaveStrategy):
    """Writes to a local pickup dir for human review.

    Default `/tmp/drifterbot-pickup/<client-slug>-<audit_id>-<date>/`.
    Folder naming matches the convention Quinn locked in:
    `clients/<name>-<audit_id>-<date>/` — adapted to local as flat
    (no top-level `clients/` prefix needed for local pickup).
    """

    def __init__(self, root: Path = None) -> None:
        self.root = root or Path('/tmp/drifterbot-pickup')

    def save(self, draft: AuditDraft, slides_spec: dict) -> Path:
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

        return run_dir


def get_save_strategy() -> SaveStrategy:
    """Return the active save strategy based on env var."""
    name = os.environ.get('DRIFTERBOT_SAVE_STRATEGY', 'local_pickup')
    if name == 'local_pickup':
        return LocalPickupStrategy()
    raise ValueError(f"unknown save strategy: {name}")


def save_audit(draft: AuditDraft, slides_spec: dict, request_id: int) -> Path:
    """Convenience entry point used by the worker."""
    return get_save_strategy().save(draft, slides_spec)
