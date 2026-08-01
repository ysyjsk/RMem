from __future__ import annotations

from plan_robust_memory.execution import stall_blocks_next_milestone


def test_stall_report_blocks_next_milestone() -> None:
    assert stall_blocks_next_milestone({"p14_triggered": True, "reported_to_user": True, "next_milestone_blocked": True})

