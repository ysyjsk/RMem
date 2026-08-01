from __future__ import annotations

from plan_robust_memory.statistics import formal_no_go_allowed


def test_primary_null_requires_stress_prompt_before_no_go() -> None:
    checks = {
        "signal_bearing_budget": True,
        "formal_power": True,
        "primary_under_delta": True,
        "stress_under_delta": False,
        "ci_excludes_delta_decision": True,
        "judge_repeatability": True,
        "non_ceiling_only": True,
        "online_gate_handled": True,
    }
    assert not formal_no_go_allowed(checks)

