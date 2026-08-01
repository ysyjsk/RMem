from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.execution import proxy_probe_result


def test_proxy_probe_uses_17897_and_finite_attempts() -> None:
    assert proxy_probe_result(17897, 2, "unavailable")["attempts"] == 2


def test_proxy_probe_rejects_infinite_retry_shape() -> None:
    with pytest.raises(ContractError, match="finite"):
        proxy_probe_result(17897, 99, "retrying")

