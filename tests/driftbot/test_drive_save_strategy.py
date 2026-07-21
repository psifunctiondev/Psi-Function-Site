"""
Unit tests for DriveSaveStrategy (Path A-corrected: native Slides in Drive,
no on-disk artifact).

Mocks SlidesClient; never hits Google. Verifies:
    - subject resolution (env / kwarg / error)
    - folder_id resolution (env / kwarg / default constant)
    - filename pattern passed to Slides API title arg
    - create + move invoked in order with correct args
    - SaveResult returned with all three fields populated
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
    """Records calls; configurable failure modes for any step."""

    def __init__(
        self, *,
        create_returns: str = 'PRES-ID-1234',
        move_returns: str = 'https://docs.google.com/presentation/d/PRES-ID-1234/edit',
        create_raises: Exception | None = None,
        move_raises: Exception | None = None,
        delete_raises: Exception | None = None,
    ):
        self.create_calls = []
        self.move_calls = []
        self.export_calls = []
        self.delete_calls = []
        self._create_returns = create_returns
        self._move_returns = move_returns
        self._create_raises = create_raises
        self._move_raises = move_raises
        self._delete_raises = delete_raises

    def create_presentation(self, title, slides_spec):
        self.create_calls.append((title, slides_spec))
        if self._create_raises is not None:
            raise self._create_raises
        return self._create_returns

    def move_to_folder(self, presentation_id, folder_id, name):
        self.move_calls.append((presentation_id, folder_id, name))
        if self._move_raises is not None:
            raise self._move_raises
        return self._move_returns

    def delete_file(self, file_id, *, swallow_404: bool = True):
        self.delete_calls.append((file_id, swallow_404))
        if self._delete_raises is not None:
            raise self._delete_raises
        return None


# ------------------------------------------------------------------
# Filename
# ------------------------------------------------------------------


def test_drive_filename_pattern(draft):
    name = _build_drive_filename(draft)
    assert name.startswith('Acme Health - Competitive Audit - ')
    tail = name[len('Acme Health - Competitive Audit - '):]
    assert len(tail) == 13
    assert '—' not in name


# ------------------------------------------------------------------
# Output folder + subject validation
# ------------------------------------------------------------------


def test_drive_save_strategy_requires_subject(monkeypatch, draft, slides_spec):
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'FOLDER-ID')
    monkeypatch.delenv('DRIFTERBOT_SUBJECT', raising=False)
    client = FakeSlidesClient()
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='',
        slides_client=client,
    )
    with pytest.raises(RuntimeError, match='no subject'):
        strategy.save(draft, slides_spec)
    assert client.create_calls == []


def test_default_output_folder_id():
    """Sanity check: default constant points at the BrandSight Client
    Output subfolder inside the DrifterBot Shared Drive.
    """
    assert DEFAULT_OUTPUT_FOLDER_ID == '1rrVimH-UB3qn0FJ0rBuZ9FoTTydSMdIS'


def test_env_var_overrides_default_folder_id(monkeypatch):
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'ENV-FOLDER-ID')
    monkeypatch.delenv('DRANDSIGHT_OUTPUT_FOLDER_ID', raising=False)
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        slides_client=FakeSlidesClient(),
    )
    assert strategy.output_folder_id == 'ENV-FOLDER-ID'


def test_kwarg_overrides_env_folder_id(monkeypatch):
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'ENV-FOLDER-ID')
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_folder_id='KWARG-FOLDER-ID',
        slides_client=FakeSlidesClient(),
    )
    assert strategy.output_folder_id == 'KWARG-FOLDER-ID'


def test_default_folder_used_when_neither_set(monkeypatch):
    monkeypatch.delenv('BRANDSIGHT_OUTPUT_FOLDER_ID', raising=False)
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        slides_client=FakeSlidesClient(),
    )
    assert strategy.output_folder_id == DEFAULT_OUTPUT_FOLDER_ID


# ------------------------------------------------------------------
# Happy path
# ------------------------------------------------------------------


def test_drive_save_strategy_happy_path_invokes_create_then_move(
    draft, slides_spec, monkeypatch,
):
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'FOLDER-XYZ')
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'drifterbot@drift-and-anchor.com')
    client = FakeSlidesClient(
        create_returns='PRES-ABCD',
        move_returns='https://docs.google.com/presentation/d/PRES-ABCD/edit',
    )
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='drifterbot@drift-and-anchor.com',
        output_folder_id='FOLDER-XYZ',
        slides_client=client,
    )
    result = strategy.save(draft, slides_spec)

    assert isinstance(result, SaveResult)
    assert result.presentation_id == 'PRES-ABCD'
    assert result.web_url == (
        'https://docs.google.com/presentation/d/PRES-ABCD/edit'
    )
    assert result.location == (
        'https://drive.google.com/drive/folders/FOLDER-XYZ'
    )

    # create was called first, with the filename as title
    assert len(client.create_calls) == 1
    title_arg, spec_arg = client.create_calls[0]
    assert title_arg.startswith('Acme Health - Competitive Audit - 2026-07-21-')
    assert spec_arg == slides_spec

    # move was called second, with the right IDs and filename
    assert client.move_calls == [
        ('PRES-ABCD', 'FOLDER-XYZ', title_arg),
    ]


def test_no_export_or_write_call_in_save(
    draft, slides_spec, monkeypatch,
):
    """Path A-corrected never calls files.export or writes a file."""
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'FOLDER-XYZ')
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'who@where.com')
    client = FakeSlidesClient()
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_folder_id='FOLDER-XYZ',
        slides_client=client,
    )
    strategy.save(draft, slides_spec)
    assert client.export_calls == []


# ------------------------------------------------------------------
# Failure modes — error propagation
# ------------------------------------------------------------------


def test_drive_save_strategy_propagates_move_failure(
    draft, slides_spec, monkeypatch,
):
    """Create succeeded, move failed → orphan deleted, no SaveResult.

    The cleanup-on-failure path is the headline behavior of this
    version. Without it, every move-failure leaves a stranded
    presentation in the impersonated user's My Drive root.
    """
    from agents.driftbot.slides_client import DriveFolderAccessError
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'FOLDER-XYZ')
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'who@where.com')
    client = FakeSlidesClient(
        create_returns='PRES-ORPHAN',
        move_raises=DriveFolderAccessError('files.patch 404'),
    )
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_folder_id='FOLDER-XYZ',
        slides_client=client,
    )
    with pytest.raises(DriveFolderAccessError, match='files.patch 404'):
        strategy.save(draft, slides_spec)
    assert len(client.create_calls) == 1
    assert len(client.move_calls) == 1
    # Cleanup path: delete_file called with the orphan presentation_id
    assert client.delete_calls == [('PRES-ORPHAN', True)]


def test_drive_save_strategy_cleanup_failure_does_not_shadow_original_error(
    draft, slides_spec, monkeypatch,
):
    """If both move fails AND delete fails, the original move error
    is the one surfaced. Cleanup failure is logged but not raised.
    Otherwise a transient orphan-cleanup glitch would mask the real
    cause in logs / DB rows.
    """
    from agents.driftbot.slides_client import (
        DriveAuthError,
        DriveFolderAccessError,
    )
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'FOLDER-XYZ')
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'who@where.com')
    client = FakeSlidesClient(
        create_returns='PRES-ORPHAN',
        move_raises=DriveFolderAccessError('files.patch 404'),
        delete_raises=DriveAuthError('files.delete 500'),
    )
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_folder_id='FOLDER-XYZ',
        slides_client=client,
    )
    with pytest.raises(DriveFolderAccessError, match='files.patch 404'):
        strategy.save(draft, slides_spec)
    # delete was attempted (and raised internally), still recorded
    assert client.delete_calls == [('PRES-ORPHAN', True)]


def test_drive_save_strategy_no_delete_on_success(
    draft, slides_spec, monkeypatch,
):
    """Happy path never calls delete_file. Cleanup is for failure only.
    """
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'FOLDER-XYZ')
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'who@where.com')
    client = FakeSlidesClient()
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_folder_id='FOLDER-XYZ',
        slides_client=client,
    )
    result = strategy.save(draft, slides_spec)
    assert result.presentation_id == 'PRES-ID-1234'
    assert client.delete_calls == []


def test_drive_save_strategy_propagates_create_failure(
    draft, slides_spec, monkeypatch,
):
    """Create failed → no move, no SaveResult."""
    from agents.driftbot.slides_client import DriveAuthError
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'FOLDER-XYZ')
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'who@where.com')

    def _raise(title, slides_spec):
        raise DriveAuthError('token grant failed')

    client = FakeSlidesClient()
    client.create_presentation = _raise
    strategy = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_folder_id='FOLDER-XYZ',
        slides_client=client,
    )
    with pytest.raises(DriveAuthError, match='token grant failed'):
        strategy.save(draft, slides_spec)
    assert client.move_calls == []


# ------------------------------------------------------------------
# Integration with SaveStrategy ABC + factory
# ------------------------------------------------------------------


def test_drive_save_strategy_is_save_strategy_subclass():
    from agents.driftbot.save_strategy import SaveStrategy
    s = DriveSaveStrategy(
        service_account_json_path='/tmp/x.json',
        subject='who@where.com',
        output_folder_id='FOLDER',
        slides_client=FakeSlidesClient(),
    )
    assert isinstance(s, SaveStrategy)


def test_get_save_strategy_factory_returns_drive(monkeypatch):
    monkeypatch.setenv('DRIFTERBOT_SAVE_STRATEGY', 'drive')
    monkeypatch.setenv('BRANDSIGHT_OUTPUT_FOLDER_ID', 'FOLDER-FACTORY')
    monkeypatch.setenv('DRIFTERBOT_SUBJECT', 'sub@example.com')
    from agents.driftbot.save_strategy import get_save_strategy
    s = get_save_strategy()
    assert isinstance(s, DriveSaveStrategy)
    assert s.output_folder_id == 'FOLDER-FACTORY'
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
