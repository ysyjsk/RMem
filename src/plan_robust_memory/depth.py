from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .contracts import ContractError
from .plans import PlanDescriptor, validate_plan_descriptor


@dataclass(frozen=True)
class DepthDescriptor:
    d_mean: float
    d_max: int
    d_joint: int
    n_supporting_leaves: int
    evidence_spans_multiple_leaves: bool
    topology_insensitive: bool = False


def answer_sessions_to_leaves(answer_session_ids: list[str], evidence_to_leaf: Mapping[str, int]) -> set[int]:
    try:
        return {int(evidence_to_leaf[item]) for item in answer_session_ids}
    except KeyError as exc:
        raise ContractError("answer session does not map to a leaf") from exc


def leaf_depths(plan: PlanDescriptor) -> dict[int, int]:
    depths = {i: 0 for i in range(plan.k)}
    for op in plan.ordered_merge_operations:
        for leaf_index in range(op.span[0], op.span[1] + 1):
            depths[leaf_index] += 1
    return depths


def _parent_map(plan: PlanDescriptor) -> tuple[dict[str, str], dict[str, tuple[int, int]]]:
    validate_plan_descriptor(plan)
    parents: dict[str, str] = {}
    spans = {f"leaf_{index}": (index, index) for index in range(plan.k)}
    for op in plan.ordered_merge_operations:
        parents[op.left] = op.output
        parents[op.right] = op.output
        spans[op.output] = op.span
    return parents, spans


def _ancestors_to_root(node_id: str, parents: Mapping[str, str]) -> tuple[str, ...]:
    ancestors = [node_id]
    current = node_id
    while current in parents:
        current = parents[current]
        ancestors.append(current)
    return tuple(ancestors)


def joint_rewrite_distance(plan: PlanDescriptor, supporting_leaves: set[int]) -> int:
    if not supporting_leaves:
        raise ContractError("supporting leaves must not be empty")
    if any(index < 0 or index >= plan.k for index in supporting_leaves):
        raise ContractError("supporting leaves must be valid leaf indices")

    parents, spans = _parent_map(plan)
    ancestor_lists = [
        _ancestors_to_root(f"leaf_{index}", parents) for index in sorted(supporting_leaves)
    ]
    common_ancestors = set(ancestor_lists[0]).intersection(*map(set, ancestor_lists[1:]))
    min_support = min(supporting_leaves)
    max_support = max(supporting_leaves)

    lca = min(
        (
            node_id
            for node_id in common_ancestors
            if spans[node_id][0] <= min_support and spans[node_id][1] >= max_support
        ),
        key=lambda node_id: spans[node_id][1] - spans[node_id][0],
    )

    distance = 0
    current = lca
    while current in parents:
        current = parents[current]
        distance += 1
    return distance


def depth_descriptor(plan: PlanDescriptor, supporting_leaves: set[int]) -> DepthDescriptor:
    if not supporting_leaves:
        raise ContractError("supporting leaves must not be empty")
    depths = leaf_depths(plan)
    selected = [depths[index] for index in supporting_leaves]
    multiple = len(supporting_leaves) > 1
    return DepthDescriptor(
        d_mean=sum(selected) / len(selected),
        d_max=max(selected),
        d_joint=joint_rewrite_distance(plan, supporting_leaves),
        n_supporting_leaves=len(supporting_leaves),
        evidence_spans_multiple_leaves=multiple,
        topology_insensitive=False,
    )


def depth_identifiability_gate(descriptors: list[Mapping[str, object]]) -> str:
    depths = {float(row["d_mean"]) for row in descriptors}
    plans = {str(row["plan_id"]) for row in descriptors}
    if len(depths) < 2 or len(plans) < 2:
        return "descriptive_only"
    if all(str(row.get("depth_plan_collinear", False)).lower() == "true" for row in descriptors):
        return "descriptive_only"
    return "identifiable"
