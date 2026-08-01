from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import ContractError, eligibility_mask


def longmemeval_counts(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    types = Counter(str(row["question_type"]) for row in rows)
    abstention = Counter(str(row["question_type"]) for row in rows if str(row["query_id"]).endswith("_abs"))
    eligible = [
        row
        for row in rows
        if row["question_type"] in {"knowledge-update", "temporal-reasoning"}
        and not str(row["query_id"]).endswith("_abs")
    ]
    return {"total": len(rows), "question_type_counts": dict(types), "abstention_counts": dict(abstention), "eligible_primary": len(eligible)}


def k_mask_manifest(episodes: Iterable[Mapping[str, Any]]) -> dict[str, dict[int, bool]]:
    return {
        str(row["episode_id"]): eligibility_mask(int(row["atomic_evidence_count"]))
        for row in episodes
    }


def audit_memoryagentbench_contexts(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    contexts = defaultdict(int)
    for row in rows:
        contexts[str(row["context_id"])] += int(row.get("question_count", 1))
    return {"construction_units": len(contexts), "questions_by_context": dict(contexts)}


def validate_locomo_construction_units(conversations: Iterable[Mapping[str, Any]]) -> None:
    count = len(list(conversations))
    if count != 10:
        raise ContractError("LoCoMo must be audited as 10 conversation construction units")


def replication_dataset_decision(audit: Mapping[str, Any]) -> str:
    if audit.get("independent_construction_units", 0) >= audit.get("minimum_required_units", 50):
        return "candidate_for_confirmatory_replication"
    return "stress_or_scope_limited"

