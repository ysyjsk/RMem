from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.leakage import assert_no_cross_split_overlap


def test_base_question_overlap_across_splits_fails() -> None:
    rows = [{"base_question_id": "bq1", "split": "calibration"}, {"base_question_id": "bq1", "split": "acceptance"}]
    with pytest.raises(ContractError, match="base_question_id"):
        assert_no_cross_split_overlap(rows, "base_question_id")

