from __future__ import annotations

from plan_robust_memory.statistics import paired_permutation_delta


def test_paired_permutation_preserves_episode_replicate_blocks() -> None:
    rows = [
        {"episode_id": "ep1", "replicate_id": 0, "plan_id": "left_deep", "score": 0},
        {"episode_id": "ep1", "replicate_id": 0, "plan_id": "canonical_balanced", "score": 1},
        {"episode_id": "ep2", "replicate_id": 0, "plan_id": "left_deep", "score": 1},
        {"episode_id": "ep2", "replicate_id": 0, "plan_id": "canonical_balanced", "score": 1},
    ]
    result = paired_permutation_delta(rows, permutations=100, seed=1)
    assert result["delta"] == 0.5
    assert 0 <= result["p_value"] <= 1

