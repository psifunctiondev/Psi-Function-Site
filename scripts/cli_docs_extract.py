#!/usr/bin/env python3
"""Extract (command-path, option-list) pairs from app/cli.py and README.md.

Reads two paths as sys.argv[1] and sys.argv[2], prints one TSV line per
command. Used by cli_docs_check.sh — kept separate so bash heredoc nesting
doesn't have to deal with backticks or quotes.

Output columns: <command-path>\\t<space-separated-options>
"""

import re
import sys
from pathlib import Path


def extract_cli(path: Path) -> list[tuple[str, list[str]]]:
    """Walk app/cli.py linearly. Click commands in this codebase put
    `@click.option(...)` decorators AFTER `@xxx_cli.command(...)`, so we
    track the most recent command and accumulate options until the next
    command boundary or a non-option line.

    Handles both single-line (`@click.option('--foo', ...)`) and multi-line
    (`@click.option(\n    '--foo', ...\n)`) decorator forms by joining lines
    until the matching close paren."""
    text = path.read_text()
    lines = text.splitlines()

    results: list[tuple[str, list[str]]] = []
    current: str | None = None  # None means no open command
    current_opts: list[str] = []

    # Regex for an option name inside a @click.option(...) block, either
    # single-line or one of multiple on separate lines.
    opt_name_re = re.compile(r"'(--[^']+)'")

    def flush():
        nonlocal current, current_opts
        if current is not None:
            results.append((current, list(current_opts)))
            current = None
            current_opts = []

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        # @click.option line — may be single-line or multi-line. If the
        # line ends with `(` or has unbalanced parens, join subsequent lines
        # until the close paren.
        if stripped.startswith("@click.option"):
            block_lines = [stripped]
            # Count parens. If unbalanced, keep appending lines.
            depth = block_lines[0].count("(") - block_lines[0].count(")")
            while depth > 0 and i + 1 < len(lines):
                i += 1
                block_lines.append(lines[i].strip())
                depth += block_lines[-1].count("(") - block_lines[-1].count(")")
            block = " ".join(block_lines)
            if current is not None:
                for m in opt_name_re.finditer(block):
                    current_opts.append(m.group(1))
            i += 1
            continue

        # @click.group line — clear pending
        if re.match(r"@click\.group\('([^']+)'\)", stripped):
            flush()
            i += 1
            continue

        # @xxx_cli.command('cmd') line — finalize previous, start new
        cm = re.match(r"@(\w+)_cli\.command\('([^']+)'\)", stripped)
        if cm:
            flush()
            current = f"flask {cm.group(1)} {cm.group(2)}"
            current_opts = []
            i += 1
            continue

        # @click.command('cmd') line — finalize previous, start new (top-level)
        tm = re.match(r"@click\.command\('([^']+)'\)", stripped)
        if tm:
            flush()
            current = f"flask {tm.group(1)}"
            current_opts = []
            i += 1
            continue

        # Any other line (def, @with_appcontext, blank, comment) — close
        # the current command.
        flush()
        i += 1

    # Close any trailing command
    flush()

    return results


def extract_readme(path: Path) -> list[tuple[str, list[str]]]:
    """Walk README.md linearly. Each `^#### `flask <path>`` heading opens a
    command block; the immediately-following Markdown table (if any) lists
    its options in the first column. The block ends at the next heading or
    end-of-file — whichever comes first — so a heading without an Options
    table doesn't accidentally pick up the *next* command's options."""
    text = path.read_text()
    lines = text.splitlines()

    # Pre-compute heading line indices for fast boundary detection.
    heading_re = re.compile(r"^#### `(flask [^`]+)`")
    heading_indices = [i for i, ln in enumerate(lines) if heading_re.match(ln)]

    results: list[tuple[str, list[str]]] = []
    for k, i in enumerate(heading_indices):
        cmd_path = heading_re.match(lines[i]).group(1)
        # Block ends at the next heading (exclusive) or EOF.
        end = heading_indices[k + 1] if k + 1 < len(heading_indices) else len(lines)
        opts: list[str] = []
        j = i + 1
        in_table = False
        while j < end:
            tl = lines[j].strip()
            if not tl.startswith("|"):
                if in_table:
                    break
                j += 1
                continue
            cells = [c.strip() for c in tl.strip("|").split("|")]
            if not in_table:
                if cells and cells[0] == "Option":
                    in_table = True
                j += 1
                continue
            if all(set(c) <= set("-: ") for c in cells):
                j += 1
                continue
            first = cells[0].strip("`").strip()
            if first.startswith("--"):
                opts.append(first)
            j += 1
        results.append((cmd_path, opts))
    return results


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: cli_docs_extract.py <cli.py> <readme.md>", file=sys.stderr)
        sys.exit(2)
    cli_path = Path(sys.argv[1])
    rm_path = Path(sys.argv[2])

    for path, opts in extract_cli(cli_path):
        print(f"{path}\t{' '.join(opts)}")
    # Separator so the bash caller can split the two sections cleanly.
    print("---README---")
    for path, opts in extract_readme(rm_path):
        print(f"{path}\t{' '.join(opts)}")


if __name__ == "__main__":
    main()