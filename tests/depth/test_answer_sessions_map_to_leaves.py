from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.depth import answer_sessions_to_leaves


def test_answer_sessions_map_to_leaf_ids() -> None:
    assert answer_sessions_to_leaves(["s1", "s2"], {"s1": 0, "s2": 3}) == {0, 3}


def test_missing_answer_session_mapping_fails() -> None:
    with pytest.raises(ContractError, match="map"):
        answer_sessions_to_leaves(["missing"], {"s1": 0})

