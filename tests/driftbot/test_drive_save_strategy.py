"""
Unit tests for DriveSaveStrategy. Mocks SlidesClient so we never hit
Google's API but verify the strategy's orchestration:
    - folder ID resolution (env / kwarg / default)
    - subject resolution (env / kwarg / error)
    - filename pattern
    - orphan handling on slide-create success + move failure
    - SaveResult shape returned to the worker
"""

from __future__ import annotations

import pytest

from agents.driftbot.runner import (
    AuditDraft,
    ClientConfig,
    CompetitorConfig,
)
from agents.driftbot.save_strategy import (
    DEFAULT_OUTPUT_FOLDER_ID,
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
    """Records calls; configurable failure modes."""

    def __init__(
        self, *,
        create_returns: str = 'PRES-ID-1234',
        move_returns: str = 'https://docs.google.com/presentation/d/PRES-ID-1234/edit',
        move_raises: Exception | None = None,
    ):
        self.create_calls = []
        self.move_calls = []
        self._create_returns = create_returns
        self._move_returns = move_returns
        self._move_raises = move_raises

    def create_presentation(self, title, slides_spec):
        self.create_calls.append((title, slides_spec))
        return self._create_returns

    def move_to_folder(self, presentation_id, folder_id, name):
        self.move_calls.append((presentation_id, folder_id, name))
        if self._move_raises is not None:
            raise self._move_raises
        return self._move_returns


def make_strategy(
    *, folder_id: str | None = None, subject: str | None = None,
    fake_client=None, monkeypatch=None,
):
    """Build a DriveSaveStrategy with optional injected fakes + env."""
    if monkeypatch is not None:
        # Default folder ID if not provided via kwarg
        if folder_id is None:
            monkeypatch.delenv('BRANDSIGHT_OUTPUT_FOLDER_ID', raising=False)
        else:
            monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', folder_id)
        if subject is None:
            monkeypatch.delenv('DRIFTERBOT_SUBJECT', raising=False)
        else:
            monkeypatch.setenv('DRIFTERBOT_SUBJECT', subject)
    return DriveSaveStrategy(
        service_account_json_path='/tmp/fake-sa.json',
        subject=subject,
        output_folder_id=folder_id,
        slides_client=fake_client,
    )


# ------------------------------------------------------------------
# Filename
# ------------------------------------------------------------------


def test_drive_filename_pattern(draft):
    """{Client Name} - Competitive Audit - {YYYY-MM-DD-HH}, hyphens, 24h UTC."""
    name = _build_drive_filename(draft)
    assert name.startswith('Acme Health - Competitive Audit - ')
    # Trailing YYYY-MM-DD-HH = 13 chars
    assert len(name) - len('Acme Health - Competitive Audit - ') == 13
    # Hyphens, no em-dashes
    assert '—' not in name
    assert ' ' in name  # spaces separate words


# ------------------------------------------------------------------
# Folder / subject validation
# ------------------------------------------------------------------


def test_drive_save_strategy_requires_folder_id(monkeypatch, draft, slides_spec):
    monkeypatch.delenv('BRANDSIGHT_OUTPUT_FOLDER_ID', raising=False)
    monkeypatch.delenv('DRIFTERBOT_OUTPUT_FOLDER_ID', raising=False)
    client = FakeSlidesClient()
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='someone@example.com',
        slides_client=client,
    )
    strategy.output_folder_id = ''  # force missing
    with pytest.raises(RuntimeError, match='no output folder'):
        strategy.save(draft, slides_spec)
    assert client.create_calls == []


def test_drive_save_strategy_requires_subject(monkeypatch, draft, slides_spec):
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'FOLDER-1')
    monkeypatch.delenv('DRIFTERBOT_SUBJECT', raising=False)
    client = FakeSlidesClient()
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='',
        output_folder_id='FOLDER-1',
        slides_client=client,
    )
    with pytest.raises(RuntimeError, match='no subject'):
        strategy.save(draft, slides_spec)


# ------------------------------------------------------------------
# Happy path
# ------------------------------------------------------------------


def test_drive_save_strategy_happy_path(draft, slides_spec):
    client = FakeSlidesClient(
        create_returns='PRES-ABCD',
        move_returns='https://docs.google.com/presentation/d/PRES-ABCD/edit',
    )
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='drifterbot@drift-and-anchor.com',
        output_folder_id='FOLDER-1',
        slides_client=client,
    )
    result = strategy.save(draft, slides_spec)

    assert isinstance(result, SaveResult)
    assert result.presentation_id == 'PRES-ABCD'
    assert result.web_url == 'https://docs.google.com/presentation/d/PRES-ABCD/edit'
    assert result.location == 'https://docs.google.com/presentation/d/PRES-ABCD/edit'

    # SlidesClient called with rendered spec
    assert len(client.create_calls) == 1
    title_arg, spec_arg = client.create_calls[0]
    assert title_arg.endswith(' - Competitive Audit - ') or 'Competitive Audit' in title_arg
    assert spec_arg == slides_spec

    # Move-to-folder called after create
    assert client.move_calls == [('PRES-ABCD', 'FOLDER-1', title_arg)]


def test_default_folder_id_used_when_no_env(monkeypatch):
    monkeypatch.delenv('BRANDSIGHT_OUTPUT_FOLDER_ID', raising=False)
    monkeypatch.delenv('DRIFTERBOT_OUTPUT_FOLDER_ID', raising=False)
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        slides_client=FakeSlidesClient(),
    )
    assert strategy.output_folder_id == DEFAULT_OUTPUT_FOLDER_ID


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'CUSTOM-FOLDER')
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        slides_client=FakeSlidesClient(),
    )
    assert strategy.output_folder_id == 'CUSTOM-FOLDER'


def test_kwarg_overrides_env(monkeypatch):
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'FROM-ENV')
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_folder_id='FROM-KWARG',
        slides_client=FakeSlidesClient(),
    )
    assert strategy.output_folder_id == 'FROM-KWARG'


# ------------------------------------------------------------------
# Failure modes — orphan preservation
# ------------------------------------------------------------------


def test_drive_save_strategy_propagates_move_failure(draft, slides_spec):
    """If create succeeded but move fails, raise so caller sees the orphan."""
    from agents.driftbot.slides_client import DriveFolderAccessError
    client = FakeSlidesClient(
        create_returns='PRES-ORPHAN',
        move_raises=DriveFolderAccessError('simulated 404'),
    )
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_folder_id='BAD-FOLDER',
        slides_client=client,
    )
    with pytest.raises(DriveFolderAccessError, match='simulated 404'):
        strategy.save(draft, slides_spec)
    # Both calls were made — the create did NOT get rolled back
    assert len(client.create_calls) == 1
    assert client.move_calls == [('PRES-ORPHAN', 'BAD-FOLDER', client.create_calls[0][0])]


def test_drive_save_strategy_propagates_auth_failure(draft, slides_spec):
    from agents.driftbot.slides_client import DriveAuthError

    def _raise_auth_error(title, slides_spec):
        raise DriveAuthError('token grant failed')

    client = FakeSlidesClient()
    client.create_presentation = _raise_auth_error
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_folder_id='FOLDER-1',
        slides_client=client,
    )
    with pytest.raises(DriveAuthError, match='token grant failed'):
        strategy.save(draft, slides_spec)
    # Move never called because create raised
    assert client.move_calls == []


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


def test_get_save_strategy_factory_returns_drive(monkeypatch):
    monkeypatch.setenv('DRIFTERBOT_SAVE_STRATEGY', 'drive')
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'F-FACTORY')
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'sub@example.com')
    from agents.driftbot.save_strategy import get_save_strategy
    s = get_save_strategy()
    assert isinstance(s, DriveSaveStrategy)
    assert s.output_folder_id == 'F-FACTORY'
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


def test_save_audit_convenience_returns_save_result(draft, slides_spec, tmp_path, monkeypatch):
    """End-to-end check on the convenience function used by the worker."""
    from agents.driftbot.save_strategy import save_audit
    monkeypatch.setenv('DRIFTERBOT_SAVE_STRATEGY', 'local_pickup')
    monkeypatch.setattr(
        'agents.driftbot.save_strategy.LocalPickupStrategy.__init__',
        lambda self, root=None: setattr(self, 'root', tmp_path) or None,
    )
    result = save_audit(draft, slides_spec, request_id=42)
    assert isinstance(result, SaveResult)
    assert result.presentation_id is None
    assert result.web_url is None
    assert str(result.location).startswith(str(tmp_path))
