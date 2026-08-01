from __future__ import annotations

from plan_robust_memory.data_audit import k_mask_manifest, longmemeval_counts


def test_longmemeval_adapter_counts_fixture_rows() -> None:
    rows = [
        {"query_id": "q1", "question_type": "knowledge-update"},
        {"query_id": "q2", "question_type": "temporal-reasoning"},
        {"query_id": "q3_abs", "question_type": "knowledge-update"},
    ]
    assert longmemeval_counts(rows)["eligible_primary"] == 2


def test_longmemeval_adapter_builds_k_masks() -> None:
    masks = k_mask_manifest([{"episode_id": "ep", "atomic_evidence_count": 8}])
    assert masks["ep"] == {4: True, 8: True, 16: False}

