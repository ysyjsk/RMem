from __future__ import annotations

import pytest

from plan_robust_memory.statistics import StatisticContractError, seed_null_pair_statistics


def test_seed_null_averages_same_number_of_runs_as_real_statistic() -> None:
    run_vectors = {
        0: {"ep-1": 0.0, "ep-2": 1.0},
        1: {"ep-1": 1.0, "ep-2": 0.0},
        2: {"ep-1": 1.0, "ep-2": 1.0},
    }
    values = seed_null_pair_statistics(run_vectors, r_required=3, draws=20, seed=7)
    assert len(values) == 20
    assert all(value >= 0 for value in values)


def test_seed_null_rejects_wrong_r_structure() -> None:
    run_vectors = {0: {"ep-1": 1.0}, 1: {"ep-1": 0.0}}
    with pytest.raises(StatisticContractError, match="R-run"):
        seed_null_pair_statistics(run_vectors, r_required=3, draws=5, seed=7)
