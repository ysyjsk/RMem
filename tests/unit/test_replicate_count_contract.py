from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError, R_FORMAL, R_PILOT, validate_replicate_counts


def test_replicate_counts_are_frozen() -> None:
    assert (R_PILOT, R_FORMAL) == (3, 5)
    validate_replicate_counts(r_pilot=3, r_formal=5)


def test_wrong_replicate_count_fails() -> None:
    with pytest.raises(ContractError, match="R_formal"):
        validate_replicate_counts(r_pilot=3, r_formal=3)

