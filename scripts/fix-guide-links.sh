#!/usr/bin/env bash
# Fix broken internal links in the TruView guide built HTML.
# These are pre-existing bugs in the MkDocs source content.
set -euo pipefail

GUIDE_DIR="${1:?Usage: $0 /path/to/truview/guide/dir}"

echo "Fixing broken links in: $GUIDE_DIR"

# --- working/viewing/inoffice/index.html ---
# Links go up 3 levels (../../../) but should only go up 2 (../../)
# From working/viewing/inoffice/, ../../../ = root, but creating/ is under working/
FILE="$GUIDE_DIR/working/viewing/inoffice/index.html"
if [ -f "$FILE" ]; then
    sed -i \
        -e 's|href="../../../creating/|href="../../creating/|g' \
        -e 's|href="../../../navigation/|href="../../navigation/|g' \
        -e 's|href="../../usage/settings|href="../../../usage/settings|g' \
        "$FILE"
    echo "Fixed: working/viewing/inoffice/index.html"
fi

# --- working/viewing/offsite/index.html ---
# ../creating.md should be ../../creating/standalone/ (or similar)
# ../creating/ should be ../../creating/
FILE="$GUIDE_DIR/working/viewing/offsite/index.html"
if [ -f "$FILE" ]; then
    sed -i \
        -e 's|href="../creating\.md"|href="../../creating/standalone/"|g' \
        -e 's|href="../creating/#pre-assigned-viewpoint"|href="../../creating/standalone/#pre-assigned-viewpoint"|g' \
        "$FILE"
    echo "Fixed: working/viewing/offsite/index.html"
fi

# --- working/checklist/index.html ---
# ../creating/ exists but has no index.html — should point to standalone/
FILE="$GUIDE_DIR/working/checklist/index.html"
if [ -f "$FILE" ]; then
    sed -i \
        's|href="../creating/#standalone-enscape-file"|href="../creating/standalone/"|g' \
        "$FILE"
    echo "Fixed: working/checklist/index.html"
fi

echo ""
echo "Done. Run the link checker again to verify."
