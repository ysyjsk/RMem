from __future__ import annotations

import json
from pathlib import Path

import pytest

from plan_robust_memory.hashing import stable_hash


def test_local_real_manifest_and_power_artifact_are_bound_and_reproducible() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest_path = root / "artifacts/longmemeval/dataset_manifest.json"
    power_path = root / "artifacts/power/power_feasibility.json"
    if not manifest_path.exists() or not power_path.exists():
        pytest.skip(
            "real data artifacts are intentionally gitignored; run the audit and power Gate locally"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    power = json.loads(power_path.read_text(encoding="utf-8"))

    assert manifest["audit_hash"] == stable_hash(
        {key: value for key, value in manifest.items() if key != "audit_hash"}
    )
    assert power["input_audit_hash"] == manifest["audit_hash"]
    assert power["artifact_hash"] == stable_hash(
        {key: value for key, value in power.items() if key != "artifact_hash"}
    )
    assert power["topology_results_seen"] is False
    assert power["full_leaf_generation_allowed"] is False
