from __future__ import annotations

import pytest

from plan_robust_memory.observability import (
    ObservabilityContractError,
    derive_merge_event_metrics,
    derive_plan_metrics,
    reconcile_work,
    validate_accepted_output_binding_raw,
    validate_merge_event_raw,
    validate_model_call_attempt_raw,
    validate_node_artifact,
    validate_plan_node_raw,
    validate_run_execution_config,
    validate_support_label_boundary,
)


def _leaf(node_id: str, leaf_id: str, start: int, end: int) -> dict:
    return {
        "logical_node_id": node_id,
        "plan_id": "plan-1",
        "node_type": "leaf",
        "leaf_id": leaf_id,
        "left_logical_child_id": None,
        "right_logical_child_id": None,
        "covered_span": [start, end],
    }


def _internal(node_id: str, left: str, right: str) -> dict:
    return {
        "logical_node_id": node_id,
        "plan_id": "plan-1",
        "node_type": "internal",
        "leaf_id": None,
        "left_logical_child_id": left,
        "right_logical_child_id": right,
        "covered_span": [0, 3],
    }


def _attempt(
    attempt_id: str = "attempt-1",
    *,
    stage: str = "merge",
    outcome: str = "accepted_materialized",
    source: str = "provider_exact",
    logical_call_id: str = "call-1",
    input_tokens: int | None = 100,
    cached_tokens: int | None = 20,
    output_tokens: int | None = 40,
) -> dict:
    return {
        "attempt_id": attempt_id,
        "run_id": "run-1",
        "stage": stage,
        "logical_call_id": logical_call_id,
        "accepted_attempt": outcome == "accepted_materialized",
        "retry_index": 0,
        "requested_model": "gpt-5.6-sol",
        "returned_model": "gpt-5.6-sol",
        "provider": "labforge",
        "provider_route": "direct",
        "request_id": f"request-{attempt_id}",
        "prompt_hash": "a" * 64,
        "response_hash": "b" * 64 if outcome != "failed_provider" else None,
        "local_serialized_input_tokens": 90,
        "local_output_content_tokens": 30,
        "tokenizer_snapshot": "tokenizer@rev1",
        "serialization_version": "serialization-v1",
        "provider_input_tokens_total": input_tokens,
        "provider_cached_input_tokens_subset": cached_tokens,
        "provider_output_tokens_total": output_tokens,
        "provider_reasoning_tokens_subset": 5 if output_tokens is not None else None,
        "usage_schema_version": "provider-usage-v1",
        "provider_usage_source": source,
        "scheduled_at": "2026-08-03T10:00:00Z",
        "started_at": "2026-08-03T10:00:01Z",
        "finished_at": "2026-08-03T10:00:02Z",
        "http_status": 200 if outcome != "failed_provider" else 500,
        "finish_reason": "stop" if outcome != "failed_provider" else None,
        "parse_status": "passed" if outcome != "failed_parse" else "failed",
        "failure_type": None if outcome.startswith(("accepted", "successful")) else "provider_error",
        "attempt_outcome": outcome,
        "status": "completed" if outcome != "failed_provider" else "failed",
    }


def _binding(attempt_id: str = "attempt-1", *, output: str = "node-r") -> dict:
    return {
        "binding_id": "binding-1",
        "run_id": "run-1",
        "stage": "merge",
        "logical_call_id": "call-1",
        "accepted_attempt_id": attempt_id,
        "output_artifact_id": output,
        "binding_status": "succeeded",
    }


def _node_artifact(source: str = "generated") -> dict:
    return {
        "materialized_node_id": "node-r",
        "logical_node_id": "root",
        "run_id": "run-1",
        "content_artifact_id": "content-r",
        "content_hash": "c" * 64,
        "artifact_kind": "merge",
        "memory_tokens_local": 70,
        "capacity_tokens": 100,
        "tokenizer_snapshot": "tokenizer@rev1",
        "serialization_version": "serialization-v1",
        "operator_config_id": "operator-v1",
        "deterministic_operator_hash": None,
        "model_snapshot": "gpt-5.6-sol@rev1",
        "prompt_hash": "a" * 64,
        "creation_event_type": "merge",
        "creation_event_id": "merge-event-1",
        "schema_version": "node-artifact-v1",
        "validation_status": "passed",
        "materialization_source": source,
        "response_hash": "b" * 64,
        "artifact_status": "completed",
    }


def test_plan_metrics_rebuild_from_child_edges_and_preserve_order_roles() -> None:
    nodes = {
        "left": _leaf("left", "leaf-1", 0, 1),
        "right": _leaf("right", "leaf-2", 2, 3),
        "root": _internal("root", "left", "right"),
    }

    metrics = derive_plan_metrics(nodes)

    assert metrics["descendant_leaf_ids"] == ["leaf-1", "leaf-2"]
    assert metrics["leaf_depth_vector"] == {"leaf-1": 1, "leaf-2": 1}
    assert metrics["order_role_path_vector"] == {
        "leaf-1": ["earlier"],
        "leaf-2": ["later"],
    }
    assert metrics["tree_height"] == 1
    assert metrics["critical_path_merge_count"] == 1
    assert metrics["merge_count"] == 1
    assert len(metrics["deterministic_plan_hash"]) == 64


def test_plan_node_raw_rejects_derived_fields_and_invalid_edges() -> None:
    node = _leaf("leaf", "leaf-1", 0, 0)
    node["descendant_leaf_ids"] = ["leaf-1"]
    with pytest.raises(ObservabilityContractError, match="derived"):
        validate_plan_node_raw(node)

    invalid = _internal("root", "left", "right")
    invalid["covered_span"] = [0, 4]
    with pytest.raises(ObservabilityContractError, match="span"):
        derive_plan_metrics({
            "left": _leaf("left", "leaf-1", 0, 1),
            "right": _leaf("right", "leaf-2", 2, 3),
            "root": invalid,
        })


def test_generated_merge_requires_one_accepted_binding_and_matching_output() -> None:
    attempt = _attempt()
    binding = _binding()
    artifact = _node_artifact()
    event = {
        "merge_event_id": "merge-event-1",
        "run_id": "run-1",
        "logical_operation_id": "call-1",
        "accepted_binding_id": "binding-1",
        "left_materialized_node_id": "node-l",
        "right_materialized_node_id": "node-r2",
        "output_materialized_node_id": "node-r",
        "output_budget": 100,
        "materialization_source": "generated",
        "cache_source_artifact_id": None,
        "event_status": "completed",
    }

    validate_accepted_output_binding_raw(binding, attempts={"attempt-1": attempt})
    validate_merge_event_raw(
        event,
        bindings={"binding-1": binding},
        attempts={"attempt-1": attempt},
        artifacts={"node-r": artifact},
    )

    binding["output_artifact_id"] = "wrong-node"
    with pytest.raises(ObservabilityContractError, match="output"):
        validate_merge_event_raw(
            event,
            bindings={"binding-1": binding},
            attempts={"attempt-1": attempt},
            artifacts={"node-r": artifact},
        )


def test_cache_and_deterministic_lineage_do_not_require_api_attempt() -> None:
    cache = _node_artifact("cache")
    cache["creation_event_id"] = "cache-event-1"
    source = {
        **_node_artifact("generated"),
        "materialized_node_id": "source-1",
        "creation_event_id": "source-event-1",
    }
    deterministic = _node_artifact("deterministic")
    deterministic["deterministic_operator_hash"] = "d" * 64
    deterministic["model_snapshot"] = None
    deterministic["prompt_hash"] = None
    deterministic["response_hash"] = None

    content_store = {"content-r": "materialized content"}
    validate_node_artifact(
        cache,
        cache_events={
            "cache-event-1": {
                "materialization_source": "cache",
                "cache_source_artifact_id": "source-1",
            }
        },
        node_artifacts={"source-1": source},
        content_artifacts=content_store,
        accepted_bindings=[],
    )
    validate_node_artifact(
        deterministic,
        content_artifacts=content_store,
        accepted_bindings=[],
    )

    event = {
        "merge_event_id": "cache-event-1",
        "run_id": "run-1",
        "logical_operation_id": "call-1",
        "accepted_binding_id": None,
        "left_materialized_node_id": "node-l",
        "right_materialized_node_id": "node-r2",
        "output_materialized_node_id": "node-r",
        "output_budget": 100,
        "materialization_source": "cache",
        "cache_source_artifact_id": "source-1",
        "event_status": "completed",
    }
    validate_merge_event_raw(event, artifacts={"source-1": source, "node-r": cache})


def test_provider_usage_is_not_conflated_and_work_reconciles() -> None:
    accepted = _attempt("accepted", logical_call_id="call-1")
    nonmaterialized = _attempt(
        "nonmaterialized",
        outcome="successful_nonmaterialized",
        logical_call_id="call-2",
    )
    failed = _attempt(
        "failed",
        outcome="failed_provider",
        logical_call_id="call-3",
    )
    binding = _binding("accepted")
    work = reconcile_work([accepted, nonmaterialized, failed], [binding])

    assert work["accepted_path"]["accepted_merge_input_tokens_total"] == 100
    assert work["accepted_path"]["accepted_merge_cached_input_tokens_subset"] == 20
    assert work["accepted_path"]["accepted_merge_uncached_input_tokens"] == 80
    assert work["observed_operational"]["observed_merge_input_tokens_total"] == 300
    assert work["observed_operational"]["observed_merge_uncached_input_tokens"] == 240
    assert work["observed_operational"]["accepted_materialized_generation_count"] == 1
    assert work["observed_operational"]["successful_nonmaterialized_attempt_count"] == 1
    assert work["observed_operational"]["failed_api_attempt_count"] == 1
    assert "accepted_materialized_generation_count" not in work


def test_missing_provider_usage_is_unknown_and_cached_subset_cannot_exceed_total() -> None:
    missing = _attempt(
        "missing",
        outcome="successful_nonmaterialized",
        source="missing",
        input_tokens=None,
        cached_tokens=None,
        output_tokens=None,
    )
    work = reconcile_work([missing], [])
    assert work["observed_operational"]["observed_merge_input_tokens_total"] == "unknown"

    invalid = _attempt("invalid", cached_tokens=101)
    with pytest.raises(ObservabilityContractError, match="subset"):
        validate_model_call_attempt_raw(invalid)


def test_run_execution_config_freezes_comparable_strategy() -> None:
    config = {
        "executor_config_hash": "a" * 64,
        "executor_mode": "formal",
        "concurrency_limit": 4,
        "cache_mode": "cold",
        "rate_limit_policy_hash": "b" * 64,
        "retry_policy_hash": "c" * 64,
        "provider_route": "direct",
        "run_started_at": "2026-08-03T10:00:00Z",
        "run_finished_at": "2026-08-03T10:01:00Z",
        "replication_index": 0,
        "execution_order_index": 1,
        "run_batch_id": "batch-1",
        "provider_observation_window": "2026-08-03T10:00:00Z/2026-08-03T10:01:00Z",
    }
    assert validate_run_execution_config(config)["cache_mode"] == "cold"
    config["cache_mode"] = "warm"
    with pytest.raises(ObservabilityContractError, match="cold"):
        validate_run_execution_config(config)


def test_support_labels_are_unavailable_until_scoring_boundary() -> None:
    construction = {"stage": "construction", "evidence_ids": ["e1"]}
    assert validate_support_label_boundary(construction)["stage"] == "construction"

    leaked = {"stage": "construction", "gold_answer": "answer"}
    with pytest.raises(ObservabilityContractError, match="support|gold"):
        validate_support_label_boundary(leaked)

    scoring = {
        "stage": "scoring",
        "gold_answer": "answer",
        "supporting_evidence_ids": ["e1"],
        "run_artifacts_frozen": True,
        "score_frozen": True,
        "access_log_id": "access-1",
    }
    assert validate_support_label_boundary(scoring)["supporting_evidence_ids"] == ["e1"]


def test_merge_event_metrics_separate_content_pressure_and_payload_ratio() -> None:
    left = {"materialized_node_id": "left", "memory_tokens_local": 30, "covered_span": [0, 1]}
    right = {"materialized_node_id": "right", "memory_tokens_local": 10, "covered_span": [2, 3]}
    output = {"materialized_node_id": "out", "memory_tokens_local": 20, "covered_span": [0, 3]}
    attempt = _attempt(input_tokens=80, cached_tokens=10, output_tokens=20)
    metrics = derive_merge_event_metrics(
        {
            "output_budget": 40,
            "materialization_source": "generated",
            "left_materialized_node_id": "left",
            "right_materialized_node_id": "right",
            "output_materialized_node_id": "out",
        },
        artifacts={"left": left, "right": right, "out": output},
        attempt=attempt,
    )
    assert metrics["content_to_budget_pressure"] == 1.0
    assert metrics["actual_compression_ratio"] == 0.5
    assert metrics["output_budget_utilization"] == 0.5
    assert metrics["token_imbalance_abs"] == 0.5
    assert metrics["token_imbalance_signed"] == 0.5
    assert metrics["payload_to_budget_ratio"] == 2.25
    assert metrics["generative_rewrite_depth"] == 1
