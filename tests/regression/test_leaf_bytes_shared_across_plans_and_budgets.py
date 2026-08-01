from __future__ import annotations

import pytest

from plan_robust_memory.capacity import validate_leaf_cache_shared
from plan_robust_memory.contracts import ContractError


def test_leaf_bytes_shared_across_plans_and_budgets() -> None:
    validate_leaf_cache_shared([
        {"episode_id": "ep", "backbone_id": "primary", "k": 8, "leaf_index": 0, "leaf_sha256": "h1"},
        {"episode_id": "ep", "backbone_id": "primary", "k": 8, "leaf_index": 0, "leaf_sha256": "h1"},
    ])


def test_leaf_hash_mismatch_fails() -> None:
    with pytest.raises(ContractError, match="leaf SHA-256"):
        validate_leaf_cache_shared([
            {"episode_id": "ep", "backbone_id": "primary", "k": 8, "leaf_index": 0, "leaf_sha256": "h1"},
            {"episode_id": "ep", "backbone_id": "primary", "k": 8, "leaf_index": 0, "leaf_sha256": "h2"},
        ])

