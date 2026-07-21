"""
DrifterBot runner — CLI entry point for the competitive audit pipeline.

Usage:
    python3 -m agents.driftbot.runner \\
        --client /path/to/client.json \\
        --competitors /path/to/competitors.json \\
        --output-root /path/to/vault/audit/runs

Scope (a) MVP: loads synthetic fixture data, generates audit draft in D&A voice,
writes Markdown to the output root. Evidence collection (scrapers, vendor APIs)
is out of scope — see TODO stubs below.
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent

from agents.driftbot.voice import (
    ANTI_PATTERNS,
    D_AND_A_LEXICON,
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ClientConfig:
    id: str
    name: str
    category: str
    audiences: list[str]
    positioning_inputs: dict


@dataclass
class CompetitorConfig:
    id: str
    name: str
    category_position: str
    summary: str


@dataclass
class AuditDraft:
    audit_id: str
    client: ClientConfig
    competitors: list[CompetitorConfig]
    competitor_cards: list[str]       # Markdown per competitor
    provocation_chapters: list[str]   # Markdown per Provocation
    generated_at: str


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_client(path: Path) -> ClientConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ClientConfig(
        id=data["id"],
        name=data["name"],
        category=data["category"],
        audiences=data["audiences"],
        positioning_inputs=data["positioning_inputs"],
    )


def load_competitors(path: Path) -> list[CompetitorConfig]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        CompetitorConfig(
            id=c["id"],
            name=c["name"],
            category_position=c["category_position"],
            summary=c["summary"],
        )
        for c in data
    ]


# ---------------------------------------------------------------------------
# Prompt template loader
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_PROVOCATION_SLUGS = {
    "Sea of Sameness": "sea_of_sameness",
    "Logo Bingo": "logo_bingo",
    "Audience Record Scratch": "audience_record_scratch",
    "Tone Deaf": "tone_deaf",
    "Brief In Context": "brief_in_context",
}


def _load_prompt_template(provocation: str) -> str:
    slug = _PROVOCATION_SLUGS[provocation]
    return (_PROMPTS_DIR / f"{slug}.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Synthesis helpers
# ---------------------------------------------------------------------------


def _synthesize_sea_of_sameness(client: ClientConfig, competitors: list[CompetitorConfig]) -> dict:
    """Synthesize analysis text for the Sea of Sameness chapter."""
    # In MVP scope (a), synthesis is template-driven from fixture data.
    # Real synthesis would call a language model with scraped evidence.
    # TODO: wire to evidence-collection layer when scrapers are built.

    comp_names = [c.name for c in competitors]
    comp_positions = [c.category_position for c in competitors]
    unique_positions = set(comp_positions)

    findings = (
        f"Across the {len(competitors)} competitors audited — "
        f"{', '.join(comp_names[:-1])}, and {comp_names[-1]} — "
        f"we found {len(unique_positions)} distinct category position{'s' if len(unique_positions) != 1 else ''}, "  # noqa: E501
        f"but the language used to express them is nearly interchangeable. "
        f"Every player claims efficiency, speed, and scale. "
        f"None have found a position that rises above the category conversation."
    )
    why = (
        f"In {client.category}, buyers face high-consequence decisions "
        f"with limited ability to evaluate functional differences between vendors. "
        f"When the language is the same, the default selection criterion becomes price — "
        f"a race to the bottom that benefits no one. "
        f"{client.name}'s position statement — '{client.positioning_inputs.get('position_statement', '')}' — "  # noqa: E501
        f"is a genuine departure. The category hasn't found it yet."
    )
    implications = (
        f"{client.name} has a defensible angle that competitors have not claimed: "
        f"{', '.join(client.positioning_inputs.get('key_differentiators', []))}. "
        f"The audit's central recommendation is that {client.name} lean hard into this white space "
        f"before a competitor realizes it exists."
    )
    return {"sea_of_sameness_findings": findings, "why_it_matters": why, "implications": implications}  # noqa: E501


def _synthesize_logo_bingo(client: ClientConfig, competitors: list[CompetitorConfig]) -> dict:
    findings = (
        f"The visual audit of {len(competitors)} competitors in {client.category} revealed "
        f"a predictable palette: blues, grays, and white space arranged around stock photography "
        f"of clinical settings and professional handshakes. "
        f"The iconography is interchangeable. The typography is safe. "
        f"Nothing is wrong — and nothing is memorable."
    )
    why = (
        f"Visual identity is the first signal. "
        f"When it is indistinguishable from the category, the brand starts every encounter "
        f"at a deficit — the burden of differentiation falls entirely on the message, "
        f"which rarely has the strength to carry it alone. "
        f"{client.name} has a positioning statement built around being different. "
        f"The visual identity should say so before a word is read."
    )
    implications = (
        f"A deliberate departure from the category's visual conventions is available to {client.name}. "  # noqa: E501
        f"That departure does not need to be radical — it needs to be consistent, "
        f"ownable, and recognizably not the same as everyone else."
    )
    return {"logo_bingo_findings": findings, "why_it_matters": why, "implications": implications}


def _synthesize_audience_record_scratch(client: ClientConfig, competitors: list[CompetitorConfig]) -> dict:  # noqa: E501
    audiences = client.audiences
    findings = (
        f"Competitor communications in {client.category} address a generic 'decision-maker' — "
        f"a composite buyer who does not exist. "
        f"None of the {len(competitors)} competitors audited demonstrate awareness that "
        f"{', '.join(audiences[:-1])}, and {audiences[-1]} are not the same person, "
        f"do not share the same fears, and do not respond to the same language. "
        f"The result: communications that feel written for no one in particular."
    )
    why = (
        f"The most consequential insight from {client.name}'s case is that the buyer's "
        f"real fear is not about capability — it's about risk. "
        f"As decisions move further down the funnel, buyers stop asking 'what can it do?' "
        f"and start asking 'what could go wrong?' "
        f"The category's messaging does not address this shift. "
        f"{client.name}'s differentiators — especially empathy-driven implementation — directly answer it."  # noqa: E501
    )
    implications = (
        f"{client.name} should build a segment-specific messaging architecture: "
        f"one for each of {', '.join(audiences)}. "
        f"Each message should address the specific fear and success metric of that buyer — "
        f"not the product's features, but the buyer's reality."
    )
    return {
        "audience_record_scratch_findings": findings,
        "why_it_matters": why,
        "implications": implications,
    }


def _synthesize_tone_deaf(client: ClientConfig, competitors: list[CompetitorConfig]) -> dict:
    findings = (
        f"The dominant tone in {client.category} competitor communications is aspirational-generic: "  # noqa: E501
        f"confident claims delivered without acknowledgment of the pressures buyers actually face. "
        f"For {client.audiences[0]}s evaluating a new platform, this register lands as noise. "
        f"For {client.audiences[-1]}s — who feel the operational consequences most directly — "
        f"it reads as disconnected from their daily reality."
    )
    why = (
        f"Tone is not decoration. In high-stakes B2B categories, it is the primary trust signal. "
        f"A brand that speaks to the weight of a buyer's decision earns attention. "
        f"A brand that does not, gets filtered out before the first meeting. "
        f"{client.name}'s positioning — '{client.positioning_inputs.get('core_claim', '')}' — "
        f"is already calibrated to the right emotional register: direct, empathetic, and specific."
    )
    implications = (
        f"The tone opportunity for {client.name} is to be the brand in {client.category} "
        f"that treats the buyer's decision with the gravity it deserves — "
        f"not as a transaction, but as a relationship with consequences. "
        f"This is especially powerful with {client.audiences[-1]}s, "
        f"who are closest to those consequences."
    )
    return {"tone_deaf_findings": findings, "why_it_matters": why, "implications": implications}


def _synthesize_brief_in_context(client: ClientConfig, competitors: list[CompetitorConfig]) -> dict:
    diffs = client.positioning_inputs.get("key_differentiators", [])
    findings = (
        f"The competitive audit surfaces a clear brief for {client.name}: "
        f"there is a defensible white space in {client.category} built on "
        f"{', '.join(diffs)}. "
        f"No competitor has claimed it. The Sea of Sameness makes the category "
        f"receptive to a brand that does something different. "
        f"The Audience Record Scratch tells us what that brand needs to say, "
        f"and to whom."
    )
    why = (
        f"The brief is only useful if it is specific enough to drive creative decisions. "
        f"A positioning statement is not a brief. "
        f"A brief tells the creative team what to make, the sales team what to say, "
        f"and the marketing team what to measure. "
        f"{client.name}'s brief, properly written, should do all three."
    )
    implications = (
        f"The brief for {client.name} should anchor on the position statement "
        f"'{client.positioning_inputs.get('position_statement', '')}' "
        f"and build outward: what does that mean for a {client.audiences[0]}? "
        f"For a {client.audiences[-1]}? For a channel partner? "
        f"The answers are different, but they all come from the same anchor point. "
        f"That is the mark of a durable positioning strategy."
    )
    return {"brief_in_context_findings": findings, "why_it_matters": why, "implications": implications}  # noqa: E501


_SYNTHESIZERS = {
    "Sea of Sameness": _synthesize_sea_of_sameness,
    "Logo Bingo": _synthesize_logo_bingo,
    "Audience Record Scratch": _synthesize_audience_record_scratch,
    "Tone Deaf": _synthesize_tone_deaf,
    "Brief In Context": _synthesize_brief_in_context,
}


# ---------------------------------------------------------------------------
# Core generation functions
# ---------------------------------------------------------------------------


def generate_competitor_card(client: ClientConfig, competitor: CompetitorConfig) -> str:
    """Produce a ~150-word Markdown block for one competitor."""
    diffs = client.positioning_inputs.get("key_differentiators", [])
    position = client.positioning_inputs.get("position_statement", "")

    differentiation = (
        f"Where {competitor.name} {competitor.category_position.split()[0]}s on "
        f"{competitor.category_position.split()[-1] if len(competitor.category_position.split()) > 1 else 'generic claims'}, "  # noqa: E501
        f"{client.name} anchors on what that approach cannot claim: "
        f"{', '.join(diffs[:2])}. "
        f"'{position}' is not a feature comparison. It is a category redefinition."
    )

    return dedent(f"""\
        ### {competitor.name}

        **Category position:** {competitor.category_position}

        {competitor.summary}

        **Differentiation angle for {client.name}:** {differentiation}
    """)


def generate_provocation_chapter(
    provocation: str,
    client: ClientConfig,
    competitors: list[CompetitorConfig],
) -> str:
    """Render a Provocation chapter by substituting synthesized analysis into the template."""
    template = _load_prompt_template(provocation)
    synthesizer = _SYNTHESIZERS[provocation]
    analysis = synthesizer(client, competitors)

    # Replace {{ client.name }} and {{ client.category }}
    result = template.replace("{{ client.name }}", client.name)
    result = result.replace("{{ client.category }}", client.category)

    # Replace audience list template (tone_deaf.md uses it)
    audiences_str = ", ".join(client.audiences)
    result = result.replace("{{ client.audiences | join(\", \") }}", audiences_str)

    # Replace analysis placeholders
    for key, value in analysis.items():
        result = result.replace("{{ analysis." + key + " }}", value)

    # Clean up any remaining unresolved placeholders (shouldn't be any)
    result = re.sub(r"\{\{[^}]+\}\}", "[SYNTHESIS PENDING]", result)

    return result


def _synthesize_executive_summary(
    client: ClientConfig,
    competitors: list[CompetitorConfig],
) -> str:
    """Generate the executive summary in D&A voice."""
    comp_count = len(competitors)
    diffs = client.positioning_inputs.get("key_differentiators", [])
    position = client.positioning_inputs.get("position_statement", "")

    return dedent(f"""\
        {client.name} competes in {client.category} — a category adrift in a Sea of Sameness.
        Across {comp_count} competitors audited, the claims converge: efficiency, speed, scale.
        The language is interchangeable. The visual identities are forgettable. No one has
        found a position that rises above the noise and stays there.

        {client.name} has one. '{position}' is not a feature claim. It is a category
        redefinition — built on {', '.join(diffs)} — that no competitor has thought to make.

        This audit documents the white space. The Sea of Sameness tells us what the category
        is doing. The Audience Record Scratch tells us who is being ignored and how.
        The Brief In Context assembles both into an executable strategic direction.

        D&A's role: anchor {client.name} above competitive noise. This is the evidence.
        The story comes next.
    """).strip()


def run_audit(client: ClientConfig, competitors: list[CompetitorConfig]) -> AuditDraft:
    """Run the full audit pipeline and return an AuditDraft."""
    audit_id = str(uuid.uuid4())[:8]
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    competitor_cards = [generate_competitor_card(client, c) for c in competitors]
    provocation_chapters = [
        generate_provocation_chapter(p, client, competitors)
        for p in D_AND_A_LEXICON["provocations"]
    ]

    return AuditDraft(
        audit_id=audit_id,
        client=client,
        competitors=competitors,
        competitor_cards=competitor_cards,
        provocation_chapters=provocation_chapters,
        generated_at=generated_at,
    )


def render_audit_draft(draft: AuditDraft) -> str:
    """Assemble the full Markdown audit draft."""
    client = draft.client
    cards_block = "\n\n".join(draft.competitor_cards)
    chapters_block = "\n\n---\n\n".join(draft.provocation_chapters)
    exec_summary = _synthesize_executive_summary(client, draft.competitors)

    return dedent(f"""\
        # {client.name} — Competitive Audit Draft
        *Generated by DrifterBot for Drift & Anchor*
        *{draft.generated_at}*
        *audit_id: {draft.audit_id}*

        ---

        ## Executive Summary

        {exec_summary}

        ---

        ## Per-competitor cards

        {cards_block}

        ---

        {chapters_block}

        ---

        *DrifterBot MVP — Scope (a): persona + voice + skill-invocation glue*
        *Evidence collection: TODO (scrapers/vendor integrations not yet built)*
        *Renderers: TODO (Slides + Google Doc not yet built)*
    """)


def _write_audit_draft_local(draft: AuditDraft, output_root: Path) -> Path:
    """Local-filesystem write of the audit draft.

    Renamed from `write_audit_draft` when the save-strategy refactor landed.
    The canonical save entry point is `agents.driftbot.save_strategy.save_audit`;
    this local helper is retained for the CLI smoke path only.
    """
    run_dir = output_root / f"{draft.client.id}-{draft.audit_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "audit-draft.md"
    out_path.write_text(render_audit_draft(draft), encoding="utf-8")
    return out_path


def check_voice(text: str, skip_sections: tuple[str, ...] = ("## Per-competitor cards",)) -> dict:
    """Check the audit draft for anti-patterns and D&A lexicon hits.

    skip_sections: section headings whose content is excluded from the
    anti-pattern check (competitor summaries are input data, not DrifterBot prose).
    """
    # Strip excluded sections before anti-pattern check
    # (competitor summaries are input data, not DrifterBot's own prose)
    check_text = text
    for heading in skip_sections:
        # Remove everything from this heading to the next --- divider
        check_text = re.sub(
            rf"{re.escape(heading)}.*?(?=\n---)",
            "",
            check_text,
            flags=re.DOTALL,
        )

    # Anti-pattern check (case-insensitive, on DrifterBot prose only)
    anti_patterns_found = []
    for phrase in ANTI_PATTERNS:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        if pattern.search(check_text):
            anti_patterns_found.append(phrase)

    # Lexicon hit count (across all categories)
    lexicon_hits = []
    all_lexicon = []
    for phrases in D_AND_A_LEXICON.values():
        all_lexicon.extend(phrases)
    for phrase in all_lexicon:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        if pattern.search(text):
            lexicon_hits.append(phrase)

    return {
        "anti_patterns_found": anti_patterns_found,
        "lexicon_hits": lexicon_hits,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DrifterBot — generate a competitive audit draft in D&A voice."
    )
    parser.add_argument("--client", required=True, type=Path, help="Path to client.json")
    parser.add_argument("--competitors", required=True, type=Path, help="Path to competitors.json")
    parser.add_argument(
        "--output-root",
        required=True,
        type=Path,
        help="Root directory for audit run output (e.g. vault/audit/runs)",
    )
    args = parser.parse_args()

    print(f"DrifterBot — loading client from {args.client}")
    client = load_client(args.client)
    competitors = load_competitors(args.competitors)
    print(f"  Client: {client.name} | Category: {client.category}")
    print(f"  Competitors: {len(competitors)}")

    print("Running audit pipeline...")
    draft = run_audit(client, competitors)

    print("Writing audit draft...")
    out_path = _write_audit_draft_local(draft, args.output_root)

    voice = check_voice(out_path.read_text(encoding="utf-8"))
    word_count = len(out_path.read_text(encoding="utf-8").split())

    print("\n=== DrifterBot audit complete ===")
    print(f"  Audit ID:       {draft.audit_id}")
    print(f"  Output:         {out_path}")
    print(f"  Word count:     {word_count}")
    print(f"  Competitors:    {len(competitors)}")
    print(f"  Chapters:       {len(draft.provocation_chapters)}")
    print(f"  Anti-patterns:  {voice['anti_patterns_found'] or 'none ✓'}")
    print(f"  Lexicon hits:   {len(voice['lexicon_hits'])} ({', '.join(voice['lexicon_hits'][:5])}{'...' if len(voice['lexicon_hits']) > 5 else ''})")  # noqa: E501


if __name__ == "__main__":
    main()
