from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.leakage import assert_no_cross_split_overlap


def test_answer_session_overlap_across_splits_fails() -> None:
    rows = [{"answer_session_ids": ["s1"], "split": "development"}, {"answer_session_ids": ["s1"], "split": "acceptance"}]
    with pytest.raises(ContractError, match="answer_session_ids"):
        assert_no_cross_split_overlap(rows, "answer_session_ids")

