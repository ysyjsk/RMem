from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_NAME = "Plan_Robust_Agent_Memory_Model_Framework_Usage.md"


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
