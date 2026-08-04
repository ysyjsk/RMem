from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_workplan_freezes_calibration_only_manifest_and_real_command() -> None:
    workplan = _read("workplan.md")
    assert "python -m plan_robust_memory.qualify_judge_repeatability" in workplan
    assert "Judge Repeatability 的唯一来源为冻结 20/30/50 划分中的 `Q_cal`" in workplan
    assert "development 不进入该 50-case manifest" in workplan
    assert "gold_equivalent = 8" in workplan
    assert "clearly_wrong = 8" in workplan
    assert "partial = 8" in workplan
    assert "temporal_reasoning = 7" in workplan
    assert "knowledge_update = 7" in workplan
    assert "formatting_variation = 6" in workplan
    assert "abstention_like = 6" in workplan


def test_workplan_freezes_raw_derived_artifacts_and_run_identity() -> None:
    workplan = _read("workplan.md")
    assert "make materialize-longmemeval-calibration" in workplan
    assert "normalized_calibration_20_30_50.json" in workplan
    assert "calibration_split_materialization_log.json" in workplan
    assert "禁止 `--normalized-episodes` 输入" in workplan
    assert "state=preparing" in workplan
    assert "not_published_for_this_run" in workplan
    for artifact in (
        "judge_repeatability_case_manifest.json",
        "judge_repeatability_transport_attempts.jsonl",
        "judge_repeatability_attempts.jsonl",
        "judge_repeatability_output_bindings.jsonl",
        "judge_repeatability_outputs.jsonl",
        "judge_repeatability.json",
        "judge_repeatability_run_state.json",
        "judge_repeatability_stall.json",
    ):
        assert artifact in workplan
    assert (
        "AcceptedOutputBindingRaw` 是 accepted generated judge API output 的唯一"
        in workplan
    )
    assert "只能依据 `judge_repeatability_run_state.json` 中本次 `run_id`" in workplan


def test_metric_spec_and_testing_principles_freeze_exact_repeatability_denominators() -> None:
    metric_spec = _read("protocol/metric_spec_v1.md")
    principles = _read("protocol/testing_principles_v1.md")
    assert "unanimous cases / 50" in metric_spec
    assert "flipped unordered replicate pairs / 150" in metric_spec
    assert "successfully parsed observations / 150" in metric_spec
    assert "exactly 50 cases x 3 unique replicates" in principles
    assert "calibration-only" in principles
    assert "does not establish human-label validity" in principles


def test_makefile_exposes_real_repeatability_gate_and_test_first_includes_it() -> None:
    makefile = _read("Makefile")
    assert "materialize-longmemeval-calibration:" in makefile
    assert "-m plan_robust_memory.materialize_longmemeval_calibration" in makefile
    assert "qualify-judge-repeatability:" in makefile
    assert "-m plan_robust_memory.qualify_judge_repeatability" in makefile
    assert "tests/qualification/test_judge_repeatability.py" in makefile
    assert "tests/qualification/test_judge_repeatability_gate.py" in makefile
    assert "tests/qualification/test_judge_repeatability_cli.py" in makefile
