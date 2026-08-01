from __future__ import annotations

from plan_robust_memory.data_audit import replication_dataset_decision


def test_replication_dataset_with_too_few_units_limits_claim_scope() -> None:
    assert replication_dataset_decision({"independent_construction_units": 10, "minimum_required_units": 50}) == "stress_or_scope_limited"

