from __future__ import annotations

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.evaluator import validate_project_judge_config


def test_project_judge_model_is_frozen() -> None:
    validate_project_judge_config({"requested_model": "gpt-5.5", "returned_model": "gpt-5.5-2026-08-01", "provider": "labforge", "base_url": "https://api.labforge.cc/v1"})


def test_project_judge_rolling_alias_fails() -> None:
    with pytest.raises(ContractError, match="frozen"):
        validate_project_judge_config({"requested_model": "gpt-5.5", "returned_model": "gpt-5.5-latest", "provider": "labforge", "base_url": "https://api.labforge.cc/v1"})

