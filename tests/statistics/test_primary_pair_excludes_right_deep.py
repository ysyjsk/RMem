from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.metrics import validate_primary_statistic_plans


def test_primary_pair_excludes_right_deep() -> None:
    validate_primary_statistic_plans(("left_deep", "canonical_balanced"))
    with pytest.raises(ContractError, match="primary statistic"):
        validate_primary_statistic_plans(("left_deep", "canonical_balanced", "right_deep"))

