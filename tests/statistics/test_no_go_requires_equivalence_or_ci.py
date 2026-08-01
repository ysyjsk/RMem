from __future__ import annotations

from plan_robust_memory.statistics import formal_no_go_allowed


def test_no_go_requires_ci_or_equivalence_to_exclude_delta() -> None:
    checks = {
        "signal_bearing_budget": True,
        "formal_power": True,
        "primary_under_delta": True,
        "stress_under_delta": True,
        "ci_excludes_delta_decision": False,
        "judge_repeatability": True,
        "non_ceiling_only": True,
        "online_gate_handled": True,
    }
    assert not formal_no_go_allowed(checks)

