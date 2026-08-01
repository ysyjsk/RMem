from __future__ import annotations

from plan_robust_memory.capacity import validate_budget_sweep


def test_same_budget_matches_all_topologies() -> None:
    validate_budget_sweep([
        {"budget_id": "B512", "plan_id": "left_deep", "B_merge": 512, "B_final": 512, "B_query": 512},
        {"budget_id": "B512", "plan_id": "canonical_balanced", "B_merge": 512, "B_final": 512, "B_query": 512},
        {"budget_id": "B1024", "plan_id": "left_deep", "B_merge": 1024, "B_final": 1024, "B_query": 1024},
    ])

