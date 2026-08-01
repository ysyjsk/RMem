from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError, validate_periodic_rebuild_interval


def test_disabled_periodic_rebuild_uses_null_interval() -> None:
    validate_periodic_rebuild_interval(False, None)


def test_enabled_periodic_rebuild_requires_positive_interval() -> None:
    with pytest.raises(ContractError, match="positive"):
        validate_periodic_rebuild_interval(True, None)

