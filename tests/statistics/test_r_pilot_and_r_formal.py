from __future__ import annotations

import pytest

from plan_robust_memory.statistics import StatisticContractError, validate_registered_r_values


def test_r_pilot_and_r_formal_are_registered() -> None:
    validate_registered_r_values(r_pilot=3, r_formal=5)


def test_wrong_registered_r_values_fail() -> None:
    with pytest.raises(StatisticContractError, match="R_pilot=3"):
        validate_registered_r_values(r_pilot=3, r_formal=4)

