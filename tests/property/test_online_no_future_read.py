from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.plans import assert_online_no_future_read, generate_plan


def test_online_plan_can_query_current_prefix_only() -> None:
    plan = generate_plan("online_canonical_balanced", 8, "online")
    assert_online_no_future_read(7, plan)


def test_online_plan_future_read_fails() -> None:
    plan = generate_plan("online_canonical_balanced", 8, "online")
    with pytest.raises(ContractError, match="future"):
        assert_online_no_future_read(3, plan)

