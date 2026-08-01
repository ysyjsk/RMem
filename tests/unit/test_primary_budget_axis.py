from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError, validate_primary_capacity


def test_primary_budget_axis_is_unified() -> None:
    validate_primary_capacity({"B_merge": 512, "B_final": 512, "B_query": 512})


@pytest.mark.parametrize(
    "capacity",
    [
        {"B_merge": 256, "B_final": 512, "B_query": 512},
        {"B_merge": 512, "B_final": 512, "B_query": 256},
    ],
)
def test_primary_budget_axis_mismatch_fails(capacity: dict) -> None:
    with pytest.raises(ContractError, match="B_merge = B_final = B_query"):
        validate_primary_capacity(capacity)

