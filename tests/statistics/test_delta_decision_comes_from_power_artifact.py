from __future__ import annotations

import pytest

from plan_robust_memory.statistics import PowerDesignError, validate_delta_decision_artifact


def test_delta_decision_comes_from_power_artifact() -> None:
    artifact = {"delta_decision": 0.075, "power": 0.81, "topology_results_seen": False}
    assert validate_delta_decision_artifact(artifact) == 0.075


def test_delta_decision_after_topology_results_fails() -> None:
    with pytest.raises(PowerDesignError, match="before topology"):
        validate_delta_decision_artifact({"delta_decision": 0.075, "power": 0.81, "topology_results_seen": True})

