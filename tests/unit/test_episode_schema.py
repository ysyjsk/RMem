from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError, validate_episode


def test_valid_episode_passes(valid_episode: dict) -> None:
    assert validate_episode(valid_episode) == valid_episode


def test_missing_construction_unit_fails(valid_episode: dict) -> None:
    valid_episode.pop("construction_unit_id")
    with pytest.raises(ContractError, match="construction_unit_id"):
        validate_episode(valid_episode)


def test_duplicate_ordered_evidence_fails(valid_episode: dict) -> None:
    valid_episode["ordered_evidence_ids"] = ["ev-001", "ev-001"]
    with pytest.raises(ContractError, match="ordered_evidence_ids"):
        validate_episode(valid_episode)

