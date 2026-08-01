from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.leakage import assert_no_cross_split_overlap


def test_construction_unit_overlap_across_splits_fails() -> None:
    rows = [{"construction_unit_id": "cu1", "split": "development"}, {"construction_unit_id": "cu1", "split": "acceptance"}]
    with pytest.raises(ContractError, match="construction_unit_id"):
        assert_no_cross_split_overlap(rows, "construction_unit_id")

