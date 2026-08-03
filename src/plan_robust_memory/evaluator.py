from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
import json
import re
import string
from typing import Any

from .contracts import ContractError
from .hashing import stable_hash


LONGMEMEVAL_OFFICIAL_SOURCE = {
    "repository": "https://github.com/xiaowu0162/LongMemEval",
    "commit": "9e0b455f4ef0e2ab8f2e582289761153549043fc",
    "path": "src/evaluation/evaluate_qa.py",
    "sha256": "ecce9c4c79dc89d99534ac17b383a5cbb5b9f0c69ee98adaf0684742e3d95251",
}
MEMORYAGENTBENCH_OFFICIAL_SOURCE = {
    "repository": "https://github.com/HUST-AI-HYZ/MemoryAgentBench",
    "commit": "455306dcabc3842526eb83cd4e225e5d486c5c5d",
    "path": "utils/eval_other_utils.py",
    "sha256": "d77976be409298970614d477a9d8003850caddb0510e56a7e821a037d98493a2",
}

JUDGE_REPEATABILITY_CATEGORY_COUNTS = {
    "gold_equivalent": 8,
    "clearly_wrong": 8,
    "partial": 8,
    "temporal_reasoning": 7,
    "knowledge_update": 7,
    "formatting_variation": 6,
    "abstention_like": 6,
}
JUDGE_REPEATABILITY_CASE_COUNT = sum(JUDGE_REPEATABILITY_CATEGORY_COUNTS.values())
JUDGE_REPEATABILITY_REPLICATES = 3


def _normalize_answer(text: str) -> str:
    """Match MemoryAgentBench's frozen ``normalize_answer`` implementation."""
    lowered = text.lower()
    without_punctuation = "".join(
        character for character in lowered if character not in string.punctuation
    )
    without_articles = re.sub(r"\b(a|an|the)\b", " ", without_punctuation)
    return " ".join(without_articles.split())


def _flatten_references(reference: str | Iterable[str]) -> tuple[str, ...]:
    if isinstance(reference, str):
        return (reference,)
    flattened: list[str] = []
    for item in reference:
        if isinstance(item, str):
            flattened.append(item)
        elif isinstance(item, Iterable) and not isinstance(item, (bytes, bytearray)):
            flattened.extend(_flatten_references(item))
        else:
            raise TypeError("reference answers must be strings or nested string iterables")
    return tuple(flattened)


def exact_match_score(reference: str | Iterable[str], candidate: str) -> int:
    return int(
        any(_normalize_answer(item) == _normalize_answer(candidate) for item in _flatten_references(reference))
    )


def substring_exact_match_score(reference: str | Iterable[str], candidate: str) -> int:
    references = _flatten_references(reference)
    candidate_norm = _normalize_answer(candidate)
    return int(any(_normalize_answer(item) in candidate_norm for item in references))


def longmemeval_judge_prompt(
    task: str,
    question: str,
    answer: str,
    response: str,
    *,
    abstention: bool = False,
) -> str:
    """Build the exact dated LongMemEval official answer-check prompt."""
    if not abstention:
        if task in {"single-session-user", "single-session-assistant", "multi-session"}:
            template = (
                "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            )
        elif task == "temporal-reasoning":
            template = (
                "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. In addition, do not penalize off-by-one errors for the number of days. If the question asks for the number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when the answer is 18), the model's response is still correct. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            )
        elif task == "knowledge-update":
            template = (
                "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response contains some previous information along with an updated answer, the response should be considered as correct as long as the updated answer is the required answer.\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            )
        elif task == "single-session-preference":
            template = (
                "I will give you a question, a rubric for desired personalized response, and a response from a model. Please answer yes if the response satisfies the desired response. Otherwise, answer no. The model does not need to reflect all the points in the rubric. The response is correct as long as it recalls and utilizes the user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            )
        else:
            raise ContractError(f"unsupported LongMemEval task type: {task}")
    else:
        template = (
            "I will give you an unanswerable question, an explanation, and a response from a model. Please answer yes if the model correctly identifies the question as unanswerable. The model could say that the information is incomplete, or some other information is given but the asked information is not.\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the question as unanswerable? Answer yes or no only."
        )
    return template.format(question, answer, response)


def parse_longmemeval_judge_label(response: str) -> bool:
    """Preserve the official evaluator's text parser for compatibility audits."""
    return "yes" in response.strip().lower()


def project_judge_prompt(
    task: str,
    question: str,
    answer: str,
    response: str,
    *,
    abstention: bool = False,
) -> str:
    """Keep LongMemEval semantics while changing only the output contract."""
    official_prompt = longmemeval_judge_prompt(
        task,
        question,
        answer,
        response,
        abstention=abstention,
    )
    official_suffix = "Answer yes or no only."
    if official_prompt.count(official_suffix) != 1:
        raise ContractError("official LongMemEval prompt has an unexpected output suffix")
    project_suffix = (
        'Return exactly one JSON object and no other text: {"label":1} for yes '
        'or {"label":0} for no.'
    )
    return official_prompt.replace(official_suffix, project_suffix)


def parse_project_judge_json_label(response: str) -> int:
    """Parse the project judge's strict, JSON-only output contract."""
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("judge response contains a duplicate JSON key")
        return dict(pairs)

    parsed = json.loads(response, object_pairs_hook=reject_duplicate_keys)
    label = parsed.get("label") if isinstance(parsed, Mapping) else None
    if isinstance(label, bool) or not isinstance(label, int) or label not in {0, 1}:
        raise ValueError("judge response must be a JSON object with integer label 0 or 1")
    if set(parsed) != {"label"}:
        raise ValueError("judge response must contain only the label key")
    return label


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


def repeatability_metrics(rows: Iterable[Mapping[str, Any]]) -> dict[str, float | int]:
    observations = list(rows)
    expected_observations = (
        JUDGE_REPEATABILITY_CASE_COUNT * JUDGE_REPEATABILITY_REPLICATES
    )
    if len(observations) != expected_observations:
        raise ContractError(
            f"judge repeatability requires exactly {expected_observations} observations"
        )

    by_case: dict[str, list[int | None]] = {}
    category_by_case: dict[str, str] = {}
    seen: set[tuple[str, int]] = set()
    parse_success = 0
    for row_index, row in enumerate(observations):
        if not isinstance(row, Mapping):
            raise ContractError(
                f"judge repeatability observation {row_index} must be an object"
            )
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ContractError("case_id must be a non-empty string")
        replicate_id = row.get("replicate_id")
        if (
            isinstance(replicate_id, bool)
            or not isinstance(replicate_id, int)
            or replicate_id not in range(JUDGE_REPEATABILITY_REPLICATES)
        ):
            raise ContractError("replicate_id must be one of 0, 1, or 2")
        identity = (case_id, replicate_id)
        if identity in seen:
            raise ContractError("duplicate case_id/replicate_id observation")
        seen.add(identity)

        category = row.get("case_category")
        if category not in JUDGE_REPEATABILITY_CATEGORY_COUNTS:
            raise ContractError("case_category is not in the frozen qualification set")
        existing_category = category_by_case.setdefault(case_id, str(category))
        if existing_category != category:
            raise ContractError("case_category must be constant across replicates")

        parsed = row.get("parse_success")
        if not isinstance(parsed, bool):
            raise ContractError("parse_success must be a boolean")
        label = row.get("label")
        if parsed:
            if isinstance(label, bool) or not isinstance(label, int) or label not in {0, 1}:
                raise ContractError("successfully parsed label must be integer 0 or 1")
        elif label is not None:
            raise ContractError("label must be null when parse_success is false")
        parse_success += int(parsed)
        by_case.setdefault(case_id, []).append(label)

    if len(by_case) != JUDGE_REPEATABILITY_CASE_COUNT:
        raise ContractError(
            f"judge repeatability requires exactly {JUDGE_REPEATABILITY_CASE_COUNT} cases"
        )
    for case_id, labels in by_case.items():
        case_replicates = {
            replicate_id
            for observed_case_id, replicate_id in seen
            if observed_case_id == case_id
        }
        if case_replicates != set(range(JUDGE_REPEATABILITY_REPLICATES)):
            raise ContractError(
                f"case {case_id} must contain replicates 0, 1, and 2 exactly once"
            )
        if len(labels) != JUDGE_REPEATABILITY_REPLICATES:
            raise ContractError(
                f"case {case_id} must contain exactly three replicate labels"
            )
    observed_categories = set(category_by_case.values())
    if observed_categories != set(JUDGE_REPEATABILITY_CATEGORY_COUNTS):
        raise ContractError("judge repeatability category coverage is incomplete")
    observed_quotas = Counter(category_by_case.values())
    if dict(observed_quotas) != JUDGE_REPEATABILITY_CATEGORY_COUNTS:
        raise ContractError("judge repeatability category quotas do not match the freeze")

    unanimity = (
        sum(1 for labels in by_case.values() if len(set(labels)) == 1)
        / JUDGE_REPEATABILITY_CASE_COUNT
    )
    flips = 0
    pairs = 0
    for labels in by_case.values():
        for i, left in enumerate(labels):
            for right in labels[i + 1 :]:
                pairs += 1
                flips += int(left != right)
    return {
        "case_count": JUDGE_REPEATABILITY_CASE_COUNT,
        "observation_count": expected_observations,
        "replicates_per_case": JUDGE_REPEATABILITY_REPLICATES,
        "unanimity_rate": unanimity,
        "pairwise_flip_rate": flips / pairs,
        "parse_success_rate": parse_success / expected_observations,
    }


def judge_repeatability_passes(rows: Iterable[Mapping[str, Any]]) -> bool:
    metrics = repeatability_metrics(rows)
    return metrics["unanimity_rate"] >= 0.95 and metrics["pairwise_flip_rate"] <= 0.05 and metrics["parse_success_rate"] == 1.0
