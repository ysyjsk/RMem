from __future__ import annotations

import pytest

from plan_robust_memory.token_accounting import (
    TokenizerSpec,
    count_tokens,
    sum_tokens,
    validate_tokenizer_spec,
)


SPEC = TokenizerSpec(
    tokenizer_id="surrogate:labforge-compatible",
    tokenizer_revision="surrogate-regex-v1-2026-08-01",
    serialization_version="memory-payload-json-v1",
)


def test_token_count_requires_explicit_tokenizer_contract() -> None:
    assert count_tokens("alpha beta gamma", SPEC) == 3


def test_token_count_uses_serialized_text_not_whitespace_only() -> None:
    assert count_tokens("你好,world", SPEC) == 4


def test_tokenizer_spec_rejects_rolling_alias() -> None:
    with pytest.raises(ValueError, match="rolling"):
        validate_tokenizer_spec(
            TokenizerSpec(
                tokenizer_id="surrogate",
                tokenizer_revision="latest",
                serialization_version="memory-payload-json-v1",
            )
        )


def test_sum_tokens_rejects_missing_counts() -> None:
    with pytest.raises(ValueError, match="token_count"):
        sum_tokens([{"text": "missing"}])
