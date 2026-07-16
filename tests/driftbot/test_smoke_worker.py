"""
Smoke test: DrifterBot worker end-to-end against a synthetic
CompetitiveAuditSubmission.

β-3 (2026-07-16) rewrite — exercises the new path:

  synthetic CompetitiveAuditSubmission row
    -> CompetitiveAuditAdapter -> ClientConfig + CompetitorConfig
    -> runner.run_audit() -> AuditDraft
    -> renderer_slides.render_slides_spec() -> dict
    -> save_strategy.save_audit() -> /tmp/.../run_dir/
    -> submission row updated to STATUS_COMPLETE

Uses SQLite in-memory so the test runs anywhere without Postgres.
Note: ``with_for_update(skip_locked=True)`` is a no-op on SQLite, which
is fine — the test is single-process, no concurrency to test.
"""

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures: spin up a fresh SQLite-backed CompetitiveAuditSubmission table
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_submission(monkeypatch, tmp_path):
    """Create a tempfile-backed SQLite engine with all Psi-Function-Site
    tables registered. File-based so multiple engines (the test's + the
    worker's) see the same DB. Uses tmp_path for cleanup.
    """
    from sqlalchemy import create_engine

    from app.extensions import db as _psf_db
    # Importing app.models registers all mappers on db.metadata.
    try:
        import app.models  # noqa: F401
    except Exception:
        pass
    from app.models.competitive_audit import CompetitiveAuditSubmission

    db_path = tmp_path / 'worker-test.db'
    db_url = f'sqlite:///{db_path}'
    monkeypatch.setenv('DATABASE_URL', db_url)

    engine = create_engine(db_url)
    _psf_db.metadata.create_all(engine)

    yield CompetitiveAuditSubmission, engine

    engine.dispose()


def _insert_fk_stubs(engine, psf_db):
    """Insert stub Client + User rows to satisfy CompetitiveAuditSubmission's FKs.

    Client requires ``is_active``; User requires ``is_admin`` and
    ``is_active_user`` (per ``app/models/user.py``).
    """
    with engine.begin() as conn:
        try:
            conn.execute(psf_db.text(
                "INSERT INTO client (id, name, slug, is_active) "
                "VALUES (1, 'Drift & Anchor', 'drift-and-anchor', 1)"
            ))
        except Exception:
            pass
        try:
            conn.execute(psf_db.text(
                "INSERT INTO \"user\" (id, email, is_admin, is_active_user) "
                "VALUES (1, 'catherine@drift-and-anchor.com', 0, 1)"
            ))
        except Exception:
            pass


def _make_portal_form_data() -> dict:
    """Build a synthetic form_data dict mirroring R1's intake shape.

    Matches ``_parse_competitive_audit_form`` in
    ``app/blueprints/portal/routes.py``: four competitor slots, each
    ``None`` or ``{'brand_name', 'home_url', 'include_socials'}``.
    """
    return {
        'client_name': 'Hallmark Health Care',
        'competitor_1': {
            'brand_name': 'Meridian Workforce Health',
            'home_url': 'https://meridian.example.com',
            'include_socials': {
                'x': True, 'facebook': False, 'instagram': False, 'youtube': False,
            },
        },
        'competitor_2': {
            'brand_name': 'ShiftBridge Clinical',
            'home_url': 'https://shiftbridge.example.com',
            'include_socials': {
                'x': False, 'facebook': True, 'instagram': False, 'youtube': False,
            },
        },
        'competitor_3': None,
        'competitor_4': None,
    }


# ---------------------------------------------------------------------------
# Adapter tests
# ---------------------------------------------------------------------------


def test_adapter_builds_client_config_from_submission(sqlite_submission):
    """CompetitiveAuditSubmission row -> ClientConfig carries name from form_data."""
    CompetitiveAuditSubmission, engine = sqlite_submission
    from app.extensions import db as _psf_db
    _insert_fk_stubs(engine, _psf_db)

    with _psf_db.Session(engine) as session:
        row = CompetitiveAuditSubmission(
            client_id=1,
            author_id=1,
            status=CompetitiveAuditSubmission.STATUS_SUBMITTED,
            form_data=_make_portal_form_data(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        from agents.driftbot.worker import CompetitiveAuditAdapter

        client_cfg = CompetitiveAuditAdapter.to_client_config(row)
        assert client_cfg.name == 'Hallmark Health Care'
        # R1 surface doesn't capture audiences; the adapter falls back
        # to a single generic placeholder so the runner's audience-aware
        # prompt templates always have something to address.
        assert client_cfg.audiences == ['decision-maker']
        # category + positioning_inputs stay empty unless R2's form
        # adds them; default is empty.
        assert client_cfg.category == ''
        assert client_cfg.positioning_inputs == {}
        assert client_cfg.id == 'hallmark-health-care'


def test_adapter_builds_competitor_configs_from_form_data(sqlite_submission):
    """form_data['competitor_<i>'] dicts -> [CompetitorConfig, ...].

    Two filled slots (competitor_1, competitor_2) plus two None slots
    in the synthetic form data — adapter must skip the None ones.
    """
    CompetitiveAuditSubmission, engine = sqlite_submission
    from app.extensions import db as _psf_db
    _insert_fk_stubs(engine, _psf_db)

    with _psf_db.Session(engine) as session:
        row = CompetitiveAuditSubmission(
            client_id=1,
            author_id=1,
            status=CompetitiveAuditSubmission.STATUS_SUBMITTED,
            form_data=_make_portal_form_data(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        from agents.driftbot.worker import CompetitiveAuditAdapter
        cfgs = CompetitiveAuditAdapter.to_competitor_configs(row)

        assert len(cfgs) == 2
        assert cfgs[0].name == 'Meridian Workforce Health'
        assert cfgs[0].id == 'meridian-workforce-health'
        assert 'x' in cfgs[0].summary  # meridian had x=True
        assert 'facebook' not in cfgs[0].summary.split('Social scans')[1]
        assert cfgs[1].name == 'ShiftBridge Clinical'
        assert cfgs[1].id == 'shiftbridge-clinical'


def test_adapter_skips_empty_competitor_slots(sqlite_submission):
    """All four slots None -> empty competitor list (no fabrication)."""
    CompetitiveAuditSubmission, engine = sqlite_submission
    from app.extensions import db as _psf_db
    _insert_fk_stubs(engine, _psf_db)

    with _psf_db.Session(engine) as session:
        row = CompetitiveAuditSubmission(
            client_id=1,
            author_id=1,
            status=CompetitiveAuditSubmission.STATUS_SUBMITTED,
            form_data={
                'client_name': 'Empty Client',
                'competitor_1': None,
                'competitor_2': None,
                'competitor_3': None,
                'competitor_4': None,
            },
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        from agents.driftbot.worker import CompetitiveAuditAdapter
        cfgs = CompetitiveAuditAdapter.to_competitor_configs(row)
        assert cfgs == []


def test_adapter_collects_social_scans_union(sqlite_submission):
    """Union of toggles across all four competitor slots, deduped + sorted."""
    CompetitiveAuditSubmission, engine = sqlite_submission
    from app.extensions import db as _psf_db
    _insert_fk_stubs(engine, _psf_db)

    with _psf_db.Session(engine) as session:
        row = CompetitiveAuditSubmission(
            client_id=1,
            author_id=1,
            status=CompetitiveAuditSubmission.STATUS_SUBMITTED,
            form_data={
                'client_name': 'Multi Channel',
                'competitor_1': {
                    'brand_name': 'A',
                    'home_url': 'https://a.example',
                    'include_socials': {
                        'x': True, 'facebook': False,
                        'instagram': False, 'youtube': True,
                    },
                },
                'competitor_2': {
                    'brand_name': 'B',
                    'home_url': 'https://b.example',
                    'include_socials': {
                        'x': True, 'facebook': True,
                        'instagram': False, 'youtube': False,
                    },
                },
                'competitor_3': None, 'competitor_4': None,
            },
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        from agents.driftbot.worker import CompetitiveAuditAdapter
        scans = CompetitiveAuditAdapter.collect_social_scans(row)
        # x (from both) + facebook (B only) + youtube (A only) — deduped, sorted
        assert scans == ['facebook', 'x', 'youtube']


# ---------------------------------------------------------------------------
# End-to-end: synthesize submission row -> run worker -> verify output
# ---------------------------------------------------------------------------


def test_run_one_audit_request_completes_and_writes_artifact(
    sqlite_submission, tmp_path, monkeypatch,
):
    """Full pipeline: synthesize row, run_one_audit_request, verify completion + artifact."""
    CompetitiveAuditSubmission, engine = sqlite_submission

    # Point LocalPickupStrategy at tmp_path so we don't pollute /tmp.
    from agents.driftbot import save_strategy
    monkeypatch.setattr(
        save_strategy.LocalPickupStrategy,
        '__init__',
        lambda self, root=None: setattr(self, 'root', tmp_path) or None,
    )

    from agents.driftbot.worker import run_one_audit_request
    from app.extensions import db as _psf_db
    _insert_fk_stubs(engine, _psf_db)

    form_data = {
        'client_name': 'Hallmark Health Care',
        'competitor_1': {
            'brand_name': 'Meridian Workforce Health',
            'home_url': 'https://meridian.example.com',
            'include_socials': {
                'x': True, 'facebook': False, 'instagram': True, 'youtube': False,
            },
        },
        'competitor_2': {
            'brand_name': 'ShiftBridge Clinical',
            'home_url': 'https://shiftbridge.example.com',
            'include_socials': {
                'x': True, 'facebook': False, 'instagram': False, 'youtube': False,
            },
        },
        'competitor_3': {
            'brand_name': 'ClearPath Health Staffing',
            'home_url': 'https://clearpath.example.com',
            'include_socials': {
                'x': False, 'facebook': True, 'instagram': False, 'youtube': True,
            },
        },
        'competitor_4': {
            'brand_name': 'NovaPulse Staffing Solutions',
            'home_url': 'https://novapulse.example.com',
            'include_socials': {
                'x': True, 'facebook': True, 'instagram': True, 'youtube': True,
            },
        },
    }

    with _psf_db.Session(engine) as session:
        row = CompetitiveAuditSubmission(
            client_id=1,
            author_id=1,
            status=CompetitiveAuditSubmission.STATUS_SUBMITTED,
            form_data=form_data,
        )
        session.add(row)
        session.commit()
        row_id = row.id
        session.expunge(row)

    # Run the worker
    success = run_one_audit_request(row_id)
    assert success is True, 'worker should report success on a submitted row'

    # Verify lifecycle: row is now complete with audit_id set
    with _psf_db.Session(engine) as session:
        completed_row = session.query(CompetitiveAuditSubmission).filter(
            CompetitiveAuditSubmission.id == row_id,
        ).one()
        assert completed_row.status == CompetitiveAuditSubmission.STATUS_COMPLETE
        assert completed_row.audit_id is not None
        assert len(completed_row.audit_id) == 8  # UUID4 prefix per spec
        assert completed_row.started_at is not None
        assert completed_row.completed_at is not None

    # Verify LocalPickupStrategy wrote artifacts to tmp_path/run_dir
    # (filter out the SQLite test DB which lives alongside)
    run_dirs = [
        d for d in tmp_path.iterdir()
        if d.is_dir() and not d.name.endswith('.db')
    ]
    assert len(run_dirs) == 1, f'expected exactly one run dir, got: {run_dirs}'
    run_dir = run_dirs[0]
    assert (run_dir / 'slides-spec.json').exists()
    assert (run_dir / 'audit-draft.md').exists()

    slides_spec = json.loads((run_dir / 'slides-spec.json').read_text())
    assert 'slides' in slides_spec
    assert len(slides_spec['slides']) >= 7  # title + exec + 5 competitor at minimum

    audit_draft = (run_dir / 'audit-draft.md').read_text()
    assert len(audit_draft) > 5000, 'audit-draft should be a real document'


def test_resolve_database_url_rejects_placeholders(monkeypatch):
    """DATABASE_URL with <user>/<pass>/<host>/<db> placeholders fails loud, not silent."""
    from agents.driftbot.worker import _resolve_database_url

    # Clear explicit overrides so we exercise the gateway-env fallback
    monkeypatch.delenv('PSIFUNCTIONSITE_DATABASE_URL', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)

    # Write a fake gateway env file with placeholders to a tmp path
    fake_env = (
        "# header\n"
        "export HOME='/Users/test'\n"
        "export DATABASE_URL='postgresql://<user>:<pass>@<host>/<db>'\n"
    )
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        env_path = Path(td) / 'fake-gateway.env'
        env_path.write_text(fake_env)
        monkeypatch.setattr(
            'agents.driftbot.worker._GATEWAY_ENV_PATH',
            env_path,
        )

        import pytest
        with pytest.raises(RuntimeError, match='still contains template placeholders'):
            _resolve_database_url()


def test_resolve_database_url_loads_from_gateway_env_file(monkeypatch):
    """Worker reads DATABASE_URL from the gateway env file when env vars aren't set."""
    from agents.driftbot.worker import _resolve_database_url

    monkeypatch.delenv('PSIFUNCTIONSITE_DATABASE_URL', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)

    fake_env = (
        "export HOME='/Users/test'\n"
        "export DATABASE_URL='postgresql://prod_user:secret@db.internal/psifunction_prod'\n"
    )
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        env_path = Path(td) / 'fake-gateway.env'
        env_path.write_text(fake_env)
        monkeypatch.setattr(
            'agents.driftbot.worker._GATEWAY_ENV_PATH',
            env_path,
        )

        assert _resolve_database_url() == 'postgresql://prod_user:secret@db.internal/psifunction_prod'


def test_resolve_database_url_prefers_env_over_file(monkeypatch):
    """If PSIFUNCTIONSITE_DATABASE_URL is set, the file is not consulted."""
    from agents.driftbot.worker import _resolve_database_url

    monkeypatch.setenv('PSIFUNCTIONSITE_DATABASE_URL', 'postgresql://env-wins/file-loser')
    # Even if the file has a different value, the env wins.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        env_path = Path(td) / 'fake-gateway.env'
        env_path.write_text("export DATABASE_URL='postgresql://from-file/db'\n")
        monkeypatch.setattr(
            'agents.driftbot.worker._GATEWAY_ENV_PATH',
            env_path,
        )
        assert _resolve_database_url() == 'postgresql://env-wins/file-loser'


def test_run_one_audit_request_skips_non_submitted(sqlite_submission):
    """Re-running on a row that's already complete should be a no-op."""
    CompetitiveAuditSubmission, engine = sqlite_submission
    from agents.driftbot.worker import run_one_audit_request
    from app.extensions import db as _psf_db
    _insert_fk_stubs(engine, _psf_db)

    with _psf_db.Session(engine) as session:
        row = CompetitiveAuditSubmission(
            client_id=1,
            author_id=1,
            status=CompetitiveAuditSubmission.STATUS_COMPLETE,  # already done
            form_data=_make_portal_form_data(),
        )
        session.add(row)
        session.commit()
        row_id = row.id

    success = run_one_audit_request(row_id)
    assert success is False, 'worker should refuse to re-run a non-submitted row'

    # Confirm the row is still complete (not flipped to processing)
    with _psf_db.Session(engine) as session:
        r = session.query(CompetitiveAuditSubmission).filter(
            CompetitiveAuditSubmission.id == row_id,
        ).one()
        assert r.status == CompetitiveAuditSubmission.STATUS_COMPLETE


def test_audit_request_adapter_is_deprecated_alias():
    """AuditRequestAdapter exists only as a deprecation shim; methods raise."""
    from agents.driftbot.worker import AuditRequestAdapter

    # Class exists
    assert AuditRequestAdapter is not None

    # Methods raise NotImplementedError to surface the rename loudly
    with pytest.raises(NotImplementedError, match='deprecated alias'):
        AuditRequestAdapter.to_client_config(None)
    with pytest.raises(NotImplementedError, match='deprecated alias'):
        AuditRequestAdapter.to_competitor_configs(None)
