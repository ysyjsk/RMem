from __future__ import annotations

from plan_robust_memory.capacity import leaf_cache_key


def test_leaf_cache_key_excludes_budget_and_topology() -> None:
    kwargs = {
        "dataset_version_or_commit": "fixture-v1",
        "episode_id": "ep-1",
        "k": 8,
        "partition_hash": "p",
        "evidence_span": (0, 3),
        "c_leaf": 512,
        "leaf_prompt_hash": "h",
        "constructor_model_snapshot": "gpt-5.6-sol-2026-08-01",
        "decoding_config_hash": "d",
        "s_leaf": 0,
        "backbone_id": "primary",
    }
    assert leaf_cache_key(**kwargs) == leaf_cache_key(**kwargs)


def test_leaf_cache_key_separates_backbone_and_k() -> None:
    base = {
        "dataset_version_or_commit": "fixture-v1",
        "episode_id": "ep-1",
        "k": 8,
        "partition_hash": "p",
        "evidence_span": (0, 3),
        "c_leaf": 512,
        "leaf_prompt_hash": "h",
        "constructor_model_snapshot": "gpt-5.6-sol-2026-08-01",
        "decoding_config_hash": "d",
        "s_leaf": 0,
        "backbone_id": "primary",
    }
    changed = {**base, "backbone_id": "replication"}
    assert leaf_cache_key(**base) != leaf_cache_key(**changed)

