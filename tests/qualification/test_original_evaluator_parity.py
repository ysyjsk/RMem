from __future__ import annotations

from plan_robust_memory.evaluator import exact_match_score, substring_exact_match_score


def test_original_evaluator_exact_match_parity() -> None:
    assert exact_match_score("Answer", " answer ") == 1
    assert exact_match_score("Answer", "different") == 0


def test_memoryagentbench_substring_exact_match_candidate_contains_gold() -> None:
    assert substring_exact_match_score("Paris", "The answer is Paris.") == 1
    assert substring_exact_match_score("Paris", "The answer is Lyon.") == 0


def test_memoryagentbench_substring_exact_match_accepts_multiple_gold_answers() -> None:
    assert substring_exact_match_score(("Madrid", "Paris"), "Final answer: paris") == 1
    assert substring_exact_match_score(("Madrid", "Paris"), "Final answer: Berlin") == 0
