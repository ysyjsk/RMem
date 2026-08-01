from __future__ import annotations

from plan_robust_memory.partition import token_balanced_partition


def test_partition_formula_changes_with_k() -> None:
    tokens = [1] * 16
    assert token_balanced_partition(tokens, 4) != token_balanced_partition(tokens, 8)

