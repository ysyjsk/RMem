from __future__ import annotations

from dataclasses import dataclass

from .contracts import ContractError, K_PLANNED
from .hashing import stable_hash


@dataclass(frozen=True)
class Span:
    start: int
    end: int


def token_balanced_partition(token_counts: list[int], k: int) -> list[Span]:
    if k not in K_PLANNED:
        raise ContractError("k must be one of the preregistered K_planned values")
    if len(token_counts) < k:
        raise ContractError("not enough atomic evidence items for k non-empty leaves")
    if any(not isinstance(value, int) or value <= 0 for value in token_counts):
        raise ContractError("token counts must be positive integers")

    total = sum(token_counts)
    cumulative = []
    running = 0
    for count in token_counts:
        running += count
        cumulative.append(running)

    boundaries: list[int] = []
    previous = 0
    n = len(token_counts)
    for j in range(1, k):
        min_boundary = previous + 1
        max_boundary = n - (k - j)
        target = j * total / k
        candidates = range(min_boundary, max_boundary + 1)
        boundary = min(candidates, key=lambda index: (abs(cumulative[index - 1] - target), index))
        boundaries.append(boundary)
        previous = boundary

    points = [0, *boundaries, n]
    return [Span(points[i], points[i + 1] - 1) for i in range(k)]


def partition_hash(spans: list[Span], k: int) -> str:
    return stable_hash({"algorithm": "token_balanced_v1", "k": k, "spans": [span.__dict__ for span in spans]})

