from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


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
DEFAULT_BASE_URL = "https://api.labforge.cc/v1"
PRIMARY_MODEL = "gpt-5.6-sol"
JUDGE_MODEL = "gpt-5.5"
PROXY_URL = "http://127.0.0.1:17897"
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


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


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
        first_byte = response.read(1)
        ttft_seconds = round(time.monotonic() - started, 3)
        raw = first_byte + response.read()
        status = int(getattr(response, "status", 200))
        response_headers = {key.lower(): value for key, value in response.headers.items()}
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
    }
    return parsed, metadata


def _error_attempt(route: str, url: str, exc: Exception, elapsed: float) -> dict[str, Any]:
    return {
        "route": route,
        "url": url,
        "success": False,
        "http_status": exc.code if isinstance(exc, urllib.error.HTTPError) else None,
        "elapsed_seconds": round(elapsed, 3),
        "error_type": type(exc).__name__,
        "error": str(exc)[:500],
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


def _usage(response: Mapping[str, Any] | None) -> dict[str, int | None]:
    usage = response.get("usage", {}) if isinstance(response, Mapping) else {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens")) if isinstance(usage, Mapping) else None
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens")) if isinstance(usage, Mapping) else None
    return {"input_tokens": int(input_tokens) if isinstance(input_tokens, (int, float)) else None, "output_tokens": int(output_tokens) if isinstance(output_tokens, (int, float)) else None}


def _usage_available(response: Mapping[str, Any] | None) -> bool:
    usage = _usage(response)
    return usage["input_tokens"] is not None and usage["output_tokens"] is not None


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
        payload = {"model": model, "input": input_text, "max_output_tokens": max_output_tokens, "stream": False}
        response, attempts = request_with_fallback(request_fn, f"{base_url}/responses", method="POST", payload=payload, headers=headers, timeout=timeout)
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
        f"{base_url}/responses",
        method="POST",
        payload={"model": PRIMARY_MODEL, "input": prompt, "max_output_tokens": 512, "stream": False},
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
            f"{base_url}/responses",
            method="POST",
            payload={
                "model": JUDGE_MODEL,
                "input": prompt,
                "max_output_tokens": 128,
                "temperature": 0,
                "stream": False,
            },
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
        "endpoint": f"{base_url}/responses",
        "decoding_parameters": {"temperature": 0, "max_output_tokens": 128, "stream": False},
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


def _greedy_pack(rankings: Sequence[Sequence[int]], documents: Sequence[str], budget_tokens: int = 12) -> list[list[int]]:
    packed: list[list[int]] = []
    for ranking in rankings:
        remaining = budget_tokens
        selected: list[int] = []
        for index in ranking:
            token_estimate = max(1, len(documents[index].split()))
            if token_estimate <= remaining:
                selected.append(index)
                remaining -= token_estimate
        packed.append(selected)
    return packed


def _explicit_revision(revision: str | None) -> bool:
    return bool(revision and revision.strip().lower() not in {"main", "master", "latest"})


def probe_embedding(
    model: str = "BAAI/bge-m3",
    revision: str | None = None,
    *,
    torch_module: Any | None = None,
    sentence_transformer_cls: Any | None = None,
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
        "torch_available": torch_available,
        "sentence_transformers_available": sentence_transformers_available,
        "cuda_available": False,
        "device_name": None,
        "vram_bytes": None,
        "embedding_executed": False,
        "encode_run_count": 0,
        "ranking_deterministic": False,
        "packing_deterministic": False,
        "single_episode_embedding_latency_seconds": None,
        "estimated_500_instance_index_seconds": None,
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
        encoder = sentence_transformer_cls(model, revision=revision, device="cuda")
        documents = [
            "alpha project deadline is Monday",
            "beta recipe uses basil and garlic",
            "alpha meeting moved to Tuesday",
            "beta travel reservation is Friday",
        ]
        queries = ["alpha project schedule", "beta recipe and travel"]
        texts = documents + queries
        ranking_runs: list[list[list[int]]] = []
        packing_runs: list[list[list[int]]] = []
        latencies: list[float] = []
        for _ in range(2):
            started = time.monotonic()
            vectors = _vectors_as_lists(
                encoder.encode(
                    texts,
                    batch_size=len(texts),
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
            )
            latencies.append(time.monotonic() - started)
            if len(vectors) != len(texts):
                raise ValueError("embedding output row count does not match probe text count")
            rankings = _rank_documents(vectors[: len(documents)], vectors[len(documents) :])
            ranking_runs.append(rankings)
            packing_runs.append(_greedy_pack(rankings, documents))
        artifact["embedding_executed"] = True
        artifact["encode_run_count"] = 2
        artifact["ranking_runs"] = ranking_runs
        artifact["packing_runs"] = packing_runs
        artifact["ranking_deterministic"] = ranking_runs[0] == ranking_runs[1]
        artifact["packing_deterministic"] = packing_runs[0] == packing_runs[1]
        artifact["single_episode_embedding_latency_seconds"] = round(sum(latencies) / len(latencies), 6)
        artifact["estimated_500_instance_index_seconds"] = round(
            artifact["single_episode_embedding_latency_seconds"] * 500,
            3,
        )
        if artifact["ranking_deterministic"] and artifact["packing_deterministic"]:
            artifact["status"] = "passed"
        else:
            artifact["blocking_reason"] = "query ranking or greedy packing changed across repeated encodes"
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
        and artifact.get("embedding_executed") is True
        and int(artifact.get("encode_run_count", 0)) >= 2
        and artifact.get("ranking_deterministic") is True
        and artifact.get("packing_deterministic") is True
    )


def _blocked_artifact(role: str, base_url: str, reason: str, attempts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"schema_version": "plan-robust-memory.day1-probe.v1", "created_at": _now(), "status": "blocked", "role": role, "base_url": base_url, "blocking_reason": reason, "attempts": attempts or []}


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
        "- Restore or provide an authorized credential, then rerun the same frozen direct→17897 command.",
        "- Freeze a different-family replication snapshot and the BAAI/bge-m3 model/tokenizer revision.",
        "- Provide real dataset-derived component workloads and dated provider pricing; otherwise keep the cost Gate blocked.",
        "",
        "## User decision required",
        "",
        "- Decide whether to provide/authorize the missing credential and frozen revisions/pricing inputs, or keep Day 1 blocked.",
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
    embedding_probe_fn: Callable[[str, str | None], dict[str, Any]] = probe_embedding,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    artifacts: dict[str, dict[str, Any]] = {}

    inventory_response, inventory_attempts = request_with_fallback(request_fn, f"{base_url}/models", headers=headers, timeout=min(timeout, 60.0))
    proxy = {"schema_version": "plan-robust-memory.proxy-probe.v1", "created_at": _now(), "status": "passed" if inventory_response is not None else "blocked", "proxy_url": PROXY_URL, "attempt_order": ["direct", "proxy_17897"], "attempts": inventory_attempts}
    artifacts["proxy_probe.json"] = proxy
    model_ids = sorted(str(row.get("id")) for row in (inventory_response or {}).get("data", []) if isinstance(row, Mapping) and row.get("id"))
    inventory = {"schema_version": "plan-robust-memory.model-inventory.v1", "created_at": _now(), "status": "passed" if inventory_response is not None else "blocked", "base_url": base_url, "provider": "labforge", "credential_present": bool(api_key), "returned_model_ids": model_ids, "required_models": [PRIMARY_MODEL, JUDGE_MODEL], "replication_model": replication_model, "attempts": inventory_attempts}
    artifacts["model_inventory.json"] = inventory

    if inventory_response is None:
        reason = "model inventory failed through direct and proxy_17897 routes"
        artifacts["primary_115k_probe.json"] = _blocked_artifact("primary_115k", base_url, reason)
        artifacts["primary_output_probe.json"] = _blocked_artifact("primary_output", base_url, reason)
        artifacts["judge_probe.json"] = _blocked_artifact("judge", base_url, reason)
        artifacts["replication_model_probe.json"] = _blocked_artifact("replication", base_url, reason)
    else:
        long_input = "probe " * 115000
        artifacts["primary_115k_probe.json"] = _primary_115k_probe(
            request_fn=request_fn,
            base_url=base_url,
            headers=headers,
            input_text=long_input,
            timeout=timeout,
        )
        artifacts["primary_output_probe.json"] = _model_probe(request_fn=request_fn, base_url=base_url, headers=headers, model=PRIMARY_MODEL, input_text="Return the word probe repeatedly within the requested output budget.", max_output_tokens=4096, repetitions=1, timeout=timeout, role="primary_output_4096")
        artifacts["judge_probe.json"] = _judge_probe(request_fn=request_fn, base_url=base_url, headers=headers, timeout=timeout)
        if replication_model and replication_model in model_ids and replication_model not in {PRIMARY_MODEL, JUDGE_MODEL}:
            artifacts["replication_model_probe.json"] = _model_probe(request_fn=request_fn, base_url=base_url, headers=headers, model=replication_model, input_text="Constructor/merge/answer capability probe.", max_output_tokens=128, repetitions=3, timeout=timeout, role="replication_constructor_merge_answer")
        else:
            artifacts["replication_model_probe.json"] = _blocked_artifact("replication", base_url, "explicit different-family replication model is missing or absent from inventory")

    embedding_artifact = dict(embedding_probe_fn("BAAI/bge-m3", embedding_revision))
    if not _embedding_qualified(embedding_artifact):
        embedding_artifact["status"] = "blocked"
        embedding_artifact.setdefault(
            "blocking_reason",
            "real encode plus deterministic ranking/packing and explicit model/tokenizer revisions are required",
        )
    artifacts["embedding_probe.json"] = embedding_artifact
    artifacts["cost_upper_bound.json"] = _build_cost_upper_bound(full_cost_inputs)

    for name in ARTIFACT_NAMES:
        _write_json(output_dir / name, artifacts[name])
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
    return {"status": "passed" if passed else "blocked", "routes": ["direct", "proxy_17897"], "output_dir": str(output_dir), "stall_report": str(stall_path) if stall_path else None, "full_leaf_generation_allowed": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the real Day 1 environment and model Gate")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/day1"))
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--replication-model", default=os.environ.get("REPLICATION_MODEL"))
    parser.add_argument("--embedding-revision", default=os.environ.get("BGE_M3_REVISION"))
    parser.add_argument(
        "--cost-inputs",
        type=Path,
        default=None,
        help="JSON with real dataset-derived full experiment components and dated provider pricing",
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args(argv)
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
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
