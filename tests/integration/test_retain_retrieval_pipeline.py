from __future__ import annotations

from plan_robust_memory.retrieval import greedy_pack, rank_evidence, render_chronologically


def test_retain_retrieval_is_query_conditioned_and_chronological_at_render() -> None:
    evidence = [
        {"evidence_id": "e1", "sequence_index": 1, "token_count": 3},
        {"evidence_id": "e0", "sequence_index": 0, "token_count": 3},
    ]
    ranked = rank_evidence("q1", evidence, {("q1", "e1"): 0.9, ("q1", "e0"): 0.8})
    packed = greedy_pack(ranked, 10)
    assert [item["evidence_id"] for item in ranked] == ["e1", "e0"]
    assert render_chronologically(packed) == ["e0", "e1"]

