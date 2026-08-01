from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .contracts import ContractError
from .plans import PlanDescriptor


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


def depth_descriptor(plan: PlanDescriptor, supporting_leaves: set[int]) -> DepthDescriptor:
    if not supporting_leaves:
        raise ContractError("supporting leaves must not be empty")
    depths = leaf_depths(plan)
    selected = [depths[index] for index in supporting_leaves]
    multiple = len(supporting_leaves) > 1
    return DepthDescriptor(
        d_mean=sum(selected) / len(selected),
        d_max=max(selected),
        d_joint=sum(selected),
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

