from __future__ import annotations

from dataclasses import dataclass

from .contracts import ContractError, PI_DIAG, PI_ONLINE, PI_PRIMARY
from .observability import derive_plan_metrics


@dataclass(frozen=True)
class MergeOp:
    left: str
    right: str
    output: str
    span: tuple[int, int]


@dataclass(frozen=True)
class PlanNodeRaw:
    logical_node_id: str
    plan_id: str
    node_type: str
    leaf_id: str | None
    left_logical_child_id: str | None
    right_logical_child_id: str | None
    covered_span: tuple[int, int]

    def as_record(self) -> dict[str, object]:
        return {
            "logical_node_id": self.logical_node_id,
            "plan_id": self.plan_id,
            "node_type": self.node_type,
            "leaf_id": self.leaf_id,
            "left_logical_child_id": self.left_logical_child_id,
            "right_logical_child_id": self.right_logical_child_id,
            "covered_span": list(self.covered_span),
        }


@dataclass(frozen=True)
class PlanDescriptor:
    plan_id: str
    plan_set_id: str
    k: int
    leaf_ids: tuple[str, ...]
    plan_nodes: tuple[PlanNodeRaw, ...]
    online_or_offline: str = "offline"
    prefix_queryable: bool = False
    rebuild_interval: int | None = None

    @property
    def ordered_merge_operations(self) -> tuple[MergeOp, ...]:
        """Derive execution order from the frozen raw child graph."""
        node_map = {node.logical_node_id: node for node in self.plan_nodes}
        child_ids = {
            child_id
            for node in self.plan_nodes
            for child_id in (
                node.left_logical_child_id,
                node.right_logical_child_id,
            )
            if child_id is not None
        }
        roots = set(node_map) - child_ids
        if len(roots) != 1:
            raise ContractError("plan child graph must have exactly one root")
        operations: list[MergeOp] = []

        def visit(node_id: str) -> None:
            node = node_map.get(node_id)
            if node is None:
                raise ContractError("plan child graph references an unknown node")
            if node.node_type == "leaf":
                return
            if node.left_logical_child_id is None or node.right_logical_child_id is None:
                raise ContractError("internal plan node requires two child IDs")
            visit(node.left_logical_child_id)
            visit(node.right_logical_child_id)
            operations.append(
                MergeOp(
                    node.left_logical_child_id,
                    node.right_logical_child_id,
                    node.logical_node_id,
                    node.covered_span,
                )
            )

        visit(next(iter(roots)))
        return tuple(operations)


@dataclass(frozen=True)
class OnlineNode:
    node_id: str
    span: tuple[int, int]
    level: int


@dataclass(frozen=True)
class OnlineState:
    prefix_index: int
    level_nodes: tuple[OnlineNode, ...]
    merge_events: tuple[MergeOp, ...]
    live_forest: tuple[OnlineNode, ...]
    render_order: tuple[str, ...]
    deployment_memory_tokens: int | None = None
    deployment_metadata_bytes: int | None = None
    deployment_capability_profile: str | None = None


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


def _plan_nodes_from_operations(
    plan_id: str, k: int, operations: tuple[MergeOp, ...]
) -> tuple[PlanNodeRaw, ...]:
    leaves = tuple(
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
    )
    internals = tuple(
        PlanNodeRaw(
            logical_node_id=operation.output,
            plan_id=plan_id,
            node_type="internal",
            leaf_id=None,
            left_logical_child_id=operation.left,
            right_logical_child_id=operation.right,
            covered_span=operation.span,
        )
        for operation in operations
    )
    return (*leaves, *internals)


def build_online_canonical_states(k: int) -> tuple[OnlineState, ...]:
    """Binary-counter online balanced compaction states for every prefix.

    The final tree for powers of two matches canonical balanced, but the
    prefix states are the contract: each prefix has an ordered live forest
    covering exactly the leaves seen so far and never contains a future span.
    """
    if k <= 0:
        raise ContractError("online state machine requires at least one leaf")

    slots: dict[int, OnlineNode] = {}
    merge_events: list[MergeOp] = []
    states: list[OnlineState] = []

    for leaf_index in range(k):
        carried = OnlineNode(f"leaf_{leaf_index}", (leaf_index, leaf_index), 0)
        while carried.level in slots:
            left = slots.pop(carried.level)
            if left.span[1] + 1 != carried.span[0]:
                raise ContractError("online compaction requires contiguous level nodes")
            output = f"node_OB_{left.span[0]}_{carried.span[1]}_L{carried.level + 1}"
            op = MergeOp(left.node_id, carried.node_id, output, (left.span[0], carried.span[1]))
            merge_events.append(op)
            carried = OnlineNode(output, op.span, carried.level + 1)
        slots[carried.level] = carried

        level_nodes = tuple(sorted(slots.values(), key=lambda node: node.level))
        live_forest = tuple(sorted(slots.values(), key=lambda node: node.span[0]))
        states.append(
            OnlineState(
                prefix_index=leaf_index,
                level_nodes=level_nodes,
                merge_events=tuple(merge_events),
                live_forest=live_forest,
                render_order=tuple(node.node_id for node in live_forest),
            )
        )

    return tuple(states)


def online_state_at_prefix(k: int, prefix_index: int) -> OnlineState:
    if prefix_index < 0 or prefix_index >= k:
        raise ContractError("prefix_index must refer to an observed leaf, not a future leaf")
    return build_online_canonical_states(k)[prefix_index]


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
        ops = build_online_canonical_states(k)[-1].merge_events
    else:
        raise ContractError(f"unknown plan_id: {plan_id}")
    online = plan_id in PI_ONLINE
    return PlanDescriptor(
        plan_id=plan_id,
        plan_set_id=plan_set_id,
        k=k,
        leaf_ids=_leaf_ids(k),
        plan_nodes=_plan_nodes_from_operations(plan_id, k, ops),
        online_or_offline="online" if online else "offline",
        prefix_queryable=online,
    )


def validate_plan_descriptor(plan: PlanDescriptor) -> None:
    if plan.k <= 1:
        raise ContractError("plan requires at least two leaves")
    if plan.plan_set_id == "primary" and plan.plan_id not in PI_PRIMARY:
        raise ContractError("primary plan descriptor can only contain Pi_primary plans")
    if plan.plan_set_id == "diagnostic" and plan.plan_id not in PI_DIAG:
        raise ContractError("diagnostic plan descriptor can only contain Pi_diag plans")
    if plan.plan_set_id == "online" and plan.plan_id not in PI_ONLINE:
        raise ContractError("online plan descriptor can only contain Pi_online plans")
    expected_leaf_ids = _leaf_ids(plan.k)
    if plan.leaf_ids != expected_leaf_ids:
        raise ContractError("plan must list every leaf exactly once in evidence order")
    if plan.online_or_offline == "online" and not plan.prefix_queryable:
        raise ContractError("online plans must be prefix queryable")
    metrics = derive_plan_metrics(node.as_record() for node in plan.plan_nodes)
    if any(node.plan_id != plan.plan_id for node in plan.plan_nodes):
        raise ContractError("PlanNodeRaw plan_id must match its Plan descriptor")
    if tuple(metrics["descendant_leaf_ids"]) != plan.leaf_ids:
        raise ContractError("plan child graph must contain every leaf once in evidence order")
    if metrics["merge_count"] != plan.k - 1:
        raise ContractError("plan must contain k-1 merge operations")


def _assert_live_forest_covers_prefix(state: OnlineState) -> None:
    next_start = 0
    for node in state.live_forest:
        if node.span[0] != next_start:
            raise ContractError("online live forest must cover the current prefix contiguously")
        if node.span[1] > state.prefix_index:
            raise ContractError("online live forest attempted a future read")
        next_start = node.span[1] + 1
    if next_start != state.prefix_index + 1:
        raise ContractError("online live forest must cover the current prefix exactly")


def assert_online_no_future_read(prefix_index: int, plan: PlanDescriptor) -> None:
    if plan.online_or_offline != "online" or not plan.prefix_queryable:
        raise ContractError("future-read checks require a prefix-queryable online plan")
    if plan.plan_id == "online_canonical_balanced":
        state = online_state_at_prefix(plan.k, prefix_index)
        for op in state.merge_events:
            if op.span[1] > prefix_index:
                raise ContractError("online plan attempted a future read")
        _assert_live_forest_covers_prefix(state)
        return

    if plan.plan_id == "eager_left_deep":
        if prefix_index < 0 or prefix_index >= plan.k:
            raise ContractError("prefix_index must refer to an observed leaf, not a future leaf")
        for op in plan.ordered_merge_operations:
            if op.span[1] <= prefix_index:
                continue
            if op.span[0] <= prefix_index:
                raise ContractError("online plan attempted a future read")
        return

    raise ContractError("unknown online plan")
