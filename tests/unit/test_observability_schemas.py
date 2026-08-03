from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate


ROOT = Path(__file__).resolve().parents[2]


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _plan() -> dict:
    return {
        "plan_id": "p1",
        "plan_family": "canonical_balanced",
        "plan_set_id": "primary",
        "k": 4,
        "leaf_ids": ["l0", "l1", "l2", "l3"],
        "plan_nodes": [
            {
                "logical_node_id": "n0",
                "plan_id": "p1",
                "node_type": "leaf",
                "leaf_id": "l0",
                "left_logical_child_id": None,
                "right_logical_child_id": None,
                "covered_span": [0, 0],
            }
        ],
        "online_or_offline": "offline",
        "prefix_queryable": False,
        "rebuild_interval": None,
        "budget_id": "b512",
        "generator_version": "plan-v1",
    }


def _artifact() -> dict:
    return {
        "materialized_node_id": "m1",
        "logical_node_id": "n1",
        "run_id": "r1",
        "content_artifact_id": "content/sha256/b",
        "content_hash": "b" * 64,
        "artifact_kind": "memory_node",
        "memory_tokens_local": 20,
        "capacity_tokens": 32,
        "tokenizer_snapshot": "tok@1",
        "serialization_version": "serialization-v1",
        "operator_config_id": "op1",
        "deterministic_operator_hash": None,
        "model_snapshot": "model@1",
        "prompt_hash": "a" * 64,
        "creation_event_type": "merge",
        "creation_event_id": "merge-1",
        "schema_version": "node-artifact-v1",
        "validation_status": "passed",
        "materialization_source": "generated",
        "response_hash": "c" * 64,
        "artifact_status": "available",
    }


def _attempt() -> dict:
    return {
        "attempt_id": "a1",
        "run_id": "r1",
        "stage": "merge",
        "logical_call_id": "call1",
        "accepted_attempt": True,
        "retry_index": 0,
        "requested_model": "model@1",
        "returned_model": "model@1",
        "provider": "labforge",
        "provider_route": "https://api.labforge.cc/v1",
        "request_id": "request1",
        "prompt_hash": "a" * 64,
        "response_hash": "b" * 64,
        "local_serialized_input_tokens": 20,
        "local_output_content_tokens": 8,
        "tokenizer_snapshot": "tok@1",
        "serialization_version": "serialization-v1",
        "provider_input_tokens_total": 20,
        "provider_cached_input_tokens_subset": 5,
        "provider_output_tokens_total": 8,
        "provider_reasoning_tokens_subset": 2,
        "usage_schema_version": "labforge-v1",
        "provider_usage_source": "provider_exact",
        "scheduled_at": "2026-08-03T00:00:00Z",
        "started_at": "2026-08-03T00:00:01Z",
        "finished_at": "2026-08-03T00:00:02Z",
        "http_status": 200,
        "finish_reason": "stop",
        "parse_status": "passed",
        "failure_type": None,
        "attempt_outcome": "accepted_materialized",
        "status": "completed",
    }


def _token_fields(prefixes: tuple[str, ...]) -> dict:
    result = {}
    for prefix in prefixes:
        result[f"{prefix}_input_tokens_total"] = 0
        result[f"{prefix}_cached_input_tokens_subset"] = 0
        result[f"{prefix}_uncached_input_tokens"] = 0
        result[f"{prefix}_output_tokens"] = 0
    return result


def _cost() -> dict:
    observed = _token_fields(("observed_leaf", "observed_merge", "observed_answer"))
    observed.update(
        {
            "api_attempt_count": 1,
            "failed_api_attempt_count": 0,
            "successful_nonmaterialized_attempt_count": 0,
            "accepted_materialized_generation_count": 1,
            "cache_hit_count": 0,
            "retry_token_overhead": 0,
            "retry_latency_overhead": 0,
            "sum_attempt_latency": 1,
            "critical_path_elapsed_latency": 1,
            "parallelism_factor": 1,
        }
    )
    return {
        "cost_id": "cost1",
        "run_id": "r1",
        "backbone_id": "backbone1",
        "k": 4,
        "budget_id": "b512",
        "plan_id": "p1",
        "model_call_attempts": [_attempt()],
        "accepted_path": _token_fields(("shared_leaf", "accepted_merge", "accepted_answer")),
        "observed_operational": observed,
        "judge_overhead": _token_fields(("accepted_judge", "observed_judge")),
        "deployment_memory_tokens": 32,
        "deployment_metadata_bytes": 128,
        "deployment_capability_profile": "FINAL_QUERY_ONLY",
        "deployment_state_measurement_protocol": "deployment-state-v1",
        "deployment_state_measurement_point": "after-final-view-before-answer",
        "shared_leaf_tokens": 64,
        "shared_raw_evidence_bytes": 1024,
        "artifact_cache_bytes": 4096,
        "C_construct": 28,
        "C_query": 8,
        "pricing_manifest": None,
        "estimated_api_cost_usd": "unavailable",
    }


def test_plan_schema_keeps_derived_fields_out_of_plan_node_raw() -> None:
    plan = _plan()
    validate(plan, _schema("plan.schema.json"))
    plan["plan_nodes"][0]["descendant_leaf_ids"] = ["l0"]
    with pytest.raises(ValidationError):
        validate(plan, _schema("plan.schema.json"))


def test_plan_schema_rejects_negative_covered_span() -> None:
    plan = _plan()
    plan["plan_nodes"][0]["covered_span"] = [-1, 0]
    with pytest.raises(ValidationError):
        validate(plan, _schema("plan.schema.json"))


def test_node_artifact_schema_has_no_parallel_cache_source_field() -> None:
    artifact = _artifact()
    validate(artifact, _schema("leaf.schema.json"))
    artifact["cache_source_artifact_id"] = "source"
    with pytest.raises(ValidationError):
        validate(artifact, _schema("leaf.schema.json"))


def test_node_artifact_schema_rejects_absolute_content_identity() -> None:
    artifact = _artifact()
    artifact["content_artifact_id"] = "/tmp/local-only.txt"
    with pytest.raises(ValidationError):
        validate(artifact, _schema("leaf.schema.json"))


def test_cost_schema_keeps_missing_provider_usage_null_and_local_only() -> None:
    cost = _cost()
    attempt = cost["model_call_attempts"][0]
    attempt["accepted_attempt"] = False
    attempt["attempt_outcome"] = "successful_nonmaterialized"
    attempt["provider_usage_source"] = "missing"
    for field in (
        "provider_input_tokens_total",
        "provider_cached_input_tokens_subset",
        "provider_output_tokens_total",
        "provider_reasoning_tokens_subset",
    ):
        attempt[field] = None
    validate(cost, _schema("cost.schema.json"))
    attempt["provider_input_tokens_total"] = attempt["local_serialized_input_tokens"]
    with pytest.raises(ValidationError):
        validate(cost, _schema("cost.schema.json"))


def test_cost_schema_excludes_durable_state_and_requires_unavailable_usd_without_pricing() -> None:
    cost = _cost()
    validate(cost, _schema("cost.schema.json"))
    invalid = deepcopy(cost)
    invalid["durable_state_tokens"] = 32
    with pytest.raises(ValidationError):
        validate(invalid, _schema("cost.schema.json"))
    invalid = deepcopy(cost)
    invalid["estimated_api_cost_usd"] = 0
    with pytest.raises(ValidationError):
        validate(invalid, _schema("cost.schema.json"))


def test_cost_schema_rejects_http_status_above_599() -> None:
    cost = _cost()
    cost["model_call_attempts"][0]["http_status"] = 600
    with pytest.raises(ValidationError):
        validate(cost, _schema("cost.schema.json"))


@pytest.mark.parametrize("status", ["failed", "invalidated"])
def test_binding_schema_requires_null_references_when_not_succeeded(status: str) -> None:
    binding = {
        "binding_id": "b1",
        "run_id": "r1",
        "stage": "merge",
        "logical_call_id": "call1",
        "accepted_attempt_id": "a1",
        "output_artifact_id": "m1",
        "binding_status": status,
    }
    binding_schema = _schema("run.schema.json")["$defs"]["AcceptedOutputBindingRaw"]
    with pytest.raises(ValidationError):
        validate(binding, binding_schema)

    binding["accepted_attempt_id"] = None
    binding["output_artifact_id"] = None
    validate(binding, binding_schema)


def test_query_labels_are_explicitly_scoring_only() -> None:
    query = {
        "query_id": "q1",
        "episode_id": "e1",
        "question_type": "knowledge-update",
        "is_abstention": False,
        "query_text": "What changed?",
        "gold_answer": "answer",
        "evaluator_id": "eval1",
        "supporting_evidence_ids": ["ev1"],
        "split": "development",
        "protected_label_access": "scoring_only",
    }
    validate(query, _schema("query.schema.json"))
    query["protected_label_access"] = "construction"
    with pytest.raises(ValidationError):
        validate(query, _schema("query.schema.json"))


def test_score_schema_requires_explicit_support_mapping_status() -> None:
    score = {
        "score_id": "s1",
        "run_id": "r1",
        "query_id": "q1",
        "score": 1,
        "evaluator_id": "eval1",
        "judge_cache_key": "cache1",
        "protected_label_access_log_id": "access1",
        "support_mappings": [
            {
                "annotation_id": "ann1",
                "support_mapping_status": "exact",
                "mapped_evidence_ids": ["ev1"],
                "mapped_chunk_ids": ["chunk1"],
                "mapped_leaf_ids": ["leaf1"],
            }
        ],
    }
    validate(score, _schema("score.schema.json"))
    score["support_mappings"][0]["support_mapping_status"] = "implicit"
    with pytest.raises(ValidationError):
        validate(score, _schema("score.schema.json"))
