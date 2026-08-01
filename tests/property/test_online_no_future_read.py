from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.plans import (
    assert_online_no_future_read,
    build_online_canonical_states,
    generate_plan,
)


def test_online_plan_can_query_current_prefix_only() -> None:
    plan = generate_plan("online_canonical_balanced", 8, "online")
    for prefix in range(8):
        assert_online_no_future_read(prefix, plan)


def test_online_plan_rejects_unobserved_prefix() -> None:
    plan = generate_plan("online_canonical_balanced", 8, "online")
    with pytest.raises(ContractError, match="observed leaf"):
        assert_online_no_future_read(8, plan)


def test_online_canonical_balanced_exposes_live_forest_for_each_prefix() -> None:
    states = build_online_canonical_states(8)
    assert [state.prefix_index for state in states] == list(range(8))
    assert states[2].render_order == ("node_OB_0_1_L1", "leaf_2")
    assert states[2].live_forest[-1].span == (2, 2)
    assert states[-1].live_forest[0].span == (0, 7)
