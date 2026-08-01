from __future__ import annotations

import pytest

from plan_robust_memory.statistics import PowerDesignError, validate_power_simulation_inputs


def test_power_does_not_use_fraction_times_n() -> None:
    with pytest.raises(PowerDesignError, match="fraction_multiple_leaves"):
        validate_power_simulation_inputs({"uses_fraction_times_n": True, "strata": [{"question_type": "temporal-reasoning", "support_leaf_class": "single"}]})

