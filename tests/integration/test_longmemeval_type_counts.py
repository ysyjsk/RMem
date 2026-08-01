from __future__ import annotations

from plan_robust_memory.data_audit import longmemeval_counts


def test_longmemeval_type_and_abs_counts_are_explicit() -> None:
    counts = longmemeval_counts([
        {"query_id": "ku-1", "question_type": "knowledge-update"},
        {"query_id": "ku-2_abs", "question_type": "knowledge-update"},
        {"query_id": "tr-1", "question_type": "temporal-reasoning"},
        {"query_id": "other-1", "question_type": "preference"},
    ])
    assert counts["question_type_counts"]["knowledge-update"] == 2
    assert counts["abstention_counts"]["knowledge-update"] == 1
    assert counts["eligible_primary"] == 2

