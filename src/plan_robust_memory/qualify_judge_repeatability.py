from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
import urllib.error
import urllib.request
import uuid

from .contracts import ContractError
from .evaluator import (
    JUDGE_REPEATABILITY_CASE_COUNT,
    JUDGE_REPEATABILITY_CATEGORY_COUNTS,
    JUDGE_REPEATABILITY_REPLICATES,
    judge_repeatability_passes,
    parse_project_judge_json_label,
    project_judge_prompt,
    repeatability_metrics,
)
from .gates import FULL_LEAF_QUALIFICATION_SEQUENCE
from .hashing import canonical_json, stable_hash
from .observability import (
    validate_accepted_output_bindings,
    validate_model_call_attempt_raw,
)


PROJECT_JUDGE_MODEL = "gpt-5.6-luna"
BASE_URL = "https://api.labforge.cc/v1"
CHAT_COMPLETIONS_URL = f"{BASE_URL}/chat/completions"
PROXY_URL = "http://127.0.0.1:17897"
SOURCE_SPLIT = "calibration"
SPLIT_CANDIDATE_ID = "20_30_50"
SPLIT_RATIO = {"development": 0.2, "calibration": 0.3, "acceptance": 0.5}
SELECTION_SEED = "judge-repeatability-calibration-v1"
PARSER_VERSION = "project-judge-strict-json-label-v1"
OUTPUT_SCHEMA_VERSION = "plan-robust-memory.project-judge-label.v1"
SERIALIZATION_VERSION = "openai-chat-single-user-v1"
LOCAL_TOKENIZER_SNAPSHOT = "unicode-wordpunct-surrogate-v1"
DECODING_CONFIG = {"temperature": 0, "max_tokens": 128, "stream": False}
MESSAGE_CONTRACT = "exactly_one_user_message_no_system_or_developer_message"
MANIFEST_SCHEMA_VERSION = "plan-robust-memory.judge-repeatability-manifest.v1"
ARTIFACT_SCHEMA_VERSION = "plan-robust-memory.judge-repeatability.v1"
RUN_STATE_SCHEMA_VERSION = "plan-robust-memory.judge-repeatability-run-state.v1"
CALIBRATION_SPLIT_SCHEMA_VERSION = (
    "plan-robust-memory.longmemeval-calibration-split.v1"
)

_ALLOWED_TASKS = {
    "single-session-user",
    "single-session-assistant",
    "multi-session",
    "single-session-preference",
    "temporal-reasoning",
    "knowledge-update",
}
_DAY1_ARTIFACT_NAMES = {
    "proxy_probe.json",
    "model_inventory.json",
    "primary_115k_probe.json",
    "primary_output_probe.json",
    "judge_probe.json",
    "replication_model_probe.json",
    "embedding_probe.json",
    "cost_upper_bound.json",
}
_PROVIDER_IDENTITY_PLACEHOLDERS = {"none", "unknown"}
_CASE_FIELDS = {
    "case_id",
    "episode_id",
    "query_id",
    "source_split",
    "question_type",
    "case_category",
    "question",
    "reference_answer",
    "candidate_answer",
    "expected_semantic_label",
    "abstention",
}
_MANIFEST_FIELDS = {
    "schema_version",
    "manifest_id",
    "source_kind",
    "source_revision",
    "source_audit_hash",
    "source_raw_checksums",
    "split_candidate_id",
    "split_ratio",
    "split_assignment_hash",
    "source_split",
    "selection_seed",
    "case_count",
    "replicate_count",
    "category_counts",
    "cases",
    "acceptance_accessed",
    "manifest_hash",
}


class JudgeRepeatabilityError(ContractError):
    """Raised when the frozen judge repeatability Gate cannot qualify."""


RequestFn = Callable[
    [str, dict[str, Any], dict[str, str], str, float],
    tuple[Mapping[str, Any], Mapping[str, Any]],
]
NowFn = Callable[[], str]
ProgressFn = Callable[[int, int], None]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _redact(value: Any, secret: str | None) -> str:
    text = str(value)
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text[:500]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(
            json.dumps(dict(row), sort_keys=True, ensure_ascii=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def _publish_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(source.read_bytes())
    temporary.replace(target)


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise JudgeRepeatabilityError(f"{name} must be a JSON object")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JudgeRepeatabilityError(f"{name} must be a non-empty string")
    return value


def _observed_provider_identity(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    if value.strip().casefold() in _PROVIDER_IDENTITY_PLACEHOLDERS:
        return None
    return value


def _text(value: Any, name: str) -> str:
    if isinstance(value, str):
        result = value.strip()
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        result = str(value)
    elif isinstance(value, (list, dict)):
        result = canonical_json(value)
    else:
        result = ""
    if not result:
        raise JudgeRepeatabilityError(f"{name} must contain renderable text")
    return result


def _partial_answer(reference: str) -> str | None:
    for separator in (",", ";", " and ", " then ", ". "):
        if separator in reference:
            fragment = reference.split(separator, 1)[0].strip()
            if fragment and fragment != reference:
                return fragment
    tokens = reference.split()
    if len(tokens) < 2:
        return None
    fragment = " ".join(tokens[: max(1, len(tokens) // 2)]).strip()
    return fragment if fragment and fragment != reference else None


def _selection_key(category: str, episode: Mapping[str, Any]) -> str:
    return stable_hash(
        {
            "selection_seed": SELECTION_SEED,
            "case_category": category,
            "episode_id": episode.get("episode_id"),
        }
    )


def _case_from_episode(
    episode: Mapping[str, Any], category: str
) -> dict[str, Any]:
    episode_id = _require_string(episode.get("episode_id"), "episode_id")
    task = _require_string(episode.get("question_type"), "question_type")
    if task not in _ALLOWED_TASKS:
        raise JudgeRepeatabilityError(f"unsupported qualification task: {task}")
    query = _require_mapping(episode.get("query"), f"episode {episode_id}.query")
    query_id = _require_string(query.get("query_id"), f"episode {episode_id}.query_id")
    question = _text(
        query.get("question_text"), f"episode {episode_id}.question_text"
    )
    reference = _text(
        query.get("gold_answer"), f"episode {episode_id}.gold_answer"
    )

    expected = 1
    if category in {"gold_equivalent", "temporal_reasoning", "knowledge_update"}:
        candidate = reference
    elif category == "formatting_variation":
        candidate = f"Final answer:\n{reference}"
    elif category == "clearly_wrong":
        candidate = "An unrelated alternative that is not the reference answer."
        expected = 0
    elif category == "abstention_like":
        candidate = "I cannot determine the answer from the available information."
        expected = 0
    elif category == "partial":
        partial = _partial_answer(reference)
        if partial is None:
            raise JudgeRepeatabilityError(
                f"episode {episode_id} cannot support a deterministic partial-answer case"
            )
        candidate = partial
        expected = 0
    else:
        raise JudgeRepeatabilityError(f"unsupported case_category: {category}")

    case_id = "jrq-" + stable_hash(
        {
            "manifest_id": SELECTION_SEED,
            "episode_id": episode_id,
            "case_category": category,
            "candidate_answer": candidate,
        }
    )[:20]
    return {
        "case_id": case_id,
        "episode_id": episode_id,
        "query_id": query_id,
        "source_split": SOURCE_SPLIT,
        "question_type": task,
        "case_category": category,
        "question": question,
        "reference_answer": reference,
        "candidate_answer": candidate,
        "expected_semantic_label": expected,
        "abstention": False,
    }


def _validated_audit_and_power(
    audit: Mapping[str, Any], power_artifact: Mapping[str, Any]
) -> tuple[Mapping[str, Any], set[str]]:
    if audit.get("status") not in {"qualified", "qualified_with_exclusions"}:
        raise JudgeRepeatabilityError("LongMemEval audit must be qualified")
    if audit.get("no_silent_drop") is not True:
        raise JudgeRepeatabilityError("LongMemEval audit must certify no_silent_drop=true")
    audit_hash = _require_string(audit.get("audit_hash"), "audit_hash")
    expected_audit_hash = stable_hash(
        {key: value for key, value in audit.items() if key != "audit_hash"}
    )
    if audit_hash != expected_audit_hash:
        raise JudgeRepeatabilityError("audit_hash does not match the dataset manifest")
    if power_artifact.get("status") != "passed":
        raise JudgeRepeatabilityError("G-POWER-FEASIBILITY must be passed")
    power_artifact_hash = _require_string(
        power_artifact.get("artifact_hash"), "power artifact_hash"
    )
    expected_power_artifact_hash = stable_hash(
        {
            key: value
            for key, value in power_artifact.items()
            if key != "artifact_hash"
        }
    )
    if power_artifact_hash != expected_power_artifact_hash:
        raise JudgeRepeatabilityError(
            "power artifact_hash does not match the power Gate contents"
        )
    if power_artifact.get("input_audit_hash") != audit_hash:
        raise JudgeRepeatabilityError("power artifact is not bound to audit_hash")
    if power_artifact.get("split_ratio") != SPLIT_RATIO:
        raise JudgeRepeatabilityError("power artifact must freeze the 20/30/50 split")

    raw_candidates = audit.get("split_candidates")
    if not isinstance(raw_candidates, list):
        raise JudgeRepeatabilityError("dataset manifest split_candidates must be a list")
    matches = [
        candidate
        for candidate in raw_candidates
        if isinstance(candidate, Mapping)
        and candidate.get("candidate_id") == SPLIT_CANDIDATE_ID
    ]
    if len(matches) != 1:
        raise JudgeRepeatabilityError("20/30/50 split candidate must exist exactly once")
    candidate = matches[0]
    if candidate.get("ratio") != SPLIT_RATIO:
        raise JudgeRepeatabilityError("20/30/50 candidate ratio is not frozen")
    assignment_hash = _require_string(
        candidate.get("assignment_hash"), "split assignment_hash"
    )
    if power_artifact.get("split_assignment_hash") != assignment_hash:
        raise JudgeRepeatabilityError(
            "power split_assignment_hash does not match the dataset manifest"
        )
    assignments = candidate.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        raise JudgeRepeatabilityError("split assignments must be a non-empty list")
    calibration_ids: set[str] = set()
    all_ids: set[str] = set()
    for assignment in assignments:
        row = _require_mapping(assignment, "split assignment")
        split = row.get("split")
        if split not in {"development", "calibration", "acceptance"}:
            raise JudgeRepeatabilityError("split assignment contains an invalid split")
        episode_ids = row.get("episode_ids")
        if not isinstance(episode_ids, list) or not episode_ids:
            raise JudgeRepeatabilityError("split assignment episode_ids must be non-empty")
        for raw_episode_id in episode_ids:
            episode_id = _require_string(raw_episode_id, "split episode_id")
            if episode_id in all_ids:
                raise JudgeRepeatabilityError("an episode appears in multiple split assignments")
            all_ids.add(episode_id)
            if split == SOURCE_SPLIT:
                calibration_ids.add(episode_id)
    if not calibration_ids:
        raise JudgeRepeatabilityError("calibration split is empty")
    return candidate, calibration_ids


def build_case_manifest(
    *,
    audit: Mapping[str, Any],
    power_artifact: Mapping[str, Any],
    normalized_episodes: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    candidate, calibration_ids = _validated_audit_and_power(audit, power_artifact)
    calibration: list[Mapping[str, Any]] = []
    seen_episode_ids: set[str] = set()
    for raw_episode in normalized_episodes:
        episode = _require_mapping(raw_episode, "normalized episode")
        episode_id = _require_string(episode.get("episode_id"), "episode_id")
        if episode_id in seen_episode_ids:
            raise JudgeRepeatabilityError(
                f"normalized episodes contain duplicate episode_id: {episode_id}"
            )
        seen_episode_ids.add(episode_id)
        if episode_id not in calibration_ids:
            raise JudgeRepeatabilityError(
                "Judge Repeatability requires a calibration-only input artifact"
            )
        calibration.append(episode)
    missing = sorted(calibration_ids - seen_episode_ids)
    if missing:
        raise JudgeRepeatabilityError(
            f"normalized episodes are missing {len(missing)} calibration assignments"
        )

    source_by_category: dict[str, list[Mapping[str, Any]]] = {}
    used: set[str] = set()
    for category, task in (
        ("temporal_reasoning", "temporal-reasoning"),
        ("knowledge_update", "knowledge-update"),
    ):
        count = JUDGE_REPEATABILITY_CATEGORY_COUNTS[category]
        eligible = sorted(
            (
                episode
                for episode in calibration
                if episode.get("question_type") == task
                and episode.get("episode_id") not in used
            ),
            key=lambda episode: _selection_key(category, episode),
        )
        if len(eligible) < count:
            raise JudgeRepeatabilityError(
                f"calibration has fewer than {count} eligible {task} episodes"
            )
        source_by_category[category] = eligible[:count]
        used.update(str(episode["episode_id"]) for episode in eligible[:count])

    for category in JUDGE_REPEATABILITY_CATEGORY_COUNTS:
        if category in source_by_category:
            continue
        count = JUDGE_REPEATABILITY_CATEGORY_COUNTS[category]
        eligible = [
            episode
            for episode in calibration
            if episode.get("episode_id") not in used
            and episode.get("question_type") in _ALLOWED_TASKS
        ]
        if category == "partial":
            eligible = [
                episode
                for episode in eligible
                if isinstance(episode.get("query"), Mapping)
                and _partial_answer(
                    _text(
                        episode["query"].get("gold_answer"),
                        f"episode {episode.get('episode_id')}.gold_answer",
                    )
                )
                is not None
            ]
        eligible = sorted(
            eligible, key=lambda episode: _selection_key(category, episode)
        )
        if len(eligible) < count:
            raise JudgeRepeatabilityError(
                f"calibration has fewer than {count} eligible {category} episodes"
            )
        source_by_category[category] = eligible[:count]
        used.update(str(episode["episode_id"]) for episode in eligible[:count])

    cases = [
        _case_from_episode(episode, category)
        for category in JUDGE_REPEATABILITY_CATEGORY_COUNTS
        for episode in source_by_category[category]
    ]
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_id": SELECTION_SEED,
        "source_kind": audit.get("source_kind", "longmemeval-calibration"),
        "source_revision": _require_string(
            audit.get("source_revision"), "source_revision"
        ),
        "source_audit_hash": audit["audit_hash"],
        "source_raw_checksums": audit.get("raw_checksums"),
        "split_candidate_id": SPLIT_CANDIDATE_ID,
        "split_ratio": dict(SPLIT_RATIO),
        "split_assignment_hash": candidate["assignment_hash"],
        "source_split": SOURCE_SPLIT,
        "selection_seed": SELECTION_SEED,
        "case_count": len(cases),
        "replicate_count": JUDGE_REPEATABILITY_REPLICATES,
        "category_counts": dict(JUDGE_REPEATABILITY_CATEGORY_COUNTS),
        "cases": cases,
        "acceptance_accessed": False,
    }
    manifest["manifest_hash"] = stable_hash(manifest)
    validate_case_manifest(manifest)
    return manifest


def materialize_calibration_split(
    *,
    audit: Mapping[str, Any],
    power_artifact: Mapping[str, Any],
    normalized_episodes: Iterable[Mapping[str, Any]],
    source_normalized_sha256: str,
) -> dict[str, Any]:
    """Trusted data-steward transform from the combined store to Q_cal only."""
    candidate, calibration_ids = _validated_audit_and_power(audit, power_artifact)
    if not re.fullmatch(r"[a-f0-9]{64}", source_normalized_sha256):
        raise JudgeRepeatabilityError("source_normalized_sha256 must be SHA-256")
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row_index, raw_episode in enumerate(normalized_episodes):
        episode = _require_mapping(raw_episode, f"normalized_episodes[{row_index}]")
        episode_id = _require_string(episode.get("episode_id"), "episode_id")
        if episode_id in seen:
            raise JudgeRepeatabilityError(
                f"normalized episodes contain duplicate episode_id: {episode_id}"
            )
        seen.add(episode_id)
        if episode_id in calibration_ids:
            selected.append(dict(episode))
    missing = calibration_ids - seen
    if missing:
        raise JudgeRepeatabilityError(
            f"combined normalized store is missing {len(missing)} calibration episodes"
        )
    selected.sort(key=lambda episode: str(episode["episode_id"]))
    artifact: dict[str, Any] = {
        "schema_version": CALIBRATION_SPLIT_SCHEMA_VERSION,
        "source_audit_hash": audit["audit_hash"],
        "source_revision": audit["source_revision"],
        "source_normalized_sha256": source_normalized_sha256,
        "source_power_artifact_hash": power_artifact["artifact_hash"],
        "split_candidate_id": SPLIT_CANDIDATE_ID,
        "split_ratio": dict(SPLIT_RATIO),
        "split_assignment_hash": candidate["assignment_hash"],
        "source_split": SOURCE_SPLIT,
        "episode_count": len(selected),
        "episodes": selected,
        "source_combined_store_scanned": True,
        "acceptance_routing_metadata_read": True,
        "acceptance_payload_exported": False,
    }
    artifact["artifact_hash"] = stable_hash(artifact)
    validate_calibration_split_artifact(
        artifact, audit=audit, power_artifact=power_artifact
    )
    return artifact


def validate_calibration_split_artifact(
    artifact: Mapping[str, Any],
    *,
    audit: Mapping[str, Any],
    power_artifact: Mapping[str, Any],
) -> Mapping[str, Any]:
    candidate, calibration_ids = _validated_audit_and_power(audit, power_artifact)
    if not isinstance(artifact, Mapping):
        raise JudgeRepeatabilityError("calibration split artifact must be an object")
    expected_fields = {
        "schema_version",
        "source_audit_hash",
        "source_revision",
        "source_normalized_sha256",
        "source_power_artifact_hash",
        "split_candidate_id",
        "split_ratio",
        "split_assignment_hash",
        "source_split",
        "episode_count",
        "episodes",
        "source_combined_store_scanned",
        "acceptance_routing_metadata_read",
        "acceptance_payload_exported",
        "artifact_hash",
    }
    if set(artifact) != expected_fields:
        raise JudgeRepeatabilityError(
            "calibration split artifact fields do not match the frozen contract"
        )
    expected_hash = stable_hash(
        {key: value for key, value in artifact.items() if key != "artifact_hash"}
    )
    if artifact.get("artifact_hash") != expected_hash:
        raise JudgeRepeatabilityError("calibration split artifact_hash does not match")
    if artifact.get("schema_version") != CALIBRATION_SPLIT_SCHEMA_VERSION:
        raise JudgeRepeatabilityError("calibration split schema_version is not frozen")
    if artifact.get("source_audit_hash") != audit.get("audit_hash"):
        raise JudgeRepeatabilityError("calibration split audit hash drifted")
    if artifact.get("source_revision") != audit.get("source_revision"):
        raise JudgeRepeatabilityError("calibration split source revision drifted")
    if artifact.get("source_power_artifact_hash") != power_artifact.get(
        "artifact_hash"
    ):
        raise JudgeRepeatabilityError("calibration split power artifact_hash drifted")
    source_sha = artifact.get("source_normalized_sha256")
    if not isinstance(source_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", source_sha):
        raise JudgeRepeatabilityError("calibration split source SHA-256 is invalid")
    if artifact.get("split_candidate_id") != SPLIT_CANDIDATE_ID:
        raise JudgeRepeatabilityError("calibration split candidate is not 20/30/50")
    if artifact.get("split_ratio") != SPLIT_RATIO:
        raise JudgeRepeatabilityError("calibration split ratio drifted")
    if artifact.get("split_assignment_hash") != candidate.get("assignment_hash"):
        raise JudgeRepeatabilityError("calibration split assignment hash drifted")
    if artifact.get("source_split") != SOURCE_SPLIT:
        raise JudgeRepeatabilityError("qualification source must be calibration-only")
    if artifact.get("source_combined_store_scanned") is not True:
        raise JudgeRepeatabilityError("split materialization scan provenance is missing")
    if artifact.get("acceptance_routing_metadata_read") is not True:
        raise JudgeRepeatabilityError("split routing provenance is missing")
    if artifact.get("acceptance_payload_exported") is not False:
        raise JudgeRepeatabilityError("calibration artifact must not export acceptance payload")
    episodes = artifact.get("episodes")
    if not isinstance(episodes, list) or any(
        not isinstance(episode, Mapping) for episode in episodes
    ):
        raise JudgeRepeatabilityError("calibration episodes must be an array of objects")
    ids = [episode.get("episode_id") for episode in episodes]
    if any(not isinstance(episode_id, str) or not episode_id for episode_id in ids):
        raise JudgeRepeatabilityError("calibration episode IDs must be non-empty strings")
    if len(ids) != len(set(ids)):
        raise JudgeRepeatabilityError("calibration episode IDs must be unique")
    if set(ids) != calibration_ids:
        raise JudgeRepeatabilityError(
            "calibration artifact must contain exactly the frozen Q_cal episode IDs"
        )
    if artifact.get("episode_count") != len(ids):
        raise JudgeRepeatabilityError("calibration episode_count does not match contents")
    return artifact


def validate_case_manifest(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(manifest, Mapping):
        raise JudgeRepeatabilityError("case manifest must be an object")
    if set(manifest) != _MANIFEST_FIELDS:
        raise JudgeRepeatabilityError("case manifest fields do not match the frozen schema")
    declared_hash = manifest.get("manifest_hash")
    expected_hash = stable_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    if declared_hash != expected_hash:
        raise JudgeRepeatabilityError("manifest_hash does not match manifest contents")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise JudgeRepeatabilityError("case manifest schema_version is not frozen")
    if manifest.get("manifest_id") != SELECTION_SEED:
        raise JudgeRepeatabilityError("case manifest_id is not frozen")
    if manifest.get("source_split") != SOURCE_SPLIT:
        raise JudgeRepeatabilityError("judge qualification cases must be calibration-only")
    if manifest.get("acceptance_accessed") is not False:
        raise JudgeRepeatabilityError("acceptance content must not be accessed")
    if manifest.get("split_candidate_id") != SPLIT_CANDIDATE_ID:
        raise JudgeRepeatabilityError("case manifest must use the frozen 20/30/50 split")
    if manifest.get("split_ratio") != SPLIT_RATIO:
        raise JudgeRepeatabilityError("case manifest split ratio is not 20/30/50")
    if manifest.get("case_count") != JUDGE_REPEATABILITY_CASE_COUNT:
        raise JudgeRepeatabilityError("case manifest must contain exactly 50 cases")
    if manifest.get("replicate_count") != JUDGE_REPEATABILITY_REPLICATES:
        raise JudgeRepeatabilityError("case manifest must freeze three replicates")
    if manifest.get("category_counts") != JUDGE_REPEATABILITY_CATEGORY_COUNTS:
        raise JudgeRepeatabilityError("case manifest category quotas are not frozen")
    _require_string(manifest.get("source_revision"), "source_revision")
    _require_string(manifest.get("source_audit_hash"), "source_audit_hash")
    _require_string(
        manifest.get("split_assignment_hash"), "split_assignment_hash"
    )
    if not isinstance(manifest.get("source_raw_checksums"), Mapping):
        raise JudgeRepeatabilityError("source_raw_checksums must be an object")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != JUDGE_REPEATABILITY_CASE_COUNT:
        raise JudgeRepeatabilityError("case manifest cases must contain exactly 50 rows")

    seen_cases: set[str] = set()
    seen_episodes: set[str] = set()
    category_counts: Counter[str] = Counter()
    for row_index, raw_case in enumerate(cases):
        case = _require_mapping(raw_case, f"cases[{row_index}]")
        if set(case) != _CASE_FIELDS:
            raise JudgeRepeatabilityError(
                f"cases[{row_index}] fields do not match the frozen case schema"
            )
        case_id = _require_string(case.get("case_id"), "case_id")
        episode_id = _require_string(case.get("episode_id"), "episode_id")
        if case_id in seen_cases:
            raise JudgeRepeatabilityError("case_id values must be unique")
        if episode_id in seen_episodes:
            raise JudgeRepeatabilityError("episode_id values must be unique across cases")
        seen_cases.add(case_id)
        seen_episodes.add(episode_id)
        if case.get("source_split") != SOURCE_SPLIT:
            raise JudgeRepeatabilityError("every case must be calibration-only")
        category = case.get("case_category")
        if category not in JUDGE_REPEATABILITY_CATEGORY_COUNTS:
            raise JudgeRepeatabilityError("case_category is not frozen")
        category_counts[str(category)] += 1
        task = case.get("question_type")
        if task not in _ALLOWED_TASKS:
            raise JudgeRepeatabilityError("question_type is not LongMemEval-compatible")
        if category == "temporal_reasoning" and task != "temporal-reasoning":
            raise JudgeRepeatabilityError(
                "temporal_reasoning cases must use temporal-reasoning episodes"
            )
        if category == "knowledge_update" and task != "knowledge-update":
            raise JudgeRepeatabilityError(
                "knowledge_update cases must use knowledge-update episodes"
            )
        for field in (
            "query_id",
            "question",
            "reference_answer",
            "candidate_answer",
        ):
            _require_string(case.get(field), field)
        expected_label = case.get("expected_semantic_label")
        if (
            isinstance(expected_label, bool)
            or not isinstance(expected_label, int)
            or expected_label not in {0, 1}
        ):
            raise JudgeRepeatabilityError("expected_semantic_label must be 0 or 1")
        if case.get("abstention") is not False:
            raise JudgeRepeatabilityError(
                "v1 qualification uses answerable calibration cases; abstention-like is a candidate style"
            )
    if dict(category_counts) != JUDGE_REPEATABILITY_CATEGORY_COUNTS:
        raise JudgeRepeatabilityError("case manifest category counts do not match quotas")
    return manifest


def repeatability_request_payload(case: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    prompt = project_judge_prompt(
        str(case["question_type"]),
        str(case["question"]),
        str(case["reference_answer"]),
        str(case["candidate_answer"]),
        abstention=bool(case["abstention"]),
    )
    payload = {
        "model": PROJECT_JUDGE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        **DECODING_CONFIG,
    }
    return payload, prompt


def _http_json_request(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    route: str,
    timeout: float,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if route not in {"direct", "proxy_17897"}:
        raise JudgeRepeatabilityError("route must be direct or proxy_17897")
    proxy_handler = urllib.request.ProxyHandler(
        {} if route == "direct" else {"http": PROXY_URL, "https": PROXY_URL}
    )
    opener = urllib.request.build_opener(proxy_handler)
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request_headers = {
        **headers,
        "Content-Type": "application/json",
        "User-Agent": "plan-robust-memory-judge-repeatability/1.0",
    }
    request = urllib.request.Request(
        url, data=body, headers=request_headers, method="POST"
    )
    started = time.monotonic()
    with opener.open(request, timeout=timeout) as response:
        raw = response.read()
        status = int(getattr(response, "status", 200))
        response_headers = {key.lower(): value for key, value in response.headers.items()}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OSError(f"provider returned non-JSON response: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise JudgeRepeatabilityError("provider response must be a JSON object")
    return parsed, {
        "http_status": status,
        "request_id": response_headers.get("x-request-id") or parsed.get("id"),
        "response_hash": _sha256_bytes(raw),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def _response_content(response: Mapping[str, Any]) -> tuple[str, str | None]:
    choices = response.get("choices")
    if (
        not isinstance(choices, Sequence)
        or isinstance(choices, (str, bytes))
        or len(choices) != 1
        or not isinstance(choices[0], Mapping)
    ):
        raise JudgeRepeatabilityError("judge response must contain exactly one choice")
    message = choices[0].get("message")
    if not isinstance(message, Mapping) or not isinstance(message.get("content"), str):
        raise JudgeRepeatabilityError("judge response choice must contain text content")
    finish_reason = choices[0].get("finish_reason")
    if finish_reason is not None and not isinstance(finish_reason, str):
        raise JudgeRepeatabilityError("judge finish_reason must be a string or null")
    return str(message["content"]), finish_reason


def _local_token_count(text: str) -> int:
    return len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE))


def _provider_usage(
    response: Mapping[str, Any],
) -> tuple[str, int | None, int | None, int | None, int | None]:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        return "missing", None, None, None, None
    input_total = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_total = usage.get("completion_tokens", usage.get("output_tokens"))
    details = usage.get("prompt_tokens_details", usage.get("input_tokens_details"))
    cached: Any = None
    if isinstance(details, Mapping):
        cached = details.get("cached_tokens")
    reasoning_details = usage.get(
        "completion_tokens_details", usage.get("output_tokens_details")
    )
    reasoning: Any = None
    if isinstance(reasoning_details, Mapping):
        reasoning = reasoning_details.get("reasoning_tokens")
    valid_int = lambda value: (
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
    )
    if not (valid_int(input_total) and valid_int(output_total) and valid_int(cached)):
        return "missing", None, None, None, None
    if reasoning is not None and not valid_int(reasoning):
        return "missing", None, None, None, None
    return (
        "provider_exact",
        int(input_total),
        int(cached),
        int(output_total),
        int(reasoning) if reasoning is not None else None,
    )


def derive_repeatability_observations(
    *,
    case_manifest: Mapping[str, Any],
    attempts: Iterable[Mapping[str, Any]],
    bindings: Iterable[Mapping[str, Any]],
    outputs: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rebuild metric rows only through accepted binding lineage."""
    validate_case_manifest(case_manifest)
    attempt_rows = list(attempts)
    binding_rows = list(bindings)
    output_rows = list(outputs)
    validate_accepted_output_bindings(attempt_rows, binding_rows)

    def unique_map(
        rows: Iterable[Mapping[str, Any]], field: str, object_name: str
    ) -> dict[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        for row_index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise JudgeRepeatabilityError(
                    f"{object_name}[{row_index}] must be an object"
                )
            identifier = row.get(field)
            if not isinstance(identifier, str) or not identifier:
                raise JudgeRepeatabilityError(
                    f"{object_name}.{field} must be a non-empty string"
                )
            if identifier in result:
                raise JudgeRepeatabilityError(
                    f"duplicate {object_name}.{field}: {identifier}"
                )
            result[identifier] = row
        return result

    attempt_map = unique_map(attempt_rows, "attempt_id", "attempt")
    output_map = unique_map(output_rows, "output_artifact_id", "judge output")
    binding_by_call = unique_map(binding_rows, "logical_call_id", "binding")
    accepted_output_ids = {
        str(binding["output_artifact_id"])
        for binding in binding_rows
        if binding.get("binding_status") == "succeeded"
    }
    if accepted_output_ids != set(output_map):
        raise JudgeRepeatabilityError(
            "raw judge outputs must resolve exactly the accepted output bindings"
        )

    observations: list[dict[str, Any]] = []
    expected_output_fields = {
        "output_artifact_id",
        "run_id",
        "logical_call_id",
        "attempt_id",
        "case_id",
        "replicate_id",
        "response_text",
        "response_content_hash",
        "response_hash",
        "raw_response",
        "received_at",
    }
    for case in case_manifest["cases"]:
        for replicate_id in range(JUDGE_REPEATABILITY_REPLICATES):
            logical_call_id = (
                f"judge-repeatability:{case['case_id']}:replicate-{replicate_id}"
            )
            binding = binding_by_call.get(logical_call_id)
            if binding is None or binding.get("binding_status") != "succeeded":
                raise JudgeRepeatabilityError(
                    "every frozen case/replicate must resolve one successful binding"
                )
            attempt = attempt_map.get(str(binding.get("accepted_attempt_id")))
            output = output_map.get(str(binding.get("output_artifact_id")))
            if attempt is None or output is None:
                raise JudgeRepeatabilityError(
                    "accepted binding does not resolve attempt and raw output"
                )
            if set(output) != expected_output_fields:
                raise JudgeRepeatabilityError(
                    "raw judge output fields do not match the frozen contract"
                )
            for field in ("run_id", "logical_call_id"):
                if output.get(field) != binding.get(field) or attempt.get(
                    field
                ) != binding.get(field):
                    raise JudgeRepeatabilityError(
                        f"binding/attempt/output {field} lineage does not match"
                    )
            if output.get("attempt_id") != attempt.get("attempt_id"):
                raise JudgeRepeatabilityError(
                    "raw judge output does not reference the accepted attempt"
                )
            if output.get("case_id") != case["case_id"] or output.get(
                "replicate_id"
            ) != replicate_id:
                raise JudgeRepeatabilityError(
                    "raw judge output case/replicate identity does not match the manifest"
                )
            response_text = output.get("response_text")
            if not isinstance(response_text, str):
                raise JudgeRepeatabilityError("raw judge response_text must be a string")
            observed_content_hash = _sha256_bytes(response_text.encode("utf-8"))
            if output.get("response_content_hash") != observed_content_hash:
                raise JudgeRepeatabilityError("raw judge output content hash does not match")
            if output.get("response_hash") != attempt.get("response_hash"):
                raise JudgeRepeatabilityError(
                    "attempt and raw output response hash do not match"
                )
            raw_response = output.get("raw_response")
            if not isinstance(raw_response, Mapping):
                raise JudgeRepeatabilityError("raw_response must be an object")
            replayed_text, _ = _response_content(raw_response)
            if replayed_text != response_text:
                raise JudgeRepeatabilityError(
                    "response_text does not replay from the raw provider output"
                )
            if raw_response.get("model") != attempt.get("returned_model"):
                raise JudgeRepeatabilityError(
                    "raw response model does not match the accepted attempt"
                )
            try:
                label = parse_project_judge_json_label(response_text)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise JudgeRepeatabilityError(
                    f"accepted raw output cannot be parsed by the frozen parser: {exc}"
                ) from exc
            observations.append(
                {
                    "case_id": case["case_id"],
                    "case_category": case["case_category"],
                    "replicate_id": replicate_id,
                    "label": label,
                    "parse_success": True,
                    "attempt_id": attempt["attempt_id"],
                    "binding_id": binding["binding_id"],
                    "output_artifact_id": output["output_artifact_id"],
                    "requested_model": attempt["requested_model"],
                    "returned_model": attempt["returned_model"],
                    "provider_route": attempt["provider_route"],
                    "prompt_hash": attempt["prompt_hash"],
                    "response_hash": attempt["response_hash"],
                    "request_id": attempt["request_id"],
                }
            )
    repeatability_metrics(observations)
    return observations


def _validate_upstream(
    *,
    evaluator_parity: Mapping[str, Any],
    evaluator_parity_run_state: Mapping[str, Any],
    evaluator_parity_sha256: str,
    protocol_state: Mapping[str, Any],
    day1_run_state: Mapping[str, Any],
    day1_artifacts: Mapping[str, Mapping[str, Any]],
    model_inventory: Mapping[str, Any],
    judge_probe: Mapping[str, Any],
) -> None:
    expected_prefix = ["observability_freeze", "evaluator_parity"]
    if protocol_state.get("completed_stages") != expected_prefix:
        raise JudgeRepeatabilityError(
            "Judge Repeatability requires the exact ordered qualification prefix"
        )
    if protocol_state.get("next_stage") != "judge_repeatability":
        raise JudgeRepeatabilityError("protocol next_stage must be judge_repeatability")
    if protocol_state.get("acceptance_accessed") is not False:
        raise JudgeRepeatabilityError("acceptance must remain inaccessible")
    sequence = protocol_state.get("qualification_sequence")
    if sequence is not None and sequence != list(FULL_LEAF_QUALIFICATION_SEQUENCE):
        raise JudgeRepeatabilityError("protocol qualification sequence is not frozen")
    if evaluator_parity.get("status") != "passed" or evaluator_parity.get(
        "evaluator_parity_passed"
    ) is not True:
        raise JudgeRepeatabilityError("Evaluator Parity has not passed")
    if evaluator_parity.get("next_stage") != "judge_repeatability":
        raise JudgeRepeatabilityError("Evaluator Parity does not authorize this stage")
    parity_run_id = _require_string(
        evaluator_parity.get("run_id"), "Evaluator Parity run_id"
    )
    if not isinstance(evaluator_parity_run_state, Mapping):
        raise JudgeRepeatabilityError("Evaluator Parity run-state is required")
    if evaluator_parity_run_state.get("state") != "completed":
        raise JudgeRepeatabilityError("Evaluator Parity run-state is not completed")
    if evaluator_parity_run_state.get("run_id") != parity_run_id:
        raise JudgeRepeatabilityError("Evaluator Parity run-state identity drifted")
    if not isinstance(evaluator_parity_sha256, str) or not re.fullmatch(
        r"[a-f0-9]{64}", evaluator_parity_sha256
    ):
        raise JudgeRepeatabilityError("Evaluator Parity checksum is invalid")
    parity_state_artifacts = _require_mapping(
        evaluator_parity_run_state.get("artifacts"),
        "Evaluator Parity run-state artifacts",
    )
    parity_entry = _require_mapping(
        parity_state_artifacts.get("evaluator_parity.json"),
        "Evaluator Parity artifact entry",
    )
    if (
        parity_entry.get("state") != "completed"
        or parity_entry.get("run_id") != parity_run_id
        or parity_entry.get("sha256") != evaluator_parity_sha256
    ):
        raise JudgeRepeatabilityError(
            "Evaluator Parity run-state artifact checksum/identity drifted"
        )
    protocol_artifacts = _require_mapping(
        protocol_state.get("artifacts"), "protocol qualification artifacts"
    )
    if (
        protocol_artifacts.get("evaluator_parity_run_id") != parity_run_id
        or protocol_artifacts.get("evaluator_parity_sha256")
        != evaluator_parity_sha256
    ):
        raise JudgeRepeatabilityError(
            "protocol and Evaluator Parity artifact checksum/identity drifted"
        )

    if not isinstance(day1_run_state, Mapping):
        raise JudgeRepeatabilityError("Day 1 run-state is required")
    day1_run_id = _require_string(day1_run_state.get("run_id"), "Day 1 run_id")
    if (
        day1_run_state.get("state") != "completed"
        or day1_run_state.get("status") != "passed"
    ):
        raise JudgeRepeatabilityError("Day 1 run-state is not completed/passed")
    if set(day1_run_state.get("artifact_names", [])) != _DAY1_ARTIFACT_NAMES:
        raise JudgeRepeatabilityError("Day 1 run-state must list all eight frozen artifacts")
    if not isinstance(day1_artifacts, Mapping) or set(day1_artifacts) != _DAY1_ARTIFACT_NAMES:
        raise JudgeRepeatabilityError("Day 1 evidence must contain all eight frozen artifacts")
    for artifact_name, artifact in day1_artifacts.items():
        if not isinstance(artifact, Mapping):
            raise JudgeRepeatabilityError(f"Day 1 {artifact_name} must be an object")
        if (
            artifact.get("artifact_name") != artifact_name
            or artifact.get("artifact_state") != "completed"
            or artifact.get("status") != "passed"
            or artifact.get("run_id") != day1_run_id
        ):
            raise JudgeRepeatabilityError(
                f"Day 1 {artifact_name} is not completed/passed for the run-state identity"
            )
    if (
        model_inventory.get("run_id") != day1_run_id
        or judge_probe.get("run_id") != day1_run_id
    ):
        raise JudgeRepeatabilityError(
            "model inventory and judge probe must belong to the same Day 1 run"
        )
    if dict(day1_artifacts["model_inventory.json"]) != dict(model_inventory):
        raise JudgeRepeatabilityError("model inventory does not match the Day 1 artifact set")
    if dict(day1_artifacts["judge_probe.json"]) != dict(judge_probe):
        raise JudgeRepeatabilityError("judge probe does not match the Day 1 artifact set")
    for name, artifact in (
        ("model inventory", model_inventory),
        ("judge probe", judge_probe),
    ):
        if artifact.get("status") != "passed" or artifact.get(
            "artifact_state"
        ) != "completed":
            raise JudgeRepeatabilityError(f"Day 1 {name} is not passed and completed")
    if PROJECT_JUDGE_MODEL not in model_inventory.get("returned_model_ids", []):
        raise JudgeRepeatabilityError("gpt-5.5 is absent from the passed model inventory")
    if judge_probe.get("requested_model") != PROJECT_JUDGE_MODEL:
        raise JudgeRepeatabilityError("Day 1 judge requested model is not gpt-5.5")
    if judge_probe.get("returned_model") != PROJECT_JUDGE_MODEL:
        raise JudgeRepeatabilityError("Day 1 judge returned model is not frozen gpt-5.5")
    if judge_probe.get("base_url") != BASE_URL:
        raise JudgeRepeatabilityError("Day 1 judge base URL is not frozen")
    if judge_probe.get("endpoint") != CHAT_COMPLETIONS_URL:
        raise JudgeRepeatabilityError("Day 1 judge endpoint is not chat/completions")
    if judge_probe.get("message_contract") != MESSAGE_CONTRACT:
        raise JudgeRepeatabilityError("Day 1 judge message contract is not injection-free")
    if judge_probe.get("parser_success_rate") != 1.0:
        raise JudgeRepeatabilityError("Day 1 judge parser probe did not fully pass")
    decoding = judge_probe.get("decoding_parameters")
    if decoding is not None and decoding != DECODING_CONFIG:
        raise JudgeRepeatabilityError("Day 1 judge decoding parameters drifted")

    parity_judge = _require_mapping(
        evaluator_parity.get("project_judge"), "Evaluator Parity project_judge"
    )
    for field, expected in (
        ("requested_model", PROJECT_JUDGE_MODEL),
        ("returned_model", PROJECT_JUDGE_MODEL),
        ("day1_run_id", day1_run_id),
        ("endpoint", CHAT_COMPLETIONS_URL),
        ("message_contract", MESSAGE_CONTRACT),
    ):
        if parity_judge.get(field) != expected:
            raise JudgeRepeatabilityError(
                f"Evaluator Parity project_judge.{field} does not match frozen evidence"
            )
    if parity_judge.get("day1_artifact_hash") != stable_hash(dict(judge_probe)):
        raise JudgeRepeatabilityError("Evaluator Parity judge artifact hash drifted")
    compatibility = evaluator_parity.get("official_compatibility")
    if not isinstance(compatibility, Mapping):
        raise JudgeRepeatabilityError("Evaluator Parity official_compatibility is required")
    if compatibility.get("inventory_run_id") != day1_run_id:
        raise JudgeRepeatabilityError("Evaluator Parity inventory run identity drifted")
    if compatibility.get("inventory_artifact_hash") != stable_hash(
        dict(model_inventory)
    ):
        raise JudgeRepeatabilityError("Evaluator Parity inventory artifact hash drifted")


def _validate_day1_file_checksums(
    *,
    day1_dir: Path,
    day1_run_state: Mapping[str, Any],
) -> None:
    """Verify optional Day 1 file lineage without changing its frozen schema."""
    raw_entries = day1_run_state.get("artifact_checksums")
    if raw_entries is None:
        candidate_entries = day1_run_state.get("artifacts")
        if isinstance(candidate_entries, Mapping) and any(
            isinstance(value, Mapping) and "sha256" in value
            for value in candidate_entries.values()
        ):
            raw_entries = candidate_entries
    if raw_entries is None:
        return
    if not isinstance(raw_entries, Mapping):
        raise JudgeRepeatabilityError("Day 1 artifact checksum map must be an object")
    day1_run_id = _require_string(day1_run_state.get("run_id"), "Day 1 run_id")
    if set(raw_entries) != _DAY1_ARTIFACT_NAMES:
        raise JudgeRepeatabilityError(
            "Day 1 artifact checksum map must contain all eight frozen artifacts"
        )
    for artifact_name in sorted(_DAY1_ARTIFACT_NAMES):
        entry = _require_mapping(
            raw_entries[artifact_name],
            f"Day 1 artifact checksum entry {artifact_name}",
        )
        if entry.get("run_id") != day1_run_id:
            raise JudgeRepeatabilityError(
                f"Day 1 artifact checksum run identity drifted for {artifact_name}"
            )
        expected = entry.get("sha256")
        if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise JudgeRepeatabilityError(
                f"Day 1 artifact checksum is invalid for {artifact_name}"
            )
        actual = _sha256_path(day1_dir / artifact_name)
        if actual != expected:
            raise JudgeRepeatabilityError(
                f"Day 1 artifact checksum drifted for {artifact_name}"
            )


def _attempt_record(
    *,
    run_id: str,
    logical_call_id: str,
    attempt_id: str,
    retry_index: int,
    route: str,
    prompt: str,
    response: Mapping[str, Any],
    response_text: str,
    response_hash: str,
    request_id: str | None,
    http_status: int,
    finish_reason: str | None,
    timestamp: str,
    outcome: str,
    parse_status: str,
    failure_type: str | None,
    requested_model: str = PROJECT_JUDGE_MODEL,
) -> dict[str, Any]:
    source, input_total, cached, output_total, reasoning = _provider_usage(response)
    returned_model = _observed_provider_identity(response.get("model"))
    record = {
        "attempt_id": attempt_id,
        "run_id": run_id,
        "stage": "judge",
        "logical_call_id": logical_call_id,
        "accepted_attempt": outcome == "accepted_materialized",
        "retry_index": retry_index,
        "requested_model": requested_model,
        "returned_model": returned_model,
        "provider": "labforge",
        "provider_route": route,
        "request_id": request_id,
        "prompt_hash": _sha256_bytes(prompt.encode("utf-8")),
        "response_hash": response_hash,
        "local_surrogate_serialized_input_tokens": _local_token_count(prompt),
        "local_surrogate_output_content_tokens": _local_token_count(response_text),
        "tokenizer_snapshot": LOCAL_TOKENIZER_SNAPSHOT,
        "serialization_version": SERIALIZATION_VERSION,
        "provider_input_tokens_total": input_total,
        "provider_cached_input_tokens_subset": cached,
        "provider_output_tokens_total": output_total,
        "provider_reasoning_tokens_subset": reasoning,
        "usage_schema_version": "openai-chat-completions-usage-v1",
        "provider_usage_source": source,
        "scheduled_at": timestamp,
        "started_at": timestamp,
        "finished_at": timestamp,
        "http_status": http_status,
        "finish_reason": finish_reason,
        "parse_status": parse_status,
        "failure_type": failure_type,
        "attempt_outcome": outcome,
        "status": "completed" if outcome == "accepted_materialized" else "failed",
    }
    validate_model_call_attempt_raw(record)
    return record


def _failed_attempt_record(
    *,
    run_id: str,
    logical_call_id: str,
    attempt_id: str,
    retry_index: int,
    route: str,
    prompt: str,
    response: Mapping[str, Any] | None,
    response_metadata: Mapping[str, Any] | None,
    http_status: int | None,
    scheduled_at: str,
    finished_at: str,
    failure_type: str,
    requested_model: str = PROJECT_JUDGE_MODEL,
) -> dict[str, Any]:
    response_object: Mapping[str, Any] = response if isinstance(response, Mapping) else {}
    metadata: Mapping[str, Any] = (
        response_metadata if isinstance(response_metadata, Mapping) else {}
    )
    source, input_total, cached, output_total, reasoning = _provider_usage(response_object)
    returned_model = _observed_provider_identity(response_object.get("model"))
    request_id = _observed_provider_identity(metadata.get("request_id"))
    if request_id is None:
        request_id = _observed_provider_identity(response_object.get("id"))
    response_hash = metadata.get("response_hash")
    if not isinstance(response_hash, str) or not response_hash.strip():
        response_hash = None
    record = {
        "attempt_id": attempt_id,
        "run_id": run_id,
        "stage": "judge",
        "logical_call_id": logical_call_id,
        "accepted_attempt": False,
        "retry_index": retry_index,
        "requested_model": requested_model,
        "returned_model": returned_model,
        "provider": "labforge",
        "provider_route": route,
        "request_id": request_id,
        "prompt_hash": _sha256_bytes(prompt.encode("utf-8")),
        "response_hash": response_hash,
        "local_surrogate_serialized_input_tokens": _local_token_count(prompt),
        "local_surrogate_output_content_tokens": 0,
        "tokenizer_snapshot": LOCAL_TOKENIZER_SNAPSHOT,
        "serialization_version": SERIALIZATION_VERSION,
        "provider_input_tokens_total": input_total,
        "provider_cached_input_tokens_subset": cached,
        "provider_output_tokens_total": output_total,
        "provider_reasoning_tokens_subset": reasoning,
        "usage_schema_version": "openai-chat-completions-usage-v1",
        "provider_usage_source": source,
        "scheduled_at": scheduled_at,
        "started_at": scheduled_at,
        "finished_at": finished_at,
        "http_status": http_status,
        "finish_reason": None,
        "parse_status": "not_attempted",
        "failure_type": failure_type,
        "attempt_outcome": "failed_provider",
        "status": "failed",
    }
    validate_model_call_attempt_raw(record)
    return record


def _error_request_id(exc: BaseException) -> str | None:
    headers = getattr(exc, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return None
    value = headers.get("x-request-id") or headers.get("X-Request-ID")
    return _observed_provider_identity(value)


def _artifact_entry(path: Path, run_id: str, state: str = "completed") -> dict[str, Any]:
    entry: dict[str, Any] = {
        "state": state,
        "run_id": run_id,
        "path": str(path),
    }
    if path.exists():
        entry["sha256"] = _sha256_path(path)
    return entry


def _previous_artifacts(protocol_state: Mapping[str, Any]) -> dict[str, Any]:
    artifacts = protocol_state.get("artifacts")
    return dict(artifacts) if isinstance(artifacts, Mapping) else {}


def run_judge_repeatability(
    *,
    output_dir: Path,
    case_manifest: Mapping[str, Any],
    evaluator_parity: Mapping[str, Any],
    evaluator_parity_run_state: Mapping[str, Any],
    evaluator_parity_sha256: str,
    protocol_state: Mapping[str, Any],
    day1_run_state: Mapping[str, Any],
    day1_artifacts: Mapping[str, Mapping[str, Any]],
    model_inventory: Mapping[str, Any],
    judge_probe: Mapping[str, Any],
    api_key: str | None,
    request_fn: RequestFn = _http_json_request,
    now_fn: NowFn = _now,
    progress_fn: ProgressFn | None = None,
    timeout: float = 120.0,
    run_id: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_id or f"judge-repeatability-{uuid.uuid4().hex}"
    started_at = started_at or now_fn()
    run_dir = output_dir / "judge_repeatability_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_state_path = output_dir / "judge_repeatability_run_state.json"
    protocol_state_path = output_dir / "protocol_qualification_state.json"
    stall_path = output_dir / "judge_repeatability_stall.json"
    run_paths = {
        "manifest": run_dir / "judge_repeatability_case_manifest.json",
        "attempts": run_dir / "judge_repeatability_attempts.jsonl",
        "bindings": run_dir / "judge_repeatability_output_bindings.jsonl",
        "outputs": run_dir / "judge_repeatability_outputs.jsonl",
        "transport": run_dir / "judge_repeatability_transport_attempts.jsonl",
        "artifact": run_dir / "judge_repeatability.json",
    }
    canonical_paths = {
        "manifest": output_dir / "judge_repeatability_case_manifest.json",
        "attempts": output_dir / "judge_repeatability_attempts.jsonl",
        "bindings": output_dir / "judge_repeatability_output_bindings.jsonl",
        "outputs": output_dir / "judge_repeatability_outputs.jsonl",
        "transport": output_dir / "judge_repeatability_transport_attempts.jsonl",
        "artifact": output_dir / "judge_repeatability.json",
    }
    _write_json(
        run_state_path,
        {
            "schema_version": RUN_STATE_SCHEMA_VERSION,
            "run_id": run_id,
            "run_started_at": started_at,
            "state": "running",
            "current_stage": "judge_repeatability",
            "run_directory": str(run_dir),
            "artifacts": {
                path.name: {"state": "pending", "run_id": run_id}
                for path in canonical_paths.values()
            },
            "completed_observations": 0,
            "acceptance_accessed": False,
            "full_leaf_generation_allowed": False,
        },
    )

    attempts: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    transport_attempts: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    derived_artifact: dict[str, Any] | None = None
    upstream_validated = False
    published_keys: set[str] = set()

    def persist_raw() -> None:
        _write_jsonl(run_paths["attempts"], attempts)
        _write_jsonl(run_paths["bindings"], bindings)
        _write_jsonl(run_paths["outputs"], outputs)
        _write_jsonl(run_paths["transport"], transport_attempts)

    try:
        validate_case_manifest(case_manifest)
        _validate_upstream(
            evaluator_parity=evaluator_parity,
            evaluator_parity_run_state=evaluator_parity_run_state,
            evaluator_parity_sha256=evaluator_parity_sha256,
            protocol_state=protocol_state,
            day1_run_state=day1_run_state,
            day1_artifacts=day1_artifacts,
            model_inventory=model_inventory,
            judge_probe=judge_probe,
        )
        upstream_validated = True
        if not isinstance(api_key, str) or not api_key.strip():
            raise JudgeRepeatabilityError("OPENAI_API_KEY is required")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise JudgeRepeatabilityError("timeout must be positive")
        _write_json(run_paths["manifest"], case_manifest)
        _write_json(
            protocol_state_path,
            {
                "schema_version": "plan-robust-memory.protocol-qualification-state.v1",
                "updated_at": started_at,
                "status": "in_progress",
                "qualification_sequence": list(FULL_LEAF_QUALIFICATION_SEQUENCE),
                "completed_stages": ["observability_freeze", "evaluator_parity"],
                "current_stage": "judge_repeatability",
                "next_stage": "judge_repeatability",
                "protocol_tag": None,
                "artifacts": _previous_artifacts(protocol_state),
                "acceptance_accessed": False,
                "full_leaf_generation_allowed": False,
            },
        )

        headers = {"Authorization": f"Bearer {api_key}"}
        cases = case_manifest["cases"]
        total = JUDGE_REPEATABILITY_CASE_COUNT * JUDGE_REPEATABILITY_REPLICATES
        for case in cases:
            payload, prompt = repeatability_request_payload(case)
            prompt_hash = _sha256_bytes(prompt.encode("utf-8"))
            for replicate_id in range(JUDGE_REPEATABILITY_REPLICATES):
                logical_call_id = (
                    f"judge-repeatability:{case['case_id']}:replicate-{replicate_id}"
                )
                response: Mapping[str, Any] | None = None
                response_metadata: Mapping[str, Any] | None = None
                accepted_route = ""
                accepted_retry_index = 0
                for retry_index, route in enumerate(("direct", "proxy_17897")):
                    attempt_started = now_fn()
                    status: Any = None
                    transport_id = "transport-" + stable_hash(
                        {
                            "run_id": run_id,
                            "logical_call_id": logical_call_id,
                            "retry_index": retry_index,
                            "route": route,
                        }
                    )[:20]
                    try:
                        response, response_metadata = request_fn(
                            CHAT_COMPLETIONS_URL,
                            payload,
                            headers,
                            route,
                            float(timeout),
                        )
                        if not isinstance(response, Mapping) or not isinstance(
                            response_metadata, Mapping
                        ):
                            raise JudgeRepeatabilityError(
                                "request function must return response and metadata objects"
                            )
                        status = response_metadata.get("http_status", 200)
                        if (
                            isinstance(status, bool)
                            or not isinstance(status, int)
                            or status < 200
                            or status >= 400
                        ):
                            raise OSError(f"provider returned HTTP status {status}")
                        transport_attempts.append(
                            {
                                "transport_attempt_id": transport_id,
                                "run_id": run_id,
                                "logical_call_id": logical_call_id,
                                "case_id": case["case_id"],
                                "replicate_id": replicate_id,
                                "retry_index": retry_index,
                                "route": route,
                                "scheduled_at": attempt_started,
                                "finished_at": now_fn(),
                                "status": "completed",
                                "http_status": status,
                                "request_id": response_metadata.get("request_id"),
                                "response_hash": response_metadata.get("response_hash"),
                                "error_type": None,
                                "error": None,
                            }
                        )
                        accepted_route = route
                        accepted_retry_index = retry_index
                        persist_raw()
                        break
                    except (
                        OSError,
                        TimeoutError,
                        urllib.error.URLError,
                        urllib.error.HTTPError,
                    ) as exc:
                        attempt_finished = now_fn()
                        failure_metadata = dict(response_metadata or {})
                        header_request_id = _error_request_id(exc)
                        if (
                            _observed_provider_identity(
                                failure_metadata.get("request_id")
                            )
                            is None
                            and header_request_id is not None
                        ):
                            failure_metadata["request_id"] = header_request_id
                        failure_http_status = (
                            status
                            if isinstance(status, int)
                            and not isinstance(status, bool)
                            and 100 <= status <= 599
                            else getattr(exc, "code", None)
                        )
                        if (
                            isinstance(failure_http_status, bool)
                            or not isinstance(failure_http_status, int)
                            or not 100 <= failure_http_status <= 599
                        ):
                            failure_http_status = None
                        failure_request_id = _observed_provider_identity(
                            failure_metadata.get("request_id")
                        )
                        failure_response_hash = failure_metadata.get("response_hash")
                        if (
                            not isinstance(failure_response_hash, str)
                            or not failure_response_hash.strip()
                        ):
                            failure_response_hash = None
                        transport_attempts.append(
                            {
                                "transport_attempt_id": transport_id,
                                "run_id": run_id,
                                "logical_call_id": logical_call_id,
                                "case_id": case["case_id"],
                                "replicate_id": replicate_id,
                                "retry_index": retry_index,
                                "route": route,
                                "scheduled_at": attempt_started,
                                "finished_at": attempt_finished,
                                "status": "failed",
                                "http_status": failure_http_status,
                                "request_id": failure_request_id,
                                "response_hash": failure_response_hash,
                                "error_type": type(exc).__name__,
                                "error": _redact(exc, api_key),
                            }
                        )
                        attempts.append(
                            _failed_attempt_record(
                                run_id=run_id,
                                logical_call_id=logical_call_id,
                                attempt_id=transport_id,
                                retry_index=retry_index,
                                route=route,
                                prompt=prompt,
                                response=response,
                                response_metadata=failure_metadata,
                                http_status=failure_http_status,
                                scheduled_at=attempt_started,
                                finished_at=attempt_finished,
                                failure_type=type(exc).__name__,
                            )
                        )
                        response = None
                        response_metadata = None
                        persist_raw()
                if response is None or response_metadata is None:
                    raise JudgeRepeatabilityError(
                        "judge access failed through direct and proxy_17897"
                    )

                returned_model = _observed_provider_identity(response.get("model"))
                response_text, finish_reason = _response_content(response)
                response_hash = response_metadata.get("response_hash")
                if not isinstance(response_hash, str) or not response_hash:
                    response_hash = _sha256_bytes(
                        canonical_json(dict(response)).encode("utf-8")
                    )
                request_id = _observed_provider_identity(
                    response_metadata.get("request_id")
                )
                if request_id is None:
                    request_id = _observed_provider_identity(response.get("id"))
                http_status = response_metadata.get("http_status", 200)
                if (
                    isinstance(http_status, bool)
                    or not isinstance(http_status, int)
                    or not 100 <= http_status <= 599
                ):
                    raise JudgeRepeatabilityError("provider http_status is invalid")
                attempt_id = "attempt-" + stable_hash(
                    {
                        "run_id": run_id,
                        "logical_call_id": logical_call_id,
                        "response_hash": response_hash,
                    }
                )[:20]
                output_artifact_id = "judge-output-" + stable_hash(
                    {
                        "run_id": run_id,
                        "logical_call_id": logical_call_id,
                        "response_hash": response_hash,
                    }
                )[:20]
                raw_output = {
                    "output_artifact_id": output_artifact_id,
                    "run_id": run_id,
                    "logical_call_id": logical_call_id,
                    "attempt_id": attempt_id,
                    "case_id": case["case_id"],
                    "replicate_id": replicate_id,
                    "response_text": response_text,
                    "response_content_hash": _sha256_bytes(
                        response_text.encode("utf-8")
                    ),
                    "response_hash": response_hash,
                    "raw_response": dict(response),
                    "received_at": now_fn(),
                }
                outputs.append(raw_output)

                if returned_model != PROJECT_JUDGE_MODEL or request_id is None:
                    failure_type = (
                        "returned_model_drift"
                        if returned_model != PROJECT_JUDGE_MODEL
                        else "missing_request_id"
                    )
                    attempts.append(
                        _attempt_record(
                            run_id=run_id,
                            logical_call_id=logical_call_id,
                            attempt_id=attempt_id,
                            retry_index=accepted_retry_index,
                            route=accepted_route,
                            prompt=prompt,
                            response=response,
                            response_text=response_text,
                            response_hash=response_hash,
                            request_id=request_id,
                            http_status=http_status,
                            finish_reason=finish_reason,
                            timestamp=now_fn(),
                            outcome="failed_validation",
                            parse_status="not_attempted",
                            failure_type=failure_type,
                        )
                    )
                    persist_raw()
                    if returned_model != PROJECT_JUDGE_MODEL:
                        raise JudgeRepeatabilityError(
                            f"judge returned model {returned_model!r}, expected frozen gpt-5.5"
                        )
                    raise JudgeRepeatabilityError(
                        "provider response is missing request_id"
                    )
                try:
                    label = parse_project_judge_json_label(response_text)
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    attempts.append(
                        _attempt_record(
                            run_id=run_id,
                            logical_call_id=logical_call_id,
                            attempt_id=attempt_id,
                            retry_index=accepted_retry_index,
                            route=accepted_route,
                            prompt=prompt,
                            response=response,
                            response_text=response_text,
                            response_hash=response_hash,
                            request_id=request_id,
                            http_status=http_status,
                            finish_reason=finish_reason,
                            timestamp=now_fn(),
                            outcome="failed_parse",
                            parse_status="failed",
                            failure_type="strict_json_parse_failure",
                        )
                    )
                    persist_raw()
                    raise JudgeRepeatabilityError(
                        f"judge response violated the strict JSON label contract: {exc}"
                    ) from exc

                attempt = _attempt_record(
                    run_id=run_id,
                    logical_call_id=logical_call_id,
                    attempt_id=attempt_id,
                    retry_index=accepted_retry_index,
                    route=accepted_route,
                    prompt=prompt,
                    response=response,
                    response_text=response_text,
                    response_hash=response_hash,
                    request_id=request_id,
                    http_status=http_status,
                    finish_reason=finish_reason,
                    timestamp=now_fn(),
                    outcome="accepted_materialized",
                    parse_status="passed",
                    failure_type=None,
                )
                binding = {
                    "binding_id": "binding-" + stable_hash(
                        {
                            "run_id": run_id,
                            "logical_call_id": logical_call_id,
                            "attempt_id": attempt_id,
                            "output_artifact_id": output_artifact_id,
                        }
                    )[:20],
                    "run_id": run_id,
                    "stage": "judge",
                    "logical_call_id": logical_call_id,
                    "accepted_attempt_id": attempt_id,
                    "output_artifact_id": output_artifact_id,
                    "binding_status": "succeeded",
                }
                attempts.append(attempt)
                bindings.append(binding)
                persist_raw()
                _write_json(
                    run_state_path,
                    {
                        "schema_version": RUN_STATE_SCHEMA_VERSION,
                        "run_id": run_id,
                        "run_started_at": started_at,
                        "state": "running",
                        "current_stage": "judge_repeatability",
                        "run_directory": str(run_dir),
                        "artifacts": {
                            path.name: {"state": "pending", "run_id": run_id}
                            for path in canonical_paths.values()
                        },
                        "completed_observations": len(bindings),
                        "acceptance_accessed": False,
                        "full_leaf_generation_allowed": False,
                    },
                )
                if progress_fn is not None:
                    progress_fn(len(bindings), total)

        observations = derive_repeatability_observations(
            case_manifest=case_manifest,
            attempts=attempts,
            bindings=bindings,
            outputs=outputs,
        )
        metrics = repeatability_metrics(observations)
        passed = judge_repeatability_passes(observations)
        derived_artifact = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "created_at": now_fn(),
            "run_id": run_id,
            "stage": "judge_repeatability",
            "status": "passed" if passed else "blocked",
            "judge_repeatability_passed": passed,
            "case_manifest_hash": case_manifest["manifest_hash"],
            "case_count": JUDGE_REPEATABILITY_CASE_COUNT,
            "replicate_count": JUDGE_REPEATABILITY_REPLICATES,
            "observation_count": len(observations),
            "category_counts": dict(JUDGE_REPEATABILITY_CATEGORY_COUNTS),
            "metrics": metrics,
            "thresholds": {
                "unanimity_rate_min": 0.95,
                "pairwise_flip_rate_max": 0.05,
                "parse_success_rate_required": 1.0,
            },
            "requested_model": PROJECT_JUDGE_MODEL,
            "returned_models": sorted(
                {str(row["returned_model"]) for row in observations}
            ),
            "provider": "labforge",
            "base_url": BASE_URL,
            "endpoint": CHAT_COMPLETIONS_URL,
            "message_contract": MESSAGE_CONTRACT,
            "decoding_config": dict(DECODING_CONFIG),
            "decoding_config_hash": stable_hash(DECODING_CONFIG),
            "parser_version": PARSER_VERSION,
            "output_schema_version": OUTPUT_SCHEMA_VERSION,
            "request_order": "case_manifest_order_then_replicate_0_1_2",
            "request_concurrency": 1,
            "transport_attempt_count": len(transport_attempts),
            "raw_artifacts": {
                run_paths[key].name: {
                    "path": str(run_paths[key]),
                    "sha256": _sha256_path(run_paths[key]),
                }
                for key in ("attempts", "bindings", "outputs", "transport")
            },
            "observations": observations,
            "evaluator_parity_run_id": evaluator_parity["run_id"],
            "evaluator_parity_artifact_hash": stable_hash(dict(evaluator_parity)),
            "day1_run_id": model_inventory["run_id"],
            "day1_inventory_artifact_hash": stable_hash(dict(model_inventory)),
            "day1_judge_artifact_hash": stable_hash(dict(judge_probe)),
            "source_split": SOURCE_SPLIT,
            "acceptance_accessed": False,
            "full_leaf_generation_allowed": False,
            "next_stage": "cache_qualification" if passed else "judge_repeatability",
            "interpretation_limit": (
                "Repeatability qualifies stability only; it does not establish agreement "
                "with human correctness judgments."
            ),
        }
        _write_json(run_paths["artifact"], derived_artifact)
        for key, source in run_paths.items():
            if source.exists():
                _publish_file(source, canonical_paths[key])
                published_keys.add(key)
        if not passed:
            raise JudgeRepeatabilityError(
                "judge repeatability thresholds did not pass; Cache Qualification is forbidden"
            )

        completed_at = now_fn()
        artifact_entries = {
            path.name: _artifact_entry(path, run_id)
            for path in canonical_paths.values()
        }
        _write_json(
            run_state_path,
            {
                "schema_version": RUN_STATE_SCHEMA_VERSION,
                "run_id": run_id,
                "run_started_at": started_at,
                "run_completed_at": completed_at,
                "state": "completed",
                "current_stage": None,
                "run_directory": str(run_dir),
                "artifacts": artifact_entries,
                "completed_observations": len(observations),
                "acceptance_accessed": False,
                "full_leaf_generation_allowed": False,
            },
        )
        protocol_artifacts = _previous_artifacts(protocol_state)
        protocol_artifacts.update(
            {
                "judge_repeatability": str(canonical_paths["artifact"]),
                "judge_repeatability_run_id": run_id,
                "judge_repeatability_sha256": _sha256_path(
                    canonical_paths["artifact"]
                ),
                "judge_repeatability_manifest_sha256": _sha256_path(
                    canonical_paths["manifest"]
                ),
            }
        )
        _write_json(
            protocol_state_path,
            {
                "schema_version": "plan-robust-memory.protocol-qualification-state.v1",
                "updated_at": completed_at,
                "status": "in_progress",
                "qualification_sequence": list(FULL_LEAF_QUALIFICATION_SEQUENCE),
                "completed_stages": [
                    "observability_freeze",
                    "evaluator_parity",
                    "judge_repeatability",
                ],
                "next_stage": "cache_qualification",
                "protocol_tag": None,
                "artifacts": protocol_artifacts,
                "acceptance_accessed": False,
                "full_leaf_generation_allowed": False,
            },
        )
        if stall_path.exists():
            stall_path.unlink()
        return derived_artifact
    except ContractError as exc:
        persist_raw()
        completed_at = now_fn()
        stall = {
            "schema_version": "plan-robust-memory.judge-repeatability-stall.v1",
            "created_at": completed_at,
            "run_id": run_id,
            "stage": "judge_repeatability",
            "status": "blocked",
            "reason": _redact(exc, api_key),
            "completed_observations": len(bindings),
            "transport_attempt_count": len(transport_attempts),
            "attempt_order": ["direct", "proxy_17897"],
            "run_directory": str(run_dir),
            "case_manifest_hash": case_manifest.get("manifest_hash"),
            "metrics": derived_artifact.get("metrics") if derived_artifact else None,
            "acceptance_accessed": False,
            "full_leaf_generation_allowed": False,
            "next_action": (
                "Do not enter Cache Qualification. Resolve the recorded failure and rerun "
                "the same frozen qualification command."
            ),
        }
        _write_json(stall_path, stall)
        artifact_entries: dict[str, Any] = {}
        for key, canonical_path in canonical_paths.items():
            if key in published_keys:
                artifact_entries[canonical_path.name] = _artifact_entry(
                    canonical_path, run_id, "completed_blocked"
                )
                continue
            entry: dict[str, Any] = {
                "state": "not_published_for_this_run",
                "run_id": run_id,
            }
            run_path = run_paths[key]
            if run_path.exists():
                entry["run_scoped_evidence"] = {
                    "path": str(run_path),
                    "sha256": _sha256_path(run_path),
                }
            artifact_entries[canonical_path.name] = entry
        artifact_entries[stall_path.name] = _artifact_entry(stall_path, run_id)
        _write_json(
            run_state_path,
            {
                "schema_version": RUN_STATE_SCHEMA_VERSION,
                "run_id": run_id,
                "run_started_at": started_at,
                "run_completed_at": completed_at,
                "state": "blocked",
                "current_stage": "judge_repeatability",
                "run_directory": str(run_dir),
                "artifacts": artifact_entries,
                "completed_observations": len(bindings),
                "blocking_reason": _redact(exc, api_key),
                "acceptance_accessed": False,
                "full_leaf_generation_allowed": False,
            },
        )
        if upstream_validated:
            _write_json(
                protocol_state_path,
                {
                    "schema_version": "plan-robust-memory.protocol-qualification-state.v1",
                    "updated_at": completed_at,
                    "status": "blocked",
                    "qualification_sequence": list(FULL_LEAF_QUALIFICATION_SEQUENCE),
                    "completed_stages": [
                        "observability_freeze",
                        "evaluator_parity",
                    ],
                    "current_stage": "judge_repeatability",
                    "next_stage": "judge_repeatability",
                    "protocol_tag": None,
                    "artifacts": _previous_artifacts(protocol_state),
                    "blocking_run_id": run_id,
                    "acceptance_accessed": False,
                    "full_leaf_generation_allowed": False,
                },
            )
        raise


def _load_json_object(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _require_mapping(payload, str(path))


_CANONICAL_JUDGE_ARTIFACT_NAMES = (
    "judge_repeatability_case_manifest.json",
    "judge_repeatability_attempts.jsonl",
    "judge_repeatability_output_bindings.jsonl",
    "judge_repeatability_outputs.jsonl",
    "judge_repeatability_transport_attempts.jsonl",
    "judge_repeatability.json",
)


def _write_preparing_run_state(
    *,
    output_dir: Path,
    run_id: str,
    started_at: str,
) -> Path:
    """Publish the identity before touching any qualification input artifact."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = output_dir / "judge_repeatability_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_state_path = output_dir / "judge_repeatability_run_state.json"
    artifacts = {
        name: {"state": "pending", "run_id": run_id}
        for name in _CANONICAL_JUDGE_ARTIFACT_NAMES
    }
    artifacts["judge_repeatability_stall.json"] = {
        "state": "pending",
        "run_id": run_id,
    }
    _write_json(
        run_state_path,
        {
            "schema_version": RUN_STATE_SCHEMA_VERSION,
            "run_id": run_id,
            "run_started_at": started_at,
            "state": "preparing",
            "current_stage": "preflight",
            "run_directory": str(run_dir),
            "artifacts": artifacts,
            "completed_observations": 0,
            "acceptance_accessed": False,
            "full_leaf_generation_allowed": False,
        },
    )
    return run_state_path


def _publish_preflight_block(
    *,
    output_dir: Path,
    run_id: str,
    started_at: str,
    completed_at: str,
    exc: BaseException,
    api_key: str | None,
) -> None:
    """Record a preparation failure without replacing a prior successful artifact."""
    output_dir = output_dir.resolve()
    run_dir = output_dir / "judge_repeatability_runs" / run_id
    stall_path = output_dir / "judge_repeatability_stall.json"
    reason = _redact(exc, api_key)
    _write_json(
        stall_path,
        {
            "schema_version": "plan-robust-memory.judge-repeatability-stall.v1",
            "created_at": completed_at,
            "run_id": run_id,
            "stage": "judge_repeatability",
            "failure_stage": "preflight",
            "failure_phase": "preparation",
            "status": "blocked",
            "reason": reason,
            "completed_observations": 0,
            "transport_attempt_count": 0,
            "attempt_order": [],
            "run_directory": str(run_dir),
            "case_manifest_hash": None,
            "metrics": None,
            "acceptance_accessed": False,
            "full_leaf_generation_allowed": False,
            "next_stage": "judge_repeatability",
            "next_action": (
                "Resolve the recorded preflight failure and rerun the same frozen "
                "qualification command. No judge request was sent."
            ),
        },
    )
    artifacts: dict[str, Any] = {}
    for name in _CANONICAL_JUDGE_ARTIFACT_NAMES:
        artifacts[name] = {
            "state": "not_published_for_this_run",
            "run_id": run_id,
        }
    artifacts[stall_path.name] = {
        "state": "completed",
        "run_id": run_id,
        "path": str(stall_path),
        "sha256": _sha256_path(stall_path),
    }
    _write_json(
        output_dir / "judge_repeatability_run_state.json",
        {
            "schema_version": RUN_STATE_SCHEMA_VERSION,
            "run_id": run_id,
            "run_started_at": started_at,
            "run_completed_at": completed_at,
            "state": "blocked",
            "current_stage": "preflight",
            "run_directory": str(run_dir),
            "artifacts": artifacts,
            "completed_observations": 0,
            "blocking_reason": reason,
            "acceptance_accessed": False,
            "full_leaf_generation_allowed": False,
        },
    )


def prepare_and_run_judge_repeatability(
    *,
    output_dir: Path,
    dataset_manifest_path: Path,
    calibration_artifact_path: Path,
    power_artifact_path: Path,
    evaluator_parity_path: Path,
    evaluator_parity_run_state_path: Path,
    protocol_state_path: Path,
    day1_run_state_path: Path,
    day1_dir: Path,
    api_key: str | None,
    request_fn: RequestFn = _http_json_request,
    now_fn: NowFn = _now,
    progress_fn: ProgressFn | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Prepare and execute Judge Repeatability under one auditable run identity.

    The preparation boundary intentionally accepts only the materialized Q_cal
    object. It validates all upstream provenance before handing control to the
    request runner, so input/provenance failures cannot be mistaken for an old
    aggregate artifact and cannot issue provider requests.
    """
    output_dir = output_dir.resolve()
    run_id = f"judge-repeatability-{uuid.uuid4().hex}"
    started_at = now_fn()
    _write_preparing_run_state(
        output_dir=output_dir,
        run_id=run_id,
        started_at=started_at,
    )
    try:
        audit = _load_json_object(dataset_manifest_path)
        power_artifact = _load_json_object(power_artifact_path)
        calibration_artifact = _load_json_object(calibration_artifact_path)
        validate_calibration_split_artifact(
            calibration_artifact,
            audit=audit,
            power_artifact=power_artifact,
        )
        episodes = calibration_artifact.get("episodes")
        if not isinstance(episodes, list):
            raise JudgeRepeatabilityError(
                "calibration artifact episodes must be an array"
            )
        manifest = build_case_manifest(
            audit=audit,
            power_artifact=power_artifact,
            normalized_episodes=episodes,
        )
        evaluator_parity_bytes = evaluator_parity_path.read_bytes()
        evaluator_parity = _require_mapping(
            json.loads(evaluator_parity_bytes), str(evaluator_parity_path)
        )
        evaluator_parity_sha256 = _sha256_bytes(evaluator_parity_bytes)
        evaluator_parity_run_state = _load_json_object(
            evaluator_parity_run_state_path
        )
        protocol_state = _load_json_object(protocol_state_path)
        day1_run_state = _load_json_object(day1_run_state_path)
        day1_artifacts = {
            name: _load_json_object(day1_dir / name)
            for name in sorted(_DAY1_ARTIFACT_NAMES)
        }
        model_inventory = day1_artifacts["model_inventory.json"]
        judge_probe = day1_artifacts["judge_probe.json"]
        validate_case_manifest(manifest)
        _validate_day1_file_checksums(
            day1_dir=day1_dir,
            day1_run_state=day1_run_state,
        )
        _validate_upstream(
            evaluator_parity=evaluator_parity,
            evaluator_parity_run_state=evaluator_parity_run_state,
            evaluator_parity_sha256=evaluator_parity_sha256,
            protocol_state=protocol_state,
            day1_run_state=day1_run_state,
            day1_artifacts=day1_artifacts,
            model_inventory=model_inventory,
            judge_probe=judge_probe,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ContractError) as exc:
        recorded_exc: BaseException = exc
        if isinstance(exc, json.JSONDecodeError):
            recorded_exc = JudgeRepeatabilityError(
                f"input artifact must contain valid JSON: {exc}"
            )
        _publish_preflight_block(
            output_dir=output_dir,
            run_id=run_id,
            started_at=started_at,
            completed_at=now_fn(),
            exc=recorded_exc,
            api_key=api_key,
        )
        raise JudgeRepeatabilityError(
            "Judge Repeatability preflight failed: "
            f"{_redact(recorded_exc, api_key)}"
        ) from exc

    return run_judge_repeatability(
        output_dir=output_dir,
        case_manifest=manifest,
        evaluator_parity=evaluator_parity,
        evaluator_parity_run_state=evaluator_parity_run_state,
        evaluator_parity_sha256=evaluator_parity_sha256,
        protocol_state=protocol_state,
        day1_run_state=day1_run_state,
        day1_artifacts=day1_artifacts,
        model_inventory=model_inventory,
        judge_probe=judge_probe,
        api_key=api_key,
        request_fn=request_fn,
        now_fn=now_fn,
        progress_fn=progress_fn,
        timeout=timeout,
        run_id=run_id,
        started_at=started_at,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the frozen calibration-only 50 x 3 project-judge repeatability Gate"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/qualification")
    )
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=Path("artifacts/longmemeval/dataset_manifest.json"),
    )
    parser.add_argument(
        "--calibration-artifact",
        type=Path,
        default=Path(
            "artifacts/longmemeval/normalized_calibration_20_30_50.json"
        ),
        help="Materialized calibration-only Q_cal artifact; combined stores are not accepted",
    )
    parser.add_argument(
        "--power-artifact",
        type=Path,
        default=Path("artifacts/power/power_feasibility.json"),
    )
    parser.add_argument(
        "--evaluator-parity",
        type=Path,
        default=Path("artifacts/qualification/evaluator_parity.json"),
    )
    parser.add_argument(
        "--protocol-state",
        type=Path,
        default=Path("artifacts/qualification/protocol_qualification_state.json"),
    )
    parser.add_argument(
        "--evaluator-parity-run-state",
        type=Path,
        default=Path("artifacts/qualification/evaluator_parity_run_state.json"),
    )
    parser.add_argument(
        "--day1-dir",
        type=Path,
        default=Path("artifacts/day1"),
        help="Completed Day 1 artifact directory containing all eight probes",
    )
    parser.add_argument(
        "--day1-run-state",
        type=Path,
        default=Path("artifacts/day1/day1_run_state.json"),
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)

    def progress(completed: int, total: int) -> None:
        if completed == total or completed % 10 == 0:
            print(
                json.dumps(
                    {
                        "stage": "judge_repeatability",
                        "completed_observations": completed,
                        "total_observations": total,
                    }
                ),
                file=sys.stderr,
                flush=True,
            )

    try:
        artifact = prepare_and_run_judge_repeatability(
            output_dir=args.output_dir,
            dataset_manifest_path=args.dataset_manifest,
            calibration_artifact_path=args.calibration_artifact,
            power_artifact_path=args.power_artifact,
            evaluator_parity_path=args.evaluator_parity,
            evaluator_parity_run_state_path=args.evaluator_parity_run_state,
            protocol_state_path=args.protocol_state,
            day1_run_state_path=args.day1_run_state,
            day1_dir=args.day1_dir,
            api_key=os.environ.get("OPENAI_API_KEY"),
            request_fn=_http_json_request,
            now_fn=_now,
            progress_fn=progress,
            timeout=args.timeout,
        )
    except ContractError as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": str(exc),
                    "next_stage": "judge_repeatability",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "run_id": artifact["run_id"],
                "metrics": artifact["metrics"],
                "next_stage": artifact["next_stage"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
