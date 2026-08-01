from __future__ import annotations

from collections.abc import Iterable


def count_tokens(text: str) -> int:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return len(text.split())


def sum_tokens(items: Iterable[dict]) -> int:
    total = 0
    for item in items:
        token_count = item.get("token_count")
        if not isinstance(token_count, int) or token_count < 0:
            raise ValueError("token_count must be a non-negative integer")
        total += token_count
    return total

