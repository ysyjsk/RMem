from __future__ import annotations

from plan_robust_memory.data_audit import audit_memoryagentbench_contexts


def test_memoryagentbench_context_is_construction_unit() -> None:
    audit = audit_memoryagentbench_contexts([
        {"context_id": "ctx-1", "question_count": 4},
        {"context_id": "ctx-2", "question_count": 3},
    ])
    assert audit["construction_units"] == 2
    assert audit["questions_by_context"]["ctx-1"] == 4

