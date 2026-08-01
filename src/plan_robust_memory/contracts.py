from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

K_PLANNED = (4, 8, 16)
K_PRIMARY = 8
R_PILOT = 3
R_FORMAL = 5
DELTA_SESOI = 0.05
DELTA_DECISION_GRID = (0.05, 0.075, 0.10, 0.125, 0.15)

PI_PRIMARY = ("left_deep", "canonical_balanced")
PI_DIAG = ("left_deep", "canonical_balanced", "right_deep")
PI_ONLINE = ("eager_left_deep", "online_canonical_balanced")


class ContractError(ValueError):
    """Raised when an artifact violates a frozen protocol contract."""


def _require_nonempty_string(record: Mapping[str, Any], field: str) -> None:
    if not isinstance(record.get(field), str) or not record[field].strip():
        raise ContractError(f"{field} must be a non-empty string")


def validate_episode(episode: Mapping[str, Any]) -> Mapping[str, Any]:
    for field in (
        "dataset_id",
        "dataset_version_or_commit",
        "episode_id",
        "construction_unit_id",
        "family_id",
        "split",
    ):
        _require_nonempty_string(episode, field)

    evidence_ids = episode.get("ordered_evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise ContractError("ordered_evidence_ids must be a non-empty list")
    if any(not isinstance(item, str) or not item for item in evidence_ids):
        raise ContractError("ordered_evidence_ids must contain non-empty strings")
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ContractError("ordered_evidence_ids must not contain duplicates")

    query_ids = episode.get("query_ids")
    if not isinstance(query_ids, list) or not query_ids:
        raise ContractError("query_ids must be a non-empty list")
    if len(query_ids) != len(set(query_ids)):
        raise ContractError("query_ids must not contain duplicates")

    if episode["split"] not in {"development", "calibration", "acceptance"}:
        raise ContractError("split must be development, calibration, or acceptance")
    if not isinstance(episode.get("provenance"), Mapping):
        raise ContractError("provenance must be an object")
    return episode


def validate_primary_capacity(capacity: Mapping[str, Any]) -> int:
    values = []
    for field in ("B_merge", "B_final", "B_query"):
        value = capacity.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ContractError(f"{field} must be a positive integer")
        values.append(value)
    if len(set(values)) != 1:
        raise ContractError("primary requires B_merge = B_final = B_query")
    return values[0]


def validate_replicate_counts(*, r_pilot: int, r_formal: int) -> None:
    if r_pilot != R_PILOT:
        raise ContractError("R_pilot must equal 3")
    if r_formal != R_FORMAL:
        raise ContractError("R_formal must equal 5")


def validate_periodic_rebuild_interval(enabled: bool, interval: int | None) -> None:
    if not enabled:
        if interval is not None:
            raise ContractError("disabled periodic reconstruction must use interval = null")
        return
    if not isinstance(interval, int) or isinstance(interval, bool) or interval <= 0:
        raise ContractError("enabled periodic reconstruction requires positive rebuild_interval")


def validate_primary_seed_rows(rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        raise ContractError("primary seed rows must not be empty")

    by_replicate: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("s_leaf") != 0:
            raise ContractError("s_leaf must equal 0 in a primary run")
        replicate_id = row.get("replicate_id")
        if not isinstance(replicate_id, int) or replicate_id < 0:
            raise ContractError("replicate_id must be a non-negative integer")
        by_replicate[replicate_id].append(row)

    for replicate_id, block in by_replicate.items():
        for field in ("s_merge", "s_answer"):
            values = {row.get(field) for row in block}
            if values != {replicate_id}:
                raise ContractError(
                    f"{field} must equal replicate_id and be paired across topology"
                )


def eligibility_mask(atomic_evidence_count: int) -> dict[int, bool]:
    if not isinstance(atomic_evidence_count, int) or atomic_evidence_count < 0:
        raise ContractError("atomic_evidence_count must be a non-negative integer")
    return {k: atomic_evidence_count >= k for k in K_PLANNED}


def validate_k_sweep_cohorts(cohorts: Mapping[int, set[str]]) -> None:
    if set(cohorts) != set(K_PLANNED):
        raise ContractError(f"k-sweep must define exactly {K_PLANNED}")
    common = cohorts[16]
    if any(cohorts[k] != common for k in K_PLANNED):
        raise ContractError("k-sweep must use the common E_16 episode cohort")


def validate_plan_sets(
    primary: Iterable[str], diagnostic: Iterable[str], online: Iterable[str]
) -> None:
    primary_tuple = tuple(primary)
    diagnostic_tuple = tuple(diagnostic)
    online_tuple = tuple(online)
    if "right_deep" in primary_tuple:
        raise ContractError("right_deep is diagnostic-only and cannot enter primary")
    if primary_tuple != PI_PRIMARY:
        raise ContractError(f"primary plan set must equal {PI_PRIMARY}")
    if diagnostic_tuple != PI_DIAG:
        raise ContractError(f"diagnostic plan set must equal {PI_DIAG}")
    if online_tuple != PI_ONLINE:
        raise ContractError(f"online plan set must equal {PI_ONLINE}")


def validate_backbone_bundle(bundle: Mapping[str, Any]) -> Mapping[str, Any]:
    required = (
        "backbone_id",
        "role",
        "model_family",
        "constructor_model_snapshot",
        "merge_model_snapshot",
        "answer_model_snapshot",
        "provider",
        "endpoint",
        "decoding_config_hash",
    )
    for field in required:
        _require_nonempty_string(bundle, field)
    if bundle["role"] not in {"primary", "replication"}:
        raise ContractError("backbone role must be primary or replication")
    for field in (
        "constructor_model_snapshot",
        "merge_model_snapshot",
        "answer_model_snapshot",
    ):
        if bundle[field].endswith("-latest") or bundle[field] in {"latest", "default"}:
            raise ContractError(f"{field} must not use a rolling alias")
    return bundle


def validate_replication_backbone(primary: Mapping[str, Any], replication: Mapping[str, Any]) -> None:
    validate_backbone_bundle(primary)
    validate_backbone_bundle(replication)
    if primary["model_family"] == replication["model_family"]:
        raise ContractError("replication backbone must use a different model family")


def validate_retrieval_config(config: Mapping[str, Any]) -> Mapping[str, Any]:
    required = (
        "retrieval_config_id",
        "embedding_model_snapshot",
        "tokenizer_snapshot",
        "retrieval_unit_version",
        "similarity_metric",
        "candidate_top_k",
        "packing_policy",
        "render_order",
        "tie_break",
        "index_version",
        "sha256",
    )
    for field in required:
        if field not in config:
            raise ContractError(f"{field} is required")
    if config["embedding_model_snapshot"] in {"BAAI/bge-m3", "latest", "default"}:
        raise ContractError("embedding_model_snapshot must include an explicit revision")
    if config["similarity_metric"] != "cosine_normalized":
        raise ContractError("similarity_metric must be cosine_normalized")
    if config["candidate_top_k"] != "all":
        raise ContractError("candidate_top_k must be all unless separately qualified")
    if config["render_order"] != "chronological":
        raise ContractError("Budget-Matched Retain must render chronologically")
    return config
