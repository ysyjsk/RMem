from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.plans import (
    MergeOp,
    PlanDescriptor,
    PlanNodeRaw,
    generate_plan,
    validate_plan_descriptor,
)


def test_generated_plans_preserve_inorder_spans() -> None:
    plan = generate_plan("canonical_balanced", 8)
    validate_plan_descriptor(plan)
    assert all(op.span[0] <= op.span[1] for op in plan.ordered_merge_operations)
    assert plan.ordered_merge_operations[-1].span == (0, 7)


def _plan_with_ops(k: int, ops: tuple[MergeOp, ...]) -> PlanDescriptor:
    plan_id = "left_deep"
    nodes = tuple(
        PlanNodeRaw(
            logical_node_id=f"leaf_{index}",
            plan_id=plan_id,
            node_type="leaf",
            leaf_id=f"leaf_{index}",
            left_logical_child_id=None,
            right_logical_child_id=None,
            covered_span=(index, index),
        )
        for index in range(k)
    ) + tuple(
        PlanNodeRaw(
            logical_node_id=op.output,
            plan_id=plan_id,
            node_type="internal",
            leaf_id=None,
            left_logical_child_id=op.left,
            right_logical_child_id=op.right,
            covered_span=op.span,
        )
        for op in ops
    )
    return PlanDescriptor(
        plan_id=plan_id,
        plan_set_id="primary",
        k=k,
        leaf_ids=tuple(f"leaf_{index}" for index in range(k)),
        plan_nodes=nodes,
    )


def test_plan_validator_rejects_reused_leaf_child() -> None:
    plan = _plan_with_ops(
        3,
        (
            MergeOp("leaf_0", "leaf_1", "node_0_1", (0, 1)),
            MergeOp("node_0_1", "leaf_1", "node_bad", (0, 2)),
        ),
    )
    with pytest.raises(ContractError, match="exactly one root"):
        validate_plan_descriptor(plan)


def test_plan_validator_rejects_non_contiguous_children() -> None:
    plan = _plan_with_ops(
        3,
        (
            MergeOp("leaf_0", "leaf_2", "node_0_2", (0, 2)),
            MergeOp("node_0_2", "leaf_1", "node_bad", (0, 2)),
        ),
    )
    with pytest.raises(ContractError, match="contiguous"):
        validate_plan_descriptor(plan)


def test_plan_validator_rejects_future_child_reference() -> None:
    plan = _plan_with_ops(
        3,
        (
            MergeOp("leaf_0", "node_future", "node_bad", (0, 1)),
            MergeOp("node_bad", "leaf_2", "node_root", (0, 2)),
        ),
    )
    with pytest.raises(ContractError, match="unknown nodes"):
        validate_plan_descriptor(plan)


def test_plan_validator_rejects_wrong_parent_span() -> None:
    plan = _plan_with_ops(2, (MergeOp("leaf_0", "leaf_1", "node_bad", (0, 0)),))
    with pytest.raises(ContractError, match="span"):
        validate_plan_descriptor(plan)
