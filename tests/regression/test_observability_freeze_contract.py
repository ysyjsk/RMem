from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from plan_robust_memory.contracts import PI_DIAG, PI_PRIMARY
from plan_robust_memory.gates import FULL_LEAF_QUALIFICATION_SEQUENCE
from plan_robust_memory.plans import PlanDescriptor


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_observability_does_not_change_primary_scientific_contract() -> None:
    workplan = _read("workplan.md")
    assert PI_PRIMARY == ("left_deep", "canonical_balanced")
    assert PI_DIAG == ("left_deep", "canonical_balanced", "right_deep")
    assert "Task Quality、Plan Robustness、Lifecycle Cost 三维分开报告" in workplan
    assert "right-deep 只进入 `Pi_diag`" in workplan
    assert "## G-OBSERVABILITY" not in workplan


def test_full_leaf_entry_order_is_frozen_in_workplan_and_code() -> None:
    workplan = _read("workplan.md")
    expected_block = "\n".join(
        (
            "Observability Freeze",
            "-> Evaluator Parity",
            "-> Judge Repeatability",
            "-> Cache Qualification",
            "-> SATURATION-01",
            "-> Final Judge/Budget Freeze",
            "-> eval-protocol-v1.0",
            "-> Q0/D_leaf micro-run",
            "-> Full Leaves",
        )
    )
    assert expected_block in workplan
    assert FULL_LEAF_QUALIFICATION_SEQUENCE == (
        "observability_freeze",
        "evaluator_parity",
        "judge_repeatability",
        "cache_qualification",
        "saturation_01",
        "final_judge_budget_freeze",
        "eval_protocol_v1_0",
        "q0_d_leaf_micro_run",
    )


def test_proposal_is_framing_and_execution_truth_is_not_parallelized() -> None:
    proposal = _read("Proposal.md")
    workplan = _read("workplan.md")
    metric_spec = _read("protocol/metric_spec_v1.md")
    assert "used only as descriptive" in proposal
    assert "execution source of truth" in proposal
    assert "不具有执行权威" in workplan
    assert "do not produce confirmatory" in metric_spec


def test_observability_uses_existing_schema_files_only() -> None:
    schema_names = {path.name for path in (ROOT / "schemas").glob("*.json")}
    assert "observability.schema.json" not in schema_names
    assert "plan.schema.json" in schema_names
    assert "leaf.schema.json" in schema_names
    assert "run.schema.json" in schema_names
    assert "cost.schema.json" in schema_names


def test_plan_descriptor_stores_raw_child_graph_not_parallel_merge_truth() -> None:
    stored_fields = {field.name for field in fields(PlanDescriptor)}
    assert "plan_nodes" in stored_fields
    assert "ordered_merge_operations" not in stored_fields


def test_workplan_freezes_real_evaluator_parity_sources_and_command() -> None:
    workplan = _read("workplan.md")
    assert "9e0b455f4ef0e2ab8f2e582289761153549043fc" in workplan
    assert "455306dcabc3842526eb83cd4e225e5d486c5c5d" in workplan
    assert "python -m plan_robust_memory.qualify_evaluator_parity" in workplan
