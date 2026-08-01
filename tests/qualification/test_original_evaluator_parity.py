from __future__ import annotations

from plan_robust_memory.evaluator import exact_match_score


def test_original_evaluator_exact_match_parity() -> None:
    assert exact_match_score("Answer", " answer ") == 1
    assert exact_match_score("Answer", "different") == 0

