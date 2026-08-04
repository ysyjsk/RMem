from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _schema(relative: str) -> dict:
    return json.loads(_read(relative))


def test_raw_schema_names_local_surrogate_counts_without_parallel_legacy_fields() -> None:
    leaf = _schema("schemas/leaf.schema.json")
    attempt = _schema("schemas/cost.schema.json")["$defs"]["ModelCallAttemptRaw"]

    assert "local_surrogate_content_tokens" in leaf["required"]
    assert "local_surrogate_content_tokens" in leaf["properties"]
    assert "memory_tokens_local" not in leaf["required"]
    assert "memory_tokens_local" not in leaf["properties"]

    for field in (
        "local_surrogate_serialized_input_tokens",
        "local_surrogate_output_content_tokens",
    ):
        assert field in attempt["required"]
        assert field in attempt["properties"]
    assert "local_serialized_input_tokens" not in attempt["properties"]
    assert "local_output_content_tokens" not in attempt["properties"]


def test_execution_docs_do_not_claim_surrogate_counts_are_exact_model_tokens() -> None:
    workplan = _read("workplan.md")
    metric_spec = _read("protocol/metric_spec_v1.md")
    principles = _read("protocol/testing_principles_v1.md")

    for document in (workplan, metric_spec, principles):
        assert "local_surrogate_content_tokens" in document

    assert "不得称为 exact model tokens" in workplan
    assert "not exact model-token measurements" in metric_spec
    assert "not exact model tokens" in principles

    assert "local_surrogate_serialized_input_tokens" in workplan
    assert "local_surrogate_output_content_tokens" in workplan
    assert "local_surrogate_serialized_input_tokens / B_merge" in metric_spec


def test_q0_requires_tokenizer_or_surrogate_safety_qualification_without_new_gate() -> None:
    workplan = _read("workplan.md")

    assert "真实模型 tokenizer" in workplan
    assert "immutable" in workplan
    assert "误差界" in workplan
    assert "safety margin" in workplan
    assert "真实模型预算" in workplan
    assert "## G-TOKEN" not in workplan
