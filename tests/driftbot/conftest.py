"""Path C (2026-07-16) — DrifterBot tests live under tests/driftbot/ but
import from agents.driftbot.* (which lives at the repo root). Add the
repo root to sys.path so the `agents` package is importable without
having to register it in the editable install's package map.

The repo root is two parents up from this file:
    tests/driftbot/conftest.py
    → tests/driftbot/
    → tests/
    → Psi-Function-Site/   ← repo root, insert into sys.path
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))