from __future__ import annotations

import pytest

from plan_robust_memory.statistics import PowerDesignError, validate_power_design


def test_repeated_rows_not_independent_episodes_for_depth_power() -> None:
    with pytest.raises(PowerDesignError, match="independent episode"):
        validate_power_design(independent_episodes=54, repeated_rows=486, r_formal=5, declared_analysis_n=486)

