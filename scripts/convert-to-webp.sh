#!/usr/bin/env bash
# Convert PNG/JPG/JPEG images to WebP and update all references.
# Usage: ./scripts/convert-to-webp.sh /path/to/mkdocs-project/docs
#
# Requires: cwebp (apt install webp)
# - Converts all .png, .jpg, .jpeg in the target directory tree
# - Updates references in .md, .html, .css files
# - Keeps originals in a backup directory (can delete after verification)

set -euo pipefail

TARGET_DIR="${1:?Usage: $0 /path/to/docs-directory}"
BACKUP_DIR="${TARGET_DIR}/../_originals_backup"
QUALITY=85  # WebP quality (80-90 is good for screenshots)

if ! command -v cwebp &>/dev/null; then
    echo "ERROR: cwebp not found. Install with: sudo apt install webp"
    exit 1
fi

if [ ! -d "$TARGET_DIR" ]; then
    echo "ERROR: Directory not found: $TARGET_DIR"
    exit 1
fi

mkdir -p "$BACKUP_DIR"

converted=0
skipped=0
total_before=0
total_after=0

echo "Converting images in: $TARGET_DIR"
echo "Quality: $QUALITY"
echo "Backup dir: $BACKUP_DIR"
echo ""

# Find all PNG, JPG, JPEG files (case-insensitive)
while IFS= read -r -d '' img; do
    # Get relative path from target dir
    rel_path="${img#"$TARGET_DIR"/}"
    ext="${img##*.}"
    ext_lower=$(echo "$ext" | tr '[:upper:]' '[:lower:]')
    base="${img%.*}"
    webp_path="${base}.webp"

    # Skip if webp already exists
    if [ -f "$webp_path" ]; then
        echo "SKIP (webp exists): $rel_path"
        ((skipped++)) || true
        continue
    fi

    # Get original size
    orig_size=$(stat -c%s "$img" 2>/dev/null || stat -f%z "$img" 2>/dev/null)
    ((total_before += orig_size)) || true

    # Convert
    if cwebp -q "$QUALITY" "$img" -o "$webp_path" -quiet 2>/dev/null; then
        new_size=$(stat -c%s "$webp_path" 2>/dev/null || stat -f%z "$webp_path" 2>/dev/null)
        ((total_after += new_size)) || true
        savings=$(( (orig_size - new_size) * 100 / (orig_size + 1) ))

        echo "OK: $rel_path ($orig_size → $new_size bytes, ${savings}% smaller)"

        # Backup original
        backup_path="$BACKUP_DIR/$rel_path"
        mkdir -p "$(dirname "$backup_path")"
        cp "$img" "$backup_path"

        ((converted++)) || true
    else
        echo "FAIL: $rel_path (cwebp error, keeping original)"
        ((skipped++)) || true
    fi
done < <(find "$TARGET_DIR" -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) -print0)

echo ""
echo "=== Conversion complete ==="
echo "Converted: $converted files"
echo "Skipped: $skipped files"
if [ "$converted" -gt 0 ]; then
    echo "Before: $((total_before / 1024 / 1024))MB"
    echo "After: $((total_after / 1024 / 1024))MB"
fi

# Now update references in source files
echo ""
echo "=== Updating references ==="

# Build sed commands for each extension
update_count=0
for ext in png jpg jpeg PNG JPG JPEG; do
    # Update .md, .html, .css files
    while IFS= read -r -d '' src_file; do
        if grep -q "\.${ext}" "$src_file" 2>/dev/null; then
            sed -i "s/\.${ext}/.webp/g" "$src_file"
            echo "Updated refs in: ${src_file#"$TARGET_DIR"/}"
            ((update_count++)) || true
        fi
    done < <(find "$TARGET_DIR" -type f \( -name '*.md' -o -name '*.html' -o -name '*.css' \) -print0)
done

echo "Updated $update_count file(s)"
echo ""
echo "=== Next steps ==="
echo "1. Review changes: git diff (in the docs directory)"
echo "2. Rebuild MkDocs: cd $(dirname "$TARGET_DIR") && mkdocs build"
echo "3. If everything looks good, delete originals: rm -rf $BACKUP_DIR"
echo "4. Delete the old PNG/JPG files: find $TARGET_DIR -type f \\( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \\) -delete"
