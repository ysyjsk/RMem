from __future__ import annotations

import pytest

from plan_robust_memory.statistics import StatisticContractError, validate_common_random_numbers


def test_common_random_numbers_are_paired_by_replicate() -> None:
    validate_common_random_numbers([
        {"replicate_id": 2, "plan_id": "left_deep", "s_merge": 2, "s_answer": 2},
        {"replicate_id": 2, "plan_id": "canonical_balanced", "s_merge": 2, "s_answer": 2},
    ])


def test_unpaired_common_random_numbers_fail() -> None:
    with pytest.raises(StatisticContractError, match="common random"):
        validate_common_random_numbers([
            {"replicate_id": 2, "plan_id": "left_deep", "s_merge": 2, "s_answer": 2},
            {"replicate_id": 2, "plan_id": "canonical_balanced", "s_merge": 3, "s_answer": 2},
        ])

