from __future__ import annotations

from plan_robust_memory.capacity import leaf_cache_key


def test_backbone_leaf_cache_namespaces_are_isolated() -> None:
    base = {
        "dataset_version_or_commit": "fixture-v1",
        "episode_id": "ep",
        "k": 8,
        "partition_hash": "p",
        "evidence_span": (0, 1),
        "c_leaf": 512,
        "leaf_prompt_hash": "lp",
        "constructor_model_snapshot": "model-a",
        "decoding_config_hash": "d",
        "s_leaf": 0,
        "backbone_id": "primary",
    }
    assert leaf_cache_key(**base) != leaf_cache_key(**{**base, "backbone_id": "replication"})

