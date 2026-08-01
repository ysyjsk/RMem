from __future__ import annotations

import pytest

from plan_robust_memory.contracts import (
    K_PLANNED,
    K_PRIMARY,
    ContractError,
    eligibility_mask,
    validate_k_sweep_cohorts,
)


def test_k_axis_is_frozen() -> None:
    assert K_PLANNED == (4, 8, 16)
    assert K_PRIMARY == 8


def test_eligibility_mask_is_parameterized() -> None:
    assert eligibility_mask(9) == {4: True, 8: True, 16: False}


def test_k_sweep_uses_common_e16() -> None:
    cohorts = {4: {"ep-1", "ep-2"}, 8: {"ep-1", "ep-2"}, 16: {"ep-1", "ep-2"}}
    validate_k_sweep_cohorts(cohorts)


def test_k_sweep_with_different_episode_sets_fails() -> None:
    cohorts = {4: {"ep-1", "ep-2"}, 8: {"ep-1"}, 16: {"ep-1"}}
    with pytest.raises(ContractError, match="common E_16"):
        validate_k_sweep_cohorts(cohorts)

