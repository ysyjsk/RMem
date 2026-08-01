from __future__ import annotations

from plan_robust_memory.metrics import sum_lifecycle_cost


def test_missing_cost_is_unknown_not_zero() -> None:
    assert sum_lifecycle_cost([{"cost": "unknown"}]) == {"C_life": "unknown"}

