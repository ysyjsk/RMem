from __future__ import annotations

from plan_robust_memory.partition import token_balanced_partition


def test_partition_spans_are_contiguous_and_cover_all_evidence() -> None:
    spans = token_balanced_partition([5, 5, 5, 5, 5, 5, 5, 5], 4)
    assert [(s.start, s.end) for s in spans] == [(0, 1), (2, 3), (4, 5), (6, 7)]

