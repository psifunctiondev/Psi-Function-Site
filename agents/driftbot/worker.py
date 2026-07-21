"""
DrifterBot worker — picks up ``submitted`` rows from Psi-Function-Site's
``competitive_audit_submission`` table (the R1 portal-intake surface)
and runs the audit pipeline against them.

β-3 (2026-07-16) rewrite — drops the old ``AuditRequest`` schema entirely
and points the worker at the new ``CompetitiveAuditSubmission`` model.

Lifecycle (raw string to avoid Python 3.13 backslash escape warnings):

    submitted -> processing -> complete
                      \\-> failed

Pickup query uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so two concurrent
worker invocations (e.g. overlapping cron ticks) cannot grab the same
row. Status transitions happen inside the same transaction; commit at
the end.

Cron wiring (heartbeat on tier/heartbeat)
-----------------------------------------
The OpenClaw cron (or any scheduler) calls ``process_pending_audit_requests``
on a short interval. Heartbeat model (``tier/heartbeat`` → gemma4:e4b)
is fine — this is mechanical DB I/O + subprocess invocation, no LLM
reasoning in the hot path. The actual DrifterBot *run* (the LLM-shaped
work inside ``runner.run_audit``) uses a different model tier; see
``worker_README.md`` for the recommended split.

Drive auth is parked. For now, LocalPickupStrategy writes to
``/tmp/drifterbot-pickup/``. When Drive auth lands, add
``DriveSaveStrategy`` and a selection branch in ``get_save_strategy()``.

DB access notes
---------------
The worker imports Psi-Function-Site's SQLAlchemy ``db`` object and the
``CompetitiveAuditSubmission`` model. Configuration:
``PSIFUNCTIONSITE_DATABASE_URL`` env var (a SQLAlchemy URL like
``postgresql+psycopg://user:pass@host/db``). Falls back to the
``DATABASE_URL`` env var if the dedicated one isn't set.

Usage
-----
    # CLI mode (process all submitted, exit):
    python3 -m agents.driftbot.worker

    # Programmatic (used by tests + cron):
    from agents.driftbot.worker import process_pending_audit_requests
    processed_ids = process_pending_audit_requests()

Public surface
--------------
- ``CompetitiveAuditAdapter`` — converts CompetitiveAuditSubmission rows
  into ``ClientConfig`` + ``CompetitorConfig`` lists. Reads from
  ``form_data`` JSON (the R1 surface shape).
- ``AuditRequestAdapter`` — retained as a deprecated alias that maps to
  ``CompetitiveAuditAdapter`` for one commit, so any external caller
  that still imports it gets a clear error instead of an ImportError.
  Will be deleted next refactor.
- ``process_pending_audit_requests()`` — pick up all submitted rows,
  process them in a single transaction, return processed IDs.
- ``run_one_audit_request(audit_request_id)`` — process a single row
  by primary key. Useful for retries / manual ops.
"""

from __future__ import annotations

import logging
import os
import traceback
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from agents.driftbot.renderer_slides import render_slides_spec
from agents.driftbot.runner import (
    AuditDraft,
    ClientConfig,
    CompetitorConfig,
    run_audit,
)
from agents.driftbot.save_strategy import save_audit

logger = logging.getLogger(__name__)

# Module-level constant for the gateway env file path. Tests monkeypatch
# this to inject fake env files without touching the real one.
_GATEWAY_ENV_PATH = Path('/Users/doxa/.openclaw/service-env/ai.openclaw.gateway.env')

# Channels surfaced in R1's competitor sub-cards' ``include_socials``
# toggles. Order matches the template's checkbox layout (x, facebook,
# instagram, youtube). Used by ``CompetitiveAuditAdapter`` to flatten
# the per-competitor toggle dict into the runner's flat social-scans
# list.
_R1_SOCIAL_CHANNELS: tuple[str, ...] = (
    'x', 'facebook', 'instagram', 'youtube',
)

# ---------------------------------------------------------------------------
# DB plumbing
# ---------------------------------------------------------------------------


def _resolve_database_url() -> str:
    """Resolve the DB URL.

    Resolution order:
    1. ``PSIFUNCTIONSITE_DATABASE_URL`` (worker-specific override).
    2. ``DATABASE_URL`` (Flask convention; matches Psi-Function-Site's
       ``app.config.SQLALCHEMY_DATABASE_URI`` lookup).
    3. Fallback: ``load_dotenv()`` from the OpenClaw gateway env file
       (``/Users/doxa/.openclaw/service-env/ai.openclaw.gateway.env``).
       This is the cron-friendly path: the cron agentTurn subprocess
       may have its env filtered (``OPENCLAW_SERVICE_MANAGED_ENV_KEYS``
       only allows whitelisted keys), so the worker re-reads the env
       file directly.

    Raises ``RuntimeError`` if no URL is found OR the URL still contains
    template placeholders (``<user>``, ``<pass>``, ``<host>``, ``<db>``).
    """
    # 1 & 2: explicit env vars
    url = (
        os.environ.get('PSIFUNCTIONSITE_DATABASE_URL')
        or os.environ.get('DATABASE_URL')
    )

    # 3: fallback — read the gateway env file directly
    if not url:
        url = _load_database_url_from_gateway_env()

    if not url:
        raise RuntimeError(
            'worker: PSIFUNCTIONSITE_DATABASE_URL (or DATABASE_URL) must be set. '
            'See worker_README.md for the cron wiring snippet.'
        )

    # Sanity: reject placeholder values so we fail loudly instead of
    # trying to connect with ``<user>`` as the username.
    placeholders = ('<user>', '<pass>', '<host>', '<db>', '***')
    if any(ph in url for ph in placeholders):
        raise RuntimeError(
            f'worker: DATABASE_URL still contains template placeholders: {url!r}. '
            'Replace <user>/<pass>/<host>/<db> in '
            '/Users/doxa/.openclaw/service-env/ai.openclaw.gateway.env '
            'with real prod credentials, then restart the gateway.'
        )

    return url


def _load_database_url_from_gateway_env() -> str | None:
    """Best-effort parse of ``DATABASE_URL`` from the gateway env file.

    The file is a shell-style ``export KEY=val`` sourceable file. We
    don't want to invoke a shell to avoid command-injection risk; parse
    line-by-line with a tiny state machine.
    """
    env_path = _GATEWAY_ENV_PATH
    if not env_path.exists():
        return None
    try:
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            # Match ``export KEY='val'`` or ``export KEY=val``
            if not line.startswith('export '):
                continue
            line = line[len('export '):].strip()
            if '=' not in line:
                continue
            key, _, val = line.partition('=')
            if key.strip() != 'DATABASE_URL':
                continue
            val = val.strip()
            # Strip surrounding single or double quotes
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            return val
    except OSError:
        return None
    return None


def _make_engine():
    """Build a SQLAlchemy engine + Session factory.

    We don't import Psi-Function-Site's ``db`` object directly because
    that pulls in Flask + extensions that the worker doesn't need (and
    that would fail outside a Flask app context). Instead, we declare
    the ``CompetitiveAuditSubmission`` table reflectively so the worker
    stays self-contained.
    """
    url = _resolve_database_url()

    # Import the model so its metadata is registered. This import pulls
    # in Psi-Function-Site's app.extensions.db, which is fine — the
    # runtime cost is one Python module load, not a Flask app boot.
    from app.extensions import db as _psf_db
    from app.models.competitive_audit import (  # noqa: F401  (side-effect: registers mapper)
        CompetitiveAuditSubmission,
    )

    engine = create_engine(url, pool_pre_ping=True, future=True)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    return engine, SessionFactory, CompetitiveAuditSubmission, _psf_db


# ---------------------------------------------------------------------------
# Adapter: CompetitiveAuditSubmission row -> runner inputs
# ---------------------------------------------------------------------------


class CompetitiveAuditAdapter:
    """Converts a Psi-Function-Site CompetitiveAuditSubmission row into
    the dataclass shapes DrifterBot's runner expects.

    The R1 portal surface stores everything in a single ``form_data``
    JSON column (client_name, competitor_1..4, each with brand_name +
    home_url + per-channel toggles). This adapter flattens that JSON
    into the runner's flat ``ClientConfig`` + list[CompetitorConfig].

    Shape contract (per ``drift_and_anchor_competitive_audit.html`` +
    ``_parse_competitive_audit_form`` in app/blueprints/portal/routes.py):

      form_data = {
        'client_name': 'Hallmark Health Care',
        'competitor_1': {'brand_name': 'Meridian', 'home_url': 'https://m.example',
                         'include_socials': {'x': True, 'facebook': False,
                                              'instagram': False, 'youtube': False}}
                        | None,   # None when the sub-card was submitted empty
        'competitor_2': ... | None,
        'competitor_3': ... | None,
        'competitor_4': ... | None,
      }
    """

    @staticmethod
    def to_client_config(submission) -> ClientConfig:
        """CompetitiveAuditSubmission -> ClientConfig.

        R1's submission shape doesn't capture ``category`` /
        ``audiences`` / ``positioning_inputs`` directly — those were
        the old ``AuditRequest`` fields. We synthesise safe defaults
        so the runner code (which dereferences them unconditionally)
        doesn't crash on an empty R1 row:

        - ``category`` defaults to ``''`` (runner accepts empty).
        - ``audiences`` defaults to ``['decision-maker']`` so the
          runner's audience-aware prompt templates always have at
          least one element to address. R2 can capture audiences
          explicitly on the form and the adapter will use them.
        - ``positioning_inputs`` defaults to ``{}``.

        If a downstream form update adds an ``audiences`` (or
        ``category`` / ``positioning``) key to ``form_data``, the
        adapter surfaces it. This keeps the adapter forward-compatible
        with R2's planned field additions without touching the worker.
        """
        form_data = submission.form_data or {}
        client_name = form_data.get('client_name') or 'Unknown Client'
        audiences = form_data.get('audiences') or ['decision-maker']
        if not isinstance(audiences, list) or not audiences:
            audiences = ['decision-maker']
        return ClientConfig(
            id=_slugify(client_name),
            name=client_name,
            category=form_data.get('category', ''),
            audiences=audiences,
            positioning_inputs=form_data.get('positioning', {}) or {},
        )

    @staticmethod
    def to_competitor_configs(submission) -> list[CompetitorConfig]:
        """CompetitiveAuditSubmission.form_data -> [CompetitorConfig, ...].

        Walks ``form_data['competitor_1']..['competitor_4']``. Empty /
        None sub-cards are skipped. A non-empty sub-card requires both
        a non-empty ``brand_name`` and a non-empty ``home_url`` to be
        surfaced as a competitor (matches the form's required-field
        validation: R1 rejects a sub-card with only a brand name).

        Social-scans toggle: ``include_socials`` is a dict of
        ``{channel: bool}`` (e.g. ``{'x': True, 'facebook': False}``).
        We synthesise a one-line summary string listing the channels
        so the downstream evidence step knows where to scan.
        """
        form_data = submission.form_data or {}
        competitors: list[CompetitorConfig] = []
        for idx in range(1, 5):  # competitor_1..competitor_4
            slot = form_data.get(f'competitor_{idx}')
            if not slot:
                continue
            brand_name = (slot.get('brand_name') or '').strip()
            home_url = (slot.get('home_url') or '').strip()
            if not brand_name:
                # R1 allows a brand_name to be absent only if home_url
                # is also absent (sub-card stored as None). Defensive
                # skip if a half-filled row slips through.
                continue
            include_socials = slot.get('include_socials') or {}
            on_channels = sorted(
                ch for ch in _R1_SOCIAL_CHANNELS if include_socials.get(ch)
            )
            social_scans_str = (
                ', '.join(on_channels) if on_channels else '(none)'
            )
            competitors.append(
                CompetitorConfig(
                    id=_slugify(brand_name),
                    name=brand_name,
                    category_position='synthesized (evidence step out of scope for MVP)',
                    summary=(
                        f'Synthesized stub for {brand_name}. '
                        f'Home URL: {home_url or "(none)"}. '
                        f'Social scans enabled: {social_scans_str}. '
                        f'Real summary requires evidence collection '
                        f'(Pathmatics/Adbeat/iSpot or manual research) — '
                        f'out of scope for the MVP. The DrifterBot run '
                        f'will produce an "evidence gap" callout for this '
                        f'competitor rather than fabricating a position '
                        f'summary.'
                    ),
                )
            )
        return competitors

    @staticmethod
    def collect_social_scans(submission) -> list[str]:
        """Union of social-scans toggles across all four competitor slots.

        Deduplicates via ``set()`` so the Slides spec doesn't repeat
        channels. The runner doesn't use this directly — it's surfaced
        to the Slides renderer as part of the payload so the
        context-source list reflects the channels the user actually
        enabled.
        """
        form_data = submission.form_data or {}
        union: set[str] = set()
        for idx in range(1, 5):
            slot = form_data.get(f'competitor_{idx}') or {}
            for channel, on in (slot.get('include_socials') or {}).items():
                if on:
                    union.add(channel)
        return sorted(union)


def _slugify(s: str) -> str:
    """Lowercase, ASCII-folded, hyphen-joined slug.

    Mirrors the convention used by Portal routes (`drift-and-anchor`).
    Used for ``ClientConfig.id`` so save-strategy folder names stay
    readable.
    """
    import re
    s = s.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = s.strip('-')
    return s or 'unnamed'


# ---------------------------------------------------------------------------
# Backwards-compat alias (delete after next refactor)
# ---------------------------------------------------------------------------


class AuditRequestAdapter(CompetitiveAuditAdapter):
    """Deprecated alias for ``CompetitiveAuditAdapter``.

    β-3 (2026-07-16) killed the ``AuditRequest`` table; the old class
    name now points at the new adapter so any stray external caller
    gets a working adapter instead of an ``ImportError``. Delete in
    the next refactor that touches the worker.
    """

    @staticmethod
    def to_client_config(*args, **kwargs):
        raise NotImplementedError(
            'AuditRequestAdapter is a deprecated alias for '
            'CompetitiveAuditAdapter and has no method binding. Use '
            'CompetitiveAuditAdapter.to_client_config(submission) directly.'
        )

    @staticmethod
    def to_competitor_configs(*args, **kwargs):
        raise NotImplementedError(
            'AuditRequestAdapter is a deprecated alias for '
            'CompetitiveAuditAdapter and has no method binding. Use '
            'CompetitiveAuditAdapter.to_competitor_configs(submission) '
            'directly.'
        )


# ---------------------------------------------------------------------------
# Pickup query + lifecycle
# ---------------------------------------------------------------------------


def _claim_pending(session: Session, CompetitiveAuditSubmission) -> Iterable:
    """Return rows in 'submitted' state, locking them for the duration of
    the transaction.

    Uses ``FOR UPDATE SKIP LOCKED`` (Postgres-specific) to prevent
    overlapping cron ticks from grabbing the same row. Each row is
    moved to 'processing' before we yield it, so a second pickup call
    (even one that bypasses SKIP LOCKED via stale indexes) won't see
    it as pending.

    Yields rows in id-ascending order so older submissions process
    first.
    """
    rows = (
        session.query(CompetitiveAuditSubmission)
        .filter(CompetitiveAuditSubmission.status == CompetitiveAuditSubmission.STATUS_SUBMITTED)
        .order_by(CompetitiveAuditSubmission.id.asc())
        .with_for_update(skip_locked=True)
        .all()
    )
    for row in rows:
        row.status = CompetitiveAuditSubmission.STATUS_PROCESSING
        row.started_at = datetime.now(UTC)
        logger.info('worker: claimed submission id=%s', row.id)
    session.flush()  # surface the status flip before we yield
    return rows


def _run_one(session: Session, CompetitiveAuditSubmission, submission_row) -> None:
    """Process a single claimed submission row end-to-end.

    On success: status -> complete, audit_id set, completed_at set.
    On failure: status -> failed, error_message set, completed_at set.
    """
    try:
        client_cfg = CompetitiveAuditAdapter.to_client_config(submission_row)
        competitor_cfgs = CompetitiveAuditAdapter.to_competitor_configs(submission_row)
        social_scans = CompetitiveAuditAdapter.collect_social_scans(submission_row)

        logger.info(
            'worker: running audit for submission id=%s client=%s n_competitors=%d',
            submission_row.id, client_cfg.name, len(competitor_cfgs),
        )

        # The actual DrifterBot run. Per spec §6, runner.run_audit
        # produces an AuditDraft dataclass with executive summary +
        # 5 Provocation chapters + per-competitor cards. social_scans
        # and context_drive_links aren't yet threaded through the MVP
        # runner (post-MVP scope) — they're captured on the submission
        # row's form_data and threaded into the Slides renderer via
        # the payload dict below for downstream consumers (e.g. the
        # eventual Drive write step, where the Slides spec + the
        # source-context metadata travel together).
        draft: AuditDraft = run_audit(
            client=client_cfg,
            competitors=competitor_cfgs,
        )

        # Render Slides spec — parked Drive push consumes this output.
        slides_spec = render_slides_spec(draft, payload={
            'social_scans': social_scans,
            'context_drive_links': [],
            'notes': None,
            'submission_id': submission_row.id,
        })

        # Save via the active strategy. LocalPickupStrategy writes to
        # /tmp/drifterbot-pickup/<run>/; DriveSaveStrategy pushes the
        # deck into the BrandSight Client Output Drive folder. Both
        # return a SaveResult dataclass with location / presentation_id
        # / web_url fields — worker has one shape to log.
        save_result = save_audit(draft, slides_spec, request_id=submission_row.id)

        # Lifecycle: success
        submission_row.status = CompetitiveAuditSubmission.STATUS_COMPLETE
        submission_row.audit_id = draft.audit_id
        submission_row.completed_at = datetime.now(UTC)
        logger.info(
            'worker: completed submission id=%s audit_id=%s save_location=%s '
            'presentation_id=%s web_url=%s',
            submission_row.id, draft.audit_id,
            save_result.location,
            save_result.presentation_id,
            save_result.web_url,
        )

    except Exception as exc:
        logger.exception('worker: failed submission id=%s', submission_row.id)
        submission_row.status = CompetitiveAuditSubmission.STATUS_FAILED
        submission_row.error_message = f'{type(exc).__name__}: {exc}\n{traceback.format_exc()}'
        submission_row.completed_at = datetime.now(UTC)


def process_pending_audit_requests() -> list[int]:
    """Pick up all submitted rows and process them in a single transaction.

    Returns the list of submission ids touched (any non-terminal state
    transitioned this call). Useful for cron ack / log scrape.
    """
    engine, SessionFactory, CompetitiveAuditSubmission, _psf_db = _make_engine()
    processed_ids: list[int] = []

    with SessionFactory() as session:
        with session.begin():
            claimed = _claim_pending(session, CompetitiveAuditSubmission)

        # Run outside the lock-holding transaction so each row's run
        # can take as long as it needs without holding a row-level
        # lock that blocks other workers. The status is already
        # 'processing' so no other pickup will grab it.
        for row in claimed:
            _run_one(session, CompetitiveAuditSubmission, row)
            processed_ids.append(row.id)

        # Second transaction commits the final status transitions.
        session.commit()

    if engine is not None:
        engine.dispose()

    return processed_ids


def run_one_audit_request(audit_request_id: int) -> bool:
    """Process a single CompetitiveAuditSubmission row by primary key.

    Useful for retries / manual ops. Returns True on success, False on
    failure (the row's ``status`` and ``error_message`` reflect the
    outcome either way).
    """
    engine, SessionFactory, CompetitiveAuditSubmission, _psf_db = _make_engine()
    try:
        with SessionFactory() as session:
            with session.begin():
                row = session.query(CompetitiveAuditSubmission).filter(
                    CompetitiveAuditSubmission.id == audit_request_id,
                ).with_for_update().one_or_none()

                if row is None:
                    logger.warning('worker: no submission id=%s', audit_request_id)
                    return False

                if row.status != CompetitiveAuditSubmission.STATUS_SUBMITTED:
                    logger.info(
                        'worker: submission id=%s already in status=%s — skipping',
                        audit_request_id, row.status,
                    )
                    return False

                row.status = CompetitiveAuditSubmission.STATUS_PROCESSING
                row.started_at = datetime.now(UTC)

            _run_one(session, CompetitiveAuditSubmission, row)
            session.commit()
        return True
    finally:
        if engine is not None:
            engine.dispose()


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI: process all submitted rows, print processed ids."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
    )
    processed = process_pending_audit_requests()
    if processed:
        print(f'worker: processed {len(processed)} request(s): {processed}')
    else:
        print('worker: no submitted requests')


if __name__ == '__main__':
    main()
