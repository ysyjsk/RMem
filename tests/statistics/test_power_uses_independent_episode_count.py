from __future__ import annotations

import pytest

from plan_robust_memory.statistics import PowerDesignError, validate_power_design


def test_power_design_uses_independent_episode_count() -> None:
    design = validate_power_design(independent_episodes=80, repeated_rows=400, r_formal=5)
    assert design.analysis_n == 80


def test_repeated_rows_cannot_be_declared_as_analysis_n() -> None:
    with pytest.raises(PowerDesignError, match="independent episode"):
        validate_power_design(
            independent_episodes=80,
            repeated_rows=400,
            r_formal=5,
            declared_analysis_n=400,
        )

