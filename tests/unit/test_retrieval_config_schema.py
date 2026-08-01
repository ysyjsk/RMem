from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import validate

from plan_robust_memory.contracts import ContractError, validate_retrieval_config


def test_retrieval_config_matches_schema(valid_retrieval_config: dict) -> None:
    schema = json.loads(Path("schemas/retrieval_config.schema.json").read_text())
    validate(valid_retrieval_config, schema)
    validate_retrieval_config(valid_retrieval_config)


def test_embedding_alias_without_revision_fails(valid_retrieval_config: dict) -> None:
    valid_retrieval_config["embedding_model_snapshot"] = "BAAI/bge-m3"
    with pytest.raises(ContractError, match="explicit revision"):
        validate_retrieval_config(valid_retrieval_config)

