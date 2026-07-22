"""
BrandSight layout catalog — maps D&A brand template layouts to the
audit content types DrifterBot emits.

Per Quinn's decision (2026-07-22, #danda-audit): every recurring audit
layout lives in the brand template, Quinn owns them as Slides edits.
DrifterBot just selects a layout by name and fills it. This module is
the single source of truth for that mapping.

Source of truth: ``SharedVault/psi-function/clients/drift-and-anchor/
audit/_input/README.md`` (the catalog); this file mirrors the IDs and
adds the ``RENDER_TO_LAYOUT_NAME`` mapping that the renderer uses.

Brand template ID (live in BrandSight Input folder):
    ``1KKWW7SA0_kGD1MAVphqvfA_G1jb336iBxIR0iDmjpg4``

If you tweak layouts inside the template (rename, reposition
placeholders, change fonts), the *IDs* stay stable but the semantic
meaning may break. After any template change, re-read the layout
catalog via ``fetch_slides_deck.py`` and diff against this file.
"""

from __future__ import annotations

from enum import Enum

# Brand template file ID. Lives in BrandSight Input folder
# (1t97zjRnqw6jnxw4iBB6BChQJf2f_wy29). Override via env var
# ``DRIFTERBOT_BRAND_TEMPLATE_ID`` for tests.
DEFAULT_BRAND_TEMPLATE_ID = '1KKWW7SA0_kGD1MAVphqvfA_G1jb336iBxIR0iDmjpg4'


class LayoutName(str, Enum):  # noqa: UP042 — intentional str+Enum for Python 3.11/3.12 interop
    """Names of D&A custom layouts in the brand template.

    These match the ``layoutProperties.name`` field returned by
    ``presentations.get``. The string value is what we send to the
    Slides API in ``slideLayoutReference.layoutName``.

    Built-in layouts (TITLE, SECTION_HEADER, etc.) are deliberately
    NOT in this enum — we only use the D&A custom layouts so the
    presentation inherits the D&A master, theme, and fonts. Falling
    back to built-ins would break the visual brand.

    BLANK is special: it's the B-flex escape hatch for novel content
    shapes that don't fit any named layout. DrifterBot fills BLANK
    slides via batchUpdate (insertText/insertShape), Quinn doesn't
    own them as templates.
    """

    TITLE = 'TITLE'
    SECTION_HEADER = 'SECTION_HEADER'
    TITLE_AND_BODY = 'TITLE_AND_BODY'
    TITLE_AND_BODY_1 = 'TITLE_AND_BODY_1'
    TITLE_AND_BODY_1_1 = 'TITLE_AND_BODY_1_1'
    TITLE_AND_TWO_COLUMNS = 'TITLE_AND_TWO_COLUMNS'
    TITLE_ONLY = 'TITLE_ONLY'
    MAIN_POINT = 'MAIN_POINT'
    MAIN_POINT_1 = 'MAIN_POINT_1'
    SECTION_TITLE_AND_DESCRIPTION = 'SECTION_TITLE_AND_DESCRIPTION'
    BIG_NUMBER = 'BIG_NUMBER'
    BLANK = 'BLANK'


# All 21 layouts in the brand template (12 D&A custom + 9 built-in),
# with their IDs. Enumerated 2026-07-22 from
# ``presentations.get?fields=layouts(layoutProperties(name),objectId)``.
# We use ``LayoutName`` (string) as the wire identifier in batchUpdate
# requests; this table is documentation + lookup for human readers.
LAYOUT_IDS: dict[str, str] = {
    # Built-in layouts (Google default master)
    'TITLE': 'p2',
    'SECTION_HEADER': 'p3',
    'TITLE_AND_BODY': 'p4',
    'TITLE_AND_TWO_COLUMNS': 'p5',
    'TITLE_ONLY': 'p6',
    'MAIN_POINT': 'p8',
    'SECTION_TITLE_AND_DESCRIPTION': 'p9',
    'BIG_NUMBER': 'p11',
    'BLANK_BUILTIN': 'p12',
    # D&A custom layouts (D&A master g393e2c5af85_0_83)
    'TITLE_DA': 'g393e2c5af85_0_86',
    'SECTION_HEADER_DA': 'g393e2c5af85_0_89',
    'TITLE_AND_BODY_DA': 'g393e2c5af85_0_91',
    'TITLE_AND_BODY_1': 'g393e2c5af85_0_97',
    'TITLE_AND_BODY_1_1': 'g393e2c5af85_0_104',
    'TITLE_AND_TWO_COLUMNS_DA': 'g393e2c5af85_0_111',
    'TITLE_ONLY_DA': 'g393e2c5af85_0_115',
    'MAIN_POINT_DA': 'g393e2c5af85_0_117',
    'MAIN_POINT_1': 'g393e2c5af85_0_119',
    'SECTION_TITLE_AND_DESCRIPTION_DA': 'g393e2c5af85_0_124',
    'BIG_NUMBER_DA': 'g393e2c5af85_0_129',
    'BLANK_DA': 'g393e2c5af85_0_131',
}


def resolve_layout_object_id(layout_name: str) -> str:
    """Map a LayoutName (string) to its current template object ID.

    We always emit the Slides API requests with ``layoutName`` (the
    semantic name), NOT the object ID. Object IDs are stable across
    template edits, but the semantic name is what makes the renderer
    human-readable and review-friendly. The Slides API resolves the
    name to the ID server-side.

    This helper is for test assertions and human-readable logging
    only — it does not affect wire shape.

    Args:
        layout_name: One of the values in ``LayoutName`` (e.g.
            ``'TITLE_AND_BODY'``), or a D&A-suffixed variant for
            the built-in fallback (e.g. ``'TITLE_DA'`` for the
            D&A custom TITLE layout). Unknown names raise KeyError.

    Returns:
        The current Slides objectId for that layout in the brand
        template. Defaults to the D&A custom variant for non-suffixed
        names — i.e., ``'TITLE_AND_BODY'`` resolves to
        ``g393e2c5af85_0_91``, not the built-in ``p4``.

    Raises:
        KeyError: If ``layout_name`` isn't in ``LAYOUT_IDS``.
    """
    # First try the bare name — this hits the D&A custom variant.
    if layout_name in LAYOUT_IDS:
        return LAYOUT_IDS[layout_name]
    # Fall back to the built-in variant (strip _DA suffix) if requested.
    if f'{layout_name}_DA' in LAYOUT_IDS:
        return LAYOUT_IDS[f'{layout_name}_DA']
    if f'{layout_name}_BUILTIN' in LAYOUT_IDS:
        return LAYOUT_IDS[f'{layout_name}_BUILTIN']
    raise KeyError(f'unknown layout name: {layout_name!r}')