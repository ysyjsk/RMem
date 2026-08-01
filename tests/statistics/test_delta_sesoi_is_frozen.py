from __future__ import annotations

from plan_robust_memory.contracts import DELTA_SESOI


def test_delta_sesoi_is_five_percentage_points() -> None:
    assert DELTA_SESOI == 0.05

