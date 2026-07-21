"""
DrifterBot voice — D&A's lexicon, rhythm rules, and anti-patterns.
Used by runner.py for synthesis and by check_voice() for QA.
"""

# Core D&A vocabulary (use these; they're proprietary to the brand)
D_AND_A_LEXICON = {
    # Three-phase methodology — always capitalize, always use as proper nouns
    "methodology": ["Set Adrift", "Boil the Ocean", "Set Anchor"],

    # Five named Provocations — the chapter titles of every audit report
    # Source: BrandSight SKILL.md v3-final + RFP cover letter ("sea of sameness", "logo bingo")
    "provocations": [
        "Sea of Sameness",
        "Logo Bingo",
        "Audience Record Scratch",
        "Tone Deaf",
        "Brief In Context",
    ],

    # D&A's positioning verbs — use over generic alternatives
    # Source: Capabilities deck ("anchor", "elevate", "magnetize", "propel")
    "verbs": [
        "anchor",
        "elevate",
        "magnetize",
        "propel",
        "differentiate",
        "captivate",
        "convert",
        "get credit for",
        "own",
        "redefine",
    ],

    # Posture phrases — D&A's worldview, distilled
    # Source: Capabilities deck (direct quotes + close paraphrases)
    "posture": [
        "We exist to help them anchor.",
        "Brand is the strategy. Sales is the outcome.",
        "Story that drives immediate performance while creating lasting connection.",
        "So that awareness and memory of their brand persists even after the scrolling stops.",
        "Get noticed and get credit for what's relevant.",
        "No more choosing between long-term growth and short-term performance.",
    ],

    # Water/drift metaphor system — D&A's brand language runs on this
    "metaphors": [
        "adrift",
        "anchor",
        "drift",
        "cast a wide net",
        "dive deep",  # allowed in D&A context (their own phrase); blocked in anti-patterns as generic filler  # noqa: E501
        "surface",
        "above the noise",
        "above competitive noise",
        "sea of sameness",
    ],
}

# Sentence rhythm rules
# These are enforced by human review, not code — but check_voice() will flag
# documents that are obviously bloated (avg sentence words > threshold).
VOICE_RULES = {
    "max_sentence_words": 28,            # D&A writes tight. Never verbose.
    "max_paragraph_sentences": 4,        # Short paragraphs. Lots of white space.
    "min_persuasion_moves_per_chapter": 2,  # Every chapter must have ≥2 named moves
    # opener patterns to AVOID (DrifterBot never opens a paragraph with these)
    "avoid_openers": [
        "In today's competitive landscape",
        "It's important to note that",
        "When it comes to",
        "As we all know",
        "In the world of",
        "At the end of the day",
    ],
}

# Anti-patterns — phrases DrifterBot NEVER uses
# Source: D&A's own RFP letter (they name the "sea of sameness" as precisely this kind of language)
ANTI_PATTERNS = [
    "leverage synergies",
    "best-in-class",
    "end-to-end solution",
    "innovative solutions",
    "industry-leading",
    "we are excited to announce",
    "game-changer",
    "game changer",
    "synergy",
    "paradigm shift",
    "circle back",
    "move the needle",
    "thought leader",
    "deliver value",
    "best practices",
    "robust solution",
    "cutting-edge",
    "state-of-the-art",
    "world-class",
    "holistic approach",
    "seamless experience",
    "bleeding edge",
    "disruptive",
    "ecosystem",          # too buzzwordy unless used precisely
    "empower",
    "impactful",
    "actionable insights",
    "data-driven",        # overused; use the specific data instead
    "scalable solution",
    "value-add",
]
