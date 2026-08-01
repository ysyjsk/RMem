from __future__ import annotations

import pytest

from plan_robust_memory.token_accounting import count_tokens, sum_tokens


def test_token_count_is_deterministic_for_fixture_text() -> None:
    assert count_tokens("alpha beta gamma") == 3


def test_sum_tokens_rejects_missing_counts() -> None:
    with pytest.raises(ValueError, match="token_count"):
        sum_tokens([{"text": "missing"}])

