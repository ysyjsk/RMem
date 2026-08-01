from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import fmean
from typing import Mapping

from .contracts import DELTA_DECISION_GRID, DELTA_SESOI, PI_PRIMARY, R_FORMAL, R_PILOT


class StatisticContractError(ValueError):
    """Raised when a statistic does not match the registered estimator."""


class PowerDesignError(ValueError):
    """Raised when a power design uses pseudo-replication."""


@dataclass(frozen=True)
class PowerDesign:
    independent_episodes: int
    repeated_rows: int
    r_formal: int
    analysis_n: int


def validate_power_design(
    *,
    independent_episodes: int,
    repeated_rows: int,
    r_formal: int,
    declared_analysis_n: int | None = None,
) -> PowerDesign:
    if independent_episodes <= 0:
        raise PowerDesignError("independent episode count must be positive")
    if r_formal <= 0:
        raise PowerDesignError("r_formal must be positive")
    if repeated_rows < independent_episodes:
        raise PowerDesignError("repeated_rows cannot be smaller than independent episodes")
    analysis_n = independent_episodes if declared_analysis_n is None else declared_analysis_n
    if analysis_n != independent_episodes:
        raise PowerDesignError("analysis_n must equal the independent episode count")
    return PowerDesign(independent_episodes, repeated_rows, r_formal, analysis_n)


def seed_null_pair_statistics(
    run_vectors: Mapping[int, Mapping[str, float]],
    *,
    r_required: int,
    draws: int,
    seed: int,
) -> list[float]:
    if len(run_vectors) < r_required:
        raise StatisticContractError(
            "diagnostic null must preserve the registered R-run averaging structure"
        )
    if r_required <= 0 or draws <= 0:
        raise StatisticContractError("r_required and draws must be positive")

    vectors = list(run_vectors.values())
    episode_ids = tuple(vectors[0])
    if not episode_ids or any(tuple(vector) != episode_ids for vector in vectors):
        raise StatisticContractError("all run vectors must cover the same ordered episodes")

    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(draws):
        pseudo_left = [rng.choice(vectors) for _ in range(r_required)]
        pseudo_balanced = [rng.choice(vectors) for _ in range(r_required)]
        left_mean = fmean(
            fmean(vector[episode_id] for vector in pseudo_left)
            for episode_id in episode_ids
        )
        balanced_mean = fmean(
            fmean(vector[episode_id] for vector in pseudo_balanced)
            for episode_id in episode_ids
        )
        values.append(abs(balanced_mean - left_mean))
    return values


def validate_common_random_numbers(rows: list[Mapping[str, object]]) -> None:
    by_rep: dict[int, set[tuple[object, object]]] = {}
    for row in rows:
        rep = int(row["replicate_id"])
        by_rep.setdefault(rep, set()).add((row.get("s_merge"), row.get("s_answer")))
    for rep, seeds in by_rep.items():
        if seeds != {(rep, rep)}:
            raise StatisticContractError("common random numbers require paired merge/answer seeds")


def paired_permutation_delta(
    paired_rows: list[Mapping[str, object]], *, permutations: int = 1000, seed: int = 0
) -> dict[str, float]:
    by_block: dict[tuple[str, int], dict[str, float]] = {}
    for row in paired_rows:
        key = (str(row["episode_id"]), int(row["replicate_id"]))
        by_block.setdefault(key, {})[str(row["plan_id"])] = float(row["score"])
    diffs = []
    for values in by_block.values():
        if set(values) != set(PI_PRIMARY):
            raise StatisticContractError("paired permutation blocks must contain only Pi_primary")
        diffs.append(values["canonical_balanced"] - values["left_deep"])
    observed = fmean(diffs)
    rng = random.Random(seed)
    more_extreme = 0
    for _ in range(permutations):
        sampled = [diff if rng.random() < 0.5 else -diff for diff in diffs]
        if abs(fmean(sampled)) >= abs(observed):
            more_extreme += 1
    return {"delta": observed, "p_value": (more_extreme + 1) / (permutations + 1)}


def validate_delta_decision_artifact(artifact: Mapping[str, object]) -> float:
    value = float(artifact.get("delta_decision", -1))
    if value not in DELTA_DECISION_GRID:
        raise PowerDesignError("delta_decision must come from the preregistered grid")
    if value < DELTA_SESOI:
        raise PowerDesignError("delta_decision must be >= delta_SESOI")
    if not artifact.get("topology_results_seen") is False:
        raise PowerDesignError("delta_decision must be frozen before topology results")
    if float(artifact.get("power", 0)) < 0.80:
        raise PowerDesignError("delta_decision requires at least 80% power")
    return value


def validate_power_simulation_inputs(inputs: Mapping[str, object]) -> None:
    if inputs.get("uses_fraction_times_n"):
        raise PowerDesignError("power simulation must not use fraction_multiple_leaves × n")
    strata = inputs.get("strata")
    if not isinstance(strata, list) or not strata:
        raise PowerDesignError("power simulation must use empirical evidence-layout strata")
    if not all("question_type" in row and "support_leaf_class" in row for row in strata):
        raise PowerDesignError("strata must include question_type and support_leaf_class")


def classify_null_result(*, power: float, ci_excludes_delta_decision: bool, significant: bool) -> str:
    if significant:
        return "go_candidate"
    if power < 0.80:
        return "inconclusive"
    if ci_excludes_delta_decision:
        return "equivalence_candidate"
    return "inconclusive"


def formal_no_go_allowed(checks: Mapping[str, bool]) -> bool:
    required = (
        "signal_bearing_budget",
        "formal_power",
        "primary_under_delta",
        "stress_under_delta",
        "ci_excludes_delta_decision",
        "judge_repeatability",
        "non_ceiling_only",
        "online_gate_handled",
    )
    return all(bool(checks.get(item)) for item in required)


def validate_registered_r_values(*, r_pilot: int, r_formal: int) -> None:
    if (r_pilot, r_formal) != (R_PILOT, R_FORMAL):
        raise StatisticContractError("registered repeats must be R_pilot=3 and R_formal=5")
