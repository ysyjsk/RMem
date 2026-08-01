from __future__ import annotations

from plan_robust_memory.capacity import validate_leaf_cache_shared


def test_budget_change_does_not_change_leaf_hash() -> None:
    rows = [
        {"episode_id": "ep", "backbone_id": "primary", "k": 8, "leaf_index": 0, "budget_id": "B512", "plan_id": "left_deep", "leaf_sha256": "a"},
        {"episode_id": "ep", "backbone_id": "primary", "k": 8, "leaf_index": 0, "budget_id": "B1024", "plan_id": "canonical_balanced", "leaf_sha256": "a"},
    ]
    validate_leaf_cache_shared(rows)

