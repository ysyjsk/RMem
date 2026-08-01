from __future__ import annotations

from plan_robust_memory.statistics import formal_no_go_allowed


def test_ceiling_control_cannot_trigger_no_go() -> None:
    checks = {
        "signal_bearing_budget": True,
        "formal_power": True,
        "primary_under_delta": True,
        "stress_under_delta": True,
        "ci_excludes_delta_decision": True,
        "judge_repeatability": True,
        "non_ceiling_only": False,
        "online_gate_handled": True,
    }
    assert not formal_no_go_allowed(checks)

