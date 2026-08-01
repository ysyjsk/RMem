from __future__ import annotations

from plan_robust_memory.statistics import formal_no_go_allowed


def test_seed_null_is_not_a_no_go_input() -> None:
    checks = {
        "signal_bearing_budget": True,
        "formal_power": True,
        "primary_under_delta": True,
        "stress_under_delta": True,
        "ci_excludes_delta_decision": True,
        "judge_repeatability": True,
        "non_ceiling_only": True,
        "online_gate_handled": True,
        "d_seed_pair_below_delta": False,
    }
    assert formal_no_go_allowed(checks)

