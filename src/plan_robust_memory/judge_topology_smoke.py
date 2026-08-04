from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
import sys
from typing import Any
import urllib.error
import uuid

from .contracts import ContractError
from .evaluator import parse_project_judge_json_label, project_judge_prompt
from .hashing import canonical_json, stable_hash
from .qualify_judge_repeatability import (
    CHAT_COMPLETIONS_URL,
    DECODING_CONFIG,
    LOCAL_TOKENIZER_SNAPSHOT,
    MESSAGE_CONTRACT,
    PROJECT_JUDGE_MODEL,
    SERIALIZATION_VERSION,
    JudgeRepeatabilityError,
    _attempt_record,
    _failed_attempt_record,
    _http_json_request,
    _now,
    _observed_provider_identity,
    _redact,
    _response_content,
    _sha256_bytes,
)
from .observability import validate_accepted_output_bindings


SMOKE_SCHEMA_VERSION = "plan-robust-memory.judge-topology-smoke.v1"
OUTPUT_NAME = "judge_topology_smoke.json"
RUN_DIR_NAME = "judge_topology_smoke_runs"
SMOKE_TOPOLOGIES = ("left_deep_smoke", "canonical_balanced_smoke")

RequestFn = Callable[
    [str, dict[str, Any], dict[str, str], str, float],
    tuple[Mapping[str, Any], Mapping[str, Any]],
]
NowFn = Callable[[], str]


class JudgeTopologySmokeError(ContractError):
    """Raised when the calibration-only judge topology smoke cannot complete."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_json_object(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise JudgeTopologySmokeError(f"{path} must contain a JSON object")
    return value


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JudgeTopologySmokeError(f"{field} must be a non-empty string")
    return value


def _eligible_calibration_episodes(
    artifact: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], int, int]:
    if artifact.get("source_split") != "calibration":
        raise JudgeTopologySmokeError("judge topology smoke is calibration-only")
    if artifact.get("acceptance_payload_exported") is not False:
        raise JudgeTopologySmokeError("calibration artifact must not export acceptance payload")
    episodes = artifact.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        raise JudgeTopologySmokeError("calibration artifact episodes must be non-empty")
    result: list[Mapping[str, Any]] = []
    for raw_episode in episodes:
        if not isinstance(raw_episode, Mapping):
            continue
        query = raw_episode.get("query")
        if not isinstance(query, Mapping):
            continue
        try:
            _require_text(raw_episode.get("episode_id"), "episode_id")
            _require_text(raw_episode.get("question_type"), "question_type")
            _require_text(query.get("query_id"), "query_id")
            _require_text(query.get("question_text"), "question_text")
            _require_text(query.get("gold_answer"), "gold_answer")
        except JudgeTopologySmokeError:
            continue
        result.append(raw_episode)
    if not result:
        raise JudgeTopologySmokeError("no answerable calibration episodes are available")
    return result, len(episodes), len(episodes) - len(result)


def _selected_episodes(
    episodes: Iterable[Mapping[str, Any]], *, case_count: int
) -> list[Mapping[str, Any]]:
    if isinstance(case_count, bool) or case_count <= 0:
        raise JudgeTopologySmokeError("case_count must be positive")
    ordered = sorted(episodes, key=lambda episode: str(episode["episode_id"]))
    if len(ordered) < case_count:
        raise JudgeTopologySmokeError("not enough calibration episodes for smoke case_count")
    return ordered[:case_count]


def _candidate_rows(episode: Mapping[str, Any], index: int) -> list[dict[str, Any]]:
    query = episode["query"]
    reference = str(query["gold_answer"])
    wrong = "UNRELATED_TO_REFERENCE: This candidate omits the reference answer."
    case_id = "smoke-" + stable_hash(
        {"episode_id": episode["episode_id"], "query_id": query["query_id"], "index": index}
    )[:20]
    base = {
        "case_id": case_id,
        "episode_id": episode["episode_id"],
        "query_id": query["query_id"],
        "question_type": episode["question_type"],
        "question": query["question_text"],
        "reference_answer": reference,
        "abstention": False,
    }
    return [
        {
            **base,
            "topology_id": "left_deep_smoke",
            "candidate_answer": wrong,
            "expected_label": 0,
        },
        {
            **base,
            "topology_id": "canonical_balanced_smoke",
            "candidate_answer": reference,
            "expected_label": 1,
        },
    ]


def _request_payload(row: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    prompt = project_judge_prompt(
        str(row["question_type"]),
        str(row["question"]),
        str(row["reference_answer"]),
        str(row["candidate_answer"]),
        abstention=bool(row["abstention"]),
    )
    payload = {
        "model": PROJECT_JUDGE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        **DECODING_CONFIG,
    }
    _validate_pure_chat_payload(payload)
    return payload, prompt


def _validate_pure_chat_payload(payload: Mapping[str, Any]) -> None:
    if payload.get("model") != PROJECT_JUDGE_MODEL:
        raise JudgeTopologySmokeError("judge smoke model drifted")
    if "response_format" in payload:
        raise JudgeTopologySmokeError("judge smoke must not send response_format")
    messages = payload.get("messages")
    if not isinstance(messages, list) or len(messages) != 1:
        raise JudgeTopologySmokeError("judge smoke must send exactly one user message")
    message = messages[0]
    if not isinstance(message, Mapping) or message.get("role") != "user":
        raise JudgeTopologySmokeError("judge smoke must send exactly one user message")
    if not isinstance(message.get("content"), str) or not message["content"]:
        raise JudgeTopologySmokeError("judge smoke user content must be non-empty")
    roles = {item.get("role") for item in messages if isinstance(item, Mapping)}
    if roles != {"user"}:
        raise JudgeTopologySmokeError("judge smoke must not inject system/developer roles")
    if payload.get("stream") is not False:
        raise JudgeTopologySmokeError("judge smoke must be non-streaming")


def _artifact_entry(
    *,
    run_id: str,
    started_at: str,
    status: str,
    cases: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    transport_attempts: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    source_episode_count: int,
    eligible_episode_count: int,
    skipped_episode_count: int,
    reason: str | None = None,
) -> dict[str, Any]:
    accepted = [row for row in observations if row["parse_success"]]
    by_case: dict[str, dict[str, int]] = {}
    for row in accepted:
        by_case.setdefault(row["case_id"], {})[row["topology_id"]] = int(row["label"])
    paired_effects = [
        values["canonical_balanced_smoke"] - values["left_deep_smoke"]
        for values in by_case.values()
        if set(values) == set(SMOKE_TOPOLOGIES)
    ]
    paired_effect = (
        sum(paired_effects) / len(paired_effects) if paired_effects else "unavailable"
    )
    return {
        "schema_version": SMOKE_SCHEMA_VERSION,
        "run_id": run_id,
        "run_started_at": started_at,
        "status": status,
        "stage": "judge_topology_smoke",
        "source_split": "calibration",
        "source_episode_count": source_episode_count,
        "eligible_episode_count": eligible_episode_count,
        "skipped_episode_count": skipped_episode_count,
        "case_count": len({row["case_id"] for row in cases}),
        "candidate_pair_count": len({row["case_id"] for row in cases}),
        "candidate_observation_count": len(observations),
        "request_contract": {
            "endpoint": CHAT_COMPLETIONS_URL,
            "model": PROJECT_JUDGE_MODEL,
            "message_contract": MESSAGE_CONTRACT,
            "messages_per_request": 1,
            "allowed_roles": ["user"],
            "forbidden_roles_absent": True,
            "response_format_sent": False,
            "decoding_config": dict(DECODING_CONFIG),
        },
        "cases": [
            {
                "case_id": row["case_id"],
                "episode_id": row["episode_id"],
                "query_id": row["query_id"],
                "question_type": row["question_type"],
                "topology_id": row["topology_id"],
                "expected_label": row["expected_label"],
                "question_hash": _sha256_bytes(str(row["question"]).encode("utf-8")),
                "reference_answer_hash": _sha256_bytes(
                    str(row["reference_answer"]).encode("utf-8")
                ),
                "candidate_answer_hash": _sha256_bytes(
                    str(row["candidate_answer"]).encode("utf-8")
                ),
            }
            for row in cases
        ],
        "attempts": attempts,
        "bindings": bindings,
        "outputs": outputs,
        "transport_attempts": transport_attempts,
        "observations": observations,
        "summary": {
            "parse_success_count": sum(row["parse_success"] for row in observations),
            "accepted_observation_count": len(accepted),
            "paired_effect_proxy": paired_effect,
            "topology_effect_proxy_observed": any(effect != 0 for effect in paired_effects),
        },
        "reason": reason,
        "acceptance_accessed": False,
        "full_leaf_generation_allowed": False,
        "next_stage": "judge_repeatability",
        "interpretation_limit": "diagnostic_smoke_not_gate",
        "warning": (
            "Synthetic calibration-only paired candidates. This is not Judge "
            "Repeatability, not a formal topology result, and not authorization "
            "for Cache Qualification or Full Leaves."
        ),
    }


def run_judge_topology_smoke(
    *,
    calibration_artifact: Mapping[str, Any],
    output_dir: Path,
    api_key: str | None,
    case_count: int = 1,
    request_fn: RequestFn = _http_json_request,
    now_fn: NowFn = _now,
    timeout: float = 120.0,
    run_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(api_key, str) or not api_key.strip():
        raise JudgeTopologySmokeError("OPENAI_API_KEY is required")
    eligible_episodes, source_episode_count, skipped_episode_count = (
        _eligible_calibration_episodes(calibration_artifact)
    )
    episodes = _selected_episodes(eligible_episodes, case_count=case_count)
    run_id = run_id or f"judge-topology-smoke-{uuid.uuid4().hex}"
    started_at = now_fn()
    output_dir = output_dir.resolve()
    run_dir = output_dir / RUN_DIR_NAME / run_id
    artifact_path = run_dir / OUTPUT_NAME
    canonical_path = output_dir / OUTPUT_NAME
    headers = {"Authorization": f"Bearer {api_key}"}

    cases = [row for index, episode in enumerate(episodes) for row in _candidate_rows(episode, index)]
    attempts: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    transport_attempts: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []

    def publish(status: str, reason: str | None = None) -> dict[str, Any]:
        artifact = _artifact_entry(
            run_id=run_id,
            started_at=started_at,
            status=status,
            cases=cases,
            attempts=attempts,
            bindings=bindings,
            outputs=outputs,
            transport_attempts=transport_attempts,
            observations=observations,
            source_episode_count=source_episode_count,
            eligible_episode_count=len(eligible_episodes),
            skipped_episode_count=skipped_episode_count,
            reason=reason,
        )
        _write_json(artifact_path, artifact)
        _write_json(canonical_path, artifact)
        return artifact

    try:
        for row in cases:
            payload, prompt = _request_payload(row)
            response: Mapping[str, Any] | None = None
            response_metadata: Mapping[str, Any] | None = None
            accepted_route = ""
            accepted_retry_index = 0
            logical_call_id = (
                f"judge-topology-smoke:{row['case_id']}:{row['topology_id']}"
            )
            for retry_index, route in enumerate(("direct", "proxy_17897")):
                attempt_started = now_fn()
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
                        raise JudgeTopologySmokeError(
                            "request function must return response and metadata objects"
                        )
                    http_status = response_metadata.get("http_status", 200)
                    if (
                        isinstance(http_status, bool)
                        or not isinstance(http_status, int)
                        or http_status < 200
                        or http_status >= 400
                    ):
                        raise OSError(f"provider returned HTTP status {http_status}")
                    transport_attempts.append(
                        {
                            "transport_attempt_id": transport_id,
                            "run_id": run_id,
                            "logical_call_id": logical_call_id,
                            "retry_index": retry_index,
                            "route": route,
                            "scheduled_at": attempt_started,
                            "finished_at": now_fn(),
                            "status": "completed",
                            "http_status": http_status,
                            "request_id": _observed_provider_identity(
                                response_metadata.get("request_id")
                            ),
                            "response_hash": response_metadata.get("response_hash"),
                            "error_type": None,
                            "error": None,
                        }
                    )
                    accepted_route = route
                    accepted_retry_index = retry_index
                    break
                except (
                    OSError,
                    TimeoutError,
                    urllib.error.URLError,
                    urllib.error.HTTPError,
                ) as exc:
                    attempt_finished = now_fn()
                    transport_attempts.append(
                        {
                            "transport_attempt_id": transport_id,
                            "run_id": run_id,
                            "logical_call_id": logical_call_id,
                            "retry_index": retry_index,
                            "route": route,
                            "scheduled_at": attempt_started,
                            "finished_at": attempt_finished,
                            "status": "failed",
                            "http_status": getattr(exc, "code", None),
                            "request_id": None,
                            "response_hash": None,
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
                            response_metadata=response_metadata,
                            http_status=getattr(exc, "code", None),
                            scheduled_at=attempt_started,
                            finished_at=attempt_finished,
                            failure_type=type(exc).__name__,
                        )
                    )
                    response = None
                    response_metadata = None
            if response is None or response_metadata is None:
                raise JudgeTopologySmokeError(
                    "judge smoke access failed through direct and proxy_17897"
                )

            response_text, finish_reason = _response_content(response)
            response_hash = response_metadata.get("response_hash")
            if not isinstance(response_hash, str) or not response_hash:
                response_hash = _sha256_bytes(canonical_json(dict(response)).encode("utf-8"))
            returned_model = _observed_provider_identity(response.get("model"))
            request_id = _observed_provider_identity(response_metadata.get("request_id"))
            if request_id is None:
                request_id = _observed_provider_identity(response.get("id"))
            attempt_id = "attempt-" + stable_hash(
                {
                    "run_id": run_id,
                    "logical_call_id": logical_call_id,
                    "response_hash": response_hash,
                }
            )[:20]
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
                        http_status=int(response_metadata.get("http_status", 200)),
                        finish_reason=finish_reason,
                        timestamp=now_fn(),
                        outcome="failed_validation",
                        parse_status="not_attempted",
                        failure_type=failure_type,
                    )
                )
                raise JudgeTopologySmokeError(failure_type)
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
                        http_status=int(response_metadata.get("http_status", 200)),
                        finish_reason=finish_reason,
                        timestamp=now_fn(),
                        outcome="failed_parse",
                        parse_status="failed",
                        failure_type="strict_json_parse_failure",
                    )
                )
                raise JudgeTopologySmokeError(f"strict JSON parse failure: {exc}") from exc

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
                http_status=int(response_metadata.get("http_status", 200)),
                finish_reason=finish_reason,
                timestamp=now_fn(),
                outcome="accepted_materialized",
                parse_status="passed",
                failure_type=None,
            )
            attempts.append(attempt)
            output_artifact_id = "judge-smoke-output-" + stable_hash(
                {
                    "run_id": run_id,
                    "logical_call_id": logical_call_id,
                    "response_hash": response_hash,
                }
            )[:20]
            binding_id = "binding-" + stable_hash(
                {
                    "run_id": run_id,
                    "logical_call_id": logical_call_id,
                    "attempt_id": attempt_id,
                    "output_artifact_id": output_artifact_id,
                }
            )[:20]
            bindings.append(
                {
                    "binding_id": binding_id,
                    "run_id": run_id,
                    "stage": "judge",
                    "logical_call_id": logical_call_id,
                    "accepted_attempt_id": attempt_id,
                    "output_artifact_id": output_artifact_id,
                    "binding_status": "succeeded",
                }
            )
            outputs.append(
                {
                    "output_artifact_id": output_artifact_id,
                    "run_id": run_id,
                    "logical_call_id": logical_call_id,
                    "attempt_id": attempt_id,
                    "case_id": row["case_id"],
                    "topology_id": row["topology_id"],
                    "response_text": response_text,
                    "response_content_hash": _sha256_bytes(response_text.encode("utf-8")),
                    "response_hash": response_hash,
                    "raw_response": dict(response),
                    "received_at": now_fn(),
                }
            )
            observations.append(
                {
                    "case_id": row["case_id"],
                    "episode_id": row["episode_id"],
                    "query_id": row["query_id"],
                    "topology_id": row["topology_id"],
                    "expected_label": row["expected_label"],
                    "label": label,
                    "parse_success": True,
                    "attempt_id": attempt_id,
                    "binding_id": binding_id,
                    "output_artifact_id": output_artifact_id,
                    "requested_model": PROJECT_JUDGE_MODEL,
                    "returned_model": returned_model,
                    "provider_route": accepted_route,
                    "prompt_hash": attempt["prompt_hash"],
                }
            )
        validate_accepted_output_bindings(attempts, bindings)
        return publish("completed")
    except ContractError as exc:
        artifact = publish("blocked", _redact(exc, api_key))
        raise JudgeTopologySmokeError(str(exc)) from exc


def prepare_and_run_judge_topology_smoke(
    *,
    calibration_artifact_path: Path,
    output_dir: Path,
    api_key: str | None,
    case_count: int,
    request_fn: RequestFn = _http_json_request,
    now_fn: NowFn = _now,
    timeout: float = 120.0,
) -> dict[str, Any]:
    return run_judge_topology_smoke(
        calibration_artifact=_load_json_object(calibration_artifact_path),
        output_dir=output_dir,
        api_key=api_key,
        case_count=case_count,
        request_fn=request_fn,
        now_fn=now_fn,
        timeout=timeout,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a calibration-only project-judge topology-effect smoke diagnostic"
    )
    parser.add_argument(
        "--calibration-artifact",
        type=Path,
        default=Path("artifacts/longmemeval/normalized_calibration_20_30_50.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/qualification"),
    )
    parser.add_argument("--case-count", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LABFORGE_API_KEY")
    try:
        artifact = prepare_and_run_judge_topology_smoke(
            calibration_artifact_path=args.calibration_artifact,
            output_dir=args.output_dir,
            api_key=api_key,
            case_count=args.case_count,
            request_fn=_http_json_request,
            now_fn=_now,
            timeout=args.timeout,
        )
    except (OSError, json.JSONDecodeError, ContractError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "stage": "judge_topology_smoke",
                    "reason": str(exc),
                    "next_stage": "judge_repeatability",
                    "full_leaf_generation_allowed": False,
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
                "candidate_pair_count": artifact["candidate_pair_count"],
                "summary": artifact["summary"],
                "artifact": str((args.output_dir / OUTPUT_NAME).resolve()),
                "next_stage": artifact["next_stage"],
                "full_leaf_generation_allowed": artifact["full_leaf_generation_allowed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
