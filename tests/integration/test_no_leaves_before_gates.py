from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.gates import assert_full_leaf_generation_allowed


QUALIFICATION_SEQUENCE = [
    "observability_freeze",
    "evaluator_parity",
    "judge_repeatability",
    "cache_qualification",
    "saturation_01",
    "final_judge_budget_freeze",
    "eval_protocol_v1_0",
    "q0_d_leaf_micro_run",
]


def _passing_gate_artifacts() -> tuple[dict, dict, dict]:
    day1 = {"status": "passed"}
    data = {
        "status": "qualified",
        "audit_hash": "audit-hash",
        "counts": {"N8": 20, "primary_N8": 20},
        "no_silent_drop": True,
    }
    power = {
        "status": "passed",
        "input_audit_hash": "audit-hash",
        "split_ratio": {"development": 0.2, "calibration": 0.3, "acceptance": 0.5},
        "delta_decision": 0.075,
        "power": 0.86,
        "power_lower_95": 0.81,
        "primary_eligible_categories": ["knowledge-update", "temporal-reasoning"],
        "evidence_layout_strata": [
            {
                "question_type": "knowledge-update",
                "support_leaf_class": "single",
                "evidence_position_bin": "early",
                "count": 20,
            }
        ],
        "hard_no_go_available": True,
        "topology_results_seen": False,
    }
    return day1, data, power


def _passing_protocol_qualification() -> dict:
    return {
        "status": "passed",
        "qualification_sequence": QUALIFICATION_SEQUENCE,
        "completed_stages": QUALIFICATION_SEQUENCE,
        "protocol_tag": "eval-protocol-v1.0",
        "full_leaf_generation_allowed": True,
    }


def test_full_leaf_generation_is_blocked_until_all_three_gates_pass() -> None:
    day1 = {"status": "blocked"}
    data = {"status": "qualified_with_exclusions", "counts": {"N8": 20}}
    power = {"status": "passed", "hard_no_go_available": True}
    with pytest.raises(ContractError, match="Day 1"):
        assert_full_leaf_generation_allowed(day1, data, power)


def test_full_leaf_generation_remains_blocked_without_protocol_qualification() -> None:
    day1, data, power = _passing_gate_artifacts()
    with pytest.raises(ContractError, match="qualification"):
        assert_full_leaf_generation_allowed(day1, data, power)


def test_full_leaf_generation_can_only_open_after_ordered_qualification() -> None:
    day1, data, power = _passing_gate_artifacts()
    assert_full_leaf_generation_allowed(
        day1, data, power, _passing_protocol_qualification()
    )


def test_full_leaf_generation_rejects_reordered_qualification() -> None:
    day1, data, power = _passing_gate_artifacts()
    qualification = _passing_protocol_qualification()
    qualification["qualification_sequence"] = [
        "observability_freeze",
        "judge_repeatability",
        "evaluator_parity",
        *QUALIFICATION_SEQUENCE[3:],
    ]
    with pytest.raises(ContractError, match="entry order"):
        assert_full_leaf_generation_allowed(day1, data, power, qualification)


def test_full_leaf_generation_requires_q0_d_leaf_micro_run() -> None:
    day1, data, power = _passing_gate_artifacts()
    qualification = _passing_protocol_qualification()
    qualification["completed_stages"] = QUALIFICATION_SEQUENCE[:-1]
    qualification["full_leaf_generation_allowed"] = False
    with pytest.raises(ContractError, match="Q0/D_leaf"):
        assert_full_leaf_generation_allowed(day1, data, power, qualification)


def test_expanded_n8_cannot_substitute_for_empty_primary_e8() -> None:
    day1, data, power = _passing_gate_artifacts()
    data["counts"] = {"N8": 323, "primary_N8": 0}

    with pytest.raises(ContractError, match="primary E8"):
        assert_full_leaf_generation_allowed(day1, data, power)


def test_ambiguous_n8_without_explicit_primary_e8_fails_closed() -> None:
    day1, data, power = _passing_gate_artifacts()
    data["counts"] = {"N8": 323}

    with pytest.raises(ContractError, match="primary E8 count is missing"):
        assert_full_leaf_generation_allowed(day1, data, power)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"status": "blocked"}, "data Gate"),
        ({"no_silent_drop": False}, "no-silent-drop"),
    ],
)
def test_each_data_gate_failure_keeps_full_leaf_generation_closed(
    mutation: dict,
    message: str,
) -> None:
    day1, data, power = _passing_gate_artifacts()
    data.update(mutation)

    with pytest.raises(ContractError, match=message):
        assert_full_leaf_generation_allowed(day1, data, power)


@pytest.mark.parametrize(
    ("field", "invalid_value", "message"),
    [
        ("split_ratio", None, "split ratio"),
        ("delta_decision", None, "delta_decision"),
        ("primary_eligible_categories", [], "categories"),
        ("evidence_layout_strata", [], "evidence-layout strata"),
    ],
)
def test_full_leaf_generation_requires_frozen_power_decision_fields(
    field: str,
    invalid_value: object,
    message: str,
) -> None:
    day1, data, power = _passing_gate_artifacts()
    power[field] = invalid_value

    with pytest.raises(ContractError, match=message):
        assert_full_leaf_generation_allowed(day1, data, power)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"status": "blocked"}, "G-POWER-FEASIBILITY"),
        ({"topology_results_seen": True}, "before topology results"),
        ({"hard_no_go_available": False}, "hard NO-GO"),
    ],
)
def test_each_power_gate_failure_keeps_full_leaf_generation_closed(
    mutation: dict,
    message: str,
) -> None:
    day1, data, power = _passing_gate_artifacts()
    power.update(mutation)

    with pytest.raises(ContractError, match=message):
        assert_full_leaf_generation_allowed(day1, data, power)
