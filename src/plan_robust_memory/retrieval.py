from __future__ import annotations

from collections.abc import Mapping

from .contracts import ContractError


def rank_evidence(question_id: str, evidence: list[Mapping[str, object]], scores: Mapping[tuple[str, str], float]) -> list[Mapping[str, object]]:
    if not question_id:
        raise ContractError("retrieval must be query-conditioned")
    return sorted(
        evidence,
        key=lambda item: (
            -float(scores[(question_id, str(item["evidence_id"]))]),
            int(item["sequence_index"]),
            str(item["evidence_id"]),
        ),
    )


def greedy_pack(ranked: list[Mapping[str, object]], budget: int) -> list[Mapping[str, object]]:
    packed = []
    used = 0
    for item in ranked:
        cost = int(item["token_count"]) + int(item.get("serialization_tokens", 0))
        if used + cost <= budget:
            packed.append(item)
            used += cost
    return packed


def render_chronologically(items: list[Mapping[str, object]]) -> list[str]:
    return [str(item["evidence_id"]) for item in sorted(items, key=lambda item: int(item["sequence_index"]))]

