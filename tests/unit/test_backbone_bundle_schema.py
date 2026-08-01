from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import validate

from plan_robust_memory.contracts import ContractError, validate_backbone_bundle


def test_backbone_bundle_matches_schema(valid_backbone: dict) -> None:
    schema = json.loads(Path("schemas/backbone_bundle.schema.json").read_text())
    validate(valid_backbone, schema)
    validate_backbone_bundle(valid_backbone)


def test_rolling_model_alias_fails(valid_backbone: dict) -> None:
    valid_backbone["constructor_model_snapshot"] = "gpt-5.6-sol-latest"
    with pytest.raises(ContractError, match="rolling alias"):
        validate_backbone_bundle(valid_backbone)

