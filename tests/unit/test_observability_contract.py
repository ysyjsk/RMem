from __future__ import annotations

from copy import deepcopy

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.observability import (
    aggregate_attempt_work,
    answer_input_view,
    build_support_exposure,
    critical_path_elapsed_latency,
    construction_input_view,
    deduplicate_shared_leaf_work,
    derive_evidence_exposure,
    derive_stage_wall_clock,
    derive_plan_metrics,
    estimate_usd_from_usage,
    lifecycle_resource_work,
    parallelism_factor,
    reconcile_work,
    rebuild_observability,
    scoring_input_view,
    validate_accepted_output_binding_raw,
    validate_accepted_output_bindings,
    validate_deployment_state_measurements,
    validate_formal_executor_configs,
    validate_label_access,
    validate_merge_event,
    validate_model_call_attempt,
    validate_node_artifact,
    validate_plan_node_raw,
    validate_provider_usage_scope,
    wall_clock_by_stage,
)


def _plan_nodes() -> list[dict]:
    return [
        {
            "logical_node_id": "leaf-0",
            "plan_id": "p1",
            "node_type": "leaf",
            "leaf_id": "l0",
            "left_logical_child_id": None,
            "right_logical_child_id": None,
            "covered_span": [0, 1],
        },
        {
            "logical_node_id": "leaf-1",
            "plan_id": "p1",
            "node_type": "leaf",
            "leaf_id": "l1",
            "left_logical_child_id": None,
            "right_logical_child_id": None,
            "covered_span": [2, 3],
        },
        {
            "logical_node_id": "root",
            "plan_id": "p1",
            "node_type": "internal",
            "leaf_id": None,
            "left_logical_child_id": "leaf-0",
            "right_logical_child_id": "leaf-1",
            "covered_span": [0, 3],
        },
    ]


def _attempt(*, attempt_id: str = "a1", stage: str = "merge", outcome: str = "accepted_materialized") -> dict:
    return {
        "attempt_id": attempt_id,
        "run_id": "run-1",
        "stage": stage,
        "logical_call_id": f"call-{attempt_id}",
        "accepted_attempt": outcome == "accepted_materialized",
        "retry_index": 0,
        "requested_model": "model-1",
        "returned_model": "model-1",
        "provider": "labforge",
        "provider_route": "https://api.labforge.cc/v1",
        "request_id": f"req-{attempt_id}",
        "prompt_hash": "a" * 64,
        "response_hash": "b" * 64,
        "local_serialized_input_tokens": 20,
        "local_output_content_tokens": 8,
        "tokenizer_snapshot": "tok@1",
        "serialization_version": "chat-v1",
        "provider_input_tokens_total": 20,
        "provider_cached_input_tokens_subset": 5,
        "provider_output_tokens_total": 8,
        "provider_reasoning_tokens_subset": 2,
        "usage_schema_version": "labforge-v1",
        "provider_usage_source": "provider_exact",
        "scheduled_at": "2026-08-03T00:00:00+00:00",
        "started_at": "2026-08-03T00:00:01+00:00",
        "finished_at": "2026-08-03T00:00:03+00:00",
        "http_status": 200,
        "finish_reason": "stop",
        "parse_status": "passed",
        "failure_type": None,
        "attempt_outcome": outcome,
        "status": "completed",
    }


def _artifact(*, source: str = "generated", event_type: str = "merge", event_id: str = "m1") -> dict:
    result = {
        "materialized_node_id": "node-1",
        "logical_node_id": "root",
        "run_id": "run-1",
        "content_artifact_id": "artifact://sha256/bbbb",
        "content_hash": "b" * 64,
        "artifact_kind": "memory_node",
        "memory_tokens_local": 8,
        "capacity_tokens": 16,
        "tokenizer_snapshot": "tok@1",
        "serialization_version": "chat-v1",
        "operator_config_id": "op-1",
        "deterministic_operator_hash": None,
        "model_snapshot": "model-1",
        "prompt_hash": "a" * 64,
        "creation_event_type": event_type,
        "creation_event_id": event_id,
        "schema_version": "observability-v1",
        "validation_status": "passed",
        "materialization_source": source,
        "response_hash": "b" * 64,
        "artifact_status": "available",
    }
    if source == "cache":
        result["model_snapshot"] = None
        result["prompt_hash"] = None
        result["response_hash"] = None
    if source == "deterministic":
        result["model_snapshot"] = None
        result["prompt_hash"] = None
        result["response_hash"] = None
        result["deterministic_operator_hash"] = "c" * 64
    return result


def _binding(*, output_artifact_id: str = "node-1", stage: str = "merge") -> dict:
    return {
        "binding_id": "b1",
        "run_id": "run-1",
        "stage": stage,
        "logical_call_id": "call-a1",
        "accepted_attempt_id": "a1",
        "output_artifact_id": output_artifact_id,
        "binding_status": "succeeded",
    }


def test_plan_node_raw_has_no_derived_fields() -> None:
    node = _plan_nodes()[0]
    node["descendant_leaf_ids"] = ["l0"]
    with pytest.raises(ContractError):
        validate_plan_node_raw(node)


def test_plan_metrics_rebuild_from_child_edges() -> None:
    metrics = derive_plan_metrics(_plan_nodes())
    assert metrics["descendant_leaf_ids"] == ["l0", "l1"]
    assert metrics["leaf_depth_vector"] == {"l0": 1, "l1": 1}
    assert metrics["tree_height"] == 1
    assert metrics["critical_path_merge_count"] == 1
    assert metrics["merge_count"] == 1
    assert metrics["order_role_path_vector"]["l0"] == ["earlier"]


def test_plan_node_raw_rejects_negative_evidence_indexes() -> None:
    node = _plan_nodes()[0]
    node["covered_span"] = [-1, 0]
    with pytest.raises(ContractError, match="evidence indexes"):
        validate_plan_node_raw(node)


def test_evidence_exposure_rebuilds_path_and_cache_does_not_change_semantic_depth() -> None:
    pressures = {"root": {"content_to_budget_pressure": 1.5}}
    generated = derive_evidence_exposure(
        _plan_nodes(),
        merge_metrics_by_logical_node=pressures,
        generative_logical_node_ids={"root"},
    )
    cache_replay = derive_evidence_exposure(
        _plan_nodes(),
        merge_metrics_by_logical_node=pressures,
        generative_logical_node_ids={"root"},
    )
    assert generated == cache_replay
    assert generated["l0"] == {
        "leaf_depth": 1,
        "generative_rewrite_depth": 1,
        "order_role_sequence": ["earlier"],
        "earlier_span_fraction": 1.0,
        "later_span_fraction": 0.0,
        "relative_position": 0.0,
        "pressure_sum": 1.5,
        "pressure_max": 1.5,
    }
    assert generated["l1"]["relative_position"] == 1.0


def test_node_artifact_content_reference_and_source_invariants() -> None:
    artifact = _artifact()
    content_store = {artifact["content_artifact_id"]: "materialized content"}
    validate_node_artifact(
        artifact,
        content_artifacts=content_store,
        accepted_bindings=[_binding()],
    )
    with pytest.raises(ContractError):
        validate_node_artifact(artifact)
    with pytest.raises(ContractError):
        validate_node_artifact(
            artifact,
            content_artifacts={},
            accepted_bindings=[_binding()],
        )
    with pytest.raises(ContractError):
        validate_node_artifact({**_artifact(), "content_artifact_id": "/absolute/local/path"})
    with pytest.raises(ContractError):
        validate_node_artifact({**_artifact(source="cache"), "creation_event_id": None})
    with pytest.raises(ContractError):
        validate_node_artifact(
            {**_artifact(source="deterministic"), "deterministic_operator_hash": None},
            content_artifacts=content_store,
            accepted_bindings=[],
        )


def test_cache_node_artifact_requires_a_matching_cache_creation_event() -> None:
    artifact = _artifact(source="cache")
    source = {
        **_artifact(),
        "materialized_node_id": "source-node",
        "creation_event_id": "source-event",
    }
    content_store = {artifact["content_artifact_id"]: "cached content"}
    event = {
        "merge_event_id": artifact["creation_event_id"],
        "run_id": artifact["run_id"],
        "output_materialized_node_id": artifact["materialized_node_id"],
        "materialization_source": "generated",
        "cache_source_artifact_id": source["materialized_node_id"],
    }
    with pytest.raises(ContractError):
        validate_node_artifact(
            artifact,
            cache_events={artifact["creation_event_id"]: event},
            node_artifacts={source["materialized_node_id"]: source},
            content_artifacts=content_store,
            accepted_bindings=[],
        )

    event["materialization_source"] = "cache"
    validate_node_artifact(
        artifact,
        cache_events={artifact["creation_event_id"]: event},
        node_artifacts={source["materialized_node_id"]: source},
        content_artifacts=content_store,
        accepted_bindings=[],
    )
    mismatched_source = {**source, "content_hash": "d" * 64}
    with pytest.raises(ContractError, match="content lineage"):
        validate_node_artifact(
            artifact,
            cache_events={artifact["creation_event_id"]: event},
            node_artifacts={source["materialized_node_id"]: mismatched_source},
            content_artifacts=content_store,
            accepted_bindings=[],
        )


def test_generated_materialization_has_exactly_one_accepted_attempt() -> None:
    binding = {
        "binding_id": "b1",
        "run_id": "run-1",
        "stage": "merge",
        "logical_call_id": "call-a1",
        "accepted_attempt_id": "a1",
        "output_artifact_id": "node-1",
        "binding_status": "succeeded",
    }
    validate_accepted_output_bindings([_attempt()], [binding])
    with pytest.raises(ContractError):
        validate_accepted_output_bindings([_attempt(), _attempt(attempt_id="a2")], [binding])


def test_binding_status_vocabulary_matches_the_single_run_schema() -> None:
    binding = {
        "binding_id": "b1",
        "run_id": "run-1",
        "stage": "merge",
        "logical_call_id": "call-a1",
        "accepted_attempt_id": "a1",
        "output_artifact_id": "node-1",
        "binding_status": "success",
    }
    with pytest.raises(ContractError):
        validate_accepted_output_bindings([_attempt()], [binding])


@pytest.mark.parametrize("status", ["failed", "invalidated"])
def test_non_succeeded_binding_cannot_retain_accepted_output_references(status: str) -> None:
    binding = {**_binding(), "binding_status": status}
    with pytest.raises(ContractError, match="must have null"):
        validate_accepted_output_binding_raw(binding)

    binding["accepted_attempt_id"] = None
    binding["output_artifact_id"] = None
    validate_accepted_output_binding_raw(binding)


def test_cache_materialization_has_no_fake_api_attempt() -> None:
    output = _artifact(source="cache")
    source = {
        **_artifact(),
        "materialized_node_id": "source-node",
        "creation_event_id": "source-event",
    }
    event = {
        "merge_event_id": "m1",
        "run_id": "run-1",
        "logical_operation_id": "call-a1",
        "accepted_binding_id": None,
        "left_materialized_node_id": "left",
        "right_materialized_node_id": "right",
        "output_materialized_node_id": "node-1",
        "output_budget": 16,
        "materialization_source": "cache",
        "cache_source_artifact_id": source["materialized_node_id"],
        "event_status": "completed",
    }
    validate_merge_event(event, [], [], [source, output])
    with pytest.raises(ContractError):
        validate_merge_event(
            {**event, "accepted_binding_id": "b1"}, [], [], [source, output]
        )


def test_merge_binding_output_matches_materialized_node() -> None:
    event = {
        "merge_event_id": "m1",
        "run_id": "run-1",
        "logical_operation_id": "call-a1",
        "accepted_binding_id": "b1",
        "left_materialized_node_id": "left",
        "right_materialized_node_id": "right",
        "output_materialized_node_id": "node-1",
        "output_budget": 16,
        "materialization_source": "generated",
        "cache_source_artifact_id": None,
        "event_status": "completed",
    }
    binding = {
        "binding_id": "b1",
        "run_id": "run-1",
        "stage": "merge",
        "logical_call_id": "call-a1",
        "accepted_attempt_id": "a1",
        "output_artifact_id": "node-1",
        "binding_status": "succeeded",
    }
    validate_merge_event(event, [_attempt()], [binding], [_artifact()])
    with pytest.raises(ContractError):
        validate_merge_event({**event, "output_materialized_node_id": "other"}, [_attempt()], [binding], [_artifact()])


def test_successful_nonmaterialized_attempt_enters_observed_work() -> None:
    accepted = _attempt()
    nonmaterialized = _attempt(attempt_id="a2", outcome="successful_nonmaterialized")
    totals = aggregate_attempt_work([accepted, nonmaterialized], accepted_attempt_ids={"a1"})
    assert totals["accepted_input_tokens_total"] == 20
    assert totals["observed_input_tokens_total"] == 40
    assert totals["successful_nonmaterialized_attempt_count"] == 1
    assert totals["accepted_materialized_generation_count"] == 1


def test_provider_usage_and_local_tokens_are_not_conflated() -> None:
    attempt = _attempt()
    attempt["provider_input_tokens_total"] = None
    attempt["provider_cached_input_tokens_subset"] = None
    attempt["provider_output_tokens_total"] = None
    attempt["provider_reasoning_tokens_subset"] = None
    attempt["provider_usage_source"] = "missing"
    validate_model_call_attempt(attempt)
    totals = aggregate_attempt_work([attempt], accepted_attempt_ids=set())
    assert totals["observed_input_tokens_total"] == "unknown"
    assert totals["local_input_tokens_total"] == 20


def test_cached_input_is_subset_and_not_double_counted() -> None:
    assert aggregate_attempt_work([_attempt()], accepted_attempt_ids={"a1"})["accepted_uncached_input_tokens"] == 15
    bad = _attempt()
    bad["provider_cached_input_tokens_subset"] = 21
    with pytest.raises(ContractError):
        validate_model_call_attempt(bad)


def test_model_call_attempt_http_status_matches_schema_range() -> None:
    bad = _attempt()
    bad["http_status"] = 600
    with pytest.raises(ContractError, match="HTTP"):
        validate_model_call_attempt(bad)


def test_missing_provider_usage_requires_null_provider_fields() -> None:
    bad = _attempt()
    bad["provider_usage_source"] = "missing"
    with pytest.raises(ContractError):
        validate_model_call_attempt(bad)


def test_estimated_usd_rebuilds_from_usage_and_pricing_manifest() -> None:
    manifest = {
        "provider": "labforge",
        "model": "model-1",
        "provider_route": "https://api.labforge.cc/v1",
        "usage_schema_version": "labforge-v1",
        "uncached_input_usd_per_million": 1.0,
        "cached_input_usd_per_million": 0.5,
        "output_usd_per_million": 2.0,
        "request_fee_usd": 0.0,
    }
    value = estimate_usd_from_usage({"input_total": 20, "cached_input": 5, "output_total": 8, "request_count": 1}, manifest)
    assert value == pytest.approx((15 + 2.5 + 16) / 1_000_000)


def test_deployment_state_excludes_experiment_artifacts() -> None:
    from plan_robust_memory.observability import deployment_state_tokens

    measurement = {
        "deployment_memory_tokens": 32,
        "deployment_metadata_bytes": 16,
        "deployment_capability_profile": "FINAL_QUERY_ONLY",
        "deployment_state_measurement_protocol": "offline-final-view-v1",
        "deployment_state_measurement_point": "after-final-view-before-answer",
        "artifact_cache_bytes": 999999,
    }
    state = deployment_state_tokens(measurement)
    assert state == 32
    validate_deployment_state_measurements([measurement, dict(measurement)])

    changed_point = {**measurement, "deployment_state_measurement_point": "after-answer"}
    with pytest.raises(ContractError, match="measurement"):
        validate_deployment_state_measurements([measurement, changed_point])


def test_support_mapping_and_unique_leaf_aggregation() -> None:
    rows = [
        {"annotation_id": "a1", "support_mapping_status": "exact", "mapped_evidence_ids": ["e1"], "mapped_chunk_ids": ["c1"], "mapped_leaf_ids": ["l1"], "rewrite_depth": 2, "pressure": 0.5, "order_role": "earlier"},
        {"annotation_id": "a2", "support_mapping_status": "expanded_to_chunks", "mapped_evidence_ids": ["e2"], "mapped_chunk_ids": ["c2"], "mapped_leaf_ids": ["l2"], "rewrite_depth": 4, "pressure": 0.9, "order_role": "later"},
    ]
    summary = build_support_exposure(rows)
    assert summary["unique_supporting_leaf_count"] == 2
    assert summary["annotated_support_rewrite_mean"] == pytest.approx(3)
    assert summary["annotated_support_rewrite_max"] == 4
    with pytest.raises(ContractError):
        build_support_exposure([{**rows[0], "support_mapping_status": "unknown"}])


@pytest.mark.parametrize(
    "field,value",
    [
        ("rewrite_depth", "not-a-number"),
        ("pressure", float("nan")),
    ],
)
def test_support_exposure_rejects_invalid_numeric_values(field: str, value: object) -> None:
    row = {
        "support_mapping_status": "exact",
        "mapped_evidence_ids": ["e1"],
        "mapped_chunk_ids": ["c1"],
        "mapped_leaf_ids": ["l1"],
        "rewrite_depth": 1,
        "pressure": 0.5,
        "order_role": "earlier",
        field: value,
    }
    with pytest.raises(ContractError):
        build_support_exposure([row])


def test_support_labels_are_stage_gated() -> None:
    validate_label_access("scoring", {"gold_answer": "x", "supporting_evidence_ids": [], "run_artifacts_frozen": True, "answer_artifacts_frozen": True, "access_log_id": "access-1"})
    with pytest.raises(ContractError):
        validate_label_access("construction", {"supporting_evidence_ids": ["e1"]})
    with pytest.raises(ContractError):
        validate_label_access("answer", {"gold_answer": "x"})


def test_label_access_payload_cannot_override_the_caller_stage() -> None:
    with pytest.raises(ContractError):
        validate_label_access(
            "construction",
            {
                "stage": "scoring",
                "gold_answer": "secret",
                "run_artifacts_frozen": True,
                "answer_artifacts_frozen": True,
                "access_log_id": "forged-access",
            },
        )


def test_stage_views_apply_whitelists_instead_of_forwarding_protected_records() -> None:
    construction = construction_input_view(
        raw_evidence=["e1"], leaf_configuration={"k": 4}, plan={"plan_id": "p1"}
    )
    assert "gold_answer" not in construction
    with pytest.raises(ContractError):
        answer_input_view(
            final_memory="memory",
            query={"query_text": "q", "gold_answer": "secret"},
            answer_configuration={"model": "m"},
        )
    scoring = scoring_input_view(
        frozen_run_artifacts={"run_id": "r1"},
        frozen_answer={"answer_id": "a1"},
        protected_labels={"gold_answer": "secret", "supporting_evidence_ids": ["e1"]},
        evaluator={"evaluator_id": "eval1"},
        access_log_id="access1",
    )
    assert scoring["gold_answer"] == "secret"


def test_stage_views_reject_nested_labels_and_nonlabel_scoring_fields() -> None:
    with pytest.raises(ContractError):
        construction_input_view(
            raw_evidence=[{"metadata": {"supporting_evidence_ids": ["e1"]}}],
            leaf_configuration={"k": 4},
            plan={"plan_id": "p1"},
        )
    with pytest.raises(ContractError):
        answer_input_view(
            final_memory="memory",
            query={"query_text": "q", "metadata": {"gold_answer": "secret"}},
            answer_configuration={"model": "m"},
        )
    with pytest.raises(ContractError):
        scoring_input_view(
            frozen_run_artifacts={"run_id": "r1"},
            frozen_answer={"answer_id": "a1"},
            protected_labels={"gold_answer": "secret", "stage": "scoring"},
            evaluator={"evaluator_id": "eval1"},
            access_log_id="access1",
        )


def test_formal_runs_share_executor_config() -> None:
    base = {"executor_config_hash": "h1", "executor_mode": "bounded", "concurrency_limit": 2, "cache_mode": "cold", "retry_policy_hash": "r1", "rate_limit_policy_hash": "l1", "provider_route": "route"}
    validate_formal_executor_configs([base, dict(base)])
    with pytest.raises(ContractError):
        validate_formal_executor_configs([base, {**base, "concurrency_limit": 3}])


def test_stage_wall_clock_and_parallelism_are_rebuildable() -> None:
    attempts = [_attempt(attempt_id="a1")]
    boundaries = {
        stage: {
            "status": "recorded",
            "first_logical_operation_scheduled_at": "2026-08-03T00:00:00Z",
            "last_required_artifact_persisted_at": "2026-08-03T00:00:03Z",
        }
        for stage in ("leaf", "merge", "answer", "judge")
    }
    with pytest.raises(ContractError):
        wall_clock_by_stage(attempts)
    assert wall_clock_by_stage(boundaries)["merge"] == pytest.approx(3.0)
    assert parallelism_factor(
        attempts, stage_timing_boundaries=boundaries
    ) == pytest.approx(2 / 3)
    assert critical_path_elapsed_latency([{"operation_id": "a", "depends_on": [], "operation_elapsed_latency": 2.0}, {"operation_id": "b", "depends_on": ["a"], "operation_elapsed_latency": 3.0}]) == pytest.approx(5.0)


def test_stage_wall_clock_uses_scheduled_to_persisted_boundaries() -> None:
    boundaries = {
        stage: {
            "status": "recorded",
            "first_logical_operation_scheduled_at": "2026-08-03T00:00:00Z",
            "last_required_artifact_persisted_at": "2026-08-03T00:00:05Z",
        }
        for stage in ("leaf", "merge", "answer", "judge")
    }
    assert derive_stage_wall_clock(boundaries) == {
        "leaf": 5.0,
        "merge": 5.0,
        "answer": 5.0,
        "judge": 5.0,
    }


def test_provider_scope_is_fixed_and_shared_leaf_work_is_deduplicated() -> None:
    first = _attempt(stage="leaf")
    second = deepcopy(first)
    second["attempt_id"] = "a2"
    second["request_id"] = "req-a2"
    second["logical_call_id"] = "call-a2"
    second["accepted_attempt"] = False
    second["attempt_outcome"] = "successful_nonmaterialized"
    validate_provider_usage_scope([first, second])
    with pytest.raises(ContractError):
        validate_provider_usage_scope([first, {**second, "provider_route": "other"}])

    row = {
        "content_artifact_id": "leaf-content-1",
        "provider_usage_source": "provider_exact",
        "provider_input_tokens_total": 20,
        "provider_cached_input_tokens_subset": 5,
        "provider_output_tokens_total": 8,
    }
    totals = deduplicate_shared_leaf_work([row, dict(row)])
    assert totals["unique_shared_leaf_count"] == 1
    assert totals["shared_leaf_input_tokens_total"] == 20


@pytest.mark.parametrize(
    "bad_row",
    [
        {"content_artifact_id": "leaf-content-1"},
        {
            "content_artifact_id": "leaf-content-1",
            "provider_usage_source": "provider_exact",
            "provider_input_tokens_total": "20",
            "provider_cached_input_tokens_subset": 5,
            "provider_output_tokens_total": 8,
        },
        {
            "content_artifact_id": "leaf-content-1",
            "provider_usage_source": "provider_exact",
            "provider_input_tokens_total": 20,
            "provider_cached_input_tokens_subset": 21,
            "provider_output_tokens_total": 8,
        },
    ],
)
def test_shared_leaf_usage_rows_fail_closed(bad_row: dict) -> None:
    with pytest.raises(ContractError):
        deduplicate_shared_leaf_work([bad_row])


def test_shared_leaf_duplicate_rows_include_reasoning_usage_in_identity() -> None:
    row = {
        "content_artifact_id": "leaf-content-1",
        "provider_usage_source": "provider_exact",
        "provider_input_tokens_total": 20,
        "provider_cached_input_tokens_subset": 5,
        "provider_output_tokens_total": 8,
        "provider_reasoning_tokens_subset": 2,
    }
    with pytest.raises(ContractError, match="disagree"):
        deduplicate_shared_leaf_work(
            [row, {**row, "provider_reasoning_tokens_subset": 3}]
        )


@pytest.mark.parametrize(
    "call",
    [
        lambda: validate_plan_node_raw(None),
        lambda: validate_model_call_attempt(None),
        lambda: validate_accepted_output_binding_raw(None),
        lambda: build_support_exposure([None]),
        lambda: deduplicate_shared_leaf_work([None]),
    ],
)
def test_public_observability_boundaries_reject_non_mapping_inputs(call) -> None:
    with pytest.raises(ContractError):
        call()


def test_judge_overhead_is_excluded_from_lifecycle_resource_work() -> None:
    accepted = _attempt()
    judge = _attempt(attempt_id="judge-a1", stage="judge")
    bindings = [
        {
            "binding_id": "b1",
            "run_id": "run-1",
            "stage": "merge",
            "logical_call_id": "call-a1",
            "accepted_attempt_id": "a1",
            "output_artifact_id": "node-1",
            "binding_status": "succeeded",
        },
        {
            "binding_id": "judge-b1",
            "run_id": "run-1",
            "stage": "judge",
            "logical_call_id": "call-judge-a1",
            "accepted_attempt_id": "judge-a1",
            "output_artifact_id": "judge-output-1",
            "binding_status": "succeeded",
        },
    ]
    reconciled = reconcile_work([accepted, judge], bindings)
    lifecycle = lifecycle_resource_work(reconciled)
    assert "accepted_judge_input_tokens_total" not in lifecycle
    assert reconciled["judge_overhead"]["accepted_judge_input_tokens_total"] == 20
    assert reconciled["observed_operational"]["api_attempt_count"] == 1
    assert reconciled["observed_operational"]["accepted_materialized_generation_count"] == 1


def test_raw_artifacts_rebuild_all_mandatory_derived_layers() -> None:
    attempt = _attempt()
    attempt["logical_call_id"] = "root"
    binding = {
        "binding_id": "b1",
        "run_id": "run-1",
        "stage": "merge",
        "logical_call_id": "root",
        "accepted_attempt_id": "a1",
        "output_artifact_id": "node-root",
        "binding_status": "succeeded",
    }
    event = {
        "merge_event_id": "m1",
        "run_id": "run-1",
        "logical_operation_id": "root",
        "accepted_binding_id": "b1",
        "left_materialized_node_id": "node-left",
        "right_materialized_node_id": "node-right",
        "output_materialized_node_id": "node-root",
        "output_budget": 16,
        "materialization_source": "generated",
        "cache_source_artifact_id": None,
        "event_status": "completed",
    }
    left = {
        **_artifact(source="deterministic", event_type="leaf", event_id="left-event"),
        "materialized_node_id": "node-left",
        "logical_node_id": "leaf-0",
        "content_artifact_id": "artifact://sha256/left",
        "content_hash": "1" * 64,
    }
    right = {
        **_artifact(source="deterministic", event_type="leaf", event_id="right-event"),
        "materialized_node_id": "node-right",
        "logical_node_id": "leaf-1",
        "content_artifact_id": "artifact://sha256/right",
        "content_hash": "2" * 64,
    }
    root = {
        **_artifact(),
        "materialized_node_id": "node-root",
        "content_artifact_id": "artifact://sha256/root",
        "content_hash": "3" * 64,
    }
    artifacts = {row["materialized_node_id"]: row for row in (left, right, root)}
    content_artifacts = {
        left["content_artifact_id"]: "left",
        right["content_artifact_id"]: "right",
        root["content_artifact_id"]: "root",
    }
    rebuilt = rebuild_observability(
        plan_nodes=_plan_nodes(),
        merge_events=[event],
        artifacts=artifacts,
        attempts=[attempt],
        bindings=[binding],
        content_artifacts=content_artifacts,
    )
    assert rebuilt["plan_metrics"]["critical_path_merge_count"] == 1
    assert rebuilt["merge_event_metrics"][0]["content_to_budget_pressure"] == 1
    assert rebuilt["evidence_exposure"]["l0"]["generative_rewrite_depth"] == 1
    assert rebuilt["resource_work"]["observed_operational"]["accepted_materialized_generation_count"] == 1

    cached_event = {
        **event,
        "accepted_binding_id": None,
        "materialization_source": "cache",
        "cache_source_artifact_id": "source-root",
    }
    cached_artifacts = deepcopy(artifacts)
    cached_artifacts["node-root"]["materialization_source"] = "cache"
    source_root = {
        **deepcopy(root),
        "materialized_node_id": "source-root",
        "creation_event_id": "source-event",
    }
    cached = rebuild_observability(
        plan_nodes=_plan_nodes(),
        merge_events=[cached_event],
        artifacts=cached_artifacts,
        attempts=[],
        bindings=[],
        content_artifacts=content_artifacts,
        cache_source_artifacts={"source-root": source_root},
    )
    assert cached["evidence_exposure"]["l0"]["generative_rewrite_depth"] == 1
    assert cached["resource_work"]["observed_operational"]["cache_hit_count"] == 1

    incomplete_artifacts = deepcopy(artifacts)
    del incomplete_artifacts["node-left"]["capacity_tokens"]
    with pytest.raises(ContractError, match="NodeArtifact is missing fields"):
        rebuild_observability(
            plan_nodes=_plan_nodes(),
            merge_events=[event],
            artifacts=incomplete_artifacts,
            attempts=[attempt],
            bindings=[binding],
            content_artifacts=content_artifacts,
        )
