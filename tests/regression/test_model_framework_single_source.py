from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_NAME = "Plan_Robust_Agent_Memory_Model_Framework_Usage.md"
LABFORGE_BASE_URL = "https://api.labforge.cc/v1"


def test_model_framework_has_one_canonical_file() -> None:
    candidates = sorted(ROOT.glob("Plan_Robust_Agent_Memory_Model_Framework_Usage*.md"))
    assert [path.name for path in candidates] == [CANONICAL_NAME]


def test_workplan_uses_only_canonical_model_framework_reference() -> None:
    workplan = (ROOT / "workplan.md").read_text(encoding="utf-8")
    assert CANONICAL_NAME in workplan
    assert "Model_Framework_Usage_v1.0.md" not in workplan
    assert "Model_Framework_Usage_v1.1.md" not in workplan


def test_model_framework_title_is_not_versioned() -> None:
    first_line = (ROOT / CANONICAL_NAME).read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "# Plan-Robust Agent Memory：模型调用框架使用说明"


def test_workplan_and_framework_freeze_clean_chat_completions_contract() -> None:
    framework = (ROOT / CANONICAL_NAME).read_text(encoding="utf-8")
    workplan = (ROOT / "workplan.md").read_text(encoding="utf-8")

    for text in (framework, workplan):
        assert LABFORGE_BASE_URL in text
        assert "/chat/completions" in text
        assert "exactly one `user` message" in text
        assert "不得注入 `system` 或 `developer` message" in text
        assert "direct → `http://127.0.0.1:17897`" in text
    assert "endpoint: responses" not in framework
    assert "`/responses` 不属于本项目" in framework


def test_day1_plan_names_exact_artifacts_and_chat_wire_fields() -> None:
    framework = (ROOT / CANONICAL_NAME).read_text(encoding="utf-8")
    workplan = (ROOT / "workplan.md").read_text(encoding="utf-8")
    artifacts = (
        "proxy_probe.json",
        "model_inventory.json",
        "primary_115k_probe.json",
        "primary_output_probe.json",
        "judge_probe.json",
        "replication_model_probe.json",
        "embedding_probe.json",
        "cost_upper_bound.json",
    )

    for text in (framework, workplan):
        assert "python -m plan_robust_memory.probe_day1" in text
        assert "request_output_limit_field: max_tokens" in text
        assert "max_route_attempts: 2" in text
        for artifact in artifacts:
            assert artifact in text
    assert "max_output_tokens:" not in framework
    assert "`max_output_tokens` 只可作为内部预算命名" in framework
    assert "max_retries: 3" not in framework
    assert workplan.startswith(
        "# Plan-Robust Agent Memory：第一阶段严格工作计划 eval-protocol-v1.0-rc3"
    )
