from __future__ import annotations

from copy import deepcopy

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.evaluator import (
    JUDGE_REPEATABILITY_CATEGORY_COUNTS,
    judge_repeatability_passes,
    project_judge_prompt,
    repeatability_metrics,
    parse_project_judge_json_label,
)


def _rows() -> list[dict]:
    rows: list[dict] = []
    case_index = 0
    for category, count in JUDGE_REPEATABILITY_CATEGORY_COUNTS.items():
        for _ in range(count):
            for replicate_id in range(3):
                rows.append(
                    {
                        "case_id": f"case-{case_index:02d}",
                        "case_category": category,
                        "replicate_id": replicate_id,
                        "label": 1,
                        "parse_success": True,
                    }
                )
            case_index += 1
    return rows


def test_judge_repeatability_requires_exact_frozen_shape_and_thresholds() -> None:
    rows = _rows()
    metrics = repeatability_metrics(rows)
    assert metrics == {
        "case_count": 50,
        "observation_count": 150,
        "replicates_per_case": 3,
        "unanimity_rate": 1.0,
        "pairwise_flip_rate": 0.0,
        "parse_success_rate": 1.0,
    }
    assert judge_repeatability_passes(rows)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda rows: [], "exactly 150"),
        (lambda rows: rows[:-1], "exactly 150"),
        (
            lambda rows: [*rows[:-1], deepcopy(rows[0])],
            "duplicate case_id/replicate_id",
        ),
        (
            lambda rows: [{**row, "replicate_id": 3} if row is rows[0] else row for row in rows],
            "replicate_id",
        ),
        (
            lambda rows: [{key: value for key, value in row.items() if key != "case_id"} if row is rows[0] else row for row in rows],
            "case_id",
        ),
        (
            lambda rows: [{**row, "label": 7} if row is rows[0] else row for row in rows],
            "label",
        ),
        (
            lambda rows: [{**row, "label": True} if row is rows[0] else row for row in rows],
            "label",
        ),
        (
            lambda rows: [{**row, "parse_success": "yes"} if row is rows[0] else row for row in rows],
            "parse_success",
        ),
        (
            lambda rows: [{**row, "case_category": "unknown"} if row is rows[0] else row for row in rows],
            "case_category",
        ),
        (
            lambda rows: [
                {**row, "case_category": "gold_equivalent"}
                if row["case_category"] == "abstention_like"
                else row
                for row in rows
            ],
            "category coverage",
        ),
    ],
)
def test_repeatability_metrics_fail_closed_on_malformed_observations(
    mutate,
    message: str,
) -> None:
    rows = _rows()
    with pytest.raises(ContractError, match=message):
        repeatability_metrics(mutate(rows))


def test_parse_failure_is_a_valid_observation_but_fails_the_gate() -> None:
    rows = _rows()
    rows[0]["parse_success"] = False
    rows[0]["label"] = None
    metrics = repeatability_metrics(rows)
    assert metrics["parse_success_rate"] == pytest.approx(149 / 150)
    assert not judge_repeatability_passes(rows)


def test_repeatability_metrics_reject_category_quota_drift_even_with_full_coverage() -> None:
    rows = _rows()
    case_id = next(
        row["case_id"] for row in rows if row["case_category"] == "gold_equivalent"
    )
    for row in rows:
        if row["case_id"] == case_id:
            row["case_category"] = "clearly_wrong"
    with pytest.raises(ContractError, match="category quotas"):
        repeatability_metrics(rows)


def test_project_json_parser_rejects_duplicate_label_keys() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        parse_project_judge_json_label('{"label":0,"label":1}')


def test_project_prompt_preserves_task_semantics_but_requires_strict_json() -> None:
    prompt = project_judge_prompt(
        "temporal-reasoning",
        "How many days elapsed?",
        "18 days",
        "19 days",
    )
    assert "do not penalize off-by-one errors" in prompt
    assert "Answer yes or no only" not in prompt
    assert '{"label":1}' in prompt
    assert '{"label":0}' in prompt

    update_prompt = project_judge_prompt(
        "knowledge-update",
        "What is the latest value?",
        "new value",
        "old value and new value",
    )
    assert "previous information along with an updated answer" in update_prompt
