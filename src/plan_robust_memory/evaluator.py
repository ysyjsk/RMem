from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
import re

from .contracts import ContractError
from .hashing import stable_hash


def _normalize_answer(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def exact_match_score(reference: str, candidate: str) -> int:
    return int(_normalize_answer(reference) == _normalize_answer(candidate))


def substring_exact_match_score(reference: str | Iterable[str], candidate: str) -> int:
    if isinstance(reference, str):
        references = (reference,)
    else:
        references = tuple(reference)
    candidate_norm = _normalize_answer(candidate)
    return int(
        any(_normalize_answer(item) and _normalize_answer(item) in candidate_norm for item in references)
    )


def validate_project_judge_config(config: Mapping[str, Any]) -> None:
    if config.get("requested_model") != "gpt-5.5":
        raise ContractError("project judge requested_model must be gpt-5.5")
    returned = str(config.get("returned_model", ""))
    if not returned or returned in {"latest", "default"} or returned.endswith("-latest"):
        raise ContractError("project judge returned_model must be frozen")
    if not config.get("provider") or not config.get("base_url"):
        raise ContractError("project judge provider/base_url must be recorded")


def judge_cache_key(*, question_id: str, reference_answer_hash: str, candidate_answer_hash: str, judge_prompt_hash: str, judge_model: str, decoding_config_hash: str, output_schema_version: str) -> str:
    return stable_hash(locals())


def repeatability_metrics(rows: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    by_case: dict[str, list[int]] = {}
    parse_success = 0
    total = 0
    for row in rows:
        total += 1
        parse_success += int(bool(row.get("parse_success")))
        by_case.setdefault(str(row["case_id"]), []).append(int(row["label"]))
    unanimity = sum(1 for labels in by_case.values() if len(set(labels)) == 1) / len(by_case)
    flips = 0
    pairs = 0
    for labels in by_case.values():
        for i, left in enumerate(labels):
            for right in labels[i + 1 :]:
                pairs += 1
                flips += int(left != right)
    return {
        "unanimity_rate": unanimity,
        "pairwise_flip_rate": flips / pairs if pairs else 0.0,
        "parse_success_rate": parse_success / total if total else 0.0,
    }


def judge_repeatability_passes(rows: Iterable[Mapping[str, Any]]) -> bool:
    metrics = repeatability_metrics(rows)
    return metrics["unanimity_rate"] >= 0.95 and metrics["pairwise_flip_rate"] <= 0.05 and metrics["parse_success_rate"] == 1.0
