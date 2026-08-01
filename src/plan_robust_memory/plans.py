from __future__ import annotations

from dataclasses import dataclass

from .contracts import ContractError, PI_DIAG, PI_ONLINE, PI_PRIMARY


@dataclass(frozen=True)
class MergeOp:
    left: str
    right: str
    output: str
    span: tuple[int, int]


@dataclass(frozen=True)
class PlanDescriptor:
    plan_id: str
    plan_set_id: str
    k: int
    leaf_ids: tuple[str, ...]
    ordered_merge_operations: tuple[MergeOp, ...]
    online_or_offline: str = "offline"
    prefix_queryable: bool = False
    rebuild_interval: int | None = None


def _leaf_ids(k: int) -> tuple[str, ...]:
    return tuple(f"leaf_{i}" for i in range(k))


def _left_deep(k: int) -> tuple[MergeOp, ...]:
    ops = []
    current = "leaf_0"
    start = 0
    for i in range(1, k):
        output = f"node_L_{i}"
        ops.append(MergeOp(current, f"leaf_{i}", output, (start, i)))
        current = output
    return tuple(ops)


def _right_deep_range(start: int, end: int) -> tuple[MergeOp, ...]:
    if start == end:
        return ()
    if end - start == 1:
        return (MergeOp(f"leaf_{start}", f"leaf_{end}", f"node_R_{start}_{end}", (start, end)),)
    inner = _right_deep_range(start + 1, end)
    right = inner[-1].output if inner else f"leaf_{start + 1}"
    return (*inner, MergeOp(f"leaf_{start}", right, f"node_R_{start}_{end}", (start, end)))


def _balanced_range(start: int, end: int) -> tuple[MergeOp, ...]:
    if start == end:
        return ()
    mid = (start + end) // 2
    left_ops = _balanced_range(start, mid)
    right_ops = _balanced_range(mid + 1, end)
    left = left_ops[-1].output if left_ops else f"leaf_{start}"
    right = right_ops[-1].output if right_ops else f"leaf_{mid + 1}"
    return (*left_ops, *right_ops, MergeOp(left, right, f"node_B_{start}_{end}", (start, end)))


def generate_plan(plan_id: str, k: int, plan_set_id: str = "primary") -> PlanDescriptor:
    if k <= 1:
        raise ContractError("plan requires at least two leaves")
    if plan_id == "left_deep":
        ops = _left_deep(k)
    elif plan_id == "canonical_balanced":
        ops = _balanced_range(0, k - 1)
    elif plan_id == "right_deep":
        ops = _right_deep_range(0, k - 1)
    elif plan_id == "eager_left_deep":
        ops = _left_deep(k)
    elif plan_id == "online_canonical_balanced":
        ops = _balanced_range(0, k - 1)
    else:
        raise ContractError(f"unknown plan_id: {plan_id}")
    online = plan_id in PI_ONLINE
    return PlanDescriptor(
        plan_id=plan_id,
        plan_set_id=plan_set_id,
        k=k,
        leaf_ids=_leaf_ids(k),
        ordered_merge_operations=ops,
        online_or_offline="online" if online else "offline",
        prefix_queryable=online,
    )


def validate_plan_descriptor(plan: PlanDescriptor) -> None:
    if plan.plan_set_id == "primary" and plan.plan_id not in PI_PRIMARY:
        raise ContractError("primary plan descriptor can only contain Pi_primary plans")
    if plan.plan_set_id == "diagnostic" and plan.plan_id not in PI_DIAG:
        raise ContractError("diagnostic plan descriptor can only contain Pi_diag plans")
    if plan.plan_set_id == "online" and plan.plan_id not in PI_ONLINE:
        raise ContractError("online plan descriptor can only contain Pi_online plans")
    if len(plan.ordered_merge_operations) != plan.k - 1:
        raise ContractError("plan must contain k-1 merge operations")
    if sorted(plan.leaf_ids) != [f"leaf_{i}" for i in range(plan.k)]:
        raise ContractError("plan must use every leaf exactly once")
    if plan.ordered_merge_operations[-1].span != (0, plan.k - 1):
        raise ContractError("root merge must cover the full span")


def assert_online_no_future_read(prefix_index: int, plan: PlanDescriptor) -> None:
    for op in plan.ordered_merge_operations:
        if op.span[1] > prefix_index:
            raise ContractError("online plan attempted a future read")

