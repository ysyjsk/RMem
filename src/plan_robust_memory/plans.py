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
    durable_state_tokens: int | None = None


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
        ordered_merge_operations=ops,
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
    if len(plan.ordered_merge_operations) != plan.k - 1:
        raise ContractError("plan must contain k-1 merge operations")
    expected_leaf_ids = _leaf_ids(plan.k)
    if plan.leaf_ids != expected_leaf_ids:
        raise ContractError("plan must list every leaf exactly once in evidence order")
    if plan.online_or_offline == "online" and not plan.prefix_queryable:
        raise ContractError("online plans must be prefix queryable")

    node_spans: dict[str, tuple[int, int]] = {
        leaf_id: (index, index) for index, leaf_id in enumerate(plan.leaf_ids)
    }
    active_nodes = set(plan.leaf_ids)

    for op in plan.ordered_merge_operations:
        if op.output in node_spans:
            raise ContractError("merge output must be a fresh node")
        if op.left == op.right:
            raise ContractError("merge children must be distinct")
        if op.left not in active_nodes or op.right not in active_nodes:
            raise ContractError("merge children must exist and be active exactly once")

        left_span = node_spans[op.left]
        right_span = node_spans[op.right]
        if left_span[1] + 1 != right_span[0]:
            raise ContractError("merge children must be contiguous and order-preserving")
        expected_span = (left_span[0], right_span[1])
        if op.span != expected_span:
            raise ContractError("merge span must equal the union of child spans")

        active_nodes.remove(op.left)
        active_nodes.remove(op.right)
        active_nodes.add(op.output)
        node_spans[op.output] = op.span

    root = plan.ordered_merge_operations[-1].output
    if active_nodes != {root}:
        raise ContractError("plan must reduce to one root without reusing nodes")
    if node_spans[root] != (0, plan.k - 1):
        raise ContractError("root merge must cover the full span")


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
