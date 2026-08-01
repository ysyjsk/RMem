from __future__ import annotations

from plan_robust_memory.retrieval import render_chronologically


def test_retain_renders_chronologically() -> None:
    assert render_chronologically([
        {"evidence_id": "late", "sequence_index": 2},
        {"evidence_id": "early", "sequence_index": 0},
    ]) == ["early", "late"]

