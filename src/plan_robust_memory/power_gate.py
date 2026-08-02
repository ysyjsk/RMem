from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import DELTA_DECISION_GRID, DELTA_SESOI, R_FORMAL, R_PILOT
from .hashing import stable_hash


SPLIT_NAMES = ("development", "calibration", "acceptance")
COUNT_NAMES = ("N_master", "N4", "N8", "N16")
SPLIT_CANDIDATES = (
    {"development": 0.20, "calibration": 0.30, "acceptance": 0.50},
    {"development": 0.15, "calibration": 0.25, "acceptance": 0.60},
    {"development": 0.10, "calibration": 0.20, "acceptance": 0.70},
)
DISCORDANCE_GRID = (0.10, 0.15, 0.25, 0.40)
SIMULATION_EFFECT_GRID = (
    -0.15,
    -0.125,
    -0.10,
    -0.075,
    -0.05,
    -0.025,
    0.0,
    0.025,
    0.05,
    0.075,
    0.10,
    0.125,
    0.15,
)
PRIMARY_CATEGORIES = frozenset(("knowledge-update", "temporal-reasoning"))
SUPPORT_LEAF_CLASSES = frozenset(("single", "multiple"))
EVIDENCE_POSITION_BINS = frozenset(("early", "middle", "late"))
JUDGE_FLIP_RATE = 0.05
POWER_THRESHOLD = 0.80
ESTIMATOR = (
    "paired sign-flip permutation test "
    "(normal approximation to the randomization distribution)"
)


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validated_categories(value: object, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not value:
        errors.append("eligible_primary_categories must be a non-empty list")
        return []
    if any(not isinstance(item, str) or not item for item in value):
        errors.append("eligible_primary_categories must contain non-empty strings")
        return []
    categories = sorted(value)
    if len(categories) != len(set(categories)):
        errors.append("eligible_primary_categories must not contain duplicates")
    unsupported = sorted(set(categories) - PRIMARY_CATEGORIES)
    if unsupported:
        errors.append(
            "eligible_primary_categories contains categories outside the frozen primary track: "
            + ", ".join(unsupported)
        )
    return categories


def _validated_ratio(value: object, candidate_index: int, errors: list[str]) -> dict[str, float] | None:
    label = f"split_candidates[{candidate_index}].ratio"
    if not isinstance(value, Mapping) or set(value) != set(SPLIT_NAMES):
        errors.append(f"{label} must define exactly {SPLIT_NAMES}")
        return None
    if any(
        not isinstance(value[name], (int, float))
        or isinstance(value[name], bool)
        or not 0.0 < float(value[name]) < 1.0
        for name in SPLIT_NAMES
    ):
        errors.append(f"{label} values must be numeric and strictly between zero and one")
        return None
    ratio = {name: float(value[name]) for name in SPLIT_NAMES}
    if not math.isclose(sum(ratio.values()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        errors.append(f"{label} must sum to one")
        return None
    if not any(
        all(math.isclose(ratio[name], preregistered[name], rel_tol=0.0, abs_tol=1e-12) for name in SPLIT_NAMES)
        for preregistered in SPLIT_CANDIDATES
    ):
        errors.append(f"{label} is not a preregistered split candidate")
    return ratio


def _validated_primary_counts(
    value: object,
    *,
    candidate_index: int,
    top_counts: Mapping[str, Any],
    errors: list[str],
) -> dict[str, dict[str, int]] | None:
    label = f"split_candidates[{candidate_index}].primary_counts"
    if not isinstance(value, Mapping) or set(value) != set(SPLIT_NAMES):
        errors.append(
            f"{label} (the real grouped_split_counts) must define exactly {SPLIT_NAMES}"
        )
        return None
    normalized: dict[str, dict[str, int]] = {}
    for split in SPLIT_NAMES:
        row = value[split]
        if not isinstance(row, Mapping) or any(name not in row for name in COUNT_NAMES):
            errors.append(f"{label}.{split} must define {COUNT_NAMES}")
            return None
        if any(not _is_nonnegative_int(row[name]) for name in COUNT_NAMES):
            errors.append(f"{label}.{split} counts must be non-negative integers")
            return None
        normalized[split] = {name: int(row[name]) for name in COUNT_NAMES}
        ordered = [normalized[split][name] for name in COUNT_NAMES]
        if ordered != sorted(ordered, reverse=True):
            errors.append(
                f"{label}.{split} must satisfy N_master >= N4 >= N8 >= N16"
            )

    for metric in COUNT_NAMES:
        top_name = f"primary_{metric}"
        top_value = top_counts.get(top_name)
        if not _is_nonnegative_int(top_value):
            errors.append(f"counts.{top_name} must be an explicit non-negative integer")
            continue
        grouped_total = sum(normalized[split][metric] for split in SPLIT_NAMES)
        if grouped_total != top_value:
            errors.append(
                f"{label} real grouped_split_counts for {metric} sum to {grouped_total}, "
                f"not counts.{top_name}={top_value}"
            )
    return normalized


def _validated_strata(
    value: object,
    *,
    candidate_index: int,
    acceptance_n8: int,
    categories: Sequence[str],
    errors: list[str],
) -> list[dict[str, Any]] | None:
    label = (
        f"split_candidates[{candidate_index}]."
        "acceptance_primary_e8_evidence_layout_strata"
    )
    if not isinstance(value, list) or not value:
        errors.append(f"{label} must be a non-empty empirical evidence_layout_strata list")
        return None

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row_index, row in enumerate(value):
        row_label = f"{label}[{row_index}]"
        if not isinstance(row, Mapping):
            errors.append(f"{row_label} must be an object")
            continue
        question_type = row.get("question_type")
        support_class = row.get("support_leaf_class")
        position = row.get("evidence_position_bin")
        count = row.get("count")
        if question_type not in categories:
            errors.append(f"{row_label}.question_type must be a frozen eligible primary category")
        if support_class not in SUPPORT_LEAF_CLASSES:
            errors.append(
                f"{row_label}.support_leaf_class must be one of {sorted(SUPPORT_LEAF_CLASSES)}"
            )
        if position not in EVIDENCE_POSITION_BINS:
            errors.append(
                f"{row_label}.evidence_position_bin must be one of {sorted(EVIDENCE_POSITION_BINS)}"
            )
        if not _is_nonnegative_int(count) or count == 0:
            errors.append(f"{row_label}.count must be a positive integer")
        if (
            isinstance(question_type, str)
            and isinstance(support_class, str)
            and isinstance(position, str)
            and _is_nonnegative_int(count)
            and count > 0
        ):
            key = (question_type, support_class, position)
            if key in seen:
                errors.append(f"{row_label} duplicates an empirical evidence-layout stratum")
            seen.add(key)
            normalized.append(
                {
                    "question_type": question_type,
                    "support_leaf_class": support_class,
                    "evidence_position_bin": position,
                    "count": int(count),
                }
            )

    strata_total = sum(row["count"] for row in normalized)
    if strata_total != acceptance_n8:
        errors.append(
            f"{label} evidence_layout_strata sum to {strata_total}, "
            f"not acceptance primary E8={acceptance_n8}"
        )
    represented_categories = {row["question_type"] for row in normalized}
    missing_categories = sorted(set(categories) - represented_categories)
    if missing_categories:
        errors.append(
            f"{label} does not represent eligible acceptance categories: "
            + ", ".join(missing_categories)
        )
    return normalized


def _validate_manifest(
    audit: Mapping[str, Any],
) -> tuple[int | None, list[str], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    declared_audit_hash = audit.get("audit_hash")
    expected_audit_hash = stable_hash(
        {key: value for key, value in audit.items() if key != "audit_hash"}
    )
    if not isinstance(declared_audit_hash, str) or not declared_audit_hash:
        errors.append("audit_hash must be present before the power Gate runs")
    elif declared_audit_hash != expected_audit_hash:
        errors.append("audit_hash does not match the real dataset manifest contents")
    if audit.get("status") not in {"qualified", "qualified_with_exclusions"}:
        errors.append("data audit status must be qualified or qualified_with_exclusions")
    if audit.get("no_silent_drop") is not True:
        errors.append("data audit must certify no_silent_drop=true")

    counts = audit.get("counts")
    if not isinstance(counts, Mapping):
        errors.append("counts must be an object with an explicit primary_N8")
        counts = {}
    raw_n8 = counts.get("primary_N8")
    n8: int | None
    if not _is_nonnegative_int(raw_n8):
        errors.append("counts.primary_N8 must be an explicit non-negative integer")
        n8 = None
    else:
        n8 = int(raw_n8)

    categories = _validated_categories(audit.get("eligible_primary_categories"), errors)
    raw_candidates = audit.get("split_candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        errors.append("split_candidates must contain real grouped candidate assignments")
        return n8, categories, [], errors

    candidates: list[dict[str, Any]] = []
    seen_ratios: set[tuple[float, float, float]] = set()
    for candidate_index, candidate in enumerate(raw_candidates):
        if not isinstance(candidate, Mapping):
            errors.append(f"split_candidates[{candidate_index}] must be an object")
            continue
        ratio = _validated_ratio(candidate.get("ratio"), candidate_index, errors)
        primary_counts = _validated_primary_counts(
            candidate.get("primary_counts"),
            candidate_index=candidate_index,
            top_counts=counts,
            errors=errors,
        )
        assignment_hash = candidate.get("assignment_hash")
        candidate_id = candidate.get("candidate_id")
        assignments = candidate.get("assignments")
        if not isinstance(candidate_id, str) or not candidate_id:
            errors.append(f"split_candidates[{candidate_index}].candidate_id must be non-empty")
        if not isinstance(assignments, list) or not assignments:
            errors.append(f"split_candidates[{candidate_index}].assignments must be non-empty")
        if not isinstance(assignment_hash, str) or not assignment_hash:
            errors.append(f"split_candidates[{candidate_index}].assignment_hash must be non-empty")
        elif isinstance(candidate_id, str) and isinstance(assignments, list):
            expected_assignment_hash = stable_hash(
                {
                    "candidate_id": candidate_id,
                    "ratio": candidate.get("ratio"),
                    "assignments": assignments,
                }
            )
            if assignment_hash != expected_assignment_hash:
                errors.append(
                    f"split_candidates[{candidate_index}].assignment_hash does not match assignments"
                )
        if ratio is not None:
            ratio_key = tuple(ratio[name] for name in SPLIT_NAMES)
            if ratio_key in seen_ratios:
                errors.append("split_candidates must not repeat a ratio")
            seen_ratios.add(ratio_key)
        if primary_counts is None:
            continue
        acceptance_n8 = primary_counts["acceptance"]["N8"]
        strata = _validated_strata(
            candidate.get("acceptance_primary_e8_evidence_layout_strata"),
            candidate_index=candidate_index,
            acceptance_n8=acceptance_n8,
            categories=categories,
            errors=errors,
        )
        if ratio is not None and strata is not None and isinstance(assignment_hash, str):
            candidates.append(
                {
                    "candidate_index": candidate_index,
                    "candidate_id": candidate_id,
                    "ratio": ratio,
                    "primary_counts": primary_counts,
                    "acceptance_n8": acceptance_n8,
                    "strata": strata,
                    "assignment_hash": assignment_hash,
                }
            )
    return n8, categories, candidates, errors


def _strata_design(strata: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    total = sum(int(row["count"]) for row in strata)
    if total <= 0:
        return []
    unnormalized: list[tuple[Mapping[str, Any], float, float]] = []
    for row in strata:
        weight = int(row["count"]) / total
        factor = 1.0
        factor *= 0.95 if row["question_type"] == "knowledge-update" else 1.05
        factor *= 0.90 if row["support_leaf_class"] == "single" else 1.10
        if row["evidence_position_bin"] == "early":
            factor *= 0.90
        elif row["evidence_position_bin"] == "late":
            factor *= 1.10
        unnormalized.append((row, weight, factor))
    normalizer = sum(weight * factor for _, weight, factor in unnormalized)
    return [
        {
            **dict(row),
            "weight": weight,
            "effect_multiplier": factor / normalizer,
        }
        for row, weight, factor in unnormalized
    ]


def _observed_difference_probabilities(
    *, effect: float, discordance: float, judge_flip_rate: float
) -> tuple[float, float, float]:
    left_probability = 0.65
    balanced_probability = max(0.0, min(1.0, left_probability + effect))
    marginal_effect = balanced_probability - left_probability
    maximum_discordance = min(
        left_probability + balanced_probability,
        2.0 - left_probability - balanced_probability,
    )
    feasible_discordance = min(
        maximum_discordance, max(abs(marginal_effect), discordance)
    )
    original = {
        (1, 0): (feasible_discordance + marginal_effect) / 2.0,
        (0, 1): (feasible_discordance - marginal_effect) / 2.0,
    }
    original[(1, 1)] = balanced_probability - original[(1, 0)]
    original[(0, 0)] = 1.0 - sum(original.values())

    observed = {-1: 0.0, 0: 0.0, 1: 0.0}
    flip = judge_flip_rate
    for (balanced, left), joint_probability in original.items():
        for observed_balanced in (0, 1):
            balanced_probability_after_judge = (1.0 - flip) if observed_balanced == balanced else flip
            for observed_left in (0, 1):
                left_probability_after_judge = (1.0 - flip) if observed_left == left else flip
                observed[observed_balanced - observed_left] += (
                    joint_probability
                    * balanced_probability_after_judge
                    * left_probability_after_judge
                )
    return observed[-1], observed[0], observed[1]


def _repeated_difference_distribution(
    *, effect: float, discordance: float, judge_flip_rate: float, repeats: int
) -> list[tuple[int, float]]:
    one_repeat = _observed_difference_probabilities(
        effect=effect,
        discordance=discordance,
        judge_flip_rate=judge_flip_rate,
    )
    distribution = {0: 1.0}
    for _ in range(repeats):
        next_distribution: dict[int, float] = {}
        for current, current_probability in distribution.items():
            for difference, probability in zip((-1, 0, 1), one_repeat, strict=True):
                next_distribution[current + difference] = (
                    next_distribution.get(current + difference, 0.0)
                    + current_probability * probability
                )
        distribution = next_distribution
    cumulative = 0.0
    rows: list[tuple[int, float]] = []
    for difference, probability in sorted(distribution.items()):
        cumulative += probability
        rows.append((difference, cumulative))
    rows[-1] = (rows[-1][0], 1.0)
    return rows


def _draw_discrete(rng: random.Random, distribution: Sequence[tuple[int, float]]) -> int:
    target = rng.random()
    for value, cumulative_probability in distribution:
        if target <= cumulative_probability:
            return value
    return distribution[-1][0]


def _paired_sign_flip_normal_p_value(differences: Sequence[int]) -> float:
    if len(differences) < 2:
        return 1.0
    observed_sum = sum(differences)
    randomization_variance = sum(value * value for value in differences)
    if randomization_variance == 0:
        return 1.0
    z = abs(observed_sum) / math.sqrt(randomization_variance)
    return math.erfc(z / math.sqrt(2.0))


def _wilson_interval(successes: int, trials: int, *, z: float = 1.959963984540054) -> tuple[float, float]:
    """Two-sided 95% Wilson interval for Monte Carlo detection probability."""
    if trials <= 0 or successes < 0 or successes > trials:
        raise ValueError("Wilson interval requires 0 <= successes <= positive trials")
    probability = successes / trials
    z_squared = z * z
    denominator = 1.0 + z_squared / trials
    center = (probability + z_squared / (2.0 * trials)) / denominator
    margin = (
        z
        * math.sqrt(
            probability * (1.0 - probability) / trials
            + z_squared / (4.0 * trials * trials)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def estimate_power(
    *,
    analysis_n: int,
    effect: float,
    discordance: float,
    strata: list[Mapping[str, Any]],
    draws: int,
    seed: int,
    judge_flip_rate: float = JUDGE_FLIP_RATE,
) -> float:
    if analysis_n <= 0:
        raise ValueError("analysis_n must be a positive independent episode count")
    if draws <= 0:
        raise ValueError("draws must be positive")
    if not 0.0 <= judge_flip_rate < 0.5:
        raise ValueError("judge_flip_rate must be in [0, 0.5)")
    design = _strata_design(strata)
    if not design:
        raise ValueError("empirical evidence-layout strata must be non-empty")

    cumulative_weight = 0.0
    strata_samplers: list[tuple[float, list[tuple[int, float]]]] = []
    for row in design:
        cumulative_weight += float(row["weight"])
        distribution = _repeated_difference_distribution(
            effect=effect * float(row["effect_multiplier"]),
            discordance=discordance,
            judge_flip_rate=judge_flip_rate,
            repeats=R_FORMAL,
        )
        strata_samplers.append((cumulative_weight, distribution))
    strata_samplers[-1] = (1.0, strata_samplers[-1][1])

    rng = random.Random(seed)
    detections = 0
    for _ in range(draws):
        differences: list[int] = []
        for _ in range(analysis_n):
            target = rng.random()
            distribution = strata_samplers[-1][1]
            for cumulative, candidate_distribution in strata_samplers:
                if target <= cumulative:
                    distribution = candidate_distribution
                    break
            differences.append(_draw_discrete(rng, distribution))
        detections += int(_paired_sign_flip_normal_p_value(differences) < 0.05)
    return detections / draws


def _artifact_hash(result: dict[str, Any]) -> dict[str, Any]:
    result["artifact_hash"] = stable_hash(
        {key: value for key, value in result.items() if key != "artifact_hash"}
    )
    return result


def _blocked_result(
    base: Mapping[str, Any],
    *,
    reason: str,
    validation_errors: Sequence[str],
    simulation_results: Sequence[Mapping[str, Any]] = (),
    candidate_results: Sequence[Mapping[str, Any]] = (),
    best_power: float | None = None,
    best_lower_95: float | None = None,
    best_design: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return _artifact_hash(
        {
            **base,
            "status": "blocked",
            "blocking_reason": reason,
            "input_validation_errors": list(validation_errors),
            "split_ratio": None,
            "actual_split_ratio": None,
            "split_ratio_frozen_from": None,
            "split_assignment_hash": None,
            "grouped_split_counts": None,
            "analysis_n": None,
            "delta_decision": None,
            "power": None,
            "power_lower_95": None,
            "best_attainable_conservative_power": best_power,
            "best_attainable_lower_95": best_lower_95,
            "best_attainable_design": dict(best_design) if best_design is not None else None,
            "hard_no_go_available": False,
            "simulation_results": list(simulation_results),
            "candidate_results": list(candidate_results),
        }
    )


def run_power_gate(
    audit: Mapping[str, Any], *, draws: int = 1000, seed: int = 20260801
) -> dict[str, Any]:
    n8, categories, candidates, validation_errors = _validate_manifest(audit)
    simulation_input = {
        "audit_hash": audit.get("audit_hash"),
        "primary_N8": n8,
        "primary_eligible_categories": categories,
        "split_candidates": [
            {
                "ratio": candidate["ratio"],
                "candidate_id": candidate["candidate_id"],
                "primary_counts": candidate["primary_counts"],
                "acceptance_primary_e8_evidence_layout_strata": candidate["strata"],
                "assignment_hash": candidate["assignment_hash"],
            }
            for candidate in candidates
        ],
        "effect_grid": list(SIMULATION_EFFECT_GRID),
        "discordance_grid": list(DISCORDANCE_GRID),
        "draws": draws,
        "seed": seed,
        "judge_flip_rate": JUDGE_FLIP_RATE,
        "R_formal": R_FORMAL,
        "estimator": ESTIMATOR,
    }
    base: dict[str, Any] = {
        "schema_version": "plan-robust-memory.power-gate.v2",
        "input_audit_hash": audit.get("audit_hash"),
        "simulation_input_hash": stable_hash(simulation_input),
        "topology_results_seen": False,
        "delta_SESOI": DELTA_SESOI,
        "delta_grid": list(DELTA_DECISION_GRID),
        "simulation_effect_grid": list(SIMULATION_EFFECT_GRID),
        "discordance_grid": list(DISCORDANCE_GRID),
        "power_threshold": POWER_THRESHOLD,
        "decision_rule": "minimum scenario Monte Carlo 95% lower bound >= 0.80",
        "R_pilot": R_PILOT,
        "R_formal": R_FORMAL,
        "draws": draws,
        "seed": seed,
        "judge_flip_rate": JUDGE_FLIP_RATE,
        "independent_episode_count": n8,
        "primary_eligible_categories": categories,
        "estimator": ESTIMATOR,
        "uses_fraction_times_n": False,
        "expanded_counts_used": False,
        "full_leaf_generation_allowed": False,
        "strata_design": _strata_design(candidates[0]["strata"]) if candidates else [],
    }

    if not isinstance(draws, int) or isinstance(draws, bool) or draws <= 0:
        validation_errors.append("draws must be a positive integer")
    if not isinstance(seed, int) or isinstance(seed, bool):
        validation_errors.append("seed must be an integer")
    if n8 == 0:
        return _blocked_result(
            base,
            reason="no eligible primary E8 episodes are available",
            validation_errors=validation_errors,
        )
    if validation_errors:
        return _blocked_result(
            base,
            reason="; ".join(validation_errors),
            validation_errors=validation_errors,
        )

    rows: list[dict[str, Any]] = []
    candidate_results: list[dict[str, Any]] = []
    chosen: tuple[dict[str, Any], float, float, float] | None = None
    best_design: dict[str, Any] | None = None
    best_power: float | None = None
    best_lower_95: float | None = None
    for candidate_position, candidate in enumerate(candidates):
        analysis_n = candidate["acceptance_n8"]
        candidate_rows: list[dict[str, Any]] = []
        for effect_index, effect in enumerate(SIMULATION_EFFECT_GRID):
            for discordance_index, discordance in enumerate(DISCORDANCE_GRID):
                scenario_seed = (
                    seed
                    + candidate_position * 1_000_000
                    + effect_index * 10_000
                    + discordance_index * 1_000
                )
                power = estimate_power(
                    analysis_n=analysis_n,
                    effect=effect,
                    discordance=discordance,
                    strata=candidate["strata"],
                    draws=draws,
                    seed=scenario_seed,
                )
                detections = int(round(power * draws))
                power_lower_95, power_upper_95 = _wilson_interval(detections, draws)
                row = {
                    "candidate_index": candidate["candidate_index"],
                    "split_ratio": candidate["ratio"],
                    "assignment_hash": candidate["assignment_hash"],
                    "analysis_n": analysis_n,
                    "effect": effect,
                    "absolute_effect": abs(effect),
                    "discordance": discordance,
                    "power": power,
                    "detections": detections,
                    "power_lower_95": power_lower_95,
                    "power_upper_95": power_upper_95,
                    "seed": scenario_seed,
                }
                rows.append(row)
                candidate_rows.append(row)

        powers_by_delta: dict[str, float] = {}
        lower_bounds_by_delta: dict[str, float] = {}
        for delta in DELTA_DECISION_GRID:
            relevant_rows = [
                row
                for row in candidate_rows
                if math.isclose(abs(row["effect"]), delta, rel_tol=0.0, abs_tol=1e-12)
            ]
            conservative_power = min(row["power"] for row in relevant_rows)
            conservative_lower_95 = min(row["power_lower_95"] for row in relevant_rows)
            powers_by_delta[str(delta)] = conservative_power
            lower_bounds_by_delta[str(delta)] = conservative_lower_95
            design = {
                "split_ratio": candidate["ratio"],
                "assignment_hash": candidate["assignment_hash"],
                "analysis_n": analysis_n,
                "delta": delta,
            }
            if best_lower_95 is None or conservative_lower_95 > best_lower_95:
                best_power = conservative_power
                best_lower_95 = conservative_lower_95
                best_design = design
            if chosen is None and conservative_lower_95 >= POWER_THRESHOLD:
                chosen = (candidate, delta, conservative_power, conservative_lower_95)

        candidate_results.append(
            {
                "candidate_index": candidate["candidate_index"],
                "split_ratio": candidate["ratio"],
                "assignment_hash": candidate["assignment_hash"],
                "primary_counts": candidate["primary_counts"],
                "analysis_n": analysis_n,
                "conservative_power_by_delta": powers_by_delta,
                "conservative_power_lower_95_by_delta": lower_bounds_by_delta,
            }
        )

    if chosen is None:
        return _blocked_result(
            base,
            reason="no preregistered delta/split candidate reaches 80% conservative power",
            validation_errors=(),
            simulation_results=rows,
            candidate_results=candidate_results,
            best_power=best_power,
            best_lower_95=best_lower_95,
            best_design=best_design,
        )

    candidate, delta, power, power_lower_95 = chosen
    grouped_counts = candidate["primary_counts"]
    actual_split_ratio = {
        split: grouped_counts[split]["N8"] / n8 for split in SPLIT_NAMES
    }
    result = {
        **base,
        "status": "passed",
        "blocking_reason": None,
        "input_validation_errors": [],
        "split_ratio": candidate["ratio"],
        "actual_split_ratio": actual_split_ratio,
        "split_ratio_frozen_from": "manifest.split_candidates[*].primary_counts",
        "split_assignment_hash": candidate["assignment_hash"],
        "grouped_split_counts": grouped_counts,
        "analysis_n": candidate["acceptance_n8"],
        "delta_decision": delta,
        "power": power,
        "power_lower_95": power_lower_95,
        "best_attainable_conservative_power": best_power,
        "best_attainable_lower_95": best_lower_95,
        "best_attainable_design": best_design,
        "hard_no_go_available": True,
        "evidence_layout_strata": candidate["strata"],
        "strata_design": _strata_design(candidate["strata"]),
        "simulation_results": rows,
        "candidate_results": candidate_results,
    }
    return _artifact_hash(result)


def _write_artifacts(output_dir: Path, result: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "power_feasibility.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = result.get("simulation_results", [])
    (output_dir / "power_simulation_rows.jsonl").write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )
    markdown = [
        "# G-POWER-FEASIBILITY",
        "",
        f"- status: {result['status']}",
        f"- independent primary E8 episodes: {result['independent_episode_count']}",
        f"- frozen split ratio: {result['split_ratio']}",
        f"- actual grouped E8 ratio: {result['actual_split_ratio']}",
        f"- acceptance independent E8 episodes: {result['analysis_n']}",
        f"- delta_SESOI: {result['delta_SESOI']}",
        f"- delta_decision: {result['delta_decision']}",
        f"- conservative signed/scenario power: {result['power']}",
        f"- conservative power 95% lower bound: {result['power_lower_95']}",
        f"- best attainable conservative power: {result['best_attainable_conservative_power']}",
        f"- best attainable 95% lower bound: {result['best_attainable_lower_95']}",
        f"- hard NO-GO available: {result['hard_no_go_available']}",
        f"- blocking reason: {result['blocking_reason']}",
        f"- estimator: {result['estimator']}",
        f"- simulation input hash: {result['simulation_input_hash']}",
        "",
    ]
    if result.get("delta_decision") is not None and result["delta_decision"] > DELTA_SESOI:
        markdown.extend(
            [
                f"Effects in [{DELTA_SESOI}, {result['delta_decision']}) remain inconclusive under this design.",
                "",
            ]
        )
    markdown.append(
        "No topology outcomes were read. Full leaf generation remains disabled until every Gate passes."
    )
    (output_dir / "power_feasibility_v1.md").write_text(
        "\n".join(markdown) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run G-POWER-FEASIBILITY from a real LongMemEval manifest"
    )
    parser.add_argument(
        "--audit", type=Path, default=Path("artifacts/longmemeval/dataset_manifest.json")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/power"))
    parser.add_argument("--draws", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260801)
    args = parser.parse_args(argv)
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    result = run_power_gate(audit, draws=args.draws, seed=args.seed)
    _write_artifacts(args.output_dir, result)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "split_ratio",
                    "delta_decision",
                    "power",
                    "hard_no_go_available",
                    "blocking_reason",
                )
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
