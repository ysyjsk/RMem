from __future__ import annotations

from plan_robust_memory.statistics import classify_null_result


def test_underpowered_null_is_inconclusive() -> None:
    assert classify_null_result(power=0.5, ci_excludes_delta_decision=True, significant=False) == "inconclusive"

