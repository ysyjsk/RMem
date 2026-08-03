from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from statistics import fmean
from typing import Any

from .contracts import ContractError, PI_DIAG, PI_PRIMARY
from .observability import (
    build_support_exposure,
    derive_evidence_exposure,
    derive_merge_event_metrics,
    derive_plan_metrics,
    reconcile_work,
)

__all__ = [
    "episode_macro_scores",
    "q_t",
    "task_quality",
    "delta_primary",
    "diagnostic_range",
    "validate_primary_statistic_plans",
    "validate_diagnostic_plans",
    "sum_lifecycle_cost",
    "derive_plan_metrics",
    "derive_evidence_exposure",
    "derive_merge_event_metrics",
    "reconcile_work",
    "build_support_exposure",
]


def episode_macro_scores(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[int, str, int], float]:
    buckets: dict[tuple[str, int, str, int], list[float]] = defaultdict(list)
    for row in rows:
        score = float(row["score"])
        if not 0 <= score <= 1:
            raise ContractError("query score must be in [0,1]")
        buckets[(str(row["episode_id"]), int(row["budget"]), str(row["plan_id"]), int(row["replicate_id"]))].append(score)

    plan_buckets: dict[tuple[int, str, int], list[float]] = defaultdict(list)
    for (_, budget, plan_id, replicate_id), scores in buckets.items():
        plan_buckets[(budget, plan_id, replicate_id)].append(fmean(scores))
    return {key: fmean(values) for key, values in plan_buckets.items()}


def q_t(rows: Iterable[Mapping[str, Any]], *, budget: int, plan_id: str) -> float:
    scores = episode_macro_scores(rows)
    values = [value for (b, plan, _), value in scores.items() if b == budget and plan == plan_id]
    if not values:
        raise ContractError("no rows for requested budget/plan")
    return fmean(values)


def task_quality(rows: Iterable[Mapping[str, Any]], *, budget: int, plan_set: tuple[str, ...]) -> dict[str, float]:
    values = [q_t(rows, budget=budget, plan_id=plan_id) for plan_id in plan_set]
    return {"Q_mean": fmean(values), "Q_worst": min(values), "Q_best": max(values)}


def delta_primary(rows: Iterable[Mapping[str, Any]], *, budget: int) -> float:
    return q_t(rows, budget=budget, plan_id="canonical_balanced") - q_t(rows, budget=budget, plan_id="left_deep")


def diagnostic_range(rows: Iterable[Mapping[str, Any]], *, budget: int) -> float:
    values = [q_t(rows, budget=budget, plan_id=plan_id) for plan_id in PI_DIAG]
    return max(values) - min(values)


def validate_primary_statistic_plans(plan_ids: Iterable[str]) -> None:
    if tuple(plan_ids) != PI_PRIMARY:
        raise ContractError("primary statistic must compare only left_deep and canonical_balanced")


def validate_diagnostic_plans(plan_ids: Iterable[str]) -> None:
    if tuple(plan_ids) != PI_DIAG:
        raise ContractError("diagnostic range must include right_deep")


def sum_lifecycle_cost(rows: Iterable[Mapping[str, Any]]) -> dict[str, float | str]:
    total = 0.0
    for row in rows:
        value = row.get("cost")
        if value == "unknown":
            return {"C_life": "unknown"}
        if value is None:
            raise ContractError("missing cost must be unknown, not absent or zero")
        total += float(value)
    return {"C_life": total}
