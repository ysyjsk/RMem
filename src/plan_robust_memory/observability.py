from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from statistics import fmean
from typing import Any

from .contracts import ContractError
from .hashing import stable_hash


class ObservabilityContractError(ContractError):
    """Raised when a raw observability artifact violates the frozen contract."""


_PLAN_NODE_FIELDS = {
    "logical_node_id",
    "plan_id",
    "node_type",
    "leaf_id",
    "left_logical_child_id",
    "right_logical_child_id",
    "covered_span",
}
_DERIVED_PLAN_FIELDS = {
    "descendant_leaf_ids",
    "tree_level",
    "depth_to_root",
    "role_path",
    "order_role_path",
    "critical_path",
    "critical_path_merge_count",
}
_NODE_ARTIFACT_FIELDS = {
    "materialized_node_id",
    "logical_node_id",
    "run_id",
    "content_artifact_id",
    "content_hash",
    "artifact_kind",
    "memory_tokens_local",
    "capacity_tokens",
    "tokenizer_snapshot",
    "serialization_version",
    "operator_config_id",
    "deterministic_operator_hash",
    "model_snapshot",
    "prompt_hash",
    "creation_event_type",
    "creation_event_id",
    "schema_version",
    "validation_status",
    "materialization_source",
    "response_hash",
    "artifact_status",
}
_ATTEMPT_FIELDS = {
    "attempt_id",
    "run_id",
    "stage",
    "logical_call_id",
    "accepted_attempt",
    "retry_index",
    "requested_model",
    "returned_model",
    "provider",
    "provider_route",
    "request_id",
    "prompt_hash",
    "response_hash",
    "local_serialized_input_tokens",
    "local_output_content_tokens",
    "tokenizer_snapshot",
    "serialization_version",
    "provider_input_tokens_total",
    "provider_cached_input_tokens_subset",
    "provider_output_tokens_total",
    "provider_reasoning_tokens_subset",
    "usage_schema_version",
    "provider_usage_source",
    "scheduled_at",
    "started_at",
    "finished_at",
    "http_status",
    "finish_reason",
    "parse_status",
    "failure_type",
    "attempt_outcome",
    "status",
}
_BINDING_FIELDS = {
    "binding_id",
    "run_id",
    "stage",
    "logical_call_id",
    "accepted_attempt_id",
    "output_artifact_id",
    "binding_status",
}
_MERGE_EVENT_FIELDS = {
    "merge_event_id",
    "run_id",
    "logical_operation_id",
    "accepted_binding_id",
    "left_materialized_node_id",
    "right_materialized_node_id",
    "output_materialized_node_id",
    "output_budget",
    "materialization_source",
    "cache_source_artifact_id",
    "event_status",
}
_STAGES = {"leaf", "merge", "answer", "judge"}
_MATERIALIZATION_SOURCES = {"generated", "cache", "deterministic"}
_PROVIDER_USAGE_SOURCES = {"provider_exact", "provider_estimated", "missing"}
_ATTEMPT_OUTCOMES = {
    "accepted_materialized",
    "successful_nonmaterialized",
    "failed_provider",
    "failed_parse",
    "failed_validation",
    "cancelled_before_start",
    "cancelled_after_start",
}
_BINDING_STATUSES = {"succeeded", "failed", "invalidated"}
_SUCCESSFUL_BINDING_STATUSES = {"succeeded"}
_DEPLOYMENT_PROFILES = {
    "FINAL_QUERY_ONLY",
    "FINAL_QUERY_AND_APPEND",
    "PREFIX_QUERY_AND_APPEND",
    "FULL_ONLINE_RECOVERY",
}

_CACHE_CONTENT_LINEAGE_FIELDS = (
    "content_artifact_id",
    "content_hash",
    "memory_tokens_local",
    "tokenizer_snapshot",
    "serialization_version",
)


def _require_mapping(value: Any, object_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ObservabilityContractError(f"{object_name} must be an object")
    return value
_PROTECTED_LABEL_FIELDS = {
    "gold_answer",
    "supporting_evidence_ids",
    "supporting_session_ids",
    "support_annotations",
}
_QUERY_FIELDS = {"query", "query_id", "query_text"}


def _require_exact_fields(record: Mapping[str, Any], allowed: set[str], object_name: str) -> None:
    _require_mapping(record, object_name)
    missing = allowed - set(record)
    if missing:
        raise ObservabilityContractError(
            f"{object_name} is missing fields: {', '.join(sorted(missing))}"
        )
    extras = set(record) - allowed
    if extras:
        label = "derived fields" if extras & _DERIVED_PLAN_FIELDS else "unknown fields"
        raise ObservabilityContractError(
            f"{object_name} contains {label}: {', '.join(sorted(extras))}"
        )


def _require_string(record: Mapping[str, Any], field: str, *, nullable: bool = False) -> None:
    value = record.get(field)
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ObservabilityContractError(f"{field} must be a non-empty string")


def _require_nonnegative_int(value: Any, field: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ObservabilityContractError(f"{field} must be a non-negative integer")


def _require_positive_int(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ObservabilityContractError(f"{field} must be a positive integer")


def _parse_timestamp(value: Any, field: str, *, nullable: bool = False) -> datetime | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ObservabilityContractError(f"{field} must be an ISO-8601 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ObservabilityContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ObservabilityContractError(f"{field} must include a timezone")
    return parsed


def _as_record_map(
    records: Mapping[str, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    id_field: str,
) -> dict[str, Mapping[str, Any]]:
    if isinstance(records, Mapping):
        result = dict(records)
        for key, record in result.items():
            if not isinstance(record, Mapping):
                raise ObservabilityContractError(f"{id_field} records must be objects")
            if record.get(id_field) != key:
                raise ObservabilityContractError(f"{id_field} mapping key does not match the record")
        return result

    try:
        iterator = iter(records)
    except TypeError as exc:
        raise ObservabilityContractError(f"{id_field} records must be iterable objects") from exc
    result: dict[str, Mapping[str, Any]] = {}
    for record in iterator:
        if not isinstance(record, Mapping):
            raise ObservabilityContractError(f"{id_field} records must be objects")
        identifier = record.get(id_field)
        if not isinstance(identifier, str) or not identifier:
            raise ObservabilityContractError(f"{id_field} must be a non-empty string")
        if identifier in result:
            raise ObservabilityContractError(f"duplicate {id_field}: {identifier}")
        result[identifier] = record
    return result


def validate_plan_node_raw(node: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_exact_fields(node, _PLAN_NODE_FIELDS, "PlanNodeRaw")
    _require_string(node, "logical_node_id")
    _require_string(node, "plan_id")
    span = node.get("covered_span")
    if (
        not isinstance(span, (list, tuple))
        or len(span) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in span)
        or any(item < 0 for item in span)
        or span[0] > span[1]
    ):
        raise ObservabilityContractError("covered_span must be an ordered pair of evidence indexes")

    node_type = node.get("node_type")
    if node_type == "leaf":
        _require_string(node, "leaf_id")
        if node.get("left_logical_child_id") is not None or node.get("right_logical_child_id") is not None:
            raise ObservabilityContractError("leaf PlanNodeRaw cannot contain child edges")
    elif node_type == "internal":
        if node.get("leaf_id") is not None:
            raise ObservabilityContractError("internal PlanNodeRaw cannot contain leaf_id")
        _require_string(node, "left_logical_child_id")
        _require_string(node, "right_logical_child_id")
        if node["left_logical_child_id"] == node["right_logical_child_id"]:
            raise ObservabilityContractError("internal PlanNodeRaw children must be distinct")
    else:
        raise ObservabilityContractError("node_type must be leaf or internal")
    return node


def derive_plan_metrics(
    nodes: Mapping[str, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    node_map = _as_record_map(nodes, "logical_node_id")
    if not node_map:
        raise ObservabilityContractError("PlanMetrics requires at least one PlanNodeRaw")
    for node in node_map.values():
        validate_plan_node_raw(node)
    plan_ids = {node["plan_id"] for node in node_map.values()}
    if len(plan_ids) != 1:
        raise ObservabilityContractError("PlanMetrics cannot combine multiple plans")

    child_ids: set[str] = set()
    for node in node_map.values():
        if node["node_type"] == "internal":
            child_ids.add(str(node["left_logical_child_id"]))
            child_ids.add(str(node["right_logical_child_id"]))
    unknown_children = child_ids - set(node_map)
    if unknown_children:
        raise ObservabilityContractError(
            f"PlanNodeRaw child edge references unknown nodes: {', '.join(sorted(unknown_children))}"
        )
    roots = set(node_map) - child_ids
    if len(roots) != 1:
        raise ObservabilityContractError("PlanNodeRaw child graph must have exactly one root")
    root_id = next(iter(roots))

    visiting: set[str] = set()
    visited: set[str] = set()
    descendants_by_node: dict[str, tuple[str, ...]] = {}
    heights: dict[str, int] = {}

    def rebuild(node_id: str) -> tuple[tuple[str, ...], int]:
        if node_id in visiting:
            raise ObservabilityContractError("PlanNodeRaw child graph contains a cycle")
        if node_id in visited:
            return descendants_by_node[node_id], heights[node_id]
        visiting.add(node_id)
        node = node_map[node_id]
        if node["node_type"] == "leaf":
            leaves = (str(node["leaf_id"]),)
            height = 0
        else:
            left_id = str(node["left_logical_child_id"])
            right_id = str(node["right_logical_child_id"])
            left_leaves, left_height = rebuild(left_id)
            right_leaves, right_height = rebuild(right_id)
            left_span = node_map[left_id]["covered_span"]
            right_span = node_map[right_id]["covered_span"]
            expected_span = [left_span[0], right_span[1]]
            if left_span[1] + 1 != right_span[0] or list(node["covered_span"]) != expected_span:
                raise ObservabilityContractError(
                    "PlanNodeRaw internal span must be the contiguous, order-preserving union of child spans"
                )
            leaves = (*left_leaves, *right_leaves)
            height = 1 + max(left_height, right_height)
        visiting.remove(node_id)
        visited.add(node_id)
        descendants_by_node[node_id] = leaves
        heights[node_id] = height
        return leaves, height

    root_leaves, tree_height = rebuild(root_id)
    if visited != set(node_map):
        raise ObservabilityContractError("PlanNodeRaw child graph contains disconnected nodes")
    if len(root_leaves) != len(set(root_leaves)):
        raise ObservabilityContractError("PlanNodeRaw child graph reuses a leaf")

    leaf_depth_vector: dict[str, int] = {}
    order_role_path_vector: dict[str, list[str]] = {}

    def walk(node_id: str, depth: int, path: tuple[str, ...]) -> None:
        node = node_map[node_id]
        if node["node_type"] == "leaf":
            leaf_id = str(node["leaf_id"])
            leaf_depth_vector[leaf_id] = depth
            order_role_path_vector[leaf_id] = list(path)
            return
        walk(str(node["left_logical_child_id"]), depth + 1, (*path, "earlier"))
        walk(str(node["right_logical_child_id"]), depth + 1, (*path, "later"))

    walk(root_id, 0, ())
    normalized_nodes = [dict(node_map[node_id]) for node_id in sorted(node_map)]
    return {
        "descendant_leaf_ids": list(root_leaves),
        "leaf_depth_vector": leaf_depth_vector,
        "order_role_path_vector": order_role_path_vector,
        "tree_height": tree_height,
        "critical_path_merge_count": tree_height,
        "merge_count": sum(node["node_type"] == "internal" for node in node_map.values()),
        "deterministic_plan_hash": stable_hash(normalized_nodes),
    }


def derive_evidence_exposure(
    nodes: Mapping[str, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    *,
    merge_metrics_by_logical_node: Mapping[str, Mapping[str, Any]],
    generative_logical_node_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Rebuild per-leaf structural and pressure exposure from frozen lineage."""
    _require_mapping(merge_metrics_by_logical_node, "MergeEventMetrics map")
    node_map = _as_record_map(nodes, "logical_node_id")
    plan_metrics = derive_plan_metrics(node_map)
    internal_ids = {
        node_id for node_id, node in node_map.items() if node["node_type"] == "internal"
    }
    if not generative_logical_node_ids <= internal_ids:
        raise ObservabilityContractError(
            "generative rewrite lineage references a non-internal logical node"
        )
    parent_by_child: dict[str, tuple[str, str]] = {}
    leaf_node_by_id: dict[str, str] = {}
    for node_id, node in node_map.items():
        if node["node_type"] == "leaf":
            leaf_node_by_id[str(node["leaf_id"])] = node_id
            continue
        for child_field, role in (
            ("left_logical_child_id", "earlier"),
            ("right_logical_child_id", "later"),
        ):
            child_id = str(node[child_field])
            if child_id in parent_by_child:
                raise ObservabilityContractError(
                    "PlanNodeRaw child cannot have multiple logical parents"
                )
            parent_by_child[child_id] = (node_id, role)

    leaf_order = list(plan_metrics["descendant_leaf_ids"])
    denominator = max(len(leaf_order) - 1, 1)
    result: dict[str, dict[str, Any]] = {}
    for position, leaf_id in enumerate(leaf_order):
        node_id = leaf_node_by_id[leaf_id]
        parent_path: list[str] = []
        roles_leaf_to_root: list[str] = []
        while node_id in parent_by_child:
            parent_id, role = parent_by_child[node_id]
            parent_path.append(parent_id)
            roles_leaf_to_root.append(role)
            node_id = parent_id
        roles = list(reversed(roles_leaf_to_root))
        generative_path = [
            parent_id for parent_id in parent_path if parent_id in generative_logical_node_ids
        ]
        pressures: list[float] = []
        for parent_id in generative_path:
            metric = merge_metrics_by_logical_node.get(parent_id)
            if not isinstance(metric, Mapping):
                raise ObservabilityContractError(
                    "generative evidence path is missing MergeEventMetrics"
                )
            pressure = metric.get("content_to_budget_pressure")
            if isinstance(pressure, bool) or not isinstance(pressure, (int, float)) or pressure < 0:
                raise ObservabilityContractError(
                    "content_to_budget_pressure must be a non-negative number"
                )
            pressures.append(float(pressure))
        depth = len(roles)
        result[leaf_id] = {
            "leaf_depth": depth,
            "generative_rewrite_depth": len(generative_path),
            "order_role_sequence": roles,
            "earlier_span_fraction": roles.count("earlier") / depth if depth else 0.0,
            "later_span_fraction": roles.count("later") / depth if depth else 0.0,
            "relative_position": position / denominator if len(leaf_order) > 1 else 0.0,
            "pressure_sum": sum(pressures),
            "pressure_max": max(pressures, default=0.0),
        }
    return result


def _content_reference_is_stable(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value.startswith(("/", "file://")):
        return False
    if len(value) >= 3 and value[1:3] in {":/", ":\\"}:
        return False
    return True


def _resolve_content_artifact(
    content_artifacts: Mapping[str, Any] | Callable[[str], Any] | None,
    content_id: str,
) -> Any:
    if content_artifacts is None:
        raise ObservabilityContractError(
            "NodeArtifact validation requires a content resolver"
        )
    if isinstance(content_artifacts, Mapping):
        return content_artifacts.get(content_id)
    if callable(content_artifacts):
        return content_artifacts(content_id)
    raise ObservabilityContractError("NodeArtifact content resolver is invalid")


def _validate_node_artifact_intrinsic(
    artifact: Mapping[str, Any],
    *,
    content_artifacts: Mapping[str, Any] | Callable[[str], Any] | None,
    object_name: str,
) -> str:
    _require_exact_fields(artifact, _NODE_ARTIFACT_FIELDS, object_name)
    for field in (
        "materialized_node_id",
        "logical_node_id",
        "run_id",
        "content_hash",
        "artifact_kind",
        "tokenizer_snapshot",
        "serialization_version",
        "operator_config_id",
        "creation_event_type",
        "creation_event_id",
        "schema_version",
        "validation_status",
        "artifact_status",
    ):
        _require_string(artifact, field)
    if not _content_reference_is_stable(artifact.get("content_artifact_id")):
        raise ObservabilityContractError(
            "content_artifact_id must be a stable artifact reference, not an absolute local path"
        )
    _require_nonnegative_int(artifact.get("memory_tokens_local"), "memory_tokens_local")
    _require_positive_int(artifact.get("capacity_tokens"), "capacity_tokens")
    if artifact["memory_tokens_local"] > artifact["capacity_tokens"]:
        raise ObservabilityContractError("memory_tokens_local exceeds capacity_tokens")
    content_id = str(artifact["content_artifact_id"])
    if _resolve_content_artifact(content_artifacts, content_id) is None:
        raise ObservabilityContractError("NodeArtifact content reference is not resolvable")
    source = artifact.get("materialization_source")
    if source not in _MATERIALIZATION_SOURCES:
        raise ObservabilityContractError(
            "materialization_source must be generated, cache, or deterministic"
        )
    if source == "generated":
        for field in ("model_snapshot", "prompt_hash", "response_hash"):
            _require_string(artifact, field)
    elif source == "deterministic":
        _require_string(artifact, "deterministic_operator_hash")
    return str(source)


def _resolve_node_artifact(
    artifacts: Mapping[str, Mapping[str, Any]] | Callable[[str], Mapping[str, Any] | None],
    artifact_id: str,
) -> Mapping[str, Any] | None:
    if isinstance(artifacts, Mapping):
        resolved = artifacts.get(artifact_id)
    elif callable(artifacts):
        resolved = artifacts(artifact_id)
    else:
        raise ObservabilityContractError("cache source artifact resolver is invalid")
    if resolved is None:
        return None
    return _require_mapping(resolved, "cache source NodeArtifact")


def _validate_cache_content_lineage(
    output: Mapping[str, Any],
    source: Mapping[str, Any],
    *,
    source_artifact_id: str,
) -> None:
    _require_exact_fields(source, _NODE_ARTIFACT_FIELDS, "cache source NodeArtifact")
    if source.get("materialized_node_id") != source_artifact_id:
        raise ObservabilityContractError(
            "cache_source_artifact_id does not match the resolved NodeArtifact identity"
        )
    if source_artifact_id == output.get("materialized_node_id"):
        raise ObservabilityContractError("cache materialization cannot reference itself")
    mismatches = [
        field
        for field in _CACHE_CONTENT_LINEAGE_FIELDS
        if source.get(field) != output.get(field)
    ]
    if mismatches:
        raise ObservabilityContractError(
            "cache source and output content lineage disagree on: "
            + ", ".join(mismatches)
        )


def validate_node_artifact(
    artifact: Mapping[str, Any],
    *,
    cache_events: Mapping[str, Mapping[str, Any]] | None = None,
    node_artifacts: (
        Mapping[str, Mapping[str, Any]]
        | Callable[[str], Mapping[str, Any] | None]
        | None
    ) = None,
    content_artifacts: Mapping[str, Any] | Callable[[str], Any] | None = None,
    accepted_bindings: Iterable[Mapping[str, Any]] | None = None,
) -> Mapping[str, Any]:
    source = _validate_node_artifact_intrinsic(
        artifact,
        content_artifacts=content_artifacts,
        object_name="NodeArtifact",
    )
    if accepted_bindings is None:
        raise ObservabilityContractError(
            "NodeArtifact validation requires the complete accepted binding set"
        )
    binding_records = list(accepted_bindings)
    for binding in binding_records:
        validate_accepted_output_binding_raw(binding)
    matching_bindings = [
        binding
        for binding in binding_records
        if binding.get("binding_status") in _SUCCESSFUL_BINDING_STATUSES
        and binding.get("output_artifact_id") == artifact["materialized_node_id"]
    ]

    if source == "generated":
        if len(matching_bindings) != 1:
            raise ObservabilityContractError(
                "generated NodeArtifact must have exactly one accepted output binding"
            )
        binding = matching_bindings[0]
        if binding["run_id"] != artifact["run_id"]:
            raise ObservabilityContractError(
                "generated NodeArtifact binding run does not match the artifact"
            )
        if artifact["creation_event_type"] in _STAGES and (
            binding["stage"] != artifact["creation_event_type"]
        ):
            raise ObservabilityContractError(
                "generated NodeArtifact binding stage does not match its creation event"
            )
    elif source == "cache":
        if cache_events is None:
            raise ObservabilityContractError(
                "cache NodeArtifact requires its creation event for lineage resolution"
            )
        _require_mapping(cache_events, "cache creation event map")
        event = cache_events.get(str(artifact["creation_event_id"]))
        if not isinstance(event, Mapping) or not isinstance(
            event.get("cache_source_artifact_id"), str
        ) or not event["cache_source_artifact_id"]:
            raise ObservabilityContractError(
                "cache NodeArtifact creation event must identify cache_source_artifact_id"
            )
        if event.get("materialization_source") != "cache":
            raise ObservabilityContractError(
                "cache NodeArtifact must resolve to a cache materialization event"
            )
        if node_artifacts is None:
            raise ObservabilityContractError(
                "cache NodeArtifact requires a cache source artifact resolver"
            )
        source_artifact_id = str(event["cache_source_artifact_id"])
        source_artifact = _resolve_node_artifact(node_artifacts, source_artifact_id)
        if source_artifact is None:
            raise ObservabilityContractError(
                "cache_source_artifact_id does not resolve to a NodeArtifact"
            )
        _validate_node_artifact_intrinsic(
            source_artifact,
            content_artifacts=content_artifacts,
            object_name="cache source NodeArtifact",
        )
        _validate_cache_content_lineage(
            artifact,
            source_artifact,
            source_artifact_id=source_artifact_id,
        )
        for event_field, artifact_field in (
            ("merge_event_id", "creation_event_id"),
            ("run_id", "run_id"),
            ("output_materialized_node_id", "materialized_node_id"),
        ):
            if event_field in event and event[event_field] != artifact[artifact_field]:
                raise ObservabilityContractError(
                    f"cache creation event {event_field} does not match NodeArtifact"
                )
        if matching_bindings:
            raise ObservabilityContractError("cache materialization cannot have an accepted attempt")
    else:
        if matching_bindings:
            raise ObservabilityContractError(
                "deterministic materialization cannot have an accepted attempt"
            )
    return artifact


def validate_model_call_attempt_raw(attempt: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_exact_fields(attempt, _ATTEMPT_FIELDS, "ModelCallAttemptRaw")
    for field in (
        "attempt_id",
        "run_id",
        "logical_call_id",
        "requested_model",
        "returned_model",
        "provider",
        "provider_route",
        "request_id",
        "prompt_hash",
        "tokenizer_snapshot",
        "serialization_version",
        "usage_schema_version",
        "parse_status",
        "status",
    ):
        _require_string(attempt, field)
    if attempt.get("response_hash") is not None:
        _require_string(attempt, "response_hash")
    if attempt.get("stage") not in _STAGES:
        raise ObservabilityContractError("stage must be leaf, merge, answer, or judge")
    if not isinstance(attempt.get("accepted_attempt"), bool):
        raise ObservabilityContractError("accepted_attempt must be a boolean derived cache")
    _require_nonnegative_int(attempt.get("retry_index"), "retry_index")
    _require_nonnegative_int(
        attempt.get("local_serialized_input_tokens"), "local_serialized_input_tokens"
    )
    _require_nonnegative_int(
        attempt.get("local_output_content_tokens"), "local_output_content_tokens"
    )

    source = attempt.get("provider_usage_source")
    if source not in _PROVIDER_USAGE_SOURCES:
        raise ObservabilityContractError(
            "provider_usage_source must be provider_exact, provider_estimated, or missing"
        )
    provider_fields = (
        "provider_input_tokens_total",
        "provider_cached_input_tokens_subset",
        "provider_output_tokens_total",
        "provider_reasoning_tokens_subset",
    )
    if source == "missing":
        if any(attempt.get(field) is not None for field in provider_fields):
            raise ObservabilityContractError(
                "missing provider usage requires null provider token fields; local counts cannot fill them"
            )
    else:
        for field in provider_fields[:3]:
            _require_nonnegative_int(attempt.get(field), field)
        _require_nonnegative_int(
            attempt.get("provider_reasoning_tokens_subset"),
            "provider_reasoning_tokens_subset",
            nullable=True,
        )
        if (
            attempt["provider_cached_input_tokens_subset"]
            > attempt["provider_input_tokens_total"]
        ):
            raise ObservabilityContractError(
                "provider_cached_input_tokens_subset must be a subset of provider_input_tokens_total"
            )
        reasoning = attempt.get("provider_reasoning_tokens_subset")
        if reasoning is not None and reasoning > attempt["provider_output_tokens_total"]:
            raise ObservabilityContractError(
                "provider_reasoning_tokens_subset must be a subset of provider_output_tokens_total"
            )

    outcome = attempt.get("attempt_outcome")
    if outcome not in _ATTEMPT_OUTCOMES:
        raise ObservabilityContractError("attempt_outcome is not recognized")
    if attempt["accepted_attempt"] != (outcome == "accepted_materialized"):
        raise ObservabilityContractError(
            "accepted_attempt cache must agree with accepted_materialized outcome"
        )
    scheduled = _parse_timestamp(attempt.get("scheduled_at"), "scheduled_at")
    started = _parse_timestamp(attempt.get("started_at"), "started_at", nullable=True)
    finished = _parse_timestamp(attempt.get("finished_at"), "finished_at", nullable=True)
    if outcome == "cancelled_before_start":
        if started is not None or finished is not None:
            raise ObservabilityContractError("cancelled_before_start cannot have execution timestamps")
    elif started is None or finished is None:
        raise ObservabilityContractError("started attempts require started_at and finished_at")
    elif not (scheduled <= started <= finished):
        raise ObservabilityContractError("attempt timestamps are not monotonic")
    http_status = attempt.get("http_status")
    if http_status is not None and (
        isinstance(http_status, bool)
        or not isinstance(http_status, int)
        or not 100 <= http_status <= 599
    ):
        raise ObservabilityContractError(
            "http_status must be null or an HTTP integer from 100 through 599"
        )
    return attempt


def validate_model_call_attempt(attempt: Mapping[str, Any]) -> Mapping[str, Any]:
    return validate_model_call_attempt_raw(attempt)


def validate_accepted_output_binding_raw(
    binding: Mapping[str, Any],
    *,
    attempts: Mapping[str, Mapping[str, Any]] | None = None,
) -> Mapping[str, Any]:
    _require_exact_fields(binding, _BINDING_FIELDS, "AcceptedOutputBindingRaw")
    for field in ("binding_id", "run_id", "stage", "logical_call_id", "binding_status"):
        _require_string(binding, field)
    if binding["stage"] not in _STAGES:
        raise ObservabilityContractError("binding stage must be leaf, merge, answer, or judge")
    if binding["binding_status"] not in _BINDING_STATUSES:
        raise ObservabilityContractError(
            "binding_status must be succeeded, failed, or invalidated"
        )
    successful = binding["binding_status"] in _SUCCESSFUL_BINDING_STATUSES
    if successful:
        _require_string(binding, "accepted_attempt_id")
        _require_string(binding, "output_artifact_id")
    elif binding.get("accepted_attempt_id") is not None or binding.get("output_artifact_id") is not None:
        raise ObservabilityContractError(
            "failed or invalidated binding must have null accepted_attempt_id and output_artifact_id"
        )
    if attempts is not None and successful:
        attempt = attempts.get(str(binding["accepted_attempt_id"]))
        if attempt is None:
            raise ObservabilityContractError("accepted binding references an unknown attempt")
        validate_model_call_attempt_raw(attempt)
        for field in ("run_id", "stage", "logical_call_id"):
            if binding[field] != attempt[field]:
                raise ObservabilityContractError(
                    f"accepted binding {field} does not match the referenced attempt"
                )
        if attempt["attempt_outcome"] != "accepted_materialized" or not attempt["accepted_attempt"]:
            raise ObservabilityContractError(
                "accepted binding must reference an accepted_materialized attempt"
            )
    return binding


def validate_accepted_output_bindings(
    attempts: Iterable[Mapping[str, Any]],
    bindings: Iterable[Mapping[str, Any]],
) -> None:
    attempt_map = _as_record_map(attempts, "attempt_id")
    binding_map = _as_record_map(bindings, "binding_id")
    for attempt in attempt_map.values():
        validate_model_call_attempt_raw(attempt)

    referenced_attempts: set[str] = set()
    accepted_logical_calls: set[tuple[str, str, str]] = set()
    for binding in binding_map.values():
        validate_accepted_output_binding_raw(binding, attempts=attempt_map)
        if binding["binding_status"] not in _SUCCESSFUL_BINDING_STATUSES:
            continue
        attempt_id = str(binding["accepted_attempt_id"])
        if attempt_id in referenced_attempts:
            raise ObservabilityContractError(
                "one accepted attempt cannot be referenced by two successful bindings"
            )
        referenced_attempts.add(attempt_id)
        logical_key = (
            str(binding["run_id"]),
            str(binding["stage"]),
            str(binding["logical_call_id"]),
        )
        if logical_key in accepted_logical_calls:
            raise ObservabilityContractError(
                "one logical call cannot have two accepted outputs"
            )
        accepted_logical_calls.add(logical_key)

    for attempt_id, attempt in attempt_map.items():
        if bool(attempt["accepted_attempt"]) != (attempt_id in referenced_attempts):
            raise ObservabilityContractError(
                "AcceptedOutputBindingRaw is the sole truth for accepted_attempt"
            )


def validate_merge_event_raw(
    event: Mapping[str, Any],
    *,
    bindings: Mapping[str, Mapping[str, Any]] | None = None,
    attempts: Mapping[str, Mapping[str, Any]] | None = None,
    artifacts: Mapping[str, Mapping[str, Any]] | None = None,
) -> Mapping[str, Any]:
    _require_exact_fields(event, _MERGE_EVENT_FIELDS, "MergeEventRaw")
    for field in (
        "merge_event_id",
        "run_id",
        "logical_operation_id",
        "left_materialized_node_id",
        "right_materialized_node_id",
        "output_materialized_node_id",
        "event_status",
    ):
        _require_string(event, field)
    _require_positive_int(event.get("output_budget"), "output_budget")
    source = event.get("materialization_source")
    if source not in _MATERIALIZATION_SOURCES:
        raise ObservabilityContractError("MergeEventRaw materialization_source is invalid")

    binding_map = bindings or {}
    attempt_map = attempts or {}
    artifact_map = artifacts or {}
    _require_mapping(binding_map, "accepted binding map")
    _require_mapping(attempt_map, "attempt map")
    _require_mapping(artifact_map, "NodeArtifact map")
    if source == "generated":
        _require_string(event, "accepted_binding_id")
        if event.get("cache_source_artifact_id") is not None:
            raise ObservabilityContractError(
                "generated MergeEventRaw cannot have cache_source_artifact_id"
            )
        binding = binding_map.get(str(event["accepted_binding_id"]))
        if binding is None:
            raise ObservabilityContractError(
                "generated MergeEventRaw must resolve exactly one accepted binding"
            )
        validate_accepted_output_binding_raw(binding, attempts=attempt_map)
        if binding["stage"] != "merge":
            raise ObservabilityContractError("generated merge binding stage must be merge")
        if binding["run_id"] != event["run_id"] or binding["logical_call_id"] != event["logical_operation_id"]:
            raise ObservabilityContractError(
                "generated merge binding run/logical operation does not match MergeEventRaw"
            )
        if binding["output_artifact_id"] != event["output_materialized_node_id"]:
            raise ObservabilityContractError(
                "merge binding output does not match output_materialized_node_id"
            )
    elif source == "cache":
        if event.get("accepted_binding_id") is not None:
            raise ObservabilityContractError("cache materialization cannot have an accepted binding")
        _require_string(event, "cache_source_artifact_id")
        fake_attempts = [
            attempt
            for attempt in attempt_map.values()
            if attempt.get("run_id") == event["run_id"]
            and attempt.get("logical_call_id") == event["logical_operation_id"]
        ]
        if fake_attempts:
            raise ObservabilityContractError("cache materialization cannot fabricate an API attempt")
        if artifacts is None:
            raise ObservabilityContractError(
                "cache MergeEventRaw requires source and output NodeArtifact resolution"
            )
        source_artifact_id = str(event["cache_source_artifact_id"])
        source_artifact = artifact_map.get(source_artifact_id)
        output_artifact = artifact_map.get(str(event["output_materialized_node_id"]))
        if not isinstance(source_artifact, Mapping):
            raise ObservabilityContractError(
                "cache_source_artifact_id does not resolve to a NodeArtifact"
            )
        if not isinstance(output_artifact, Mapping):
            raise ObservabilityContractError(
                "cache MergeEventRaw output does not resolve to a NodeArtifact"
            )
        _validate_cache_content_lineage(
            output_artifact,
            source_artifact,
            source_artifact_id=source_artifact_id,
        )
    else:
        if event.get("accepted_binding_id") is not None:
            raise ObservabilityContractError(
                "deterministic materialization cannot have an accepted binding"
            )

    output = artifact_map.get(str(event["output_materialized_node_id"]))
    if output is not None:
        if output.get("materialized_node_id") != event["output_materialized_node_id"]:
            raise ObservabilityContractError("merge output artifact identity is inconsistent")
        if output.get("creation_event_id") != event["merge_event_id"]:
            raise ObservabilityContractError("NodeArtifact creation event is not the MergeEventRaw")
        if output.get("materialization_source") != source:
            raise ObservabilityContractError("merge output materialization source is inconsistent")
    return event


def validate_merge_event(
    event: Mapping[str, Any],
    attempts: Iterable[Mapping[str, Any]],
    bindings: Iterable[Mapping[str, Any]],
    artifacts: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any]:
    return validate_merge_event_raw(
        event,
        attempts=_as_record_map(attempts, "attempt_id"),
        bindings=_as_record_map(bindings, "binding_id"),
        artifacts=_as_record_map(artifacts, "materialized_node_id"),
    )


def derive_merge_event_metrics(
    event: Mapping[str, Any],
    *,
    artifacts: Mapping[str, Mapping[str, Any]],
    attempt: Mapping[str, Any] | None = None,
    plan_nodes_by_logical_node: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    _require_mapping(event, "MergeEventRaw")
    _require_mapping(artifacts, "NodeArtifact map")
    if plan_nodes_by_logical_node is not None:
        _require_mapping(plan_nodes_by_logical_node, "PlanNodeRaw map")
    budget = event.get("output_budget")
    _require_positive_int(budget, "output_budget")
    try:
        left = artifacts[str(event["left_materialized_node_id"])]
        right = artifacts[str(event["right_materialized_node_id"])]
        output = artifacts[str(event["output_materialized_node_id"])]
    except KeyError as exc:
        raise ObservabilityContractError("MergeEventMetrics requires all three NodeArtifacts") from exc
    left_tokens = left.get("memory_tokens_local")
    right_tokens = right.get("memory_tokens_local")
    output_tokens = output.get("memory_tokens_local")
    for value, field in (
        (left_tokens, "left memory_tokens_local"),
        (right_tokens, "right memory_tokens_local"),
        (output_tokens, "output memory_tokens_local"),
    ):
        _require_nonnegative_int(value, field)
    total_children = int(left_tokens) + int(right_tokens)
    if total_children <= 0:
        raise ObservabilityContractError("merge child token total must be positive")

    signed: float | str = "unavailable"
    left_span = left.get("covered_span")
    right_span = right.get("covered_span")
    if plan_nodes_by_logical_node is not None:
        left_logical_id = left.get("logical_node_id")
        right_logical_id = right.get("logical_node_id")
        if left_logical_id in plan_nodes_by_logical_node:
            left_span = plan_nodes_by_logical_node[str(left_logical_id)].get("covered_span")
        if right_logical_id in plan_nodes_by_logical_node:
            right_span = plan_nodes_by_logical_node[str(right_logical_id)].get("covered_span")
    if (
        isinstance(left_span, (list, tuple))
        and isinstance(right_span, (list, tuple))
        and len(left_span) == 2
        and len(right_span) == 2
        and left_span[1] < right_span[0]
    ):
        signed = (int(left_tokens) - int(right_tokens)) / total_children

    payload_ratio: float | str = "unavailable"
    if attempt is not None:
        validate_model_call_attempt_raw(attempt)
        payload_ratio = attempt["local_serialized_input_tokens"] / budget
    return {
        "logical_operation_id": event.get("logical_operation_id"),
        "materialization_source": event.get("materialization_source"),
        "content_to_budget_pressure": total_children / budget,
        "actual_compression_ratio": int(output_tokens) / total_children,
        "output_budget_utilization": int(output_tokens) / budget,
        "payload_to_budget_ratio": payload_ratio,
        "token_imbalance_abs": abs(int(left_tokens) - int(right_tokens)) / total_children,
        "token_imbalance_signed": signed,
        "time_span_imbalance": "unavailable",
        "generative_rewrite_depth": 1 if event.get("materialization_source") == "generated" else 0,
    }


def _provider_totals(attempts: Iterable[Mapping[str, Any]]) -> dict[str, int | str]:
    records = list(attempts)
    if not records:
        return {"input": 0, "cached": 0, "uncached": 0, "output": 0, "reasoning": 0}
    provider_fields = (
        "provider_input_tokens_total",
        "provider_cached_input_tokens_subset",
        "provider_output_tokens_total",
        "provider_reasoning_tokens_subset",
    )
    for record in records:
        if not isinstance(record, Mapping):
            raise ObservabilityContractError("provider usage rows must be objects")
        source = record.get("provider_usage_source")
        if source not in _PROVIDER_USAGE_SOURCES:
            raise ObservabilityContractError(
                "provider_usage_source must be provider_exact, provider_estimated, or missing"
            )
        if source == "missing":
            if any(record.get(field) is not None for field in provider_fields):
                raise ObservabilityContractError(
                    "missing provider usage requires null provider token fields"
                )
            continue
        for field in provider_fields[:3]:
            _require_nonnegative_int(record.get(field), field)
        _require_nonnegative_int(
            record.get("provider_reasoning_tokens_subset"),
            "provider_reasoning_tokens_subset",
            nullable=True,
        )
        if (
            record["provider_cached_input_tokens_subset"]
            > record["provider_input_tokens_total"]
        ):
            raise ObservabilityContractError(
                "provider_cached_input_tokens_subset must be a subset of provider_input_tokens_total"
            )
        reasoning = record.get("provider_reasoning_tokens_subset")
        if reasoning is not None and reasoning > record["provider_output_tokens_total"]:
            raise ObservabilityContractError(
                "provider_reasoning_tokens_subset must be a subset of provider_output_tokens_total"
            )
    if any(record.get("provider_usage_source") == "missing" for record in records):
        return {
            "input": "unknown",
            "cached": "unknown",
            "uncached": "unknown",
            "output": "unknown",
            "reasoning": "unknown",
        }
    input_total = sum(int(record["provider_input_tokens_total"]) for record in records)
    cached_total = sum(int(record["provider_cached_input_tokens_subset"]) for record in records)
    output_total = sum(int(record["provider_output_tokens_total"]) for record in records)
    reasoning_values = [record.get("provider_reasoning_tokens_subset") for record in records]
    reasoning_total: int | str = (
        "unknown"
        if any(value is None for value in reasoning_values)
        else sum(int(value) for value in reasoning_values)
    )
    return {
        "input": input_total,
        "cached": cached_total,
        "uncached": input_total - cached_total,
        "output": output_total,
        "reasoning": reasoning_total,
    }


def _attempt_duration(attempt: Mapping[str, Any]) -> float:
    started = _parse_timestamp(attempt.get("started_at"), "started_at", nullable=True)
    finished = _parse_timestamp(attempt.get("finished_at"), "finished_at", nullable=True)
    if started is None or finished is None:
        return 0.0
    return (finished - started).total_seconds()


def aggregate_attempt_work(
    attempts: Iterable[Mapping[str, Any]],
    *,
    accepted_attempt_ids: set[str],
) -> dict[str, Any]:
    records = list(attempts)
    for record in records:
        validate_model_call_attempt_raw(record)
    observed_records = [
        record for record in records if record["attempt_outcome"] != "cancelled_before_start"
    ]
    accepted_records = [
        record for record in records if record["attempt_id"] in accepted_attempt_ids
    ]
    for record in accepted_records:
        if record["attempt_outcome"] != "accepted_materialized":
            raise ObservabilityContractError(
                "accepted attempt IDs must refer only to accepted_materialized attempts"
            )
    accepted = _provider_totals(accepted_records)
    observed = _provider_totals(observed_records)
    return {
        "accepted_input_tokens_total": accepted["input"],
        "accepted_cached_input_tokens_subset": accepted["cached"],
        "accepted_uncached_input_tokens": accepted["uncached"],
        "accepted_output_tokens": accepted["output"],
        "observed_input_tokens_total": observed["input"],
        "observed_cached_input_tokens_subset": observed["cached"],
        "observed_uncached_input_tokens": observed["uncached"],
        "observed_output_tokens": observed["output"],
        "local_input_tokens_total": sum(
            int(record["local_serialized_input_tokens"]) for record in records
        ),
        "local_output_tokens_total": sum(
            int(record["local_output_content_tokens"]) for record in records
        ),
        "api_attempt_count": len(records),
        "failed_api_attempt_count": sum(
            record["attempt_outcome"]
            in {"failed_provider", "failed_parse", "failed_validation", "cancelled_after_start"}
            for record in records
        ),
        "successful_nonmaterialized_attempt_count": sum(
            record["attempt_outcome"] == "successful_nonmaterialized" for record in records
        ),
        "accepted_materialized_generation_count": len(accepted_records),
        "sum_attempt_latency": sum(_attempt_duration(record) for record in observed_records),
    }


def _put_stage_totals(
    target: dict[str, Any],
    prefix: str,
    totals: Mapping[str, int | str],
) -> None:
    target[f"{prefix}_input_tokens_total"] = totals["input"]
    target[f"{prefix}_cached_input_tokens_subset"] = totals["cached"]
    target[f"{prefix}_uncached_input_tokens"] = totals["uncached"]
    target[f"{prefix}_output_tokens"] = totals["output"]


def reconcile_work(
    attempts: Iterable[Mapping[str, Any]],
    bindings: Iterable[Mapping[str, Any]],
    *,
    merge_events: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    attempt_records = list(attempts)
    binding_records = list(bindings)
    validate_accepted_output_bindings(attempt_records, binding_records)
    accepted_ids = {
        str(binding["accepted_attempt_id"])
        for binding in binding_records
        if binding["binding_status"] in _SUCCESSFUL_BINDING_STATUSES
    }
    accepted_path: dict[str, Any] = {}
    observed_operational: dict[str, Any] = {}
    judge_overhead: dict[str, Any] = {}
    stage_prefixes = {
        "leaf": ("shared_leaf", "observed_leaf"),
        "merge": ("accepted_merge", "observed_merge"),
        "answer": ("accepted_answer", "observed_answer"),
        "judge": ("accepted_judge", "observed_judge"),
    }
    for stage, (accepted_prefix, observed_prefix) in stage_prefixes.items():
        accepted_stage = [
            attempt
            for attempt in attempt_records
            if attempt["stage"] == stage and attempt["attempt_id"] in accepted_ids
        ]
        observed_stage = [
            attempt
            for attempt in attempt_records
            if attempt["stage"] == stage
            and attempt["attempt_outcome"] != "cancelled_before_start"
        ]
        destination = judge_overhead if stage == "judge" else accepted_path
        _put_stage_totals(destination, accepted_prefix, _provider_totals(accepted_stage))
        destination = judge_overhead if stage == "judge" else observed_operational
        _put_stage_totals(destination, observed_prefix, _provider_totals(observed_stage))

    lifecycle_attempts = [
        attempt for attempt in attempt_records if attempt["stage"] != "judge"
    ]
    observed_all = [
        attempt
        for attempt in lifecycle_attempts
        if attempt["attempt_outcome"] != "cancelled_before_start"
    ]
    accepted_all = [
        attempt for attempt in lifecycle_attempts if attempt["attempt_id"] in accepted_ids
    ]
    observed_totals = _provider_totals(observed_all)
    accepted_totals = _provider_totals(accepted_all)
    if isinstance(observed_totals["input"], int) and isinstance(accepted_totals["input"], int):
        retry_token_overhead: int | str = (
            observed_totals["input"]
            + int(observed_totals["output"])
            - accepted_totals["input"]
            - int(accepted_totals["output"])
        )
    else:
        retry_token_overhead = "unknown"
    nonaccepted_started = [
        attempt for attempt in observed_all if attempt["attempt_id"] not in accepted_ids
    ]
    observed_operational.update(
        {
            "api_attempt_count": len(lifecycle_attempts),
            "failed_api_attempt_count": sum(
                attempt["attempt_outcome"]
                in {
                    "failed_provider",
                    "failed_parse",
                    "failed_validation",
                    "cancelled_after_start",
                }
                for attempt in lifecycle_attempts
            ),
            "successful_nonmaterialized_attempt_count": sum(
                attempt["attempt_outcome"] == "successful_nonmaterialized"
                for attempt in lifecycle_attempts
            ),
            "accepted_materialized_generation_count": len(accepted_all),
            "cache_hit_count": sum(
                event.get("materialization_source") == "cache" for event in merge_events
            ),
            "retry_token_overhead": retry_token_overhead,
            "retry_latency_overhead": sum(
                _attempt_duration(attempt) for attempt in nonaccepted_started
            ),
            "sum_attempt_latency": sum(
                _attempt_duration(attempt) for attempt in observed_all
            ),
            "critical_path_elapsed_latency": "unknown",
            "parallelism_factor": "unknown",
        }
    )
    return {
        "accepted_path": accepted_path,
        "observed_operational": observed_operational,
        "judge_overhead": judge_overhead,
    }


def _decimal_nonnegative(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ObservabilityContractError(f"{field} must be a finite non-negative number")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ObservabilityContractError(f"{field} must be a finite non-negative number") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ObservabilityContractError(f"{field} must be a finite non-negative number")
    return parsed


def estimate_usd_from_usage(
    usage: Mapping[str, Any], pricing_manifest: Mapping[str, Any] | None
) -> float | str:
    _require_mapping(usage, "provider usage")
    if pricing_manifest is None:
        return "unavailable"
    _require_mapping(pricing_manifest, "PricingManifest")
    for usage_field, manifest_field in (
        ("provider", "provider"),
        ("model", "model"),
        ("provider_route", "provider_route"),
        ("usage_schema_version", "usage_schema_version"),
    ):
        if usage_field in usage and manifest_field in pricing_manifest:
            if usage[usage_field] != pricing_manifest[manifest_field]:
                raise ObservabilityContractError(
                    "pricing and provider usage scope must use the same provider/model/route/schema"
                )
    input_total = usage.get("input_total")
    cached = usage.get("cached_input")
    output_total = usage.get("output_total")
    if "unknown" in {input_total, cached, output_total}:
        return "unavailable"
    input_tokens = _decimal_nonnegative(input_total, "input_total")
    cached_tokens = _decimal_nonnegative(cached, "cached_input")
    output_tokens = _decimal_nonnegative(output_total, "output_total")
    request_count = _decimal_nonnegative(usage.get("request_count", 0), "request_count")
    if cached_tokens > input_tokens:
        raise ObservabilityContractError("cached_input must be a subset of input_total")
    uncached_rate = _decimal_nonnegative(
        pricing_manifest.get("uncached_input_usd_per_million"),
        "uncached_input_usd_per_million",
    )
    cached_rate = _decimal_nonnegative(
        pricing_manifest.get("cached_input_usd_per_million"),
        "cached_input_usd_per_million",
    )
    output_rate = _decimal_nonnegative(
        pricing_manifest.get("output_usd_per_million"), "output_usd_per_million"
    )
    request_fee = _decimal_nonnegative(
        pricing_manifest.get("request_fee_usd", 0), "request_fee_usd"
    )
    value = (
        uncached_rate * (input_tokens - cached_tokens)
        + cached_rate * cached_tokens
        + output_rate * output_tokens
    ) / Decimal(1_000_000) + request_fee * request_count
    return float(value)


def deployment_state_tokens(state: Mapping[str, Any]) -> int:
    _require_mapping(state, "deployment state measurement")
    _require_nonnegative_int(state.get("deployment_memory_tokens"), "deployment_memory_tokens")
    _require_nonnegative_int(
        state.get("deployment_metadata_bytes"), "deployment_metadata_bytes"
    )
    profile = state.get("deployment_capability_profile")
    if profile not in _DEPLOYMENT_PROFILES:
        raise ObservabilityContractError("deployment_capability_profile is invalid")
    _require_string(state, "deployment_state_measurement_protocol")
    _require_string(state, "deployment_state_measurement_point")
    return int(state["deployment_memory_tokens"])


def validate_deployment_state_measurements(
    states: Iterable[Mapping[str, Any]],
) -> None:
    records = list(states)
    if not records:
        raise ObservabilityContractError(
            "deployment state comparison requires measurements"
        )
    for state in records:
        deployment_state_tokens(state)
    comparison_fields = (
        "deployment_capability_profile",
        "deployment_state_measurement_protocol",
        "deployment_state_measurement_point",
    )
    reference = tuple(records[0][field] for field in comparison_fields)
    if any(
        tuple(state[field] for field in comparison_fields) != reference
        for state in records[1:]
    ):
        raise ObservabilityContractError(
            "deployment state measurements must use the same capability, protocol, and measurement point"
        )


def build_support_exposure(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = list(rows)
    allowed_statuses = {"exact", "expanded_to_chunks", "unresolved"}
    per_leaf: dict[str, tuple[float, float, str]] = {}
    unresolved = 0
    for record in records:
        _require_mapping(record, "support exposure row")
        status = record.get("support_mapping_status")
        if status not in allowed_statuses:
            raise ObservabilityContractError("support_mapping_status must be explicit")
        for field in ("mapped_evidence_ids", "mapped_chunk_ids", "mapped_leaf_ids"):
            values = record.get(field)
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value for value in values
            ):
                raise ObservabilityContractError(f"{field} must be a list of stable IDs")
        if status == "unresolved":
            unresolved += 1
            if record["mapped_leaf_ids"]:
                raise ObservabilityContractError("unresolved support mapping cannot claim mapped leaves")
            continue
        if not record["mapped_leaf_ids"]:
            raise ObservabilityContractError("resolved support mapping requires mapped_leaf_ids")
        _require_nonnegative_int(record.get("rewrite_depth"), "rewrite_depth")
        pressure_value = _decimal_nonnegative(record.get("pressure"), "pressure")
        _require_string(record, "order_role")
        rewrite = float(record["rewrite_depth"])
        pressure = float(pressure_value)
        role = str(record["order_role"])
        for leaf_id in record["mapped_leaf_ids"]:
            value = (rewrite, pressure, role)
            if leaf_id in per_leaf and per_leaf[leaf_id] != value:
                raise ObservabilityContractError(
                    "the same supporting leaf has inconsistent exposure values"
                )
            per_leaf[leaf_id] = value
    rewrites = [value[0] for value in per_leaf.values()]
    pressures = [value[1] for value in per_leaf.values()]
    roles: dict[str, int] = defaultdict(int)
    for _, _, role in per_leaf.values():
        roles[role] += 1
    total_annotations = len(records)
    return {
        "unique_supporting_leaf_count": len(per_leaf),
        "unresolved_support_mapping_count": unresolved,
        "unresolved_support_mapping_fraction": (
            unresolved / total_annotations if total_annotations else 0.0
        ),
        "annotated_support_rewrite_mean": fmean(rewrites) if rewrites else "unavailable",
        "annotated_support_rewrite_max": max(rewrites) if rewrites else "unavailable",
        "annotated_support_pressure_mean": fmean(pressures) if pressures else "unavailable",
        "annotated_support_pressure_max": max(pressures) if pressures else "unavailable",
        "annotated_support_order_role_summary": dict(sorted(roles.items())),
    }


def _nested_field_names(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        result = {key for key in value if isinstance(key, str)}
        for child in value.values():
            result.update(_nested_field_names(child))
        return result
    if isinstance(value, (list, tuple)):
        result: set[str] = set()
        for child in value:
            result.update(_nested_field_names(child))
        return result
    return set()


def validate_support_label_boundary(view: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_mapping(view, "label access view")
    stage = view.get("stage")
    if stage not in {"construction", "answer", "scoring"}:
        raise ObservabilityContractError("label access stage must be construction, answer, or scoring")
    present = _PROTECTED_LABEL_FIELDS & set(view)
    if stage == "construction":
        leaked_fields = _nested_field_names(view) & (
            _PROTECTED_LABEL_FIELDS | _QUERY_FIELDS
        )
        if leaked_fields:
            raise ObservabilityContractError(
                "construction stage cannot access query, gold, or support labels"
            )
    elif stage == "answer":
        if _nested_field_names(view) & _PROTECTED_LABEL_FIELDS:
            raise ObservabilityContractError("answer stage cannot access gold or support labels")
    elif stage == "scoring" and present:
        answers_frozen = view.get("answer_artifacts_frozen") is True or view.get("score_frozen") is True
        if view.get("run_artifacts_frozen") is not True or not answers_frozen:
            raise ObservabilityContractError(
                "scoring labels require frozen run and answer artifacts"
            )
        _require_string(view, "access_log_id")
    return view


def validate_label_access(stage: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_mapping(payload, "label access payload")
    if "stage" in payload:
        raise ObservabilityContractError("label access payload cannot override its caller stage")
    return validate_support_label_boundary({**payload, "stage": stage})


def construction_input_view(
    *, raw_evidence: Any, leaf_configuration: Mapping[str, Any], plan: Mapping[str, Any]
) -> dict[str, Any]:
    _require_mapping(leaf_configuration, "leaf configuration")
    _require_mapping(plan, "plan")
    view = {
        "stage": "construction",
        "raw_evidence": raw_evidence,
        "leaf_configuration": dict(leaf_configuration),
        "plan": dict(plan),
    }
    validate_support_label_boundary(view)
    return view


def answer_input_view(
    *, final_memory: Any, query: Mapping[str, Any] | str, answer_configuration: Mapping[str, Any]
) -> dict[str, Any]:
    _require_mapping(answer_configuration, "answer configuration")
    if isinstance(query, Mapping):
        if _nested_field_names(query) & _PROTECTED_LABEL_FIELDS:
            raise ObservabilityContractError(
                "AnswerInputView query must be stripped of gold and support labels"
            )
        query_value: Any = dict(query)
    else:
        query_value = query
    view = {
        "stage": "answer",
        "final_memory": final_memory,
        "query": query_value,
        "answer_configuration": dict(answer_configuration),
    }
    validate_support_label_boundary(view)
    return view


def scoring_input_view(
    *,
    frozen_run_artifacts: Mapping[str, Any],
    frozen_answer: Mapping[str, Any],
    protected_labels: Mapping[str, Any],
    evaluator: Mapping[str, Any],
    access_log_id: str,
) -> dict[str, Any]:
    _require_mapping(frozen_run_artifacts, "frozen run artifacts")
    _require_mapping(frozen_answer, "frozen answer")
    _require_mapping(protected_labels, "protected labels")
    _require_mapping(evaluator, "evaluator")
    unknown_label_fields = set(protected_labels) - _PROTECTED_LABEL_FIELDS
    if unknown_label_fields:
        raise ObservabilityContractError(
            "ScoringInputView protected_labels contains non-label fields: "
            + ", ".join(sorted(str(field) for field in unknown_label_fields))
        )
    view = {
        "stage": "scoring",
        "run_artifacts": dict(frozen_run_artifacts),
        "answer": dict(frozen_answer),
        "evaluator": dict(evaluator),
        "run_artifacts_frozen": True,
        "answer_artifacts_frozen": True,
        "access_log_id": access_log_id,
        **dict(protected_labels),
    }
    validate_support_label_boundary(view)
    return view


_EXECUTOR_COMPARE_FIELDS = (
    "executor_config_hash",
    "executor_mode",
    "concurrency_limit",
    "cache_mode",
    "rate_limit_policy_hash",
    "retry_policy_hash",
    "provider_route",
)
_RUN_EXECUTION_FIELDS = {
    *_EXECUTOR_COMPARE_FIELDS,
    "run_started_at",
    "run_finished_at",
    "replication_index",
    "execution_order_index",
    "run_batch_id",
    "provider_observation_window",
}


def _validate_executor_comparison_fields(config: Mapping[str, Any]) -> None:
    _require_mapping(config, "formal executor configuration")
    for field in _EXECUTOR_COMPARE_FIELDS:
        if field not in config:
            raise ObservabilityContractError(f"formal executor configuration is missing {field}")
    for field in (
        "executor_config_hash",
        "executor_mode",
        "cache_mode",
        "rate_limit_policy_hash",
        "retry_policy_hash",
        "provider_route",
    ):
        _require_string(config, field)
    _require_positive_int(config.get("concurrency_limit"), "concurrency_limit")
    if config["cache_mode"] != "cold":
        raise ObservabilityContractError("formal topology comparison requires cold cache mode")


def validate_run_execution_config(config: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_exact_fields(config, _RUN_EXECUTION_FIELDS, "Run execution configuration")
    _validate_executor_comparison_fields(config)
    started = _parse_timestamp(config.get("run_started_at"), "run_started_at")
    finished = _parse_timestamp(config.get("run_finished_at"), "run_finished_at")
    if finished < started:
        raise ObservabilityContractError("run_finished_at precedes run_started_at")
    _require_nonnegative_int(config.get("replication_index"), "replication_index")
    _require_nonnegative_int(config.get("execution_order_index"), "execution_order_index")
    _require_string(config, "run_batch_id")
    _require_string(config, "provider_observation_window")
    return config


def validate_formal_executor_configs(configs: Iterable[Mapping[str, Any]]) -> None:
    records = list(configs)
    if not records:
        raise ObservabilityContractError("formal executor comparison requires run configurations")
    for config in records:
        _validate_executor_comparison_fields(config)
    reference = tuple(records[0][field] for field in _EXECUTOR_COMPARE_FIELDS)
    for config in records[1:]:
        current = tuple(config[field] for field in _EXECUTOR_COMPARE_FIELDS)
        if current != reference:
            raise ObservabilityContractError(
                "formal topology runs must share executor, concurrency, cache, retry, rate-limit, and route configuration"
            )


def validate_provider_usage_scope(attempts: Iterable[Mapping[str, Any]]) -> None:
    """Require one provider/model/route/usage-schema scope per comparison block."""
    records = list(attempts)
    for record in records:
        validate_model_call_attempt_raw(record)
    scopes = {
        (
            record["provider"],
            record["returned_model"],
            record["provider_route"],
            record["usage_schema_version"],
        )
        for record in records
    }
    if len(scopes) > 1:
        raise ObservabilityContractError(
            "provider usage scope must be fixed to provider/model/route/usage schema"
        )


def deduplicate_shared_leaf_work(rows: Iterable[Mapping[str, Any]]) -> dict[str, int | str]:
    """Aggregate shared leaf observations once across plans and budgets."""
    records = list(rows)
    by_artifact: dict[str, Mapping[str, Any]] = {}
    for row in records:
        _require_mapping(row, "shared leaf usage row")
        artifact_id = row.get("content_artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ObservabilityContractError("shared leaf rows require content_artifact_id")
        if artifact_id in by_artifact:
            previous = by_artifact[artifact_id]
            for field in (
                "provider_usage_source",
                "provider_input_tokens_total",
                "provider_cached_input_tokens_subset",
                "provider_output_tokens_total",
                "provider_reasoning_tokens_subset",
            ):
                if previous.get(field) != row.get(field):
                    raise ObservabilityContractError(
                        "shared leaf duplicate rows disagree on raw usage"
                    )
        else:
            by_artifact[artifact_id] = row
    totals = _provider_totals(by_artifact.values())
    return {
        "unique_shared_leaf_count": len(by_artifact),
        "shared_leaf_input_tokens_total": totals["input"],
        "shared_leaf_cached_input_tokens_subset": totals["cached"],
        "shared_leaf_uncached_input_tokens": totals["uncached"],
        "shared_leaf_output_tokens": totals["output"],
    }


def lifecycle_resource_work(reconciled: Mapping[str, Any]) -> dict[str, int | str]:
    """Return memory lifecycle resource work without judge overhead."""
    _require_mapping(reconciled, "reconciled work")
    accepted = reconciled.get("accepted_path")
    if not isinstance(accepted, Mapping):
        raise ObservabilityContractError("reconciled work is missing accepted_path")
    fields = (
        "accepted_merge_input_tokens_total",
        "accepted_merge_cached_input_tokens_subset",
        "accepted_merge_uncached_input_tokens",
        "accepted_merge_output_tokens",
        "accepted_answer_input_tokens_total",
        "accepted_answer_cached_input_tokens_subset",
        "accepted_answer_uncached_input_tokens",
        "accepted_answer_output_tokens",
    )
    result: dict[str, int | str] = {}
    for field in fields:
        merge_value = accepted.get(field)
        if merge_value is None:
            raise ObservabilityContractError(f"accepted_path is missing {field}")
        result[field] = merge_value
    return result


def validate_stage_timing_boundaries(
    boundaries: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Mapping[str, Any]]:
    _require_mapping(boundaries, "stage timing boundaries")
    required = {"leaf", "merge", "answer", "judge"}
    if set(boundaries) != required:
        raise ObservabilityContractError(
            "stage timing boundaries must contain leaf, merge, answer, and judge"
        )
    for stage, boundary in boundaries.items():
        if not isinstance(boundary, Mapping):
            raise ObservabilityContractError(f"{stage} timing boundary must be an object")
        status = boundary.get("status")
        if status not in {"recorded", "unavailable"}:
            raise ObservabilityContractError("stage timing status must be recorded or unavailable")
        first = boundary.get("first_logical_operation_scheduled_at")
        last = boundary.get("last_required_artifact_persisted_at")
        if status == "unavailable":
            if first is not None or last is not None:
                raise ObservabilityContractError(
                    "unavailable stage timing must have null boundary timestamps"
                )
            continue
        first_dt = _parse_timestamp(first, f"{stage}.first_logical_operation_scheduled_at")
        last_dt = _parse_timestamp(last, f"{stage}.last_required_artifact_persisted_at")
        if last_dt < first_dt:
            raise ObservabilityContractError(f"{stage} stage timing boundary is reversed")
    return boundaries


def derive_stage_wall_clock(
    boundaries: Mapping[str, Mapping[str, Any]],
) -> dict[str, float | str]:
    validate_stage_timing_boundaries(boundaries)
    result: dict[str, float | str] = {}
    for stage, boundary in boundaries.items():
        if boundary["status"] == "unavailable":
            result[stage] = "unavailable"
            continue
        first = _parse_timestamp(
            boundary["first_logical_operation_scheduled_at"],
            f"{stage}.first_logical_operation_scheduled_at",
        )
        last = _parse_timestamp(
            boundary["last_required_artifact_persisted_at"],
            f"{stage}.last_required_artifact_persisted_at",
        )
        result[stage] = (last - first).total_seconds()
    return result


def wall_clock_by_stage(
    stage_timing_boundaries: Mapping[str, Mapping[str, Any]],
) -> dict[str, float | str]:
    if not isinstance(stage_timing_boundaries, Mapping):
        raise ObservabilityContractError(
            "stage wall-clock requires persisted-artifact timing boundaries"
        )
    return derive_stage_wall_clock(stage_timing_boundaries)


def parallelism_factor(
    attempts: Iterable[Mapping[str, Any]],
    *,
    stage_timing_boundaries: Mapping[str, Mapping[str, Any]],
) -> float | str:
    records = list(attempts)
    if not records:
        return "unavailable"
    for record in records:
        validate_model_call_attempt_raw(record)
    stages = {str(record["stage"]) for record in records}
    if len(stages) != 1:
        raise ObservabilityContractError("parallelism_factor must be rebuilt for one stage at a time")
    stage = next(iter(stages))
    elapsed = wall_clock_by_stage(stage_timing_boundaries)[stage]
    if elapsed == "unavailable":
        return "unavailable"
    if elapsed <= 0:
        return "unavailable"
    return sum(_attempt_duration(record) for record in records) / elapsed


def critical_path_elapsed_latency(operations: Iterable[Mapping[str, Any]]) -> float:
    records = _as_record_map(operations, "operation_id")
    if not records:
        return 0.0
    visiting: set[str] = set()
    memo: dict[str, float] = {}

    def longest(operation_id: str) -> float:
        if operation_id in visiting:
            raise ObservabilityContractError("operation dependency graph contains a cycle")
        if operation_id in memo:
            return memo[operation_id]
        visiting.add(operation_id)
        record = records[operation_id]
        dependencies = record.get("depends_on")
        if not isinstance(dependencies, list) or any(
            not isinstance(item, str) or item not in records for item in dependencies
        ):
            raise ObservabilityContractError("operation depends_on must reference known operations")
        elapsed = record.get("operation_elapsed_latency")
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or elapsed < 0:
            raise ObservabilityContractError(
                "operation_elapsed_latency must be a non-negative number"
            )
        prefix = max((longest(item) for item in dependencies), default=0.0)
        visiting.remove(operation_id)
        memo[operation_id] = prefix + float(elapsed)
        return memo[operation_id]

    return max(longest(operation_id) for operation_id in records)


def _artifact_has_generative_lineage(
    artifact_id: str,
    *,
    artifacts: Mapping[str, Mapping[str, Any]],
    cache_events: Mapping[str, Mapping[str, Any]],
    visiting: set[str] | None = None,
) -> bool:
    visiting = set() if visiting is None else visiting
    if artifact_id in visiting:
        raise ObservabilityContractError("cache source artifact lineage contains a cycle")
    artifact = artifacts.get(artifact_id)
    if not isinstance(artifact, Mapping):
        raise ObservabilityContractError("materialized lineage references an unknown NodeArtifact")
    source = artifact.get("materialization_source")
    if source == "generated":
        return True
    if source == "deterministic":
        return False
    if source != "cache":
        raise ObservabilityContractError("NodeArtifact materialization_source is invalid")
    event = cache_events.get(str(artifact.get("creation_event_id")))
    if not isinstance(event, Mapping):
        raise ObservabilityContractError(
            "cache NodeArtifact lineage is missing its creation event"
        )
    source_artifact_id = event.get("cache_source_artifact_id")
    if not isinstance(source_artifact_id, str) or not source_artifact_id:
        raise ObservabilityContractError(
            "cache NodeArtifact lineage is missing cache_source_artifact_id"
        )
    visiting.add(artifact_id)
    result = _artifact_has_generative_lineage(
        source_artifact_id,
        artifacts=artifacts,
        cache_events=cache_events,
        visiting=visiting,
    )
    visiting.remove(artifact_id)
    return result


def rebuild_observability(
    *,
    plan_nodes: Mapping[str, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    merge_events: Iterable[Mapping[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
    attempts: Iterable[Mapping[str, Any]],
    bindings: Iterable[Mapping[str, Any]],
    content_artifacts: Mapping[str, Any] | Callable[[str], Any] | None = None,
    cache_source_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    plan_node_map = _as_record_map(plan_nodes, "logical_node_id")
    attempt_records = list(attempts)
    binding_records = list(bindings)
    event_records = list(merge_events)
    attempt_map = _as_record_map(attempt_records, "attempt_id")
    binding_map = _as_record_map(binding_records, "binding_id")
    artifact_map = _as_record_map(artifacts, "materialized_node_id")
    source_artifact_map = _as_record_map(
        cache_source_artifacts or {}, "materialized_node_id"
    )
    collisions = set(artifact_map) & set(source_artifact_map)
    if any(artifact_map[key] != source_artifact_map[key] for key in collisions):
        raise ObservabilityContractError(
            "current and cache source artifact resolvers disagree on identity"
        )
    all_artifacts = {**source_artifact_map, **artifact_map}
    event_map = _as_record_map(event_records, "merge_event_id")
    derive_plan_metrics(plan_node_map)
    validate_accepted_output_bindings(attempt_records, binding_records)
    for event in event_records:
        validate_merge_event_raw(
            event,
            attempts=attempt_map,
            bindings=binding_map,
            artifacts=all_artifacts,
        )
    for artifact in artifact_map.values():
        validate_node_artifact(
            artifact,
            cache_events=event_map,
            node_artifacts=all_artifacts,
            content_artifacts=content_artifacts,
            accepted_bindings=binding_records,
        )
    merge_metrics = [
        derive_merge_event_metrics(
            event,
            artifacts=artifact_map,
            plan_nodes_by_logical_node=plan_node_map,
            attempt=(
                attempt_map[
                    binding_map[str(event["accepted_binding_id"])]["accepted_attempt_id"]
                ]
                if event.get("accepted_binding_id") is not None
                else None
            ),
        )
        for event in event_records
    ]
    metrics_by_logical_node = {
        str(metric["logical_operation_id"]): metric for metric in merge_metrics
    }
    generative_logical_node_ids = {
        str(event["logical_operation_id"])
        for event in event_records
        if _artifact_has_generative_lineage(
            str(event["output_materialized_node_id"]),
            artifacts=all_artifacts,
            cache_events=event_map,
        )
    }
    return {
        "plan_metrics": derive_plan_metrics(plan_node_map),
        "merge_event_metrics": merge_metrics,
        "evidence_exposure": derive_evidence_exposure(
            plan_node_map,
            merge_metrics_by_logical_node=metrics_by_logical_node,
            generative_logical_node_ids=generative_logical_node_ids,
        ),
        "resource_work": reconcile_work(
            attempt_records, binding_records, merge_events=event_records
        ),
    }
