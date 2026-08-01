from __future__ import annotations

from plan_robust_memory.evaluator import judge_repeatability_passes, repeatability_metrics


def test_judge_repeatability_thresholds() -> None:
    rows = [{"case_id": f"c{i}", "label": 1, "parse_success": True} for i in range(50) for _ in range(3)]
    metrics = repeatability_metrics(rows)
    assert metrics == {"unanimity_rate": 1.0, "pairwise_flip_rate": 0.0, "parse_success_rate": 1.0}
    assert judge_repeatability_passes(rows)

