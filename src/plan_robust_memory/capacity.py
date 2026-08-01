from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import ContractError, validate_primary_capacity
from .hashing import stable_hash


def leaf_cache_key(
    *,
    dataset_version_or_commit: str,
    episode_id: str,
    k: int,
    partition_hash: str,
    evidence_span: tuple[int, int],
    c_leaf: int,
    leaf_prompt_hash: str,
    constructor_model_snapshot: str,
    decoding_config_hash: str,
    s_leaf: int,
    backbone_id: str,
) -> str:
    return stable_hash(
        {
            "dataset_version_or_commit": dataset_version_or_commit,
            "episode_id": episode_id,
            "k": k,
            "partition_hash": partition_hash,
            "evidence_span": evidence_span,
            "C_leaf": c_leaf,
            "leaf_prompt_hash": leaf_prompt_hash,
            "constructor_model_snapshot": constructor_model_snapshot,
            "decoding_config_hash": decoding_config_hash,
            "s_leaf": s_leaf,
            "backbone_id": backbone_id,
        }
    )


def validate_leaf_cache_shared(rows: Iterable[Mapping[str, Any]]) -> None:
    by_leaf: dict[tuple[str, str, int, int], set[str]] = {}
    for row in rows:
        key = (
            str(row["episode_id"]),
            str(row["backbone_id"]),
            int(row["k"]),
            int(row["leaf_index"]),
        )
        by_leaf.setdefault(key, set()).add(str(row["leaf_sha256"]))
    bad = [key for key, hashes in by_leaf.items() if len(hashes) != 1]
    if bad:
        raise ContractError("all budgets/topologies must reuse the same leaf SHA-256")


def validate_budget_sweep(rows: Iterable[Mapping[str, Any]]) -> None:
    by_budget: dict[str, int] = {}
    for row in rows:
        b = validate_primary_capacity(row)
        budget_id = str(row.get("budget_id"))
        if budget_id in by_budget and by_budget[budget_id] != b:
            raise ContractError("same budget_id must use the same B across topologies")
        by_budget[budget_id] = b
    if len(set(by_budget.values())) <= 1 and len(by_budget) > 1:
        raise ContractError("primary budget sweep must actually change B_query")

