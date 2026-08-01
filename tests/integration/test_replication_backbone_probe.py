from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError, validate_replication_backbone
from plan_robust_memory.execution import validate_endpoint_probe


def test_replication_backbone_must_be_different_family(valid_backbone: dict) -> None:
    replication = {**valid_backbone, "backbone_id": "rep", "role": "replication", "model_family": "claude"}
    validate_replication_backbone(valid_backbone, replication)


def test_same_family_replication_fails(valid_backbone: dict) -> None:
    replication = {**valid_backbone, "backbone_id": "rep", "role": "replication"}
    with pytest.raises(ContractError, match="different model family"):
        validate_replication_backbone(valid_backbone, replication)


def test_probe_records_requested_and_returned_model() -> None:
    validate_endpoint_probe({"requested_model": "gpt-5.6-sol", "returned_model": "gpt-5.6-sol-2026-08-01", "provider": "labforge", "base_url": "https://api.labforge.cc/v1", "success": True})

