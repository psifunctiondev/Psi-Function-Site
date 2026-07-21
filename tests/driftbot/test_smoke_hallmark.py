"""
Smoke test: DrifterBot MVP on the Hallmark synthetic test fixture.

Acceptance criteria (per spec, 2026-07-15):
- 5 Provocation chapters present
- 5+ per-competitor cards present
- ## Per-competitor cards section present
- Zero anti-pattern phrases in output
- ≥3 D&A lexicon phrase hits in output
- Output file > 5,000 bytes (real document, not a stub)

Portal pipeline extension (2026-07-15, spec §7):
- portal-request.json fixture loads cleanly + validates against expected shape
- Slides renderer produces well-formed presentation JSON
- Save strategy emits both `slides-spec.json` + `audit-draft.md` in the run dir
- Slides spec contains all four D&A brand-palette hex codes
"""

import json
from pathlib import Path

import pytest

from agents.driftbot.renderer_slides import (
    DA_ACCENT,
    DA_NEUTRAL_DARK,
    DA_NEUTRAL_LIGHT,
    DA_PRIMARY,
    render_slides_spec,
)
from agents.driftbot.runner import (
    AuditDraft,
    ClientConfig,
    CompetitorConfig,
    check_voice,
    load_client,
    load_competitors,
    render_audit_draft,
    run_audit,
)
from agents.driftbot.save_strategy import (
    LocalPickupStrategy,
)
from agents.driftbot.voice import D_AND_A_LEXICON

# Path to vault test fixtures. Path C moved the tests under tests/driftbot/
# of the Psi-Function-Site repo (one less parent than the original
# brandsight/agents/driftbot/tests/ location), so parents[2] lands us at
# the workspace root which is where vaults/ is mounted.
_VAULT_ROOT = Path(__file__).parents[2]
FIXTURE_ROOT = (
    _VAULT_ROOT
    / "vaults/shared/Shared Obsidian/psi-function/clients/drift-and-anchor"
    / "audit/_input/test-fixtures/hallmark"
)

# The Hallmark fixture is a synthetic D&A test asset that lives in Quinn's
# Obsidian vault (synced via Seafile, NOT committed to the repo). When the
# vault isn't mounted — e.g. on the GitHub CI runner — these tests skip
# with a clear message instead of failing with a misleading "Missing
# client.json" assertion. Local runs on Belel see the vault via the
# Seafile sync, so the tests run normally there.
_FIXTURES_AVAILABLE = FIXTURE_ROOT.is_dir() and (FIXTURE_ROOT / "client.json").exists()
pytestmark = pytest.mark.skipif(
    not _FIXTURES_AVAILABLE,
    reason=(
        f"Vault fixtures not present at {FIXTURE_ROOT}. "
        "These tests require the Obsidian vault to be synced locally. "
        "On CI (no Seafile mount) they are intentionally skipped."
    ),
)


def _hydrate_runner_inputs_from_portal_request(portal_req: dict) -> tuple[ClientConfig, list[CompetitorConfig]]:  # noqa: E501
    """Adapter mirroring spec §5 `_audit_request_to_client`.

    The portal-request.json shape differs from client.json/competitors.json:
    competitors arrive as a flat list of names (category_position + summary
    are TBD pending Doxa triage). The adapter is intentionally local to the
    test until worker.py lands the canonical version (spec §5).
    """
    client = ClientConfig(
        id="hallmark-health-care",
        name=portal_req["client_name"],
        category=portal_req["client_category"],
        audiences=portal_req["audiences"],
        positioning_inputs=portal_req.get("positioning", {}),
    )
    competitors = [
        CompetitorConfig(
            id=f"comp-{i + 1}",
            name=name,
            category_position="(TBD)",
            summary="(TBD)",
        )
        for i, name in enumerate(portal_req["competitors"])
    ]
    return client, competitors


def test_fixture_files_exist():
    """Fixtures must be staged in the vault before the build test can run."""
    assert (FIXTURE_ROOT / "client.json").exists(), f"Missing client.json at {FIXTURE_ROOT}"
    assert (FIXTURE_ROOT / "competitors.json").exists(), f"Missing competitors.json at {FIXTURE_ROOT}"  # noqa: E501
    assert (FIXTURE_ROOT / "portal-request.json").exists(), (
        f"Missing portal-request.json at {FIXTURE_ROOT}"
    )


def test_hallmark_smoke_produces_audit_draft(tmp_path):
    """End-to-end smoke: load → run → render → voice check → write."""
    client = load_client(FIXTURE_ROOT / "client.json")
    competitors = load_competitors(FIXTURE_ROOT / "competitors.json")

    # Basic fixture integrity
    assert client.name == "Hallmark Health Care"
    assert len(competitors) == 5, f"Expected 5 competitors, got {len(competitors)}"

    # Run the pipeline
    draft = run_audit(client, competitors)
    assert len(draft.competitor_cards) == 5
    assert len(draft.provocation_chapters) == 5

    # Render
    md = render_audit_draft(draft)

    # Structure: all 5 Provocation chapters must be present
    for provocation in D_AND_A_LEXICON["provocations"]:
        assert f"# {provocation}" in md, f"Missing Provocation chapter: {provocation}"

    # Structure: per-competitor cards section + 5 cards
    assert "## Per-competitor cards" in md, "Missing Per-competitor cards section"
    assert md.count("### ") >= 5, "Expected at least 5 per-competitor card headers"

    # Voice: no anti-patterns
    voice = check_voice(md)
    assert voice["anti_patterns_found"] == [], (
        f"Anti-patterns found in output: {voice['anti_patterns_found']}"
    )

    # Voice: D&A lexicon must appear
    assert len(voice["lexicon_hits"]) >= 3, (
        f"Expected ≥3 D&A lexicon hits, got {len(voice['lexicon_hits'])}: {voice['lexicon_hits']}"
    )

    # Size: should be a real document
    out = tmp_path / "audit-draft.md"
    out.write_text(md, encoding="utf-8")
    assert out.exists()
    assert out.stat().st_size > 5000, f"Audit draft too small ({out.stat().st_size} bytes) — likely a stub"  # noqa: E501

    # Print summary for human review
    print("\n=== Smoke test passed ===")
    print(f"  Word count: {len(md.split())}")
    print(f"  Lexicon hits: {voice['lexicon_hits']}")
    print("  Anti-patterns: none ✓")
    print("\n--- First 30 lines of audit draft ---")
    for line in md.splitlines()[:30]:
        print(line)


def test_portal_request_fixture_well_formed():
    """The portal-request.json must parse and match the spec §7 schema."""
    raw = (FIXTURE_ROOT / "portal-request.json").read_text(encoding="utf-8")
    req = json.loads(raw)  # well-formed JSON check

    # Required spec fields, in order:
    assert req["client_name"] == "Hallmark Health Care"
    assert req["client_category"] == "healthcare clinical staffing technology"
    assert isinstance(req["competitors"], list) and len(req["competitors"]) == 5
    assert req["audiences"] == ["CFO", "CTO", "Nurse Manager"]
    assert req["positioning"]["core_claim"].startswith("Only Hallmark")
    assert req["positioning"]["position_statement"] == "Don't just outsource. Insource."
    assert len(req["positioning"]["key_differentiators"]) == 3
    # TikTok per spec (deliberately included)
    assert "TikTok" in req["social_scans"]
    assert req["context_drive_links"] == []
    assert req["notes"].startswith("synthetic test")


def test_portal_pipeline_renders_slides_and_saves(tmp_path):
    """End-to-end portal pipeline: portal-request → run_audit → render_slides_spec → save.

    Acceptance (per spec §7 + §10):
    - Slides spec is well-formed JSON, written to disk
    - D&A brand color hex codes are present in the spec
    - Save strategy lays down both slides-spec.json AND audit-draft.md
    - Existing voice check still passes on the rendered Slides prose
    """
    # ----- Load portal-request.json fixture -----
    req = json.loads((FIXTURE_ROOT / "portal-request.json").read_text(encoding="utf-8"))
    client, competitors = _hydrate_runner_inputs_from_portal_request(req)

    payload = {
        "request_id": 0,  # synthetic for the smoke test
        "social_scans": req["social_scans"],
        "context_drive_links": req["context_drive_links"],
        "notes": req.get("notes", ""),
        "requested_at": "2026-07-15T00:00:00+00:00",
    }

    # ----- Run audit -----
    draft: AuditDraft = run_audit(client, competitors)
    assert draft.client.name == "Hallmark Health Care"
    assert len(draft.competitors) == 5

    # ----- Render Slides spec -----
    spec = render_slides_spec(draft, payload)

    # Structure
    assert spec["title"].startswith("Hallmark Health Care")
    assert spec["locale"] == "en_US"
    # 1 title + 1 exec-summary + 5 competitor cards + 5 provocation chapters
    assert len(spec["slides"]) == 12, f"Expected 12 slides, got {len(spec['slides'])}"
    assert spec["slides"][0]["slideId"] == "slide-title"
    assert spec["slides"][1]["slideId"] == "slide-exec-summary"
    for i in range(1, 6):
        assert f"slide-comp-{i}" in {s["slideId"] for s in spec["slides"]}
    for i in range(1, 6):
        assert f"slide-prov-{i}" in {s["slideId"] for s in spec["slides"]}

    # D&A brand palette — all four hex codes must appear in the spec
    spec_str = json.dumps(spec)
    for hex_code in (DA_PRIMARY, DA_ACCENT, DA_NEUTRAL_LIGHT, DA_NEUTRAL_DARK):
        assert hex_code in spec_str, f"Missing D&A brand color: {hex_code}"

    # Meta block (per spec §6.2)
    assert spec["_dandA_meta"]["client"] == "Hallmark Health Care"
    assert spec["_dandA_meta"]["audit_id"] == draft.audit_id
    assert spec["_dandA_meta"]["folder_name"].startswith("clients/")
    assert spec["_dandA_meta"]["folder_name"].endswith(draft.audit_id)

    # ----- Save strategy: write to tmp -----
    strategy = LocalPickupStrategy(root=tmp_path)
    result = strategy.save(draft, spec)
    run_dir = result.location  # Path for LocalPickup, URL for Drive
    assert run_dir.exists() if hasattr(run_dir, 'exists') else True
    assert run_dir.is_dir() if hasattr(run_dir, 'is_dir') else False
    # LocalPickup doesn't produce Drive-side identifiers
    assert result.presentation_id is None
    assert result.web_url is None

    # slides-spec.json exists, is well-formed JSON, contains brand colors
    spec_path = run_dir / "slides-spec.json"
    assert spec_path.exists(), "slides-spec.json was not written by the save strategy"
    on_disk = json.loads(spec_path.read_text(encoding="utf-8"))
    # The top-level `presentation` shape doesn't include audit_id directly;
    # verify via the _dandA_meta block per spec §6.2.
    assert on_disk["_dandA_meta"]["audit_id"] == draft.audit_id
    for hex_code in (DA_PRIMARY, DA_ACCENT, DA_NEUTRAL_LIGHT, DA_NEUTRAL_DARK):
        assert hex_code in spec_path.read_text(encoding="utf-8"), (
            f"slides-spec.json on disk missing D&A brand color: {hex_code}"
        )

    # audit-draft.md exists alongside (the Markdown eye-balling preview)
    md_path = run_dir / "audit-draft.md"
    assert md_path.exists(), "audit-draft.md was not written by the save strategy"
    md_text = md_path.read_text(encoding="utf-8")

    # Voice check on the saved Markdown preview (matches worker behavior)
    voice = check_voice(md_text)
    assert voice["anti_patterns_found"] == [], (
        f"Anti-patterns in saved draft: {voice['anti_patterns_found']}"
    )

    # Print summary for human review
    print("\n=== Portal pipeline smoke passed ===")
    print(f"  Run dir:        {run_dir}")
    print(f"  Slides:         {len(spec['slides'])}")
    print(f"  D&A colors:     primary={DA_PRIMARY} accent={DA_ACCENT}")
    print("  Anti-patterns:  none ✓")
    print(f"  Lexicon hits:   {len(voice['lexicon_hits'])}")


def test_save_strategy_factory_returns_local_pickup_by_default():
    """Factory contract: `DRIFTERBOT_SAVE_STRATEGY` env var selects the strategy.

    The default name is `local_pickup`; other names must raise. Save_strategy
    is only exercised via factory in the worker — keep this test isolating the
    factory behavior so a /tmp write doesn't leak across tests.
    """
    import os

    from agents.driftbot.save_strategy import get_save_strategy

    # default
    os.environ.pop("DRIFTERBOT_SAVE_STRATEGY", None)
    strat = get_save_strategy()
    assert isinstance(strat, LocalPickupStrategy)
    assert strat.root == Path("/tmp/drifterbot-pickup")

    # explicit
    os.environ["DRIFTERBOT_SAVE_STRATEGY"] = "local_pickup"
    assert isinstance(get_save_strategy(), LocalPickupStrategy)

    # unknown name → ValueError, never a silent fallback
    os.environ["DRIFTERBOT_SAVE_STRATEGY"] = "nope"
    try:
        get_save_strategy()
    except ValueError as e:
        assert "unknown save strategy" in str(e)
    else:
        raise AssertionError("Expected ValueError for unknown strategy name")

    # reset
    os.environ.pop("DRIFTERBOT_SAVE_STRATEGY", None)
