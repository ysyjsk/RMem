from __future__ import annotations

from plan_robust_memory.reproducibility import rebuild_power_artifact_hash


def test_power_artifact_rebuild_hash_is_stable() -> None:
    artifact = {"delta_decision": 0.075, "power": 0.81, "seed": 7}
    assert rebuild_power_artifact_hash(artifact) == rebuild_power_artifact_hash({"seed": 7, "power": 0.81, "delta_decision": 0.075})

