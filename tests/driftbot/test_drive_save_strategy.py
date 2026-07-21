"""
Unit tests for DriveSaveStrategy (B2 architecture).

Mocks SlidesClient + filesystem; never hits Google or rclone. Verifies:
    - output path resolution (env / kwarg / default)
    - subject resolution (env / kwarg / error)
    - filename pattern (incl. .pptx extension on disk)
    - file written to disk with the bytes the SlidesClient exported
    - SaveResult returned with file path (not Drive URL) for location
    - failure propagation at each step
"""

from __future__ import annotations

import pytest

from agents.driftbot.runner import (
    AuditDraft,
    ClientConfig,
    CompetitorConfig,
)
from agents.driftbot.save_strategy import (
    DriveSaveStrategy,
    SaveResult,
    _build_drive_filename,
)

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def draft():
    client = ClientConfig(
        id='acme',
        name='Acme Health',
        category='healthcare',
        audiences=['admin'],
        positioning_inputs={},
    )
    competitors = [
        CompetitorConfig(
            id='c1', name='C1', category_position='staffing', summary='x',
        ),
    ]
    return AuditDraft(
        audit_id='audit-1234',
        client=client,
        competitors=competitors,
        competitor_cards=['### C1\nBody'],
        provocation_chapters=['## Prov 1\nbody'],
        generated_at='2026-07-21T09:00:00Z',
    )


@pytest.fixture
def slides_spec():
    return {
        'title': 'Acme Health — Competitive Audit Draft',
        'locale': 'en_US',
        'slides': [
            {
                'slideId': 'slide-title',
                'layout': 'TITLE',
                'elements': [
                    {'type': 'text', 'placeholder': 'TITLE', 'text': 'Title'},
                    {'type': 'text', 'placeholder': 'SUBTITLE', 'text': 'Sub'},
                ],
            },
        ],
        'theme': {'primary': '#160E33', 'accent': '#C9A66B'},
    }


class FakeSlidesClient:
    """Records calls; configurable failure modes for any step."""

    def __init__(
        self, *,
        create_returns: str = 'PRES-ID-1234',
        export_returns: bytes = b'FAKE-PPTX-BYTES',
        create_raises: Exception | None = None,
        export_raises: Exception | None = None,
    ):
        self.create_calls = []
        self.export_calls = []
        self._create_returns = create_returns
        self._export_returns = export_returns
        self._create_raises = create_raises
        self._export_raises = export_raises

    def create_presentation(self, title, slides_spec):
        self.create_calls.append((title, slides_spec))
        if self._create_raises is not None:
            raise self._create_raises
        return self._create_returns

    def export_to_pptx(self, presentation_id):
        self.export_calls.append(presentation_id)
        if self._export_raises is not None:
            raise self._export_raises
        return self._export_returns


def make_strategy(
    *, output_path=None, subject=None,
    fake_client=None, monkeypatch=None,
):
    if monkeypatch is not None:
        if output_path is None:
            monkeypatch.delenv('BRANDSIGHT_OUTPUT_PATH', raising=False)
        else:
            monkeypatch.setenv('BRANDSIGHT_OUTPUT_PATH', str(output_path))
        if subject is None:
            monkeypatch.delenv('DRIFTERBOT_SUBJECT', raising=False)
        else:
            monkeypatch.setenv('DRIFTERBOT_SUBJECT', subject)
    return DriveSaveStrategy(
        service_account_json_path='/tmp/fake-sa.json',
        subject=subject,
        output_path=output_path,
        slides_client=fake_client,
    )


# ------------------------------------------------------------------
# Filename
# ------------------------------------------------------------------


def test_drive_filename_pattern(draft):
    name = _build_drive_filename(draft)
    assert name.startswith('Acme Health - Competitive Audit - ')
    tail = name[len('Acme Health - Competitive Audit - '):]
    assert len(tail) == 13
    assert '—' not in name
    assert ' ' in name


# ------------------------------------------------------------------
# Output path / subject validation
# ------------------------------------------------------------------


def test_drive_save_strategy_requires_subject(monkeypatch, draft, slides_spec, tmp_path):
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_PATH', str(tmp_path))
    monkeypatch.delenv('DRIFTERBOT_SUBJECT', raising=False)
    client = FakeSlidesClient()
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='',
        output_path=tmp_path,
        slides_client=client,
    )
    with pytest.raises(RuntimeError, match='no subject'):
        strategy.save(draft, slides_spec)
    assert client.create_calls == []


# ------------------------------------------------------------------
# Happy path — file written to disk
# ------------------------------------------------------------------


def test_drive_save_strategy_happy_path_writes_pptx(
    draft, slides_spec, tmp_path, monkeypatch,
):
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_PATH', str(tmp_path))
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'drifterbot@drift-and-anchor.com')
    client = FakeSlidesClient(
        create_returns='PRES-ABCD',
        export_returns=b'PK\x03\x04FAKE-PPTX-CONTENT',
    )
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='drifterbot@drift-and-anchor.com',
        output_path=tmp_path,
        slides_client=client,
    )
    result = strategy.save(draft, slides_spec)

    assert isinstance(result, SaveResult)
    assert result.presentation_id == 'PRES-ABCD'
    assert result.web_url == 'https://docs.google.com/presentation/d/PRES-ABCD/edit'

    from pathlib import Path as PathlibPath
    assert isinstance(result.location, PathlibPath)

    expected_filename = _build_drive_filename(draft) + '.pptx'
    expected_path = tmp_path / expected_filename
    assert result.location == expected_path
    assert expected_path.exists()
    assert expected_path.read_bytes() == b'PK\x03\x04FAKE-PPTX-CONTENT'

    assert len(client.create_calls) == 1
    title_arg = client.create_calls[0][0]
    assert title_arg.startswith('Acme Health - Competitive Audit - 2026-07-21-')
    assert client.create_calls[0][1] == slides_spec
    assert client.export_calls == ['PRES-ABCD']


def test_drive_save_strategy_creates_output_dir_if_missing(
    draft, slides_spec, tmp_path, monkeypatch,
):
    nested = tmp_path / 'deep' / 'nest' / 'here'
    assert not nested.exists()
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_PATH', str(nested))
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'someone@example.com')
    client = FakeSlidesClient()
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='someone@example.com',
        output_path=nested,
        slides_client=client,
    )
    strategy.save(draft, slides_spec)
    assert nested.is_dir()
    files = list(nested.iterdir())
    assert len(files) == 1
    assert files[0].suffix == '.pptx'


# ------------------------------------------------------------------
# Default output path
# ------------------------------------------------------------------


def test_default_output_path_used_when_no_env(monkeypatch):
    monkeypatch.delenv('BRANDSIGHT_OUTPUT_PATH', raising=False)
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        slides_client=FakeSlidesClient(),
    )
    assert str(strategy.output_path) == '/mnt/brandsight-output'


def test_env_var_overrides_default_output_path(monkeypatch, tmp_path):
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_PATH', str(tmp_path))
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        slides_client=FakeSlidesClient(),
    )
    assert strategy.output_path == tmp_path


def test_kwarg_overrides_env_output_path(monkeypatch, tmp_path):
    other = tmp_path / 'other'
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_PATH', str(tmp_path))
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_path=other,
        slides_client=FakeSlidesClient(),
    )
    assert strategy.output_path == other


# ------------------------------------------------------------------
# Failure modes — error propagation
# ------------------------------------------------------------------


def test_drive_save_strategy_propagates_export_failure(
    draft, slides_spec, tmp_path, monkeypatch,
):
    from agents.driftbot.slides_client import DriveAuthError
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_PATH', str(tmp_path))
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'who@where.com')
    client = FakeSlidesClient(
        create_returns='PRES-ORPHAN',
        export_raises=DriveAuthError('simulated 500'),
    )
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_path=tmp_path,
        slides_client=client,
    )
    with pytest.raises(DriveAuthError, match='simulated 500'):
        strategy.save(draft, slides_spec)
    assert list(tmp_path.iterdir()) == []
    assert len(client.create_calls) == 1
    assert client.export_calls == ['PRES-ORPHAN']


def test_drive_save_strategy_propagates_create_failure(
    draft, slides_spec, tmp_path, monkeypatch,
):
    from agents.driftbot.slides_client import DriveAuthError
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_PATH', str(tmp_path))
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'who@where.com')

    def _raise(title, slides_spec):
        raise DriveAuthError('token grant failed')

    client = FakeSlidesClient()
    client.create_presentation = _raise
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_path=tmp_path,
        slides_client=client,
    )
    with pytest.raises(DriveAuthError, match='token grant failed'):
        strategy.save(draft, slides_spec)
    assert list(tmp_path.iterdir()) == []
    assert client.export_calls == []


def test_drive_save_strategy_propagates_write_failure(
    draft, slides_spec, tmp_path, monkeypatch,
):
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_PATH', str(tmp_path))
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'who@where.com')
    client = FakeSlidesClient(create_returns='PRES-OK')
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_path=tmp_path,
        slides_client=client,
    )
    from unittest.mock import patch
    with patch.object(
        type(strategy.output_path / 'x.pptx'), 'write_bytes',
        side_effect=OSError('disk full'),
    ):
        with pytest.raises(RuntimeError, match='cannot write pptx'):
            strategy.save(draft, slides_spec)


# ------------------------------------------------------------------
# Integration with SaveStrategy ABC + factory
# ------------------------------------------------------------------


def test_drive_save_strategy_is_save_strategy_subclass():
    from agents.driftbot.save_strategy import SaveStrategy
    s = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        slides_client=FakeSlidesClient(),
    )
    assert isinstance(s, SaveStrategy)


def test_get_save_strategy_factory_returns_drive(monkeypatch, tmp_path):
    monkeypatch.setenv('DRIFTERBOT_SAVE_STRATEGY', 'drive')
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_PATH', str(tmp_path))
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'sub@example.com')
    from agents.driftbot.save_strategy import get_save_strategy
    s = get_save_strategy()
    assert isinstance(s, DriveSaveStrategy)
    assert s.output_path == tmp_path
    assert s.subject == 'sub@example.com'


def test_get_save_strategy_factory_rejects_unknown(monkeypatch):
    monkeypatch.setenv('DRIFTERBOT_SAVE_STRATEGY', 's3upload')
    from agents.driftbot.save_strategy import get_save_strategy
    with pytest.raises(ValueError, match='unknown save strategy'):
        get_save_strategy()


def test_get_save_strategy_default_is_local_pickup(monkeypatch):
    monkeypatch.delenv('DRIFTERBOT_SAVE_STRATEGY', raising=False)
    from agents.driftbot.save_strategy import LocalPickupStrategy, get_save_strategy
    assert isinstance(get_save_strategy(), LocalPickupStrategy)
