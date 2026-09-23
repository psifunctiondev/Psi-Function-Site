"""OpenProject read-cache layer.

Per the 2026-04-24 spec §"Caching strategy" / "Read cache":

* 60-second TTL, keyed by ``(project_id, filter_fingerprint)``.
* Invalidation: any successful write for a ``project_id`` clears ALL
  cached entries whose first tuple element equals that ``project_id``.

Deliberately small and stdlib-only — no Redis yet. A module-level dict
protected by a ``threading.Lock`` is enough for the per-process Flask
runtime. Per the spec: "Flask-side, use a small module-level dict with
a lock; or cachetools.TTLCache. No Redis yet."

Public API:
    fingerprint(project_id, filter_dict) -> str
        Stable string fingerprint of a (project, filter) pair, used as
        the cache key suffix. Insensitive to dict key insertion order.

    cache_get(project_id, fp) -> Any | None
        Return the cached value if present and within TTL, else None.

    cache_set(project_id, fp, value) -> None
        Store ``value`` under (project_id, fp). Replaces prior entry.

    cache_invalidate(project_id) -> None
        Delete every cached entry whose project_id equals the argument.
        Called after every successful write for that project, per spec.

    reset_cache_for_tests() -> None
        Empty the cache. Autouse fixture in tests uses this to isolate
        each test from the previous.

    TTL_SECONDS: int
        Exported so tests can pin it and operators can inspect it.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

# Per spec: 60 seconds. Pinned in tests.
TTL_SECONDS = 60

# Cache layout: dict[(project_id, fp)] = (value, expires_at_monotonic).
# ``expires_at_monotonic`` is a ``time.monotonic()`` float so tests can
# fast-forward the clock with ``mock.patch.object(time, "time", ...)``.
_cache: dict[tuple[int, str], tuple[Any, float]] = {}

# Module-level lock — Flask requests run in worker threads (gunicorn
# default), so the dict needs guarding even though CPython's GIL keeps
# individual dict ops atomic.
_lock = threading.Lock()


def fingerprint(project_id: int, filter_dict: dict | None) -> str:
    """Return a stable fingerprint for a (project, filter) pair.

    Two filter dicts with the same items in different insertion order
    produce the same fingerprint — ``sort_keys=True`` ensures this.
    Filters are JSON-serialized and hashed so callers can pass nested
    dicts and lists without caring about equality semantics.
    """
    canonical = json.dumps(
        filter_dict or {}, sort_keys=True, separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{project_id}:{digest[:16]}"


def cache_get(project_id: int, fp: str) -> Any | None:
    """Return the cached value if present and within TTL, else None."""
    now = time.monotonic()
    key = (project_id, fp)
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if now >= expires_at:
            _cache.pop(key, None)
            return None
        return value


def cache_set(project_id: int, fp: str, value: Any) -> None:
    """Store ``value`` under (project_id, fp) for TTL_SECONDS."""
    expires_at = time.monotonic() + TTL_SECONDS
    key = (project_id, fp)
    with _lock:
        _cache[key] = (value, expires_at)


def cache_invalidate(project_id: int) -> None:
    """Delete every cached entry whose project_id equals ``project_id``.

    Called after every successful write for that project, per the
    spec's "Invalidated immediately after any successful write for
    that project (delete the key)" rule. Since the cache key is
    ``(project_id, fp)`` and a write doesn't know which fingerprints
    are in flight, the safe move is to drop them all for the project.
    """
    with _lock:
        stale = [k for k in _cache if k[0] == project_id]
        for k in stale:
            _cache.pop(k, None)


def reset_cache_for_tests() -> None:
    """Empty the cache. Test-only — production code never calls this."""
    with _lock:
        _cache.clear()
