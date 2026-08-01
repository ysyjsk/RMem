from __future__ import annotations

import json
from pathlib import Path

from plan_robust_memory.contracts import validate_k_sweep_cohorts


def test_fixture_k_sweep_cohort_uses_common_e16() -> None:
    manifest = json.loads(Path("data/fixtures/test_set_manifest_v1.json").read_text())
    e16 = {row["episode_id"] for row in manifest["episodes"] if row["atomic_evidence_count"] >= 16}
    validate_k_sweep_cohorts({4: e16, 8: e16, 16: e16})

