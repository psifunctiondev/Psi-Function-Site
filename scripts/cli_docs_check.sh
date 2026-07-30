#!/usr/bin/env bash
# Psi-Function-Site CLI/docs drift check
# Compares commands implemented in app/cli.py against the Administration CLI
# section of README.md. Emits a Markdown report on stdout. Exits 0 always
# (the cron agent decides whether to post the report or an error).
#
# Usage:
#   ./cli_docs_check.sh            # check current main
#
# This is intentionally a plain shell script — the procedure is mechanical
# (parse app/cli.py Click decorators, parse README headings + tables, diff,
# post to Discord). Putting it in a shell script means the cron model only
# has to `exec` it once; the script does the rest deterministically.

set -euo pipefail

REPO_ROOT="/Users/doxa/.openclaw/workspace/Psi-Function-Site"
CLI_FILE="$REPO_ROOT/app/cli.py"
README_FILE="$REPO_ROOT/README.md"
EXTRACT="$REPO_ROOT/scripts/cli_docs_extract.py"

# Confirm we're on main with a clean tree; if not, report that and bail
# (cron is read-only on origin/main by contract).
cd "$REPO_ROOT"
git fetch --prune origin >/dev/null 2>&1 || true
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" != "main" ]; then
  echo "⚠️ Expected branch 'main', currently on '$CURRENT_BRANCH'. Refusing to run (cron is read-only on origin/main)."
  exit 1
fi
git pull --rebase origin main >/dev/null 2>&1 || {
  echo "⚠️ git pull --rebase origin main failed. Refusing to run; please rebase manually."
  exit 1
}

MAIN_SHA="$(git rev-parse HEAD)"

echo "📋 Psi-Function-Site CLI/docs drift — main @ ${MAIN_SHA:0:10}"
echo

# --- Extract commands + options from both sources ---------------------------
RAW="$(python3 "$EXTRACT" "$CLI_FILE" "$README_FILE")"
CLI_TSV="$(printf '%s\n' "$RAW" | sed -n '/^---README---$/!p;/^---README---$/q')"
README_TSV="$(printf '%s\n' "$RAW" | awk '/^---README---$/{flag=1;next} flag')"

CLI_COMMANDS="$(printf '%s\n' "$CLI_TSV" | cut -f1 | sort -u)"
README_COMMANDS="$(printf '%s\n' "$README_TSV" | cut -f1 | sort -u)"

# --- Diff the command sets --------------------------------------------------
UN_DOCUMENTED="$(comm -23 <(echo "$CLI_COMMANDS") <(echo "$README_COMMANDS"))"
STALE_DOCS="$(comm -13 <(echo "$CLI_COMMANDS") <(echo "$README_COMMANDS"))"

# --- Option diff (only for commands present in both) ------------------------
OPT_DIFF="$(python3 - <<PYEOF
cli_tsv = """$CLI_TSV"""
rm_tsv = """$README_TSV"""

def parse(tsv):
    out = {}
    for line in tsv.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        path = parts[0]
        opts = parts[1].split() if len(parts) > 1 and parts[1] else []
        out[path] = set(opts)
    return out

cli_opts = parse(cli_tsv)
rm_opts = parse(rm_tsv)

for path in sorted(cli_opts):
    if path not in rm_opts:
        continue
    only_cli = sorted(cli_opts[path] - rm_opts[path])
    only_rm = sorted(rm_opts[path] - cli_opts[path])
    if only_cli or only_rm:
        parts = []
        if only_cli:
            parts.append(f"only in app/cli.py: {', '.join(only_cli)}")
        if only_rm:
            parts.append(f"only in README: {', '.join(only_rm)}")
        print(f"  - {path}: " + "; ".join(parts))
PYEOF
)"

DRIFT=0

if [ -n "$UN_DOCUMENTED" ]; then
  DRIFT=1
  echo "Un-documented (in app/cli.py, missing from README):"
  echo "$UN_DOCUMENTED" | sed 's/^/  - /'
  echo
fi

if [ -n "$STALE_DOCS" ]; then
  DRIFT=1
  echo "Stale docs (in README, missing from app/cli.py):"
  echo "$STALE_DOCS" | sed 's/^/  - /'
  echo
fi

if [ -n "$OPT_DIFF" ]; then
  DRIFT=1
  echo "Option mismatches:"
  echo "$OPT_DIFF"
  echo
fi

if [ "$DRIFT" -eq 0 ]; then
  CLI_COUNT="$(echo "$CLI_COMMANDS" | wc -l | tr -d ' ')"
  echo "✅ No drift detected — $CLI_COUNT commands in app/cli.py match $CLI_COUNT documented in README."
fi