from __future__ import annotations

from plan_robust_memory.statistics import validate_power_simulation_inputs


def test_power_uses_empirical_evidence_layout_strata() -> None:
    validate_power_simulation_inputs({"uses_fraction_times_n": False, "strata": [{"question_type": "knowledge-update", "support_leaf_class": "multiple"}]})

