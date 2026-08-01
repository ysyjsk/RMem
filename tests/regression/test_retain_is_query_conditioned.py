from __future__ import annotations

from plan_robust_memory.retrieval import rank_evidence


def test_retain_is_query_conditioned() -> None:
    evidence = [{"evidence_id": "e1", "sequence_index": 0}, {"evidence_id": "e2", "sequence_index": 1}]
    scores = {("q1", "e1"): 0.9, ("q1", "e2"): 0.1, ("q2", "e1"): 0.1, ("q2", "e2"): 0.9}
    assert [item["evidence_id"] for item in rank_evidence("q1", evidence, scores)] == ["e1", "e2"]
    assert [item["evidence_id"] for item in rank_evidence("q2", evidence, scores)] == ["e2", "e1"]

