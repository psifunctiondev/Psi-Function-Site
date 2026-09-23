"""Tests for the OpenProject snapshot worker + CLI commands.

Covers:

* ``snapshot_one_project`` — upserts one row per (project, day);
  returns None when the project has no WPs (but still writes a
  count=0 + empty-distribution row so the Progress chart shows a flat
  line at SP=0).
* ``run_snapshot_for_active_clients`` — walks every active client with
  a wired master project; clients without one are skipped silently;
  clients whose OP fetch errors are logged and skipped without
  aborting the loop.
* ``flask openproject snapshot`` CLI — happy path, dry-run, missing
  env vars (exits non-zero with a clear message).
* ``flask openproject backfill-snapshots`` CLI — happy path.
* Idempotency: re-running for the same day updates the existing row
  rather than creating a duplicate.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest import mock

import pytest
from click.testing import CliRunner

from app import create_app
from app.cli import openproject_cli
from app.extensions import db
from app.models.client import Client
from app.models.op_snapshot import OpProjectSnapshot
from app.services.openproject_snapshot import (
    backfill_snapshots_for_project,
    run_snapshot_for_active_clients,
    snapshot_one_project,
)


def _wp(status, sp=3, wp_id=1):
    return {
        'id': wp_id, 'storyPoints': sp,
        '_links': {'status': {'title': status, 'href': f'/api/v3/statuses/{status}'}},
    }


def _project(pid, name='Project X'):
    return {'id': pid, 'name': name}


@pytest.fixture
def wired_client(db_session):
    """An active client with an OP master project id wired."""
    c = Client(name='Wired Corp', slug='wired-corp',
               openproject_master_project_id=42)
    c.is_active = True
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def unwired_client(db_session):
    """An active client without an OP master (under wiring)."""
    c = Client(name='Unwired Corp', slug='unwired-corp',
               openproject_master_project_id=None)
    c.is_active = True
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def op_stub():
    """A MagicMock standing in for OpenProjectClient."""
    return mock.MagicMock()


# --------------------------------------------------------------------------- #
# snapshot_one_project
# --------------------------------------------------------------------------- #
class TestSnapshotOneProject:

    def test_writes_distribution_and_count(self, db_session, op_stub):
        op_stub.get_work_packages.return_value = [
            _wp('New', sp=3),
            _wp('New', sp=5),
            _wp('Completed', sp=8),
        ]
        snap = snapshot_one_project(op_stub, 42, date(2026, 9, 22))
        assert snap is not None
        assert snap.work_package_count == 3
        assert snap.distribution == {'New': 8, 'Completed': 8}

    def test_empty_project_writes_zero_row(self, db_session, op_stub):
        """No WPs in the project -> row with count=0 + empty dist.
        Renders as a flat line at SP=0 in the Progress chart rather
        than disappearing from the time series.
        """
        op_stub.get_work_packages.return_value = []
        snap = snapshot_one_project(op_stub, 42, date(2026, 9, 22))
        assert snap is not None
        assert snap.work_package_count == 0
        assert snap.distribution == {}

    def test_idempotent_re_run_updates_in_place(self, db_session, op_stub):
        op_stub.get_work_packages.return_value = [_wp('New', sp=3)]
        first = snapshot_one_project(op_stub, 42, date(2026, 9, 22))
        first_id = first.id

        # Re-run with updated data — same date.
        op_stub.get_work_packages.return_value = [
            _wp('New', sp=3), _wp('In progress', sp=5),
        ]
        second = snapshot_one_project(op_stub, 42, date(2026, 9, 22))
        assert second.id == first_id
        assert second.work_package_count == 2
        assert second.distribution == {'New': 3, 'In progress': 5}

    def test_different_dates_create_different_rows(
        self, db_session, op_stub,
    ):
        op_stub.get_work_packages.return_value = [_wp('New', sp=3)]
        a = snapshot_one_project(op_stub, 42, date(2026, 9, 22))
        b = snapshot_one_project(op_stub, 42, date(2026, 9, 23))
        assert a.id != b.id
        assert a.snapshot_date == date(2026, 9, 22)
        assert b.snapshot_date == date(2026, 9, 23)


# --------------------------------------------------------------------------- #
# run_snapshot_for_active_clients
# --------------------------------------------------------------------------- #
class TestRunSnapshotForActiveClients:

    def test_walks_wired_clients_only(
        self, db_session, op_stub, wired_client, unwired_client,
    ):
        # Master project fetches return just [42] for both clients
        # (helper handles children internally; we stub via the
        # portal helper here).
        op_stub.get_project.return_value = _project(42, 'Master')
        op_stub.get_child_projects.return_value = []

        with mock.patch(
            'app.services.openproject_portal.get_client_projects',
            return_value=[_project(42, 'Master')],
        ):
            summary = run_snapshot_for_active_clients(
                op_stub, day=date(2026, 9, 22),
            )

        assert 'wired-corp' in summary
        assert summary['wired-corp'] == 1
        # Unwired client was skipped silently — not in summary.
        assert 'unwired-corp' not in summary

    def test_missing_master_is_noop(self, db_session, op_stub):
        # No clients wired at all.
        summary = run_snapshot_for_active_clients(
            op_stub, day=date(2026, 9, 22),
        )
        assert summary == {}

    def test_one_client_failure_does_not_abort_loop(
        self, db_session, op_stub, wired_client,
    ):
        # Add a second wired client.
        other = Client(name='Other', slug='other-corp',
                       openproject_master_project_id=99)
        other.is_active = True
        db_session.add(other)
        db_session.commit()

        # First client errors on project fetch; second succeeds.
        with mock.patch(
            'app.services.openproject_portal.get_client_projects',
            side_effect=[
                RuntimeError('OP 500'),
                [_project(99, 'Other Master')],
            ],
        ):
            op_stub.get_work_packages.return_value = []
            summary = run_snapshot_for_active_clients(
                op_stub, day=date(2026, 9, 22),
            )

        # First client recorded as 0 (the error case); second recorded
        # as 1. The loop didn't abort.
        assert summary['wired-corp'] == 0
        assert summary['other-corp'] == 1


# --------------------------------------------------------------------------- #
# CLI: flask openproject snapshot
# --------------------------------------------------------------------------- #
class TestOpenProjectSnapshotCLI:

    def test_happy_path_writes_rows(
        self, app, db_session, wired_client, monkeypatch,
    ):
        monkeypatch.setenv('OPENPROJECT_URL', 'https://op.example.com')
        monkeypatch.setenv('OPENPROJECT_API_KEY', 'test-key')

        runner = CliRunner()
        with mock.patch(
            'app.services.openproject_portal.get_client_projects',
            return_value=[_project(42, 'Master')],
        ):
            op = mock.MagicMock()
            op.get_work_packages.return_value = [_wp('New', sp=3)]
            with mock.patch(
                'app.cli.current_op_client', return_value=op,
            ):
                result = runner.invoke(openproject_cli, ['snapshot'])
        assert result.exit_code == 0, result.output
        assert 'Snapshotted' in result.output
        assert 'wired-corp' in result.output

    def test_dry_run_does_not_write(
        self, app, db_session, wired_client, monkeypatch,
    ):
        monkeypatch.setenv('OPENPROJECT_URL', 'https://op.example.com')
        monkeypatch.setenv('OPENPROJECT_API_KEY', 'test-key')

        runner = CliRunner()
        result = runner.invoke(openproject_cli, ['snapshot', '--dry-run'])
        assert result.exit_code == 0, result.output
        assert 'DRY-RUN' in result.output
        assert 'wired-corp' in result.output
        # No snapshot row written.
        assert OpProjectSnapshot.query.count() == 0

    def test_missing_env_vars_exits_2(self, app, monkeypatch):
        monkeypatch.delenv('OPENPROJECT_URL', raising=False)
        monkeypatch.delenv('OPENPROJECT_API_KEY', raising=False)

        runner = CliRunner()
        result = runner.invoke(openproject_cli, ['snapshot'])
        assert result.exit_code == 2
        assert 'OPENPROJECT_URL' in result.output
        assert 'OPENPROJECT_API_KEY' in result.output


# --------------------------------------------------------------------------- #
# CLI: flask openproject backfill-snapshots
# --------------------------------------------------------------------------- #
class TestBackfillSnapshotsCLI:

    def test_happy_path_writes_snapshots(
        self, app, db_session, monkeypatch,
    ):
        monkeypatch.setenv('OPENPROJECT_URL', 'https://op.example.com')
        monkeypatch.setenv('OPENPROJECT_API_KEY', 'test-key')

        # Mock the snapshot worker so we don't need to simulate weeks
        # of journal data — just verify the CLI plumbs args correctly.
        with mock.patch(
            'app.cli.backfill_snapshots_for_project',
            return_value=8,
        ) as mock_backfill:
            runner = CliRunner()
            result = runner.invoke(
                openproject_cli, ['backfill-snapshots', '42'],
            )
        assert result.exit_code == 0, result.output
        assert 'Backfilled 8' in result.output
        mock_backfill.assert_called_once()
        args, kwargs = mock_backfill.call_args
        assert args[1] == 42  # project_id
        assert kwargs.get('weeks') == 8

    def test_passes_weeks_option(self, app, monkeypatch):
        monkeypatch.setenv('OPENPROJECT_URL', 'https://op.example.com')
        monkeypatch.setenv('OPENPROJECT_API_KEY', 'test-key')

        with mock.patch(
            'app.cli.backfill_snapshots_for_project',
            return_value=4,
        ) as mock_backfill:
            runner = CliRunner()
            result = runner.invoke(
                openproject_cli,
                ['backfill-snapshots', '42', '--weeks', '4'],
            )
        assert result.exit_code == 0, result.output
        assert mock_backfill.call_args.kwargs['weeks'] == 4


# --------------------------------------------------------------------------- #
# backfill_snapshots_for_project (worker)
# --------------------------------------------------------------------------- #
class TestBackfillWorker:

    def test_writes_one_snapshot_per_boundary(
        self, db_session, op_stub, monkeypatch,
    ):
        from app.services.openproject_cache import reset_cache_for_tests
        reset_cache_for_tests()

        op_stub.get_work_packages.return_value = [
            {'id': 1, 'storyPoints': 3,
             '_links': {'status': {'title': 'New'}}},
        ]
        op_stub.get_work_package_journals.return_value = [
            {'id': 10, 'createdAt': '2026-09-01T10:00:00Z',
             '_links': {'newValue': {
                 'title': 'New', 'href': '/api/v3/statuses/1',
             }}},
        ]

        written = backfill_snapshots_for_project(
            op_stub, 42, weeks=8,
        )
        assert written == 8

        rows = OpProjectSnapshot.query.filter_by(
            project_op_id=42,
        ).order_by(OpProjectSnapshot.snapshot_date).all()
        assert len(rows) == 8
        # Each row has distribution from the same status (New).
        for row in rows:
            assert row.distribution.get('New') == 3

    def test_zero_wp_project_writes_nothing(self, db_session, op_stub):
        op_stub.get_work_packages.return_value = []
        written = backfill_snapshots_for_project(op_stub, 42, weeks=4)
        assert written == 0
