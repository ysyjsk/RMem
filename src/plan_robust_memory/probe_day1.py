from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .hashing import stable_hash


ARTIFACT_NAMES = (
    "proxy_probe.json",
    "model_inventory.json",
    "primary_115k_probe.json",
    "primary_output_probe.json",
    "judge_probe.json",
    "replication_model_probe.json",
    "embedding_probe.json",
    "cost_upper_bound.json",
)
RUN_STATE_NAME = "day1_run_state.json"
DEFAULT_BASE_URL = "https://api.labforge.cc/v1"
CHAT_COMPLETIONS_PATH = "/chat/completions"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HF_HUB_CACHE = REPOSITORY_ROOT / "cache" / "huggingface" / "hub"
PRIMARY_MODEL = "gpt-5.6-sol"
JUDGE_MODEL = "gpt-5.5"
BGE_M3_MODEL = "BAAI/bge-m3"
BGE_M3_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
BGE_M3_EMBEDDING_DIMENSION = 1024
BGE_M3_MAX_SEQUENCE_LENGTH = 8192
EMBEDDING_PROBE_PACK_BUDGET_TOKENS = 4096
HUGGINGFACE_PROBE_URL = "https://huggingface.co"
PROXY_URL = "http://127.0.0.1:17897"
DEFAULT_LONGMEMEVAL_RAW_PATH = Path("data/raw/longmemeval-cleaned/longmemeval_s_cleaned.json")
DEFAULT_LONGMEMEVAL_NORMALIZED_PATH = Path("artifacts/longmemeval/normalized_episodes.json")
DEFAULT_LONGMEMEVAL_MANIFEST_PATH = Path("artifacts/longmemeval/dataset_manifest.json")
LONGMEMEVAL_CLEANED_FILENAME = "longmemeval_s_cleaned.json"
PRIMARY_CONTEXT_SENTINEL_PREFIX = "PLAN_ROBUST_MEMORY_115K_END_SENTINEL"
PRIMARY_CONCURRENCY_LEVELS = (1, 2, 4)
PRIMARY_REQUIRED_SUCCESSES = 5
PRIMARY_INPUT_TOKEN_TARGET = 115_000
PRIMARY_INPUT_TOKEN_TOLERANCE = 10_000
PRIMARY_P95_LATENCY_LIMIT_SECONDS = 180.0
REQUIRED_COST_COMPONENTS = ("primary", "replication", "SATURATION", "D_leaf", "future_k_sweep")
RequestFn = Callable[..., tuple[dict[str, Any], dict[str, Any]]]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            Path(temporary_name).unlink()
        except FileNotFoundError:
            pass


def inspect_day1_run(output_dir: Path) -> dict[str, Any]:
    """Classify published Day 1 evidence without trusting filenames or mtimes."""

    output_dir = output_dir.resolve()
    state_path = output_dir / RUN_STATE_NAME
    if not state_path.exists():
        return {
            "evidence_status": "unknown",
            "reason": "missing_run_state",
            "output_dir": str(output_dir),
        }
    try:
        run_state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "evidence_status": "unknown",
            "reason": "invalid_run_state",
            "output_dir": str(output_dir),
        }
    run_id = run_state.get("run_id")
    if run_state.get("state") != "completed" or not run_id:
        return {
            "evidence_status": "unknown",
            "reason": "run_not_completed",
            "run_id": run_id,
            "run_state": run_state.get("state"),
            "output_dir": str(output_dir),
        }

    missing: list[str] = []
    mismatched: list[str] = []
    nonterminal: list[str] = []
    artifact_statuses: dict[str, Any] = {}
    for name in ARTIFACT_NAMES:
        path = output_dir / name
        if not path.exists():
            missing.append(name)
            continue
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            nonterminal.append(name)
            continue
        if artifact.get("run_id") != run_id:
            mismatched.append(name)
        if artifact.get("artifact_state") != "completed":
            nonterminal.append(name)
        artifact_statuses[name] = artifact.get("status")
    if missing or mismatched or nonterminal:
        return {
            "evidence_status": "unknown",
            "reason": "artifact_set_not_coherent",
            "run_id": run_id,
            "missing_artifacts": missing,
            "mismatched_run_id_artifacts": mismatched,
            "nonterminal_artifacts": nonterminal,
            "output_dir": str(output_dir),
        }
    return {
        "evidence_status": "verified",
        "run_id": run_id,
        "status": run_state.get("status"),
        "artifact_statuses": artifact_statuses,
        "output_dir": str(output_dir),
    }


def http_json_request(
    url: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    route: str = "direct",
    timeout: float = 300.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    proxy_handler = urllib.request.ProxyHandler({} if route == "direct" else {"http": PROXY_URL, "https": PROXY_URL})
    opener = urllib.request.build_opener(proxy_handler)
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {"Content-Type": "application/json", "User-Agent": "plan-robust-memory-day1/1.0", **dict(headers or {})}
    request = urllib.request.Request(url, data=body, method=method, headers=request_headers)
    started = time.monotonic()
    with opener.open(request, timeout=timeout) as response:
        first_byte = b"" if method == "HEAD" else response.read(1)
        ttft_seconds = round(time.monotonic() - started, 3)
        raw = first_byte + (b"" if method == "HEAD" else response.read())
        status = int(getattr(response, "status", 200))
        response_headers = {key.lower(): value for key, value in response.headers.items()}
    if method == "HEAD":
        parsed: Any = {}
    else:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"non-JSON response status={status} body_hash={_sha256_bytes(raw)}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("JSON response must be an object")
    metadata = {
        "status": status,
        "route": route,
        "request_id": response_headers.get("x-request-id") or parsed.get("id"),
        "ttft_seconds": ttft_seconds,
        "ttft_definition": "time_to_first_response_body_byte_non_streaming",
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "response_sha256": _sha256_bytes(raw),
        "response_hash": _sha256_bytes(raw),
    }
    return parsed, metadata


def _error_attempt(route: str, url: str, exc: Exception, elapsed: float) -> dict[str, Any]:
    raw_error_body: bytes | None = None
    if isinstance(exc, urllib.error.HTTPError):
        try:
            raw_error_body = exc.read()
        except Exception:
            raw_error_body = None
    return {
        "route": route,
        "url": url,
        "success": False,
        "http_status": exc.code if isinstance(exc, urllib.error.HTTPError) else None,
        "elapsed_seconds": round(elapsed, 3),
        "error_type": type(exc).__name__,
        "error": str(exc)[:500],
        "response_hash": _sha256_bytes(raw_error_body) if raw_error_body is not None else None,
        "response_body_bytes": len(raw_error_body) if raw_error_body is not None else None,
    }


def request_with_fallback(
    request_fn: RequestFn,
    url: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 300.0,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for route in ("direct", "proxy_17897"):
        started = time.monotonic()
        try:
            response, metadata = request_fn(url, method=method, payload=payload, headers=headers, route=route, timeout=timeout)
            status = int(metadata.get("status", 0))
            attempt = {"route": route, "url": url, "success": 200 <= status < 300, "http_status": status, **metadata}
            attempts.append(attempt)
            if attempt["success"]:
                return response, attempts
        except Exception as exc:
            attempts.append(_error_attempt(route, url, exc, time.monotonic() - started))
    return None, attempts


def probe_huggingface_connectivity(
    *, request_fn: RequestFn = http_json_request, timeout: float = 15.0
) -> dict[str, Any]:
    response, attempts = request_with_fallback(
        request_fn,
        HUGGINGFACE_PROBE_URL,
        method="HEAD",
        timeout=timeout,
    )
    successful_route = None
    if response is not None and attempts:
        successful_route = attempts[-1].get("route")
    return {
        "schema_version": "plan-robust-memory.proxy-probe.v2",
        "created_at": _now(),
        "status": "passed" if response is not None else "blocked",
        "target": HUGGINGFACE_PROBE_URL,
        "proxy_url": PROXY_URL,
        "attempt_order": ["direct", "proxy_17897"],
        "successful_route": successful_route,
        "attempts": attempts,
    }


def _usage(response: Mapping[str, Any] | None) -> dict[str, int | None]:
    usage = response.get("usage", {}) if isinstance(response, Mapping) else {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens")) if isinstance(usage, Mapping) else None
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens")) if isinstance(usage, Mapping) else None
    return {"input_tokens": int(input_tokens) if isinstance(input_tokens, (int, float)) else None, "output_tokens": int(output_tokens) if isinstance(output_tokens, (int, float)) else None}


def _usage_available(response: Mapping[str, Any] | None) -> bool:
    usage = _usage(response)
    return usage["input_tokens"] is not None and usage["output_tokens"] is not None


def _response_hash(attempt: Mapping[str, Any] | None) -> str | None:
    if not isinstance(attempt, Mapping):
        return None
    value = attempt.get("response_hash") or attempt.get("response_sha256")
    return str(value) if isinstance(value, str) else None


def _response_text(response: Mapping[str, Any] | None) -> str | None:
    if not isinstance(response, Mapping):
        return None
    output_text = response.get("output_text")
    if isinstance(output_text, str):
        return output_text
    output = response.get("output")
    if isinstance(output, Sequence) and not isinstance(output, (str, bytes)):
        texts: list[str] = []
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
                for part in content:
                    if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                        texts.append(str(part["text"]))
            elif isinstance(item.get("text"), str):
                texts.append(str(item["text"]))
        if texts:
            return "".join(texts)
    choices = response.get("choices")
    if isinstance(choices, Sequence) and choices and isinstance(choices[0], Mapping):
        message = choices[0].get("message")
        if isinstance(message, Mapping) and isinstance(message.get("content"), str):
            return str(message["content"])
    return None


def _contains_context_length_error(attempts: Sequence[Mapping[str, Any]], response: Mapping[str, Any] | None) -> bool:
    haystack = " ".join(str(row.get("error", "")) for row in attempts)
    if isinstance(response, Mapping) and isinstance(response.get("error"), Mapping):
        haystack += " " + str(response["error"].get("message", ""))
    lowered = haystack.lower()
    return "context" in lowered and any(token in lowered for token in ("length", "window", "maximum", "too long"))


def _p95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _chat_payload(
    *,
    model: str,
    user_content: str,
    max_tokens: int,
    temperature: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": user_content}],
        "max_tokens": max_tokens,
        "stream": False,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    return payload


def _model_probe(
    *,
    request_fn: RequestFn,
    base_url: str,
    headers: Mapping[str, str],
    model: str,
    input_text: str,
    max_output_tokens: int,
    repetitions: int,
    timeout: float,
    role: str,
) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    last_response: Mapping[str, Any] | None = None
    all_attempts: list[dict[str, Any]] = []
    for index in range(repetitions):
        payload = _chat_payload(
            model=model,
            user_content=input_text,
            max_tokens=max_output_tokens,
        )
        response, attempts = request_with_fallback(
            request_fn,
            f"{base_url}{CHAT_COMPLETIONS_PATH}",
            method="POST",
            payload=payload,
            headers=headers,
            timeout=timeout,
        )
        all_attempts.extend({**attempt, "call_index": index} for attempt in attempts)
        success = response is not None
        last_response = response or last_response
        final_attempt = attempts[-1] if attempts else {}
        calls.append(
            {
                "call_index": index,
                "success": success,
                "requested_model": model,
                "returned_model": response.get("model") if response else None,
                "request_id": final_attempt.get("request_id"),
                "route": final_attempt.get("route"),
                "response_hash": _response_hash(final_attempt),
                "usage": _usage(response),
                "usage_available": _usage_available(response),
                "ttft_seconds": final_attempt.get("ttft_seconds"),
                "latency_seconds": final_attempt.get("elapsed_seconds"),
                "http_status": final_attempt.get("http_status", final_attempt.get("status")),
                "retry_count": max(0, len(attempts) - 1),
                "context_length_error": _contains_context_length_error(attempts, response),
            }
        )
    latencies = sorted(float(row["latency_seconds"]) for row in calls if isinstance(row.get("latency_seconds"), (int, float)))
    p95 = latencies[min(len(latencies) - 1, round(0.95 * (len(latencies) - 1)))] if latencies else None
    successes = sum(bool(row["success"]) for row in calls)
    return {
        "schema_version": "plan-robust-memory.day1-probe.v1",
        "created_at": _now(),
        "status": "passed" if successes == repetitions else "blocked",
        "role": role,
        "requested_model": model,
        "returned_model": last_response.get("model") if last_response else None,
        "base_url": base_url,
        "endpoint": f"{base_url}{CHAT_COMPLETIONS_PATH}",
        "request_protocol": "openai_compatible_chat_completions",
        "message_contract": "exactly_one_user_message_no_system_or_developer_message",
        "requested_max_tokens": max_output_tokens,
        "max_output_tokens": max_output_tokens,
        "requested_input_token_target": 115000 if len(input_text) > 100000 else None,
        "success_count": successes,
        "required_success_count": repetitions,
        "p95_latency_seconds": p95,
        "usage": _usage(last_response),
        "calls": calls,
        "attempts": all_attempts,
        "silent_truncation_detected": False if successes == repetitions else None,
    }


def _primary_115k_call(
    *,
    request_fn: RequestFn,
    base_url: str,
    headers: Mapping[str, str],
    input_text: str,
    timeout: float,
    concurrency: int,
    call_index: int,
    phase: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sentinel = f"{PRIMARY_CONTEXT_SENTINEL_PREFIX}:{phase}:c{concurrency}:i{call_index}"
    prompt = (
        input_text.rstrip()
        + "\n\nThe request ends with the sentinel below. Return that exact sentinel verbatim in the response.\n"
        + sentinel
    )
    response, attempts = request_with_fallback(
        request_fn,
        f"{base_url}{CHAT_COMPLETIONS_PATH}",
        method="POST",
        payload=_chat_payload(
            model=PRIMARY_MODEL,
            user_content=prompt,
            max_tokens=512,
        ),
        headers=headers,
        timeout=timeout,
    )
    final_attempt = attempts[-1] if attempts else {}
    usage = _usage(response)
    http_success = response is not None
    output_text = _response_text(response)
    context_length_error = _contains_context_length_error(attempts, response)
    silent_truncation = http_success and (not isinstance(output_text, str) or sentinel not in output_text)
    usage_available = usage["input_tokens"] is not None and usage["output_tokens"] is not None
    input_tokens_in_range = bool(
        usage["input_tokens"] is not None
        and PRIMARY_INPUT_TOKEN_TARGET - PRIMARY_INPUT_TOKEN_TOLERANCE
        <= usage["input_tokens"]
        <= PRIMARY_INPUT_TOKEN_TARGET + PRIMARY_INPUT_TOKEN_TOLERANCE
    )
    returned_model = response.get("model") if isinstance(response, Mapping) else None
    model_match = returned_model == PRIMARY_MODEL
    success = bool(
        http_success
        and usage_available
        and input_tokens_in_range
        and not context_length_error
        and not silent_truncation
        and model_match
    )
    call = {
        "phase": phase,
        "call_index": call_index,
        "concurrency": concurrency,
        "success": success,
        "http_success": http_success,
        "requested_model": PRIMARY_MODEL,
        "returned_model": returned_model,
        "model_match": model_match,
        "request_id": final_attempt.get("request_id"),
        "response_hash": _response_hash(final_attempt),
        "usage": usage,
        "usage_available": usage_available,
        "input_tokens_in_target_range": input_tokens_in_range,
        "ttft_seconds": final_attempt.get("ttft_seconds"),
        "ttft_definition": final_attempt.get("ttft_definition", "request_fn_metadata"),
        "latency_seconds": final_attempt.get("elapsed_seconds"),
        "http_status": final_attempt.get("http_status", final_attempt.get("status")),
        "route": final_attempt.get("route"),
        "retry_count": max(0, len(attempts) - 1),
        "context_length_error": context_length_error,
        "silent_truncation_detected": silent_truncation,
        "sentinel_sha256": _sha256_bytes(sentinel.encode("utf-8")),
    }
    return call, attempts


def _primary_115k_probe(
    *,
    request_fn: RequestFn,
    base_url: str,
    headers: Mapping[str, str],
    input_text: str,
    timeout: float,
) -> dict[str, Any]:
    warmup, warmup_attempts = _primary_115k_call(
        request_fn=request_fn,
        base_url=base_url,
        headers=headers,
        input_text=input_text,
        timeout=timeout,
        concurrency=1,
        call_index=0,
        phase="warmup",
    )
    warmup["excluded_from_success_count"] = True

    calls: list[dict[str, Any]] = []
    all_attempts: list[dict[str, Any]] = [
        {**attempt, "phase": "warmup", "concurrency": 1, "call_index": 0}
        for attempt in warmup_attempts
    ]
    concurrency_runs: list[dict[str, Any]] = []
    for concurrency in PRIMARY_CONCURRENCY_LEVELS:
        def execute(call_index: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
            return _primary_115k_call(
                request_fn=request_fn,
                base_url=base_url,
                headers=headers,
                input_text=input_text,
                timeout=timeout,
                concurrency=concurrency,
                call_index=call_index,
                phase="measurement",
            )

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            results = list(executor.map(execute, range(PRIMARY_REQUIRED_SUCCESSES)))
        run_calls = [row[0] for row in results]
        calls.extend(run_calls)
        for call, attempts in results:
            all_attempts.extend(
                {
                    **attempt,
                    "phase": "measurement",
                    "concurrency": concurrency,
                    "call_index": call["call_index"],
                }
                for attempt in attempts
            )
        http_success_count = sum(bool(call["http_success"]) for call in run_calls)
        success_count = sum(bool(call["success"]) for call in run_calls)
        run_latencies = [
            float(call["latency_seconds"])
            for call in run_calls
            if isinstance(call.get("latency_seconds"), (int, float))
        ]
        concurrency_runs.append(
            {
                "concurrency": concurrency,
                "required_success_count": PRIMARY_REQUIRED_SUCCESSES,
                "success_count": success_count,
                "http_success_count": http_success_count,
                "http_error_rate": (PRIMARY_REQUIRED_SUCCESSES - http_success_count)
                / PRIMARY_REQUIRED_SUCCESSES,
                "p95_latency_seconds": _p95(run_latencies),
            }
        )

    baseline = next(row for row in concurrency_runs if row["concurrency"] == 1)
    concurrency_four = next(row for row in concurrency_runs if row["concurrency"] == 4)
    latencies = [
        float(call["latency_seconds"])
        for call in calls
        if isinstance(call.get("latency_seconds"), (int, float))
    ]
    p95_latency = _p95(latencies)
    context_error_count = sum(bool(call["context_length_error"]) for call in calls)
    silent_truncation_count = sum(bool(call["silent_truncation_detected"]) for call in calls)
    usage_available = all(bool(call["usage_available"]) for call in calls)
    canonical_checks = {
        "success_5_of_5": baseline["success_count"] == PRIMARY_REQUIRED_SUCCESSES,
        "context_length_errors_zero": context_error_count == 0,
        "silent_truncation_zero": silent_truncation_count == 0,
        "usage_available": usage_available,
        "p95_latency_lte_180_seconds": p95_latency is not None
        and p95_latency <= PRIMARY_P95_LATENCY_LIMIT_SECONDS,
        "concurrency_4_error_rate_lte_0_05": concurrency_four["http_error_rate"] <= 0.05,
    }
    usage_totals = {
        "input_tokens": sum(int(call["usage"]["input_tokens"] or 0) for call in calls),
        "output_tokens": sum(int(call["usage"]["output_tokens"] or 0) for call in calls),
    }
    return {
        "schema_version": "plan-robust-memory.primary-115k-probe.v1",
        "created_at": _now(),
        "status": "passed" if all(canonical_checks.values()) else "blocked",
        "role": "primary_115k",
        "requested_model": PRIMARY_MODEL,
        "returned_models": sorted(
            {str(call["returned_model"]) for call in calls if call.get("returned_model")}
        ),
        "base_url": base_url,
        "endpoint": f"{base_url}{CHAT_COMPLETIONS_PATH}",
        "request_protocol": "openai_compatible_chat_completions",
        "message_contract": "exactly_one_user_message_no_system_or_developer_message",
        "requested_input_token_target": PRIMARY_INPUT_TOKEN_TARGET,
        "requested_input_token_tolerance": PRIMARY_INPUT_TOKEN_TOLERANCE,
        "max_output_tokens": 512,
        "warmup": warmup,
        "concurrency_levels": list(PRIMARY_CONCURRENCY_LEVELS),
        "concurrency_runs": concurrency_runs,
        "success_count": baseline["success_count"],
        "required_success_count": PRIMARY_REQUIRED_SUCCESSES,
        "p95_latency_seconds": p95_latency,
        "usage": usage_totals,
        "usage_available": usage_available,
        "ttft_available": all(call.get("ttft_seconds") is not None for call in calls),
        "retry_count": sum(int(call["retry_count"]) for call in calls),
        "http_statuses": sorted(
            {int(call["http_status"]) for call in calls if isinstance(call.get("http_status"), int)}
        ),
        "context_length_error_count": context_error_count,
        "silent_truncation_count": silent_truncation_count,
        "calls": calls,
        "attempts": all_attempts,
        "canonical_checks": canonical_checks,
    }


def _judge_probe(*, request_fn: RequestFn, base_url: str, headers: Mapping[str, str], timeout: float) -> dict[str, Any]:
    cases = [
        ("correct-1", "2+2? Reference: 4. Candidate: 4. Return JSON label 1 or 0.", 1),
        ("correct-2", "Capital of France? Reference: Paris. Candidate: Paris. Return JSON label 1 or 0.", 1),
        ("wrong-1", "2+2? Reference: 4. Candidate: 5. Return JSON label 1 or 0.", 0),
        ("wrong-2", "Capital of France? Reference: Paris. Candidate: Rome. Return JSON label 1 or 0.", 0),
        ("partial-1", "Reference: red and blue. Candidate: red. Return strict JSON with label.", None),
    ]
    attempts: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for case_id, prompt, expected in cases:
        response, rows = request_with_fallback(
            request_fn,
            f"{base_url}{CHAT_COMPLETIONS_PATH}",
            method="POST",
            payload=_chat_payload(
                model=JUDGE_MODEL,
                user_content=prompt,
                max_tokens=128,
                temperature=0,
            ),
            headers=headers,
            timeout=timeout,
        )
        attempts.extend({**row, "case_id": case_id} for row in rows)
        text = _response_text(response)
        parsed_label: int | None = None
        parser_error: str | None = None
        try:
            parsed = json.loads(text) if isinstance(text, str) else None
            label = parsed.get("label") if isinstance(parsed, Mapping) else None
            if isinstance(label, bool) or not isinstance(label, int) or label not in {0, 1}:
                raise ValueError("JSON object must contain integer label 0 or 1")
            parsed_label = label
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            parser_error = str(exc)
        http_success = response is not None
        parser_success = parsed_label is not None
        expected_match = None if expected is None or not parser_success else parsed_label == expected
        returned_model = response.get("model") if response else None
        model_match = returned_model == JUDGE_MODEL and not str(returned_model).endswith("-latest")
        usage = _usage(response)
        usage_available = _usage_available(response)
        outputs.append(
            {
                "case_id": case_id,
                "expected": expected,
                "http_success": http_success,
                "parser_success": parser_success,
                "parser_error": parser_error,
                "parsed_label": parsed_label,
                "expected_match": expected_match,
                "success": bool(
                    http_success
                    and parser_success
                    and expected_match is not False
                    and model_match
                    and usage_available
                ),
                "returned_model": returned_model,
                "model_match": model_match,
                "route": rows[-1].get("route") if rows else None,
                "request_id": rows[-1].get("request_id") if rows else None,
                "response_hash": _response_hash(rows[-1] if rows else None),
                "usage": usage,
                "usage_available": usage_available,
            }
        )
    parser_success_count = sum(bool(row["parser_success"]) for row in outputs)
    parser_success_rate = parser_success_count / len(outputs)
    parser_probe_success = parser_success_count == len(outputs)
    passed = parser_probe_success and all(row["success"] for row in outputs)
    returned_models = sorted(
        {str(row["returned_model"]) for row in outputs if row.get("returned_model")}
    )
    return {
        "schema_version": "plan-robust-memory.judge-probe.v1",
        "created_at": _now(),
        "status": "passed" if passed else "blocked",
        "role": "project_longmemeval_compatible_judge",
        "requested_model": JUDGE_MODEL,
        "returned_model": returned_models[0] if len(returned_models) == 1 else None,
        "returned_models": returned_models,
        "base_url": base_url,
        "endpoint": f"{base_url}{CHAT_COMPLETIONS_PATH}",
        "request_protocol": "openai_compatible_chat_completions",
        "message_contract": "exactly_one_user_message_no_system_or_developer_message",
        "decoding_parameters": {"temperature": 0, "max_tokens": 128, "stream": False},
        "case_count": len(cases),
        "parser_success_count": parser_success_count,
        "parser_success_rate": parser_success_rate,
        "parser_probe_success": parser_probe_success,
        "usage_complete": all(bool(row["usage_available"]) for row in outputs),
        "rolling_fallback_detected": any(
            str(row.get("returned_model", "")).endswith("-latest") for row in outputs
        ),
        "cases": outputs,
        "attempts": attempts,
    }


def _session_turn_text(session: Any) -> list[str]:
    if not isinstance(session, Sequence) or isinstance(session, (str, bytes)):
        raise ValueError("LongMemEval haystack session must be a list of turns")
    turns: list[str] = []
    for turn in session:
        if not isinstance(turn, Mapping):
            raise ValueError("LongMemEval session turn must be an object")
        role = str(turn.get("role", "unknown"))
        content = turn.get("content", "")
        turns.append(f"{role}: {content}")
    if not turns:
        raise ValueError("LongMemEval haystack session must contain at least one turn")
    return turns


def _episode_unit_text(timestamp: Any, turns: Sequence[str]) -> str:
    timestamp_text = str(timestamp) if timestamp is not None else "unknown-time"
    return f"timestamp: {timestamp_text}\n" + "\n".join(str(turn) for turn in turns)


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"required Day 1 episode source is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in Day 1 episode source: {path}") from exc


def _default_weight_resolver(
    model: str,
    revision: str | None,
    *,
    cache_dir: Path = DEFAULT_HF_HUB_CACHE,
) -> dict[str, Any]:
    if not _explicit_revision(revision):
        raise ValueError("an explicit model revision is required to resolve embedding weights")
    filename = "pytorch_model.bin"
    try:
        from huggingface_hub import hf_hub_download

        path = Path(
            hf_hub_download(
                repo_id=model,
                filename=filename,
                revision=revision,
                cache_dir=str(cache_dir),
                local_files_only=True,
            )
        )
    except Exception as exc:
        raise RuntimeError(
            f"could not resolve frozen official embedding weight {model}@{revision}/{filename}"
        ) from exc
    return {
        "weight_filename": filename,
        "weight_sha256": _sha256_file(path),
        "cache_dir": str(cache_dir.resolve()),
        "cache_hit_offline": True,
        "resolved_path": str(path.resolve()),
    }


def _choose_real_probe_episode(
    normalized: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any] | None,
    *,
    split: str,
    candidate_id: str,
) -> Mapping[str, Any]:
    by_id = {
        str(row.get("episode_id")): row
        for row in normalized
        if isinstance(row, Mapping) and row.get("episode_id")
    }
    if manifest is not None:
        candidates = next(
            (
                candidate
                for candidate in manifest.get("split_candidates", [])
                if isinstance(candidate, Mapping) and candidate.get("candidate_id") == candidate_id
            ),
            None,
        )
        if isinstance(candidates, Mapping):
            episode_ids = sorted(
                episode_id
                for assignment in candidates.get("assignments", [])
                if isinstance(assignment, Mapping) and assignment.get("split") == split
                for episode_id in assignment.get("episode_ids", [])
                if str(episode_id) in by_id
                and bool(by_id[str(episode_id)].get("primary_eligible"))
                and bool(by_id[str(episode_id)].get("eligible_for_k8"))
            )
            if episode_ids:
                return by_id[episode_ids[0]]
        raise ValueError(
            f"split manifest has no primary k=8 {split} episode for candidate {candidate_id}"
        )
    fallback = sorted(
        (
            row
            for row in normalized
            if bool(row.get("primary_eligible")) and bool(row.get("eligible_for_k8"))
        ),
        key=lambda row: str(row.get("episode_id")),
    )
    if not fallback:
        raise ValueError("normalized LongMemEval artifact has no primary k=8 episode")
    return fallback[0]


def load_real_episode_probe(
    *,
    raw_path: Path = DEFAULT_LONGMEMEVAL_RAW_PATH,
    normalized_path: Path = DEFAULT_LONGMEMEVAL_NORMALIZED_PATH,
    manifest_path: Path | None = DEFAULT_LONGMEMEVAL_MANIFEST_PATH,
    episode_id: str | None = None,
    split: str = "development",
    candidate_id: str = "20_30_50",
) -> dict[str, Any]:
    """Load one deterministic primary LongMemEval episode for the embedding Gate.

    The normalized audit supplies the immutable evidence order and surrogate token
    accounting; the official cleaned raw row supplies every timestamped session
    body.  No answer/support labels are returned to the encoder.
    """
    raw_path = Path(raw_path).resolve()
    normalized_path = Path(normalized_path).resolve()
    if not raw_path.exists() or not normalized_path.exists():
        missing = [str(path) for path in (raw_path, normalized_path) if not path.exists()]
        raise FileNotFoundError("missing official LongMemEval probe source: " + ", ".join(missing))
    raw_rows = _read_json_file(raw_path)
    normalized_rows = _read_json_file(normalized_path)
    if not isinstance(raw_rows, list) or not all(isinstance(row, Mapping) for row in raw_rows):
        raise ValueError("cleaned LongMemEval raw source must be a JSON array of objects")
    if not isinstance(normalized_rows, list) or not all(isinstance(row, Mapping) for row in normalized_rows):
        raise ValueError("normalized LongMemEval source must be a JSON array of objects")
    manifest: Mapping[str, Any] | None = None
    if manifest_path is not None:
        resolved_manifest_path = Path(manifest_path).resolve()
        if not resolved_manifest_path.exists():
            raise FileNotFoundError(
                f"required LongMemEval split manifest is missing: {resolved_manifest_path}"
            )
        loaded_manifest = _read_json_file(resolved_manifest_path)
        if not isinstance(loaded_manifest, Mapping):
            raise ValueError("LongMemEval dataset manifest must be an object")
        manifest = loaded_manifest
        audit_hash = manifest.get("audit_hash")
        if not isinstance(audit_hash, str) or audit_hash != stable_hash(
            {key: value for key, value in manifest.items() if key != "audit_hash"}
        ):
            raise ValueError("LongMemEval split manifest audit hash is invalid")
    elif episode_id is None:
        raise ValueError("a split manifest is required unless an explicit fixture episode is selected")
    raw_sha256 = _sha256_file(raw_path)
    if manifest is not None:
        raw_checksums = manifest.get("raw_checksums")
        checksum_row = (
            raw_checksums.get(LONGMEMEVAL_CLEANED_FILENAME)
            if isinstance(raw_checksums, Mapping)
            else None
        )
        expected_raw_sha256 = (
            checksum_row.get("sha256") if isinstance(checksum_row, Mapping) else None
        )
        if expected_raw_sha256 != raw_sha256:
            raise ValueError(
                "official LongMemEval raw checksum does not match the audited split manifest"
            )
    normalized = (
        next((row for row in normalized_rows if str(row.get("episode_id")) == episode_id), None)
        if episode_id is not None
        else _choose_real_probe_episode(
            normalized_rows, manifest, split=split, candidate_id=candidate_id
        )
    )
    if not isinstance(normalized, Mapping):
        raise ValueError(f"normalized LongMemEval episode not found: {episode_id}")
    if manifest is not None and normalized.get("dataset_version_or_commit") != manifest.get(
        "source_revision"
    ):
        raise ValueError("normalized episode revision does not match the audited split manifest")
    selected_id = str(normalized.get("episode_id"))
    raw = next((row for row in raw_rows if str(row.get("question_id")) == selected_id), None)
    if not isinstance(raw, Mapping):
        raise ValueError(f"official cleaned raw episode not found: {selected_id}")
    dates = raw.get("haystack_dates")
    source_ids = raw.get("haystack_session_ids")
    sessions = raw.get("haystack_sessions")
    evidence = normalized.get("evidence")
    if not (
        isinstance(dates, list)
        and isinstance(source_ids, list)
        and isinstance(sessions, list)
        and isinstance(evidence, list)
        and len(dates) == len(source_ids) == len(sessions) == len(evidence)
        and len(sessions) > 0
    ):
        raise ValueError(f"raw/normalized evidence cardinality mismatch for {selected_id}")
    units: list[dict[str, Any]] = []
    for sequence_index, (date, source_id, session, evidence_row) in enumerate(
        zip(dates, source_ids, sessions, evidence, strict=True)
    ):
        if not isinstance(evidence_row, Mapping):
            raise ValueError(f"invalid normalized evidence row for {selected_id}:{sequence_index}")
        if evidence_row.get("sequence_index") != sequence_index:
            raise ValueError(
                f"normalized evidence sequence index mismatch for {selected_id}:{sequence_index}"
            )
        if evidence_row.get("source_session_id") is not None and str(
            evidence_row.get("source_session_id")
        ) != str(source_id):
            raise ValueError(
                f"normalized evidence source session mismatch for {selected_id}:{sequence_index}"
            )
        expected_session_hash = stable_hash(session)
        if evidence_row.get("raw_sha256") is not None and evidence_row.get(
            "raw_sha256"
        ) != expected_session_hash:
            raise ValueError(
                f"normalized evidence hash mismatch for {selected_id}:{sequence_index}"
            )
        turns = _session_turn_text(session)
        unit = {
            "sequence_index": sequence_index,
            "source_session_id": str(source_id),
            "evidence_id": str(evidence_row.get("evidence_id")),
            "timestamp": str(date),
            "turns": turns,
            "text": _episode_unit_text(date, turns),
            "surrogate_token_count": int(evidence_row.get("token_count", 0)),
        }
        if unit["surrogate_token_count"] <= 0:
            raise ValueError(f"non-positive normalized token count for {selected_id}:{sequence_index}")
        units.append(unit)
    normalized_hash = _sha256_bytes(
        json.dumps(dict(normalized), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    return {
        "episode_id": selected_id,
        "question_type": str(normalized.get("question_type")),
        "dataset_revision": str(normalized.get("dataset_version_or_commit")),
        "raw_path": str(raw_path),
        "raw_sha256": raw_sha256,
        "normalized_path": str(normalized_path),
        "normalized_episode_sha256": normalized_hash,
        "session_count": len(units),
        "unit_count": len(units),
        "surrogate_token_count": sum(int(unit["surrogate_token_count"]) for unit in units),
        "max_unit_surrogate_tokens": max(int(unit["surrogate_token_count"]) for unit in units),
        "query_text": str(raw.get("question") or normalized.get("query", {}).get("question_text", "")),
        "units": units,
        "selection": {
            "split": split if episode_id is None else "explicit_fixture",
            "candidate_id": candidate_id if episode_id is None else None,
            "explicit_episode_id": episode_id,
            "manifest_audit_hash": manifest.get("audit_hash") if manifest is not None else None,
        },
    }


def _vectors_as_lists(value: Any) -> list[list[float]]:
    raw = value.tolist() if hasattr(value, "tolist") else value
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError("embedding output must be a matrix")
    matrix: list[list[float]] = []
    for row in raw:
        row = row.tolist() if hasattr(row, "tolist") else row
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
            raise ValueError("embedding row must be a numeric sequence")
        matrix.append([float(item) for item in row])
    if not matrix or not matrix[0] or any(len(row) != len(matrix[0]) for row in matrix):
        raise ValueError("embedding matrix must be non-empty and rectangular")
    return matrix


def _embedding_matrix_sha256(matrix: Sequence[Sequence[float]]) -> str:
    encoded = json.dumps(
        [[float(value) for value in row] for row in matrix],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _package_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _rank_documents(document_vectors: Sequence[Sequence[float]], query_vectors: Sequence[Sequence[float]]) -> list[list[int]]:
    return [
        sorted(
            range(len(document_vectors)),
            key=lambda index: (-_cosine(document_vectors[index], query), index),
        )
        for query in query_vectors
    ]


def _greedy_pack(
    rankings: Sequence[Sequence[int]],
    documents: Sequence[str],
    budget_tokens: int = EMBEDDING_PROBE_PACK_BUDGET_TOKENS,
    *,
    token_counts: Sequence[int] | None = None,
) -> list[list[int]]:
    counts = (
        [max(1, len(document.split())) for document in documents]
        if token_counts is None
        else [int(value) for value in token_counts]
    )
    if len(counts) != len(documents) or any(value <= 0 for value in counts):
        raise ValueError("packing token counts must be positive and match the documents")
    packed: list[list[int]] = []
    for ranking in rankings:
        remaining = budget_tokens
        selected: list[int] = []
        for index in ranking:
            token_estimate = counts[index]
            if token_estimate <= remaining:
                selected.append(index)
                remaining -= token_estimate
        packed.append(sorted(selected))
    return packed


def _explicit_revision(revision: str | None) -> bool:
    return bool(revision and revision.strip().lower() not in {"main", "master", "latest"})


def _model_token_count(tokenizer: Any, text: str) -> int:
    if tokenizer is not None:
        encoded = tokenizer(text, add_special_tokens=True, truncation=False)
        input_ids = encoded.get("input_ids") if isinstance(encoded, Mapping) else None
        if hasattr(input_ids, "tolist"):
            input_ids = input_ids.tolist()
        if isinstance(input_ids, Sequence) and input_ids and isinstance(input_ids[0], Sequence):
            input_ids = input_ids[0]
        if isinstance(input_ids, Sequence) and not isinstance(input_ids, (str, bytes)):
            return len(input_ids)
    # This fallback is deliberately conservative and is only used by injected
    # test encoders that do not expose a tokenizer.
    return max(1, len(text.split()))


def _split_episode_unit_for_model(
    unit: Mapping[str, Any], *, tokenizer: Any, max_sequence_length: int
) -> list[dict[str, Any]]:
    text = str(unit["text"])
    if _model_token_count(tokenizer, text) <= max_sequence_length:
        return [dict(unit, model_token_count=_model_token_count(tokenizer, text), chunk_index=0)]
    turns = [str(turn) for turn in unit.get("turns", [])]
    timestamp = str(unit.get("timestamp", "unknown-time"))
    chunks: list[str] = []
    current: list[str] = []
    for turn in turns:
        candidate = _episode_unit_text(timestamp, [*current, turn])
        if current and _model_token_count(tokenizer, candidate) > max_sequence_length:
            chunks.append(_episode_unit_text(timestamp, current))
            current = [turn]
            if _model_token_count(tokenizer, _episode_unit_text(timestamp, current)) <= max_sequence_length:
                continue
            current = []
        if not current and _model_token_count(tokenizer, _episode_unit_text(timestamp, [turn])) > max_sequence_length:
            words = turn.split()
            word_chunk: list[str] = []
            for word in words:
                candidate_words = " ".join([*word_chunk, word])
                if word_chunk and _model_token_count(tokenizer, _episode_unit_text(timestamp, [candidate_words])) > max_sequence_length:
                    chunks.append(_episode_unit_text(timestamp, [" ".join(word_chunk)]))
                    word_chunk = [word]
                else:
                    word_chunk.append(word)
            if word_chunk:
                current = [" ".join(word_chunk)]
            continue
        current.append(turn)
    if current:
        chunks.append(_episode_unit_text(timestamp, current))
    if not chunks:
        raise ValueError(f"unable to split episode unit {unit.get('sequence_index')}")
    total_surrogate = int(unit["surrogate_token_count"])
    model_counts = [_model_token_count(tokenizer, chunk) for chunk in chunks]
    if any(count > max_sequence_length for count in model_counts):
        raise ValueError(
            f"episode unit {unit.get('sequence_index')} remains above model limit {max_sequence_length}"
        )
    # Preserve the normalized episode total while making the chunk allocation
    # auditable and deterministic.
    weights = [max(1, count) for count in model_counts]
    allocated: list[int] = []
    remaining = total_surrogate
    for index, weight in enumerate(weights):
        if index == len(weights) - 1:
            value = remaining
        else:
            value = max(1, round(total_surrogate * weight / sum(weights)))
            value = min(value, remaining - (len(weights) - index - 1))
        allocated.append(value)
        remaining -= value
    return [
        {
            **dict(unit),
            "text": chunk,
            "chunk_index": chunk_index,
            "model_token_count": model_counts[chunk_index],
            "surrogate_token_count": allocated[chunk_index],
            "evidence_id": f"{unit['evidence_id']}:chunk:{chunk_index:03d}",
        }
        for chunk_index, chunk in enumerate(chunks)
    ]


def _prepare_episode_units(
    episode_probe: Mapping[str, Any], *, tokenizer: Any, max_sequence_length: int
) -> list[dict[str, Any]]:
    raw_units = episode_probe.get("units")
    if not isinstance(raw_units, Sequence) or isinstance(raw_units, (str, bytes)) or not raw_units:
        raise ValueError("real episode probe must contain non-empty ordered units")
    prepared: list[dict[str, Any]] = []
    for unit in raw_units:
        if not isinstance(unit, Mapping):
            raise ValueError("real episode probe unit must be an object")
        prepared.extend(
            _split_episode_unit_for_model(
                unit, tokenizer=tokenizer, max_sequence_length=max_sequence_length
            )
        )
    return prepared


def probe_embedding(
    model: str = BGE_M3_MODEL,
    revision: str | None = BGE_M3_REVISION,
    *,
    torch_module: Any | None = None,
    sentence_transformer_cls: Any | None = None,
    episode_probe: Mapping[str, Any] | None = None,
    weight_resolver: Callable[[str, str | None], Mapping[str, Any]] = _default_weight_resolver,
    hf_cache_dir: Path = DEFAULT_HF_HUB_CACHE,
) -> dict[str, Any]:
    torch_available = torch_module is not None or importlib.util.find_spec("torch") is not None
    sentence_transformers_available = (
        sentence_transformer_cls is not None
        or importlib.util.find_spec("sentence_transformers") is not None
    )
    artifact: dict[str, Any] = {
        "schema_version": "plan-robust-memory.embedding-probe.v1",
        "created_at": _now(),
        "status": "blocked",
        "model": model,
        "revision": revision,
        "tokenizer_revision": revision if _explicit_revision(revision) else None,
        "model_snapshot": f"{model}@{revision}" if _explicit_revision(revision) else None,
        "tokenizer_snapshot": f"{model}@{revision}" if _explicit_revision(revision) else None,
        "precision": "fp16",
        "similarity": "cosine_over_normalized_vectors",
        "normalize_embeddings": True,
        "trust_remote_code": False,
        "use_safetensors": False,
        "hf_cache_dir": str(Path(hf_cache_dir).resolve()),
        "hf_cache_policy": "repo_local_offline_frozen_snapshot",
        "hf_cache_hit_offline": None,
        "resolved_weight_path": None,
        "weight_filename": None,
        "weight_sha256": None,
        "expected_embedding_dimension": BGE_M3_EMBEDDING_DIMENSION,
        "expected_max_sequence_length": BGE_M3_MAX_SEQUENCE_LENGTH,
        "torch_available": torch_available,
        "sentence_transformers_available": sentence_transformers_available,
        "torch_version": None,
        "sentence_transformers_version": None,
        "cuda_runtime_version": None,
        "cuda_available": False,
        "device_name": None,
        "vram_bytes": None,
        "model_parameter_dtype": None,
        "embedding_dimension": None,
        "normalized_vectors_verified": False,
        "embedding_output_sha256_runs": [],
        "embedding_executed": False,
        "encode_run_count": 0,
        "real_episode_probe": False,
        "episode_id": None,
        "episode_selection": None,
        "question_type": None,
        "dataset_revision": None,
        "raw_sha256": None,
        "normalized_episode_sha256": None,
        "session_count": None,
        "episode_unit_count": None,
        "surrogate_token_count": None,
        "max_unit_surrogate_tokens": None,
        "max_unit_model_tokens": None,
        "episode_batch_size": None,
        "peak_vram_bytes": None,
        "peak_vram_bytes_available": False,
        "ranking_deterministic": False,
        "packing_deterministic": False,
        "packing_nonempty": False,
        "packing_budget_tokens": EMBEDDING_PROBE_PACK_BUDGET_TOKENS,
        "packing_token_totals_runs": [],
        "single_episode_embedding_latency_seconds": None,
        "estimated_500_instance_index_seconds": None,
        "micro_probe_latency_seconds": None,
        "ranking_runs": [],
        "packing_runs": [],
        "blocking_reason": None,
    }
    missing: list[str] = []
    if not _explicit_revision(revision):
        missing.append("explicit non-rolling model/tokenizer revision")
    if not torch_available:
        missing.append("torch")
    if not sentence_transformers_available:
        missing.append("sentence-transformers")
    if missing:
        artifact["blocking_reason"] = "missing " + ", ".join(missing)
        return artifact

    try:
        if torch_module is None:
            import torch as imported_torch

            torch_module = imported_torch
        artifact["torch_version"] = str(getattr(torch_module, "__version__", "unknown"))
        artifact["cuda_runtime_version"] = str(
            getattr(getattr(torch_module, "version", None), "cuda", "unknown")
        )
        cuda_available = bool(torch_module.cuda.is_available())
        artifact["cuda_available"] = cuda_available
        if not cuda_available:
            artifact["blocking_reason"] = "CUDA is required for the frozen local embedding probe"
            return artifact
        artifact["device_name"] = str(torch_module.cuda.get_device_name(0))
        try:
            properties = torch_module.cuda.get_device_properties(0)
            artifact["vram_bytes"] = int(properties.total_memory)
        except (AttributeError, TypeError, ValueError):
            artifact["vram_bytes"] = None

        if sentence_transformer_cls is None:
            from sentence_transformers import SentenceTransformer

            sentence_transformer_cls = SentenceTransformer
        artifact["sentence_transformers_version"] = str(
            getattr(sentence_transformer_cls, "package_version", None)
            or _package_version("sentence-transformers")
            or "unknown"
        )
        if weight_resolver is _default_weight_resolver:
            weight_record = weight_resolver(
                model,
                revision,
                cache_dir=Path(hf_cache_dir),
            )
        else:
            weight_record = weight_resolver(model, revision)
        artifact["weight_filename"] = weight_record.get("weight_filename")
        artifact["weight_sha256"] = weight_record.get("weight_sha256")
        artifact["hf_cache_hit_offline"] = weight_record.get("cache_hit_offline")
        artifact["resolved_weight_path"] = weight_record.get("resolved_path")
        if artifact["weight_filename"] != "pytorch_model.bin" or not (
            isinstance(artifact["weight_sha256"], str)
            and len(artifact["weight_sha256"]) == 64
        ):
            raise ValueError("frozen official pytorch_model.bin weight provenance is required")
        encoder = sentence_transformer_cls(
            model,
            cache_folder=str(Path(hf_cache_dir).resolve()),
            revision=revision,
            device="cuda",
            trust_remote_code=False,
            local_files_only=True,
            model_kwargs={
                "torch_dtype": torch_module.float16,
                "use_safetensors": False,
            },
            tokenizer_kwargs={"local_files_only": True},
            config_kwargs={"local_files_only": True},
        )
        try:
            first_parameter = next(iter(encoder.parameters()))
            artifact["model_parameter_dtype"] = str(first_parameter.dtype)
        except (AttributeError, StopIteration, TypeError):
            artifact["model_parameter_dtype"] = None
        tokenizer = getattr(encoder, "tokenizer", None)
        if tokenizer is None:
            try:
                tokenizer = getattr(encoder._first_module(), "tokenizer", None)
            except (AttributeError, TypeError):
                tokenizer = None
        model_max_sequence_length = min(
            BGE_M3_MAX_SEQUENCE_LENGTH,
            int(getattr(encoder, "max_seq_length", BGE_M3_MAX_SEQUENCE_LENGTH)),
        )
        real_episode = episode_probe is not None
        if real_episode:
            prepared_units = _prepare_episode_units(
                episode_probe,
                tokenizer=tokenizer,
                max_sequence_length=model_max_sequence_length,
            )
            documents = [str(unit["text"]) for unit in prepared_units]
            document_token_counts = [
                int(unit["surrogate_token_count"]) for unit in prepared_units
            ]
            queries = [str(episode_probe.get("query_text", ""))]
            if not queries[0].strip():
                raise ValueError("real episode probe query is empty")
            artifact.update(
                {
                    "real_episode_probe": True,
                    "episode_id": str(episode_probe.get("episode_id")),
                    "episode_selection": episode_probe.get("selection"),
                    "question_type": episode_probe.get("question_type"),
                    "dataset_revision": episode_probe.get("dataset_revision"),
                    "raw_sha256": episode_probe.get("raw_sha256"),
                    "normalized_episode_sha256": episode_probe.get("normalized_episode_sha256"),
                    "session_count": int(episode_probe.get("session_count", len(prepared_units))),
                    "episode_unit_count": len(prepared_units),
                    "surrogate_token_count": sum(
                        int(unit["surrogate_token_count"]) for unit in prepared_units
                    ),
                    "max_unit_surrogate_tokens": max(
                        int(unit["surrogate_token_count"]) for unit in prepared_units
                    ),
                    "max_unit_model_tokens": max(
                        int(unit.get("model_token_count", _model_token_count(tokenizer, str(unit["text"]))))
                        for unit in prepared_units
                    ),
                    "episode_batch_size": 1,
                }
            )
        else:
            documents = [
                "alpha project deadline is Monday",
                "beta recipe uses basil and garlic",
                "alpha meeting moved to Tuesday",
                "beta travel reservation is Friday",
            ]
            document_token_counts = [max(1, len(document.split())) for document in documents]
            queries = ["alpha project schedule", "beta recipe and travel"]
        texts = documents + queries
        ranking_runs: list[list[list[int]]] = []
        packing_runs: list[list[list[int]]] = []
        output_hashes: list[str] = []
        latencies: list[float] = []
        peak_vram_values: list[int] = []
        for _ in range(2):
            if real_episode and hasattr(torch_module.cuda, "reset_peak_memory_stats"):
                torch_module.cuda.reset_peak_memory_stats()
            started = time.monotonic()
            vectors = _vectors_as_lists(
                encoder.encode(
                    texts,
                    batch_size=1 if real_episode else len(texts),
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
            )
            latencies.append(time.monotonic() - started)
            if real_episode:
                peak_value = None
                for name in ("max_memory_reserved", "max_memory_allocated"):
                    method = getattr(torch_module.cuda, name, None)
                    if callable(method):
                        try:
                            peak_value = max(int(method()), int(peak_value or 0))
                        except (RuntimeError, TypeError, ValueError):
                            pass
                if peak_value is None:
                    peak_value = artifact.get("vram_bytes")
                if isinstance(peak_value, int):
                    peak_vram_values.append(peak_value)
            if len(vectors) != len(texts):
                raise ValueError("embedding output row count does not match probe text count")
            dimension = len(vectors[0])
            if any(len(vector) != dimension for vector in vectors):
                raise ValueError("embedding output dimensions differ across probe texts")
            artifact["embedding_dimension"] = dimension
            output_hashes.append(_embedding_matrix_sha256(vectors))
            rankings = _rank_documents(vectors[: len(documents)], vectors[len(documents) :])
            ranking_runs.append(rankings)
            packing_runs.append(
                _greedy_pack(
                    rankings,
                    documents,
                    token_counts=document_token_counts,
                )
            )
        artifact["embedding_executed"] = True
        artifact["encode_run_count"] = 2
        artifact["ranking_runs"] = ranking_runs
        artifact["packing_runs"] = packing_runs
        artifact["packing_token_totals_runs"] = [
            [sum(document_token_counts[index] for index in selected) for selected in run]
            for run in packing_runs
        ]
        artifact["embedding_output_sha256_runs"] = output_hashes
        artifact["normalized_vectors_verified"] = all(
            math.isclose(
                math.sqrt(sum(value * value for value in vector)),
                1.0,
                rel_tol=0.0,
                abs_tol=5e-3,
            )
            for vector in vectors
        )
        artifact["ranking_deterministic"] = ranking_runs[0] == ranking_runs[1]
        artifact["packing_deterministic"] = packing_runs[0] == packing_runs[1]
        artifact["packing_nonempty"] = all(
            bool(selected) for run in packing_runs for selected in run
        )
        artifact["micro_probe_latency_seconds"] = round(sum(latencies) / len(latencies), 6)
        if real_episode:
            artifact["single_episode_embedding_latency_seconds"] = artifact[
                "micro_probe_latency_seconds"
            ]
            artifact["estimated_500_instance_index_seconds"] = round(
                artifact["micro_probe_latency_seconds"] * 500, 3
            )
            if peak_vram_values:
                artifact["peak_vram_bytes"] = max(peak_vram_values)
                artifact["peak_vram_bytes_available"] = True
        if (
            artifact["ranking_deterministic"]
            and artifact["packing_deterministic"]
            and artifact["packing_nonempty"]
            and all(
                total <= EMBEDDING_PROBE_PACK_BUDGET_TOKENS
                for run in artifact["packing_token_totals_runs"]
                for total in run
            )
            and len(set(output_hashes)) == 1
            and artifact["embedding_dimension"] == BGE_M3_EMBEDDING_DIMENSION
            and artifact["normalized_vectors_verified"] is True
            and artifact["model_parameter_dtype"] == "torch.float16"
        ):
            artifact["status"] = "passed" if real_episode else "diagnostic_only"
        else:
            artifact["blocking_reason"] = (
                "fp16 dtype, 1024-dimensional normalized embeddings, repeated output bytes, "
                "query ranking, and greedy packing must all qualify"
            )
    except Exception as exc:
        artifact["blocking_reason"] = f"embedding execution failed: {type(exc).__name__}: {str(exc)[:500]}"
    return artifact


def _embedding_qualified(artifact: Mapping[str, Any]) -> bool:
    revision = artifact.get("revision")
    tokenizer_revision = artifact.get("tokenizer_revision")
    return bool(
        artifact.get("status") == "passed"
        and isinstance(revision, str)
        and _explicit_revision(revision)
        and isinstance(tokenizer_revision, str)
        and _explicit_revision(tokenizer_revision)
        and artifact.get("model_snapshot") == f"{artifact.get('model')}@{revision}"
        and artifact.get("tokenizer_snapshot") == f"{artifact.get('model')}@{tokenizer_revision}"
        and artifact.get("precision") == "fp16"
        and artifact.get("similarity") == "cosine_over_normalized_vectors"
        and artifact.get("use_safetensors") is False
        and artifact.get("weight_filename") == "pytorch_model.bin"
        and isinstance(artifact.get("weight_sha256"), str)
        and len(artifact.get("weight_sha256", "")) == 64
        and isinstance(artifact.get("torch_version"), str)
        and bool(artifact.get("torch_version"))
        and isinstance(artifact.get("sentence_transformers_version"), str)
        and bool(artifact.get("sentence_transformers_version"))
        and isinstance(artifact.get("cuda_runtime_version"), str)
        and bool(artifact.get("cuda_runtime_version"))
        and artifact.get("cuda_available") is True
        and isinstance(artifact.get("device_name"), str)
        and artifact.get("model_parameter_dtype") == "torch.float16"
        and artifact.get("embedding_dimension") == BGE_M3_EMBEDDING_DIMENSION
        and artifact.get("normalized_vectors_verified") is True
        and isinstance(artifact.get("embedding_output_sha256_runs"), list)
        and len(artifact.get("embedding_output_sha256_runs", [])) >= 2
        and len(set(artifact.get("embedding_output_sha256_runs", []))) == 1
        and artifact.get("embedding_executed") is True
        and int(artifact.get("encode_run_count", 0)) >= 2
        and artifact.get("real_episode_probe") is True
        and isinstance(artifact.get("episode_id"), str)
        and bool(artifact.get("episode_id"))
        and isinstance(artifact.get("episode_selection"), Mapping)
        and artifact.get("episode_selection", {}).get("split") == "development"
        and artifact.get("episode_selection", {}).get("candidate_id") == "20_30_50"
        and isinstance(
            artifact.get("episode_selection", {}).get("manifest_audit_hash"), str
        )
        and len(artifact.get("episode_selection", {}).get("manifest_audit_hash", "")) == 64
        and isinstance(artifact.get("raw_sha256"), str)
        and len(artifact.get("raw_sha256", "")) == 64
        and isinstance(artifact.get("normalized_episode_sha256"), str)
        and len(artifact.get("normalized_episode_sha256", "")) == 64
        and int(artifact.get("session_count", 0)) > 0
        and int(artifact.get("episode_unit_count", 0)) > 0
        and int(artifact.get("episode_batch_size", 0)) == 1
        and artifact.get("single_episode_embedding_latency_seconds") is not None
        and artifact.get("peak_vram_bytes") is not None
        and artifact.get("ranking_deterministic") is True
        and artifact.get("packing_deterministic") is True
        and artifact.get("packing_nonempty") is True
        and int(artifact.get("packing_budget_tokens", 0)) > 0
        and all(
            isinstance(total, (int, float))
            and not isinstance(total, bool)
            and 0 < total <= int(artifact.get("packing_budget_tokens", 0))
            for run in artifact.get("packing_token_totals_runs", [])
            if isinstance(run, Sequence) and not isinstance(run, (str, bytes))
            for total in run
        )
        and bool(artifact.get("packing_token_totals_runs"))
    )


def _blocked_artifact(
    role: str,
    base_url: str,
    reason: str,
    attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "plan-robust-memory.day1-probe.v1",
        "created_at": _now(),
        "status": "blocked",
        "role": role,
        "base_url": base_url,
        "endpoint": f"{base_url}{CHAT_COMPLETIONS_PATH}",
        "request_protocol": "openai_compatible_chat_completions",
        "message_contract": "exactly_one_user_message_no_system_or_developer_message",
        "blocking_reason": reason,
        "attempts": attempts or [],
    }


def _probe_only_bound() -> dict[str, Any]:
    primary_115k_calls = 1 + len(PRIMARY_CONCURRENCY_LEVELS) * PRIMARY_REQUIRED_SUCCESSES
    return {
        "status": "probe_only_not_full_experiment",
        "primary_115k_calls_including_warmup": primary_115k_calls,
        "primary_output_4096_calls": 1,
        "judge_calls": 5,
        "replication_calls": 3,
        "input_token_upper_bound": primary_115k_calls * PRIMARY_INPUT_TOKEN_TARGET
        + 4096
        + 5 * 2048
        + 3 * 4096,
        "output_token_upper_bound": primary_115k_calls * 512 + 4096 + 5 * 128 + 3 * 128,
        "may_not_be_used_as_formal_experiment_budget": True,
    }


def _build_cost_upper_bound(full_cost_inputs: Mapping[str, Any] | None = None) -> dict[str, Any]:
    required_inputs = [
        "real dataset checksum and primary eligible episode counts",
        "frozen split/budget/topology/repeat workload counts",
        "provider pricing for every frozen primary, judge, and replication model",
    ]
    artifact: dict[str, Any] = {
        "schema_version": "plan-robust-memory.cost-upper-bound.v2",
        "created_at": _now(),
        "status": "blocked",
        "scope": "full_experiment_upper_bound",
        "components": {
            name: {
                "status": "unknown",
                "call_upper_bound": None,
                "input_token_upper_bound": None,
                "output_token_upper_bound": None,
                "monetary_upper_bound": None,
            }
            for name in REQUIRED_COST_COMPONENTS
        },
        "probe_only_bound": _probe_only_bound(),
        "dataset_source": None,
        "dataset_checksum": None,
        "pricing_source": None,
        "currency": None,
        "monetary_upper_bound": None,
        "unknown_cost_not_zero": True,
        "required_inputs": required_inputs,
        "blocking_reasons": list(required_inputs),
    }
    if not isinstance(full_cost_inputs, Mapping):
        return artifact
    components = full_cost_inputs.get("components")
    dataset_checksum = full_cost_inputs.get("dataset_checksum")
    dataset_source = full_cost_inputs.get("dataset_source")
    pricing_source = full_cost_inputs.get("pricing_source")
    currency = full_cost_inputs.get("currency")
    if not (
        isinstance(components, Mapping)
        and dataset_checksum
        and dataset_source
        and pricing_source
        and currency
    ):
        return artifact
    normalized: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_COST_COMPONENTS:
        component = components.get(name)
        if not isinstance(component, Mapping):
            return artifact
        numeric_fields = (
            "call_upper_bound",
            "input_token_upper_bound",
            "output_token_upper_bound",
            "monetary_upper_bound",
        )
        if any(
            isinstance(component.get(field), bool)
            or not isinstance(component.get(field), (int, float))
            or float(component[field]) < 0
            for field in numeric_fields
        ):
            return artifact
        normalized[name] = {
            "status": "frozen",
            **{field: component[field] for field in numeric_fields},
        }
    artifact.update(
        {
            "status": "passed",
            "components": normalized,
            "dataset_source": str(dataset_source),
            "dataset_checksum": str(dataset_checksum),
            "pricing_source": str(pricing_source),
            "currency": str(currency),
            "monetary_upper_bound": sum(
                float(component["monetary_upper_bound"]) for component in normalized.values()
            ),
            "blocking_reasons": [],
        }
    )
    return artifact


def _unique_attempts(artifacts: Mapping[str, Mapping[str, Any]]) -> list[tuple[str, Mapping[str, Any]]]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[tuple[str, Mapping[str, Any]]] = []
    for name, artifact in artifacts.items():
        if name == "proxy_probe.json":
            continue
        for attempt in artifact.get("attempts", []):
            if not isinstance(attempt, Mapping):
                continue
            key = (
                attempt.get("url"),
                attempt.get("route"),
                attempt.get("phase"),
                attempt.get("concurrency"),
                attempt.get("call_index"),
                attempt.get("case_id"),
                attempt.get("request_id"),
                attempt.get("http_status"),
                attempt.get("error_type"),
                attempt.get("error"),
            )
            if key not in seen:
                seen.add(key)
                unique.append((name, attempt))
    return unique


def _completed_call_rows(artifacts: Mapping[str, Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for name in ("primary_115k_probe.json", "primary_output_probe.json", "replication_model_probe.json"):
        artifact = artifacts.get(name, {})
        warmup = artifact.get("warmup")
        if isinstance(warmup, Mapping):
            rows.append(warmup)
        rows.extend(row for row in artifact.get("calls", []) if isinstance(row, Mapping))
    rows.extend(
        row
        for row in artifacts.get("judge_probe.json", {}).get("cases", [])
        if isinstance(row, Mapping)
    )
    return rows


def _stall_root_cause(artifacts: Mapping[str, Mapping[str, Any]]) -> str:
    attempts = [attempt for _, attempt in _unique_attempts(artifacts)]
    statuses = {attempt.get("http_status") for attempt in attempts}
    errors = " ".join(str(attempt.get("error", "")) for attempt in attempts).lower()
    if 401 in statuses or 403 in statuses:
        return "API credential is missing, invalid, or lacks permission for the frozen provider/models."
    if "name or service not known" in errors or "dns" in errors:
        return "DNS resolution failed on both recorded routes."
    if "certificate" in errors or "ssl" in errors or "tls" in errors:
        return "TLS/certificate negotiation failed on the recorded routes."
    if "timed out" in errors or "timeout" in errors:
        return "The provider did not make progress within the finite direct/proxy timeouts."
    if attempts and all(not bool(attempt.get("success")) for attempt in attempts):
        return "No recorded HTTP route produced a successful provider response; inspect the classified errors below."
    embedding = artifacts.get("embedding_probe.json", {})
    if embedding.get("status") != "passed":
        return str(embedding.get("blocking_reason") or "Local embedding qualification did not pass.")
    if artifacts.get("cost_upper_bound.json", {}).get("status") != "passed":
        return "Real dataset-derived workload counts and/or provider pricing are not frozen."
    return "One or more Day 1 qualification artifacts failed; inspect the per-artifact evidence below."


def _write_stall_report(output_dir: Path, artifacts: Mapping[str, Mapping[str, Any]]) -> Path:
    stall_dir = output_dir / "stall_reports"
    stall_dir.mkdir(parents=True, exist_ok=True)
    path = stall_dir / f"stall_report_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.md"
    attempts = _unique_attempts(artifacts)
    attempt_lines = [
        f"- {name}: route={attempt.get('route')} success={attempt.get('success')} "
        f"status={attempt.get('http_status')} error_type={attempt.get('error_type')} "
        f"error={attempt.get('error')}"
        for name, attempt in attempts
    ]
    call_rows = _completed_call_rows(artifacts)
    input_tokens = sum(int(_usage(row)["input_tokens"] or 0) for row in call_rows)
    output_tokens = sum(int(_usage(row)["output_tokens"] or 0) for row in call_rows)
    usage_unknown_calls = sum(not _usage_available(row) for row in call_rows if row.get("http_success", row.get("success")))
    models = [
        PRIMARY_MODEL,
        JUDGE_MODEL,
        str(artifacts.get("model_inventory.json", {}).get("replication_model") or "replication model not frozen"),
        str(artifacts.get("embedding_probe.json", {}).get("model") or "BAAI/bge-m3"),
    ]
    error_types = sorted(
        {
            str(attempt.get("error_type") or f"HTTP_{attempt.get('http_status')}")
            for _, attempt in attempts
            if attempt.get("error_type") or attempt.get("http_status")
        }
    )
    root_cause = _stall_root_cause(artifacts)
    embedding_passed = artifacts.get("embedding_probe.json", {}).get("status") == "passed"
    candidate_paths = [
        "Resolve the provider/edge HTTP 400 or credential authorization scope, then rerun the same frozen direct→17897 command.",
        "Freeze and probe an explicit different-family replication snapshot from the authenticated inventory.",
    ]
    if not embedding_passed:
        candidate_paths.append(
            "Qualify the frozen BAAI/bge-m3 model/tokenizer revision on the local CUDA environment."
        )
    candidate_paths.append(
        "Provide real dataset-derived component workloads and dated provider pricing; otherwise keep the cost Gate blocked."
    )
    body = [
        "# Day 1 Gate stall report",
        "",
        f"Created: {_now()}",
        "",
        "- Current Gate: G-NETWORK / Day 1 model and embedding qualification",
        "- P14 triggered: true",
        "- Next milestone blocked: true",
        "",
        "## Models used",
        "",
        *(f"- {model}" for model in models),
        "",
        "## Sub-Gate status",
        "",
        f"- Hugging Face connectivity: {artifacts.get('proxy_probe.json', {}).get('status', 'unknown')}",
        f"- API model inventory: {artifacts.get('model_inventory.json', {}).get('status', 'unknown')}",
        f"- embedding: {artifacts.get('embedding_probe.json', {}).get('status', 'unknown')}",
        f"- replication model: {artifacts.get('replication_model_probe.json', {}).get('status', 'unknown')}",
        f"- full cost upper bound: {artifacts.get('cost_upper_bound.json', {}).get('status', 'unknown')}",
        "",
        "## Error classification",
        "",
        *(f"- {error_type}" for error_type in error_types or ["No HTTP error type recorded"]),
        "",
        "## Cumulative calls",
        "",
        f"- Logical model calls completed or attempted: {len(call_rows) + (1 if attempts else 0)}",
        f"- HTTP route attempts: {len(attempts)}",
        "",
        "## Cumulative tokens",
        "",
        f"- Recorded input tokens: {input_tokens}",
        f"- Recorded output tokens: {output_tokens}",
        f"- Successful calls with missing usage: {usage_unknown_calls}",
        "",
        "## Cumulative cost",
        "",
        "- Unknown; provider pricing and the full experiment workload are not frozen. Unknown is not recorded as zero.",
        "",
        "## Most likely root cause",
        "",
        f"- {root_cause}",
        "",
        "## Candidate paths",
        "",
        *(f"- {path}" for path in candidate_paths),
        "",
        "## User decision required",
        "",
        "- Decide whether to resolve the provider/API authorization or edge rejection condition and provide frozen pricing inputs, or keep Day 1 blocked.",
        "",
        "## Evidence",
        "",
        *(attempt_lines or ["- No successful endpoint attempt was recorded."]),
    ]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def run_day1_probe(
    output_dir: Path,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    replication_model: str | None = None,
    embedding_revision: str | None = None,
    full_cost_inputs: Mapping[str, Any] | None = None,
    timeout: float = 300.0,
    request_fn: RequestFn = http_json_request,
    embedding_probe_fn: Callable[[str, str | None], dict[str, Any]] | None = None,
    episode_probe: Mapping[str, Any] | None = None,
    hf_cache_dir: Path = DEFAULT_HF_HUB_CACHE,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
    if base_url != DEFAULT_BASE_URL:
        raise ValueError(f"canonical base URL is {DEFAULT_BASE_URL}")
    api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
    embedding_revision = embedding_revision or BGE_M3_REVISION
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    artifacts: dict[str, dict[str, Any]] = {}
    run_id = f"day1-{uuid.uuid4().hex}"
    run_started_at = _now()
    run_state_path = output_dir / RUN_STATE_NAME
    run_state = {
        "schema_version": "plan-robust-memory.day1-run-state.v1",
        "run_id": run_id,
        "state": "running",
        "status": "running",
        "started_at": run_started_at,
        "completed_at": None,
        "pid": os.getpid(),
        "base_url": base_url,
        "artifact_names": list(ARTIFACT_NAMES),
    }
    _write_json(run_state_path, run_state)
    for name in ARTIFACT_NAMES:
        _write_json(
            output_dir / name,
            {
                "schema_version": "plan-robust-memory.day1-artifact-state.v1",
                "artifact_name": name,
                "artifact_state": "pending",
                "status": "pending",
                "run_id": run_id,
                "run_started_at": run_started_at,
                "artifact_completed_at": None,
            },
        )

    def publish_artifact(name: str, value: Mapping[str, Any]) -> dict[str, Any]:
        artifact = dict(value)
        artifact.update(
            {
                "artifact_name": name,
                "artifact_state": "completed",
                "run_id": run_id,
                "run_started_at": run_started_at,
                "artifact_completed_at": _now(),
            }
        )
        artifacts[name] = artifact
        _write_json(output_dir / name, artifact)
        return artifact

    proxy = probe_huggingface_connectivity(
        request_fn=request_fn, timeout=min(timeout, 15.0)
    )
    inventory_response, inventory_attempts = request_with_fallback(request_fn, f"{base_url}/models", headers=headers, timeout=min(timeout, 60.0))
    proxy["api_inventory_attempts"] = inventory_attempts
    publish_artifact("proxy_probe.json", proxy)
    model_ids = sorted(str(row.get("id")) for row in (inventory_response or {}).get("data", []) if isinstance(row, Mapping) and row.get("id"))
    missing_required_models = [
        model_id for model_id in (PRIMARY_MODEL, JUDGE_MODEL) if model_id not in model_ids
    ]
    if inventory_response is None:
        inventory_reason = "model inventory failed through direct and proxy_17897 routes"
    elif missing_required_models:
        inventory_reason = "required models absent from authenticated inventory: " + ", ".join(
            missing_required_models
        )
    else:
        inventory_reason = None
    inventory = {
        "schema_version": "plan-robust-memory.model-inventory.v1",
        "created_at": _now(),
        "status": "passed" if inventory_reason is None else "blocked",
        "base_url": base_url,
        "endpoint": f"{base_url}/models",
        "request_protocol": "openai_compatible_models_inventory",
        "provider": "labforge",
        "credential_present": bool(api_key),
        "returned_model_ids": model_ids,
        "required_models": [PRIMARY_MODEL, JUDGE_MODEL],
        "missing_required_models": missing_required_models,
        "replication_model": replication_model,
        "blocking_reason": inventory_reason,
        "attempts": inventory_attempts,
    }
    publish_artifact("model_inventory.json", inventory)

    if inventory_reason is not None:
        reason = inventory_reason
        publish_artifact(
            "primary_115k_probe.json",
            _blocked_artifact("primary_115k", base_url, reason),
        )
        publish_artifact(
            "primary_output_probe.json",
            _blocked_artifact("primary_output", base_url, reason),
        )
        publish_artifact(
            "judge_probe.json", _blocked_artifact("judge", base_url, reason)
        )
        publish_artifact(
            "replication_model_probe.json",
            _blocked_artifact("replication", base_url, reason),
        )
    else:
        long_input = "probe " * 115000
        publish_artifact(
            "primary_115k_probe.json",
            _primary_115k_probe(
                request_fn=request_fn,
                base_url=base_url,
                headers=headers,
                input_text=long_input,
                timeout=timeout,
            ),
        )
        publish_artifact(
            "primary_output_probe.json",
            _model_probe(request_fn=request_fn, base_url=base_url, headers=headers, model=PRIMARY_MODEL, input_text="Return the word probe repeatedly within the requested output budget.", max_output_tokens=4096, repetitions=1, timeout=timeout, role="primary_output_4096"),
        )
        publish_artifact(
            "judge_probe.json",
            _judge_probe(
                request_fn=request_fn,
                base_url=base_url,
                headers=headers,
                timeout=timeout,
            ),
        )
        if replication_model and replication_model in model_ids and replication_model not in {PRIMARY_MODEL, JUDGE_MODEL}:
            publish_artifact(
                "replication_model_probe.json",
                _model_probe(request_fn=request_fn, base_url=base_url, headers=headers, model=replication_model, input_text="Constructor/merge/answer capability probe.", max_output_tokens=128, repetitions=3, timeout=timeout, role="replication_constructor_merge_answer"),
            )
        else:
            publish_artifact(
                "replication_model_probe.json",
                _blocked_artifact("replication", base_url, "explicit different-family replication model is missing or absent from inventory"),
            )

    if embedding_probe_fn is None:
        try:
            episode_probe = episode_probe or load_real_episode_probe()
            embedding_artifact = dict(
                probe_embedding(
                    BGE_M3_MODEL,
                    embedding_revision,
                    episode_probe=episode_probe,
                    hf_cache_dir=hf_cache_dir,
                )
            )
        except Exception as exc:
            embedding_artifact = dict(
                probe_embedding(
                    BGE_M3_MODEL,
                    embedding_revision,
                    episode_probe=None,
                    hf_cache_dir=hf_cache_dir,
                )
            )
            embedding_artifact["blocking_reason"] = (
                f"real LongMemEval episode probe could not be loaded: {type(exc).__name__}: {str(exc)[:500]}"
            )
    else:
        # Tests and explicitly injected qualification fixtures use the old
        # two-argument hook; they must still satisfy the full artifact contract.
        embedding_artifact = dict(embedding_probe_fn(BGE_M3_MODEL, embedding_revision))
    if not _embedding_qualified(embedding_artifact):
        embedding_artifact["status"] = "blocked"
        embedding_artifact.setdefault(
            "blocking_reason",
            "real encode plus deterministic ranking/packing and explicit model/tokenizer revisions are required",
        )
    publish_artifact("embedding_probe.json", embedding_artifact)
    publish_artifact(
        "cost_upper_bound.json", _build_cost_upper_bound(full_cost_inputs)
    )
    required_gate_names = (
        "model_inventory.json",
        "primary_115k_probe.json",
        "primary_output_probe.json",
        "judge_probe.json",
        "replication_model_probe.json",
        "embedding_probe.json",
        "cost_upper_bound.json",
    )
    passed = all(artifacts[name].get("status") == "passed" for name in required_gate_names)
    stall_path = None
    if not passed:
        stall_path = _write_stall_report(output_dir, artifacts)
    final_status = "passed" if passed else "blocked"
    run_state.update(
        {
            "state": "completed",
            "status": final_status,
            "completed_at": _now(),
            "stall_report": str(stall_path) if stall_path else None,
        }
    )
    _write_json(run_state_path, run_state)
    return {
        "status": final_status,
        "run_id": run_id,
        "run_state": str(run_state_path),
        "evidence": inspect_day1_run(output_dir),
        "routes": ["direct", "proxy_17897"],
        "output_dir": str(output_dir),
        "stall_report": str(stall_path) if stall_path else None,
        "full_leaf_generation_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the real Day 1 environment and model Gate")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/day1"))
    parser.add_argument("--base-url", default=None)
    parser.add_argument(
        "--hf-cache-dir",
        type=Path,
        default=DEFAULT_HF_HUB_CACHE,
        help="Ignored repo-local Hugging Face hub cache containing the frozen snapshot",
    )
    parser.add_argument("--replication-model", default=os.environ.get("REPLICATION_MODEL"))
    parser.add_argument(
        "--embedding-revision",
        default=os.environ.get("BGE_M3_REVISION") or BGE_M3_REVISION,
    )
    parser.add_argument(
        "--cost-inputs",
        type=Path,
        default=None,
        help="JSON with real dataset-derived full experiment components and dated provider pricing",
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args(argv)
    if args.embedding_revision != BGE_M3_REVISION:
        parser.error(f"BGE-M3 revision is frozen at {BGE_M3_REVISION}")
    full_cost_inputs = (
        json.loads(args.cost_inputs.read_text(encoding="utf-8")) if args.cost_inputs is not None else None
    )
    result = run_day1_probe(
        args.output_dir,
        base_url=args.base_url,
        replication_model=args.replication_model,
        embedding_revision=args.embedding_revision,
        full_cost_inputs=full_cost_inputs,
        timeout=args.timeout,
        hf_cache_dir=args.hf_cache_dir,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
