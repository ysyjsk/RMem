from __future__ import annotations

import pytest


@pytest.fixture
def valid_episode() -> dict:
    return {
        "dataset_id": "fixture",
        "dataset_version_or_commit": "fixture-v1",
        "episode_id": "ep-001",
        "construction_unit_id": "cu-001",
        "ordered_evidence_ids": ["ev-001", "ev-002", "ev-003", "ev-004"],
        "query_ids": ["q-001", "q-002"],
        "family_id": "family-001",
        "split": "development",
        "provenance": {"source_sha256": "a" * 64},
    }


@pytest.fixture
def valid_backbone() -> dict:
    return {
        "backbone_id": "primary-sol",
        "role": "primary",
        "model_family": "gpt-5.6",
        "constructor_model_snapshot": "gpt-5.6-sol-2026-08-01",
        "merge_model_snapshot": "gpt-5.6-sol-2026-08-01",
        "answer_model_snapshot": "gpt-5.6-sol-2026-08-01",
        "provider": "labforge",
        "endpoint": "responses",
        "decoding_config_hash": "a" * 64,
    }


@pytest.fixture
def valid_retrieval_config() -> dict:
    return {
        "retrieval_config_id": "retrieval-v1",
        "embedding_model_snapshot": "BAAI/bge-m3@abc123",
        "tokenizer_snapshot": "BAAI/bge-m3-tokenizer@abc123",
        "retrieval_unit_version": "timestamped_session_v1",
        "similarity_metric": "cosine_normalized",
        "candidate_top_k": "all",
        "packing_policy": "deterministic_greedy_no_truncate",
        "render_order": "chronological",
        "tie_break": ["score_desc", "sequence_index_asc", "evidence_id_lex"],
        "index_version": "fixture-index-v1",
        "sha256": "b" * 64,
    }


@pytest.fixture
def score_rows() -> list[dict]:
    return [
        {"episode_id": "ep-1", "budget": 512, "plan_id": "left_deep", "replicate_id": 0, "query_id": "q1", "score": 0},
        {"episode_id": "ep-1", "budget": 512, "plan_id": "canonical_balanced", "replicate_id": 0, "query_id": "q1", "score": 1},
        {"episode_id": "ep-1", "budget": 512, "plan_id": "right_deep", "replicate_id": 0, "query_id": "q1", "score": 0.5},
        {"episode_id": "ep-2", "budget": 512, "plan_id": "left_deep", "replicate_id": 0, "query_id": "q2", "score": 1},
        {"episode_id": "ep-2", "budget": 512, "plan_id": "canonical_balanced", "replicate_id": 0, "query_id": "q2", "score": 1},
        {"episode_id": "ep-2", "budget": 512, "plan_id": "right_deep", "replicate_id": 0, "query_id": "q2", "score": 0},
    ]

