from __future__ import annotations

from plan_robust_memory.hashing import stable_hash


def test_stable_hash_is_order_independent_for_dict_keys() -> None:
    assert stable_hash({"b": 2, "a": 1}) == stable_hash({"a": 1, "b": 2})


def test_stable_hash_changes_with_content() -> None:
    assert stable_hash({"a": 1}) != stable_hash({"a": 2})

