# render2photo source assets

These are the two source images embedded (as base64) inside
`../render2photo.svg`. The SVG is the production asset that gets loaded
on the Products page; these PNG and JPEG files are the editable
source-of-truth.

## Why this folder exists

`render2photo.svg` is a self-contained animated SVG with the two source
images embedded inline as base64 (`<image xlink:href="data:image/...">`).
Embedding keeps the SVG portable: when the browser loads the SVG via
`<img src>`, no external requests are needed and the crossfade animation
plays immediately.

The cost is asset weight — the SVG runs ~81KB, mostly because the two
source images together total ~60KB before base64 expansion. This is
acceptable for a single hero asset on the Products page but not
something we want to keep growing.

## What the next rebuild should do

When this asset gets redesigned (Quinn's note: "i'm sure it will evolve
soon anyway"), the natural progression is:

1. **Edit these source files** (`sketch.png` and `photo.jpg`) — drop in
   new renders / photos.
2. **Re-encode the SVG** — replace the two `data:image/...` URIs inside
   `../render2photo.svg` with fresh base64 from the updated sources.

A helper script for step 2 is at `scripts/rebuild_render2photo.py` (in
the repo root). Run it after editing the sources and the SVG is
regenerated in place.

## Future slim paths (not done yet)

Tools that would actually shrink the SVG meaningfully:

- `pngquant` — palette-reduce `sketch.png` to 256 colors. Realistic 2-3x
  reduction on this line-art-with-flat-fill source.
- `jpegoptim` / `mozjpeg` — re-encode `photo.jpg` at quality 80-85 with
  progressive scan. Realistic ~30-40% reduction.
- `svgo` — minify the SVG itself (whitespace, redundant attributes).
  Saves a few KB on the markup.

None of these are installed in the workspace as of 2026-06-30. The
"rebuild" intent recorded in `feat/products` commit history is to make
source files first-class repo assets so the slim path is one script run
away once the tools land.