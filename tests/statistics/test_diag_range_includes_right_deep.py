from __future__ import annotations

from plan_robust_memory.metrics import diagnostic_range, validate_diagnostic_plans


def test_diag_range_includes_right_deep(score_rows: list[dict]) -> None:
    validate_diagnostic_plans(("left_deep", "canonical_balanced", "right_deep"))
    assert diagnostic_range(score_rows, budget=512) == 0.75
