from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import ContractError


def assert_full_leaf_generation_allowed(
    day1_artifact: Mapping[str, Any],
    data_artifact: Mapping[str, Any],
    power_artifact: Mapping[str, Any],
) -> None:
    if day1_artifact.get("status") != "passed":
        raise ContractError("Day 1 Gate has not passed; full leaf generation is forbidden")
    if data_artifact.get("status") not in {"qualified", "qualified_with_exclusions"}:
        raise ContractError("LongMemEval data Gate has not qualified; full leaf generation is forbidden")
    counts = data_artifact.get("counts")
    if not isinstance(counts, Mapping):
        raise ContractError("LongMemEval primary E8 count is missing; full leaf generation is forbidden")
    if "primary_N8" not in counts:
        raise ContractError("LongMemEval primary E8 count is missing; full leaf generation is forbidden")
    primary_n8_value = counts.get("primary_N8")
    try:
        primary_n8 = int(primary_n8_value)
    except (TypeError, ValueError) as exc:
        raise ContractError("LongMemEval primary E8 count is invalid; full leaf generation is forbidden") from exc
    if primary_n8 <= 0:
        raise ContractError("LongMemEval primary E8 is empty; full leaf generation is forbidden")
    if data_artifact.get("no_silent_drop") is not True:
        raise ContractError("LongMemEval no-silent-drop qualification is missing")
    audit_hash = data_artifact.get("audit_hash")
    if not isinstance(audit_hash, str) or not audit_hash:
        raise ContractError("LongMemEval audit hash is missing; full leaf generation is forbidden")
    if power_artifact.get("status") != "passed":
        raise ContractError("G-POWER-FEASIBILITY has not passed; full leaf generation is forbidden")
    if power_artifact.get("input_audit_hash") != audit_hash:
        raise ContractError("power artifact is not bound to the LongMemEval audit hash; full leaf generation is forbidden")
    split_ratio = power_artifact.get("split_ratio")
    if not isinstance(split_ratio, Mapping) or any(
        not isinstance(split_ratio.get(name), (int, float))
        for name in ("development", "calibration", "acceptance")
    ):
        raise ContractError("power split ratio has not been frozen; full leaf generation is forbidden")
    delta_decision = power_artifact.get("delta_decision")
    if isinstance(delta_decision, bool) or not isinstance(delta_decision, (int, float)) or delta_decision <= 0:
        raise ContractError("power delta_decision has not been frozen; full leaf generation is forbidden")
    power_lower_95 = power_artifact.get("power_lower_95")
    if isinstance(power_lower_95, bool) or not isinstance(power_lower_95, (int, float)) or power_lower_95 < 0.80:
        raise ContractError("power 95% lower bound is below 0.80; hard NO-GO remains unavailable")
    categories = power_artifact.get("primary_eligible_categories")
    if not isinstance(categories, list) or not categories:
        raise ContractError("power primary eligible categories have not been frozen; full leaf generation is forbidden")
    strata = power_artifact.get("evidence_layout_strata")
    if not isinstance(strata, list) or not any(
        isinstance(row, Mapping) and isinstance(row.get("count"), int) and row["count"] > 0
        for row in strata
    ):
        raise ContractError("power evidence-layout strata have not been frozen; full leaf generation is forbidden")
    if power_artifact.get("topology_results_seen") is not False:
        raise ContractError("power decision must be frozen before topology results")
    if power_artifact.get("hard_no_go_available") is not True:
        raise ContractError("hard NO-GO authority is unavailable; full leaf generation remains blocked")
