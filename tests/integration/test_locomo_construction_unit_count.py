from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.data_audit import validate_locomo_construction_units


def test_locomo_uses_ten_conversation_units() -> None:
    validate_locomo_construction_units([{"conversation_id": str(i)} for i in range(10)])


def test_locomo_query_count_cannot_replace_conversation_units() -> None:
    with pytest.raises(ContractError, match="10 conversation"):
        validate_locomo_construction_units([{"query_id": str(i)} for i in range(50)])

