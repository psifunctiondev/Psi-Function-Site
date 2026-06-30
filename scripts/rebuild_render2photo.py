"""rebuild_render2photo.py — re-encode render2photo.svg from source images.

Reads app/static/images/products/render2photo-sources/sketch.png and
photo.jpg, base64-encodes them, and rewrites the two data: URIs inside
app/static/images/products/render2photo.svg.

Run after editing the source files:

    python scripts/rebuild_render2photo.py

No external dependencies (Python stdlib only). The SVG's SMIL animation
tags and timing are preserved verbatim — this script only swaps the
binary blobs.

Why this script exists: the SVG is the production asset that ships to
the browser, but the editable source-of-truth lives in the
render2photo-sources/ folder. Editing the SVG directly to swap images
requires manual base64 encoding, which is error-prone. This script
makes the swap one command.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "app" / "static" / "images" / "products" / "render2photo-sources"
SVG_PATH = REPO_ROOT / "app" / "static" / "images" / "products" / "render2photo.svg"

# The SVG has exactly two data URIs in this order:
#   index 0 -> sketch (PNG)
#   index 1 -> photo  (JPEG)
SOURCES: list[tuple[str, str]] = [
    ("sketch.png", "image/png"),
    ("photo.jpg", "image/jpeg"),
]


def main() -> int:
    svg = SVG_PATH.read_text(encoding="utf-8")
    original_size = len(svg)

    for filename, mime in SOURCES:
        source_path = SOURCES_DIR / filename
        if not source_path.exists():
            print(f"  MISSING: {source_path}")
            return 1
        raw = source_path.read_bytes()
        encoded = base64.b64encode(raw).decode("ascii")
        # Match the full data URI (everything between the opening quote
        # after xlink:href="data:image/...;base64, and the closing quote).
        pattern = re.compile(
            r'xlink:href="data:' + re.escape(mime) + r';base64,[^"]+"'
        )
        replacement = f'xlink:href="data:{mime};base64,{encoded}"'
        svg, n = pattern.subn(replacement, svg)
        if n != 1:
            print(f"  expected 1 match for {mime}, found {n}")
            return 1
        print(f"  rewrote {filename} ({len(raw)} bytes -> {len(encoded)} b64 chars)")

    SVG_PATH.write_text(svg, encoding="utf-8")
    new_size = len(svg)
    print(f"  SVG: {original_size:,} -> {new_size:,} bytes ({new_size - original_size:+d})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())