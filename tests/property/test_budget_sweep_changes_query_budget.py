from __future__ import annotations

from plan_robust_memory.capacity import validate_budget_sweep


def test_budget_sweep_changes_query_budget() -> None:
    validate_budget_sweep([
        {"budget_id": "B512", "B_merge": 512, "B_final": 512, "B_query": 512},
        {"budget_id": "B1024", "B_merge": 1024, "B_final": 1024, "B_query": 1024},
    ])

