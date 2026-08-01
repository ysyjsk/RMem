from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TokenizerSpec:
    tokenizer_id: str
    tokenizer_revision: str
    serialization_version: str
    estimator: str = "surrogate_regex_bytes_v1"
    safety_margin: float = 0.0


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]|[^\s]")


def validate_tokenizer_spec(spec: TokenizerSpec | Mapping[str, Any]) -> TokenizerSpec:
    if not isinstance(spec, TokenizerSpec):
        spec = TokenizerSpec(**dict(spec))
    for field in ("tokenizer_id", "tokenizer_revision", "serialization_version", "estimator"):
        value = getattr(spec, field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        if value in {"latest", "default"} or value.endswith("-latest"):
            raise ValueError(f"{field} must not use a rolling alias")
    if spec.safety_margin < 0:
        raise ValueError("safety_margin must be non-negative")
    if spec.estimator != "surrogate_regex_bytes_v1":
        raise ValueError("unsupported tokenizer estimator")
    return spec


def count_tokens(text: str, tokenizer_spec: TokenizerSpec | Mapping[str, Any]) -> int:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    spec = validate_tokenizer_spec(tokenizer_spec)
    base_count = len(TOKEN_PATTERN.findall(text))
    if base_count == 0:
        return 0
    return int(math.ceil(base_count * (1.0 + spec.safety_margin)))


def sum_tokens(items: Iterable[dict]) -> int:
    total = 0
    for item in items:
        token_count = item.get("token_count")
        if not isinstance(token_count, int) or token_count < 0:
            raise ValueError("token_count must be a non-negative integer")
        total += token_count
    return total
