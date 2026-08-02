from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from plan_robust_memory.audit_longmemeval import audit_cleaned_dataset
from plan_robust_memory.contracts import DELTA_DECISION_GRID
from plan_robust_memory.hashing import stable_hash
from plan_robust_memory.power_gate import run_power_gate


def _audit(n: int = 600) -> dict:
    def candidate(
        ratio: tuple[float, float, float], counts: tuple[int, int, int], suffix: str
    ) -> dict:
        split_names = ("development", "calibration", "acceptance")
        ratio_record = dict(zip(split_names, ratio, strict=True))
        primary_counts = {
            split: {"N_master": count, "N4": count, "N8": count, "N16": count}
            for split, count in zip(split_names, counts, strict=True)
        }
        acceptance = counts[-1]
        assignments = [
            {"group_id": f"group-{suffix}", "split": "acceptance", "episode_ids": [f"episode-{suffix}"]}
        ]
        return {
            "candidate_id": suffix,
            "ratio": ratio_record,
            "primary_counts": primary_counts,
            "expanded_counts": primary_counts,
            "acceptance_primary_e8_evidence_layout_strata": [
                {
                    "question_type": "knowledge-update",
                    "support_leaf_class": "single",
                    "evidence_position_bin": "early",
                    "count": acceptance // 2,
                },
                {
                    "question_type": "temporal-reasoning",
                    "support_leaf_class": "multiple",
                    "evidence_position_bin": "late",
                    "count": acceptance - acceptance // 2,
                },
            ],
            "assignments": assignments,
            "assignment_hash": stable_hash(
                {"candidate_id": suffix, "ratio": ratio_record, "assignments": assignments}
            ),
        }

    # The first candidate deliberately differs from ratio * n by group-rounding.
    first_counts = (max(0, n // 5 - 1), max(0, 3 * n // 10 - 1), 0)
    first_counts = (*first_counts[:2], n - sum(first_counts[:2]))
    second_counts = (3 * n // 20, n // 4, n - 3 * n // 20 - n // 4)
    third_counts = (n // 10, n // 5, n - n // 10 - n // 5)
    audit = {
        "status": "qualified_with_exclusions",
        "no_silent_drop": True,
        "counts": {
            "N_master": n,
            "N4": n,
            "N8": n,
            "N16": n,
            "primary_N_master": n,
            "primary_N4": n,
            "primary_N8": n,
            "primary_N16": n,
        },
        "eligible_primary_categories": ["knowledge-update", "temporal-reasoning"],
        "split_candidates": [
            candidate((0.2, 0.3, 0.5), first_counts, "20_30_50"),
            candidate((0.15, 0.25, 0.6), second_counts, "15_25_60"),
            candidate((0.1, 0.2, 0.7), third_counts, "10_20_70"),
        ],
    }
    audit["audit_hash"] = stable_hash(audit)
    return audit


def test_power_gate_is_reproducible_and_freezes_the_real_grouped_split() -> None:
    audit = _audit()
    first = run_power_gate(audit, draws=80, seed=19)
    second = run_power_gate(audit, draws=80, seed=19)

    assert first == second
    assert first["status"] == "passed"
    assert first["grouped_split_counts"] == audit["split_candidates"][0]["primary_counts"]
    assert first["split_ratio"] == {
        "development": 0.2,
        "calibration": 0.3,
        "acceptance": 0.5,
    }
    assert first["analysis_n"] == audit["split_candidates"][0]["primary_counts"]["acceptance"]["N8"]
    assert first["analysis_n"] != int(audit["counts"]["primary_N8"] * 0.5)
    assert first["independent_episode_count"] == audit["counts"]["primary_N8"]
    assert first["delta_decision"] in DELTA_DECISION_GRID
    assert first["delta_decision"] >= 0.05
    assert first["power"] >= 0.80
    assert first["power_lower_95"] >= 0.80
    assert first["decision_rule"] == "minimum scenario Monte Carlo 95% lower bound >= 0.80"
    assert first["topology_results_seen"] is False
    assert first["hard_no_go_available"] is True
    assert first["split_ratio_frozen_from"] == "manifest.split_candidates[*].primary_counts"
    assert first["split_assignment_hash"] == audit["split_candidates"][0]["assignment_hash"]
    assert first["artifact_hash"] == stable_hash(
        {key: value for key, value in first.items() if key != "artifact_hash"}
    )


def test_power_gate_runs_the_preregistered_signed_effect_grid() -> None:
    result = run_power_gate(_audit(), draws=20, seed=7)
    simulated_effects = {row["effect"] for row in result["simulation_results"]}
    assert {0.0, -0.025, 0.025, -0.05, 0.05, -0.075, 0.075, -0.1, 0.1, -0.15, 0.15} <= simulated_effects
    assert {row["analysis_n"] for row in result["simulation_results"]} <= {302, 360, 420}
    assert result["estimator"] == "paired sign-flip permutation test (normal approximation to the randomization distribution)"
    assert all(
        0.0 <= row["power_lower_95"] <= row["power"] <= row["power_upper_95"] <= 1.0
        for row in result["simulation_results"]
    )


def test_one_lucky_monte_carlo_draw_cannot_grant_hard_no_go_authority() -> None:
    result = run_power_gate(_audit(), draws=1, seed=2)

    assert result["status"] == "blocked"
    assert result["hard_no_go_available"] is False
    assert result["delta_decision"] is None
    assert result["power"] is None
    assert result["best_attainable_conservative_power"] in {0.0, 1.0}
    assert result["best_attainable_lower_95"] < 0.80


def test_power_gate_consumes_the_adapter_written_manifest_without_schema_translation(
    tmp_path: Path,
) -> None:
    rows = []
    for index in range(40):
        question_id = f"question-{index}"
        session_ids = [f"{question_id}-session-{session}" for session in range(8)]
        rows.append(
            {
                "question_id": question_id,
                "question_type": "knowledge-update" if index % 2 == 0 else "temporal-reasoning",
                "question": f"question {index}",
                "answer": f"answer {index}",
                "question_date": "2026-01-31",
                "haystack_session_ids": session_ids,
                "haystack_dates": ["2026-01-01"] * 8,
                "haystack_sessions": [
                    [{"role": "user", "content": f"unique {index} session {session}"}]
                    for session in range(8)
                ],
                "answer_session_ids": [session_ids[-1]],
            }
        )
    raw = tmp_path / "longmemeval_s_cleaned.json"
    raw.write_text(json.dumps(rows), encoding="utf-8")
    audit_cleaned_dataset(raw, tmp_path / "audit", revision="fixture-revision")
    manifest = json.loads((tmp_path / "audit" / "dataset_manifest.json").read_text(encoding="utf-8"))

    result = run_power_gate(manifest, draws=1, seed=5)

    assert result["input_validation_errors"] == []
    assert result["independent_episode_count"] == 40
    assert result["simulation_results"]
    assert {row["assignment_hash"] for row in result["simulation_results"]} == {
        candidate["assignment_hash"] for candidate in manifest["split_candidates"]
    }


def test_power_gate_blocks_when_real_manifest_has_no_eligible_e8_episodes() -> None:
    audit = _audit(0)
    result = run_power_gate(audit, draws=50, seed=1)

    assert result["status"] == "blocked"
    assert result["hard_no_go_available"] is False
    assert result["power"] is None
    assert result["simulation_results"] == []
    assert "primary E8" in result["blocking_reason"]
    assert result["artifact_hash"]


def test_power_gate_never_falls_back_to_expanded_n8() -> None:
    audit = _audit()
    del audit["counts"]["primary_N8"]
    audit["counts"]["N8"] = 50_000

    result = run_power_gate(audit, draws=10, seed=1)

    assert result["status"] == "blocked"
    assert result["independent_episode_count"] is None
    assert result["analysis_n"] is None
    assert result["power"] is None
    assert result["simulation_results"] == []
    assert "primary_N8" in result["blocking_reason"]


def test_power_gate_blocks_inconsistent_real_grouped_counts() -> None:
    audit = _audit()
    audit["split_candidates"][0]["primary_counts"]["acceptance"]["N8"] -= 1

    result = run_power_gate(audit, draws=10, seed=1)

    assert result["status"] == "blocked"
    assert result["split_ratio"] is None
    assert result["delta_decision"] is None
    assert result["power"] is None
    assert result["simulation_results"] == []
    assert "grouped_split_counts" in result["blocking_reason"]


def test_power_gate_blocks_a_tampered_group_assignment_hash() -> None:
    audit = _audit()
    audit["split_candidates"][0]["assignments"][0]["split"] = "development"

    result = run_power_gate(audit, draws=10, seed=1)

    assert result["status"] == "blocked"
    assert result["power"] is None
    assert result["simulation_results"] == []
    assert "assignment_hash" in result["blocking_reason"]


def test_power_gate_blocks_strata_that_do_not_describe_all_primary_e8_episodes() -> None:
    audit = _audit()
    audit["split_candidates"][0]["acceptance_primary_e8_evidence_layout_strata"][0]["count"] -= 1

    result = run_power_gate(audit, draws=10, seed=1)

    assert result["status"] == "blocked"
    assert result["power"] is None
    assert result["simulation_results"] == []
    assert "evidence_layout_strata" in result["blocking_reason"]


def test_power_gate_blocks_unknown_or_non_empirical_layout_bins() -> None:
    audit = _audit()
    audit["split_candidates"][0]["acceptance_primary_e8_evidence_layout_strata"][0]["evidence_position_bin"] = "unknown"

    result = run_power_gate(audit, draws=10, seed=1)

    assert result["status"] == "blocked"
    assert result["power"] is None
    assert "evidence_position_bin" in result["blocking_reason"]


def test_power_gate_records_empirical_strata_in_the_simulation_input_hash() -> None:
    first_audit = _audit()
    second_audit = deepcopy(first_audit)
    second_audit["split_candidates"][0]["acceptance_primary_e8_evidence_layout_strata"][0]["support_leaf_class"] = "multiple"
    second_audit["audit_hash"] = stable_hash(
        {key: value for key, value in second_audit.items() if key != "audit_hash"}
    )

    first = run_power_gate(first_audit, draws=20, seed=11)
    second = run_power_gate(second_audit, draws=20, seed=11)

    assert first["simulation_input_hash"] != second["simulation_input_hash"]
    assert first["strata_design"] != second["strata_design"]


def test_underpowered_gate_does_not_attach_best_case_power_to_an_unfrozen_delta() -> None:
    audit = _audit(9)
    candidate = audit["split_candidates"][0]
    candidate["primary_counts"] = {
        split: {metric: count for metric in ("N_master", "N4", "N8", "N16")}
        for split, count in {"development": 1, "calibration": 1, "acceptance": 7}.items()
    }
    candidate["acceptance_primary_e8_evidence_layout_strata"] = [
        {
            "question_type": "knowledge-update",
            "support_leaf_class": "single",
            "evidence_position_bin": "middle",
            "count": 3,
        },
        {
            "question_type": "temporal-reasoning",
            "support_leaf_class": "multiple",
            "evidence_position_bin": "late",
            "count": 4,
        },
    ]
    audit["split_candidates"] = [candidate]
    audit["audit_hash"] = stable_hash(
        {key: value for key, value in audit.items() if key != "audit_hash"}
    )

    result = run_power_gate(audit, draws=60, seed=3)

    assert result["status"] == "blocked"
    assert result["delta_decision"] is None
    assert result["power"] is None
    assert result["hard_no_go_available"] is False
    assert result["best_attainable_conservative_power"] is not None
    assert result["simulation_results"]
