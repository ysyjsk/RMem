from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError, validate_primary_seed_rows


def test_primary_leaf_seed_is_zero_and_plan_seeds_are_paired() -> None:
    rows = [
        {"plan_id": "left_deep", "replicate_id": 0, "s_leaf": 0, "s_merge": 0, "s_answer": 0},
        {"plan_id": "canonical_balanced", "replicate_id": 0, "s_leaf": 0, "s_merge": 0, "s_answer": 0},
    ]
    validate_primary_seed_rows(rows)


@pytest.mark.parametrize("field", ["s_merge", "s_answer"])
def test_topology_seed_mismatch_fails(field: str) -> None:
    rows = [
        {"plan_id": "left_deep", "replicate_id": 1, "s_leaf": 0, "s_merge": 1, "s_answer": 1},
        {"plan_id": "canonical_balanced", "replicate_id": 1, "s_leaf": 0, "s_merge": 1, "s_answer": 1},
    ]
    rows[1][field] = 99
    with pytest.raises(ContractError, match=field):
        validate_primary_seed_rows(rows)


def test_nonzero_primary_leaf_seed_fails() -> None:
    rows = [{"plan_id": "left_deep", "replicate_id": 0, "s_leaf": 1, "s_merge": 0, "s_answer": 0}]
    with pytest.raises(ContractError, match="s_leaf"):
        validate_primary_seed_rows(rows)

