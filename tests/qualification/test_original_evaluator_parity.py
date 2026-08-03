from __future__ import annotations

import hashlib

import pytest

from plan_robust_memory.evaluator import (
    exact_match_score,
    longmemeval_judge_prompt,
    parse_longmemeval_judge_label,
    parse_project_judge_json_label,
    substring_exact_match_score,
)


def test_original_evaluator_exact_match_parity() -> None:
    assert exact_match_score("Answer", " answer ") == 1
    assert exact_match_score("Answer", "different") == 0


def test_memoryagentbench_substring_exact_match_candidate_contains_gold() -> None:
    assert substring_exact_match_score("Paris", "The answer is Paris.") == 1
    assert substring_exact_match_score("Paris", "The answer is Lyon.") == 0


def test_memoryagentbench_substring_exact_match_accepts_multiple_gold_answers() -> None:
    assert substring_exact_match_score(("Madrid", "Paris"), "Final answer: paris") == 1
    assert substring_exact_match_score(("Madrid", "Paris"), "Final answer: Berlin") == 0


@pytest.mark.parametrize(
    "reference,candidate,expected",
    [
        ("quick brown fox", "The quick, brown fox!", 1),
        ("the quick brown fox", "quick brown fox", 1),
        ("C++", "c", 1),
        ("answer", "", 0),
        ("The answer", "answer", 1),
    ],
)
def test_memoryagentbench_official_drqa_normalization_cases(
    reference: str, candidate: str, expected: int
) -> None:
    assert exact_match_score(reference, candidate) == expected


def test_memoryagentbench_official_substring_direction_and_nested_answers() -> None:
    assert substring_exact_match_score("Paris", "The answer is Paris.") == 1
    assert substring_exact_match_score("The answer is Paris", "Paris") == 0
    assert substring_exact_match_score([["Madrid"], ["Paris"]], "Final answer: paris") == 1


def test_longmemeval_prompt_is_task_specific_and_officially_worded() -> None:
    prompt = longmemeval_judge_prompt(
        "knowledge-update", "What changed?", "Paris", "Paris now"
    )
    assert "updated answer" in prompt
    assert "Answer yes or no only." in prompt
    assert "Correct Answer: Paris" in prompt

    temporal = longmemeval_judge_prompt(
        "temporal-reasoning", "How many days?", "18", "19"
    )
    assert "off-by-one errors" in temporal


def test_judge_parsers_keep_official_and_project_contracts_distinct() -> None:
    assert parse_longmemeval_judge_label("YES") is True
    assert parse_longmemeval_judge_label("No") is False
    assert parse_project_judge_json_label('{"label": 1}') == 1
    assert parse_project_judge_json_label('{"label": 0}') == 0
    with pytest.raises(ValueError):
        parse_project_judge_json_label("yes")


@pytest.mark.parametrize(
    "task,abstention,expected_sha256",
    [
        ("single-session-user", False, "c973231683d914de5192e37a06cbd1ba0d16c3c5dad99d9fb1242708b6a624d6"),
        ("temporal-reasoning", False, "68eece862c1e5d18c997191d6dd816a9f56e5ec3b8d04502df332fa71fdb6484"),
        ("knowledge-update", False, "992fa870a148dc7958741db4e4d9590f0947b17e1516ecd8b6c6424fd38c6747"),
        ("single-session-preference", False, "cac49761fd13dbf5e46b602c9a23867a4c96ad11729ebeb1f9846f85aa2bd15b"),
        ("knowledge-update", True, "879152708d282cd7102c4a39182451ec48da2bd424d2e29cea52fbf045b59593"),
    ],
)
def test_longmemeval_prompt_hashes_match_pinned_official_source(
    task: str, abstention: bool, expected_sha256: str
) -> None:
    prompt = longmemeval_judge_prompt(task, "Q", "A", "R", abstention=abstention)
    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() == expected_sha256
