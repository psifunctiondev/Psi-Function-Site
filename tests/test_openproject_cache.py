"""Unit tests for the OpenProject read cache.

A small in-process memoization layer for read calls into the OpenProject
client. Per the 2026-04-24 spec §"Caching strategy":

* TTL: 60 seconds, keyed by ``(project_id, filter_fingerprint)``.
* Invalidation: any successful write for a ``project_id`` clears ALL
  cached entries whose first tuple element equals that project_id.

This is a deliberately small module — no Redis yet. A module-level dict
protected by a threading.Lock is enough for the per-process Flask
runtime. Tests verify the contract; production code uses the module's
public functions ``op_cache_get``, ``op_cache_set``, ``op_cache_invalidate``.

Note: the cache stores the project_id as the first tuple element so
``invalidate(project_id)`` can scan-and-delete without needing the
fingerprint (writes happen without knowing what read keys exist).
"""

from __future__ import annotations

import time
from unittest import mock

import pytest

from app.services.openproject_cache import (
    cache_get,
    cache_set,
    cache_invalidate,
    fingerprint,
    reset_cache_for_tests,
    TTL_SECONDS,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    """Each test starts with an empty cache and the same TTL baseline."""
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()


def test_fingerprint_stable_for_same_inputs():
    """Same project + same filter dict => same fingerprint string."""
    fp1 = fingerprint(42, {"types": ["User story"], "statuses": ["New"]})
    fp2 = fingerprint(42, {"types": ["User story"], "statuses": ["New"]})
    assert fp1 == fp2
    assert isinstance(fp1, str)


def test_fingerprint_changes_with_project_id():
    """Different project => different fingerprint."""
    fp1 = fingerprint(42, {"types": ["User story"]})
    fp2 = fingerprint(43, {"types": ["User story"]})
    assert fp1 != fp2


def test_fingerprint_changes_with_filter_dict():
    """Different filter content => different fingerprint."""
    fp1 = fingerprint(42, {"types": ["User story"]})
    fp2 = fingerprint(42, {"types": ["Task"]})
    assert fp1 != fp2


def test_fingerprint_insensitive_to_dict_key_order():
    """Filter dicts with same items in different insertion order should
    produce the same fingerprint — callers must not get cache misses
    because they built their filter dict in a different order."""
    fp1 = fingerprint(42, {"a": 1, "b": 2})
    fp2 = fingerprint(42, {"b": 2, "a": 1})
    assert fp1 == fp2


def test_cache_set_then_get_returns_value():
    cache_set(42, "fp1", {"data": "value1"})
    assert cache_get(42, "fp1") == {"data": "value1"}


def test_cache_get_returns_none_when_unset():
    assert cache_get(42, "missing") is None


def test_cache_get_returns_none_after_ttl_expires():
    """TTL is 60 seconds; tests fast-forward the clock.

    The cache uses ``time.monotonic`` for TTL bookkeeping (immune to
    wall-clock NTP jumps), so this test patches ``time.monotonic``.
    """
    cache_set(42, "fp1", "value")
    # Move "now" past the TTL window.
    with mock.patch.object(time, "monotonic", return_value=time.monotonic() + TTL_SECONDS + 1):
        assert cache_get(42, "fp1") is None


def test_cache_get_returns_value_within_ttl():
    """Within the TTL window, the cached value is returned."""
    cache_set(42, "fp1", "value")
    with mock.patch.object(time, "monotonic", return_value=time.monotonic() + TTL_SECONDS - 5):
        assert cache_get(42, "fp1") == "value"


def test_cache_invalidate_clears_all_entries_for_project():
    """Invalidating project 42 must clear every fingerprint under it."""
    cache_set(42, "fp1", "v1")
    cache_set(42, "fp2", "v2")
    cache_set(43, "fp1", "v3")  # different project — must survive
    cache_invalidate(42)
    assert cache_get(42, "fp1") is None
    assert cache_get(42, "fp2") is None
    # project 43 untouched
    assert cache_get(43, "fp1") == "v3"


def test_cache_invalidate_no_op_when_project_unknown():
    """Invalidating a project with no cached entries must not raise."""
    cache_invalidate(999)  # no prior writes — should be silent


def test_cache_separates_projects_under_same_fingerprint():
    """Same fingerprint string under different project_ids must not collide."""
    cache_set(1, "shared-fp", "value-for-1")
    cache_set(2, "shared-fp", "value-for-2")
    assert cache_get(1, "shared-fp") == "value-for-1"
    assert cache_get(2, "shared-fp") == "value-for-2"


def test_cache_overwrites_existing_key():
    """A second ``cache_set`` for the same (project, fingerprint) replaces
    the prior value."""
    cache_set(42, "fp1", "old")
    cache_set(42, "fp1", "new")
    assert cache_get(42, "fp1") == "new"


def test_ttl_constant_is_60_seconds():
    """Per the spec: 60-second TTL. Pin this so a casual change is loud."""
    assert TTL_SECONDS == 60
