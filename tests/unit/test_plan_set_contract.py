from __future__ import annotations

import pytest

from plan_robust_memory.contracts import PI_DIAG, PI_ONLINE, PI_PRIMARY, ContractError, validate_plan_sets


def test_plan_sets_are_claim_scoped() -> None:
    assert PI_PRIMARY == ("left_deep", "canonical_balanced")
    assert PI_DIAG == ("left_deep", "canonical_balanced", "right_deep")
    assert PI_ONLINE == ("eager_left_deep", "online_canonical_balanced")
    validate_plan_sets(PI_PRIMARY, PI_DIAG, PI_ONLINE)


def test_right_deep_in_primary_fails() -> None:
    with pytest.raises(ContractError, match="right_deep"):
        validate_plan_sets(("left_deep", "right_deep"), PI_DIAG, PI_ONLINE)

