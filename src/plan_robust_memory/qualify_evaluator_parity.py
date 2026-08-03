from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.request
import uuid

from .contracts import ContractError
from .evaluator import (
    LONGMEMEVAL_OFFICIAL_SOURCE,
    MEMORYAGENTBENCH_OFFICIAL_SOURCE,
    exact_match_score,
    longmemeval_judge_prompt,
    substring_exact_match_score,
)
from .gates import FULL_LEAF_QUALIFICATION_SEQUENCE
from .hashing import stable_hash


OFFICIAL_DATED_JUDGE_MODEL = "gpt-4o-2024-08-06"
PROXY_URL = "http://127.0.0.1:17897"
PROMPT_HASH_FIXTURES = (
    ("single-session-user", False, "c973231683d914de5192e37a06cbd1ba0d16c3c5dad99d9fb1242708b6a624d6"),
    ("temporal-reasoning", False, "68eece862c1e5d18c997191d6dd816a9f56e5ec3b8d04502df332fa71fdb6484"),
    ("knowledge-update", False, "992fa870a148dc7958741db4e4d9590f0947b17e1516ecd8b6c6424fd38c6747"),
    ("single-session-preference", False, "cac49761fd13dbf5e46b602c9a23867a4c96ad11729ebeb1f9846f85aa2bd15b"),
    ("knowledge-update", True, "879152708d282cd7102c4a39182451ec48da2bd424d2e29cea52fbf045b59593"),
)


class EvaluatorParityError(ContractError):
    """Raised when the evaluator parity stage cannot be qualified."""


FetchFn = Callable[[str, str, float], bytes]
NowFn = Callable[[], str]


def _source_spec(name: str, source: Mapping[str, str]) -> dict[str, str]:
    commit = source["commit"]
    path = source["path"]
    repository = source["repository"]
    owner_and_repo = repository.removeprefix("https://github.com/")
    return {
        "name": name,
        "repository": repository,
        "commit": commit,
        "path": path,
        "url": f"https://raw.githubusercontent.com/{owner_and_repo}/{commit}/{path}",
        "sha256": source["sha256"],
    }


DEFAULT_SOURCE_SPECS = (
    _source_spec("longmemeval", LONGMEMEVAL_OFFICIAL_SOURCE),
    _source_spec("memoryagentbench", MEMORYAGENTBENCH_OFFICIAL_SOURCE),
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fetch_bytes(url: str, route: str, timeout: float) -> bytes:
    if route not in {"direct", "proxy_17897"}:
        raise EvaluatorParityError("source route must be direct or proxy_17897")
    proxy_handler = urllib.request.ProxyHandler(
        {} if route == "direct" else {"http": PROXY_URL, "https": PROXY_URL}
    )
    opener = urllib.request.build_opener(proxy_handler)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "plan-robust-memory-evaluator-parity/1.0"},
    )
    with opener.open(request, timeout=timeout) as response:
        return response.read()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _validate_day1_evidence(
    model_inventory: Mapping[str, Any], judge_probe: Mapping[str, Any]
) -> None:
    for name, artifact in (
        ("model inventory", model_inventory),
        ("judge probe", judge_probe),
    ):
        if artifact.get("status") != "passed" or artifact.get("artifact_state") != "completed":
            raise EvaluatorParityError(f"Day 1 {name} is not passed and completed")
    if model_inventory.get("run_id") != judge_probe.get("run_id"):
        raise EvaluatorParityError("model inventory and judge probe must belong to the same Day 1 run")
    if judge_probe.get("requested_model") != "gpt-5.5":
        raise EvaluatorParityError("project judge must remain frozen to requested model gpt-5.5")
    returned = judge_probe.get("returned_model")
    if returned != "gpt-5.5" or str(returned).endswith("-latest"):
        raise EvaluatorParityError("project judge returned model is not the frozen gpt-5.5 snapshot")
    if judge_probe.get("message_contract") != (
        "exactly_one_user_message_no_system_or_developer_message"
    ):
        raise EvaluatorParityError("project judge message contract is not injection-free")
    if judge_probe.get("parser_success_rate") != 1.0:
        raise EvaluatorParityError("Day 1 project judge parser probe did not fully pass")
    endpoint = str(judge_probe.get("endpoint", ""))
    if not endpoint.endswith("/chat/completions"):
        raise EvaluatorParityError("project judge must use the chat/completions endpoint")


def _fetch_and_verify_sources(
    source_specs: Sequence[Mapping[str, str]],
    *,
    fetch_fn: FetchFn,
    timeout: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for spec in source_specs:
        name = str(spec.get("name", ""))
        url = str(spec.get("url", ""))
        expected = str(spec.get("sha256", ""))
        if not name or not url or len(expected) != 64:
            raise EvaluatorParityError("official evaluator source spec is incomplete")
        attempts: list[dict[str, Any]] = []
        verified: dict[str, Any] | None = None
        for route in ("direct", "proxy_17897"):
            try:
                payload = fetch_fn(url, route, timeout)
                digest = hashlib.sha256(payload).hexdigest()
                attempt = {
                    "route": route,
                    "status": "fetched",
                    "bytes": len(payload),
                    "sha256": digest,
                    "checksum_match": digest == expected,
                }
                attempts.append(attempt)
                if digest != expected:
                    continue
                verified = {
                    "name": name,
                    "repository": spec.get("repository"),
                    "commit": spec.get("commit"),
                    "path": spec.get("path"),
                    "url": url,
                    "expected_sha256": expected,
                    "observed_sha256": digest,
                    "source_bytes": len(payload),
                    "successful_route": route,
                    "attempts": attempts,
                    "status": "passed",
                }
                break
            except (OSError, TimeoutError, urllib.error.URLError) as exc:
                attempts.append(
                    {
                        "route": route,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                    }
                )
        if verified is None:
            if any(attempt.get("checksum_match") is False for attempt in attempts):
                reason = "official evaluator source checksum mismatch through direct/proxy attempts"
            else:
                reason = "official evaluator source access failed through direct/proxy attempts"
            raise EvaluatorParityError(f"{name}: {reason}")
        results.append(verified)
    return results


def _deterministic_parity() -> dict[str, Any]:
    cases = [
        ("exact-article-punctuation", "exact", "quick brown fox", "The quick, brown fox!", 1),
        ("exact-negative", "exact", "Paris", "Lyon", 0),
        ("substring-positive", "substring", "Paris", "The answer is Paris.", 1),
        ("substring-direction", "substring", "The answer is Paris", "Paris", 0),
        ("substring-empty-output", "substring", "answer", "", 0),
        ("substring-multiple", "substring", ("Madrid", "Paris"), "Final answer: paris", 1),
    ]
    outputs: list[dict[str, Any]] = []
    for case_id, metric, reference, candidate, expected in cases:
        if metric == "exact":
            actual = exact_match_score(reference, candidate)
        else:
            actual = substring_exact_match_score(reference, candidate)
        outputs.append(
            {
                "case_id": case_id,
                "metric": metric,
                "expected": expected,
                "actual": actual,
                "passed": actual == expected,
            }
        )
    return {
        "status": "passed" if all(row["passed"] for row in outputs) else "blocked",
        "case_count": len(outputs),
        "cases": outputs,
    }


def _prompt_parity() -> dict[str, Any]:
    rows = []
    for task, abstention, expected in PROMPT_HASH_FIXTURES:
        prompt = longmemeval_judge_prompt(task, "Q", "A", "R", abstention=abstention)
        observed = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        rows.append(
            {
                "task": task,
                "abstention": abstention,
                "expected_sha256": expected,
                "observed_sha256": observed,
                "passed": observed == expected,
            }
        )
    return {
        "status": "passed" if all(row["passed"] for row in rows) else "blocked",
        "case_count": len(rows),
        "cases": rows,
    }


def _write_stall(output_dir: Path, *, now: str, run_id: str, reason: str) -> None:
    _write_json(
        output_dir / "evaluator_parity_stall.json",
        {
            "schema_version": "plan-robust-memory.evaluator-parity-stall.v1",
            "created_at": now,
            "run_id": run_id,
            "stage": "evaluator_parity",
            "status": "blocked",
            "reason": reason,
            "attempt_order": ["direct", "proxy_17897"],
            "full_leaf_generation_allowed": False,
            "next_action": "resolve source/provenance mismatch and rerun the same frozen parity command",
        },
    )


def run_evaluator_parity(
    *,
    output_dir: Path,
    model_inventory: Mapping[str, Any],
    judge_probe: Mapping[str, Any],
    source_specs: Sequence[Mapping[str, str]] = DEFAULT_SOURCE_SPECS,
    fetch_fn: FetchFn = _fetch_bytes,
    now_fn: NowFn = _now,
    timeout: float = 30.0,
) -> dict[str, Any]:
    now = now_fn()
    run_id = f"evaluator-parity-{uuid.uuid4().hex}"
    output_dir.mkdir(parents=True, exist_ok=True)
    run_state_path = output_dir / "evaluator_parity_run_state.json"
    protocol_state_path = output_dir / "protocol_qualification_state.json"
    _write_json(
        run_state_path,
        {
            "schema_version": "plan-robust-memory.evaluator-parity-run-state.v1",
            "run_id": run_id,
            "run_started_at": now,
            "state": "running",
            "current_stage": "source_and_wrapper_parity",
            "artifacts": {
                "evaluator_parity.json": {"state": "pending", "run_id": run_id},
                "evaluator_parity_stall.json": {"state": "pending", "run_id": run_id},
            },
            "full_leaf_generation_allowed": False,
        },
    )
    _write_json(
        protocol_state_path,
        {
            "schema_version": "plan-robust-memory.protocol-qualification-state.v1",
            "updated_at": now,
            "status": "in_progress",
            "qualification_sequence": list(FULL_LEAF_QUALIFICATION_SEQUENCE),
            "completed_stages": ["observability_freeze"],
            "current_stage": "evaluator_parity",
            "next_stage": "evaluator_parity",
            "protocol_tag": None,
            "acceptance_accessed": False,
            "full_leaf_generation_allowed": False,
        },
    )
    try:
        _validate_day1_evidence(model_inventory, judge_probe)
        source_checks = _fetch_and_verify_sources(
            source_specs, fetch_fn=fetch_fn, timeout=timeout
        )
        deterministic = _deterministic_parity()
        prompt_parity = _prompt_parity()
        if deterministic["status"] != "passed" or prompt_parity["status"] != "passed":
            raise EvaluatorParityError("local evaluator wrapper does not match frozen parity cases")

        model_ids = model_inventory.get("returned_model_ids")
        if not isinstance(model_ids, list) or any(not isinstance(item, str) for item in model_ids):
            raise EvaluatorParityError("Day 1 model inventory is missing returned_model_ids")
        official_available = OFFICIAL_DATED_JUDGE_MODEL in model_ids
        if official_available:
            raise EvaluatorParityError(
                "official dated judge is available; fixed-subset agreement audit is required before parity can pass"
            )
        official_compatibility = {
            "status": "unavailable_external_limitation",
            "requested_model": OFFICIAL_DATED_JUDGE_MODEL,
            "available_in_passed_day1_inventory": False,
            "inventory_run_id": model_inventory["run_id"],
            "inventory_artifact_hash": stable_hash(dict(model_inventory)),
            "compatibility_calls_made": 0,
            "fallback_used": False,
            "rolling_alias_used": False,
            "limitation": (
                "The official LongMemEval dated GPT-4o snapshot is absent from the passed provider "
                "inventory. The project judge remains gpt-5.5; scores cannot be represented as "
                "directly identical to official GPT-4o scores."
            ),
        }
        artifact = {
            "schema_version": "plan-robust-memory.evaluator-parity.v1",
            "created_at": now,
            "run_id": run_id,
            "stage": "evaluator_parity",
            "status": "passed",
            "evaluator_parity_passed": True,
            "official_source_checks": source_checks,
            "deterministic_evaluator_parity": deterministic,
            "longmemeval_prompt_parity": prompt_parity,
            "project_judge": {
                "requested_model": judge_probe["requested_model"],
                "returned_model": judge_probe["returned_model"],
                "endpoint": judge_probe["endpoint"],
                "message_contract": judge_probe["message_contract"],
                "day1_run_id": judge_probe["run_id"],
                "day1_artifact_hash": stable_hash(dict(judge_probe)),
                "day1_endpoint_probe_passed": True,
            },
            "official_compatibility": official_compatibility,
            "judge_repeatability_completed": False,
            "cache_qualification_completed": False,
            "saturation_01_completed": False,
            "acceptance_accessed": False,
            "full_leaf_generation_allowed": False,
            "next_stage": "judge_repeatability",
        }
        parity_path = output_dir / "evaluator_parity.json"
        _write_json(parity_path, artifact)
        parity_sha256 = hashlib.sha256(parity_path.read_bytes()).hexdigest()
        _write_json(
            run_state_path,
            {
                "schema_version": "plan-robust-memory.evaluator-parity-run-state.v1",
                "run_id": run_id,
                "run_started_at": now,
                "run_completed_at": now,
                "state": "completed",
                "current_stage": None,
                "artifacts": {
                    "evaluator_parity.json": {
                        "state": "completed",
                        "run_id": run_id,
                        "sha256": parity_sha256,
                    },
                    "evaluator_parity_stall.json": {
                        "state": "not_created",
                        "run_id": run_id,
                    },
                },
                "full_leaf_generation_allowed": False,
            },
        )
        state = {
            "schema_version": "plan-robust-memory.protocol-qualification-state.v1",
            "updated_at": now,
            "status": "in_progress",
            "qualification_sequence": list(FULL_LEAF_QUALIFICATION_SEQUENCE),
            "completed_stages": ["observability_freeze", "evaluator_parity"],
            "next_stage": "judge_repeatability",
            "protocol_tag": None,
            "artifacts": {
                "evaluator_parity": str(parity_path),
                "evaluator_parity_run_id": run_id,
                "evaluator_parity_sha256": parity_sha256,
            },
            "acceptance_accessed": False,
            "full_leaf_generation_allowed": False,
        }
        _write_json(protocol_state_path, state)
        stall_path = output_dir / "evaluator_parity_stall.json"
        if stall_path.exists():
            stall_path.unlink()
        return artifact
    except ContractError as exc:
        _write_stall(output_dir, now=now, run_id=run_id, reason=str(exc))
        _write_json(
            run_state_path,
            {
                "schema_version": "plan-robust-memory.evaluator-parity-run-state.v1",
                "run_id": run_id,
                "run_started_at": now,
                "run_completed_at": now,
                "state": "blocked",
                "current_stage": "evaluator_parity",
                "artifacts": {
                    "evaluator_parity.json": {
                        "state": "not_published_for_this_run",
                        "run_id": run_id,
                    },
                    "evaluator_parity_stall.json": {
                        "state": "completed",
                        "run_id": run_id,
                    },
                },
                "blocking_reason": str(exc),
                "full_leaf_generation_allowed": False,
            },
        )
        _write_json(
            protocol_state_path,
            {
                "schema_version": "plan-robust-memory.protocol-qualification-state.v1",
                "updated_at": now,
                "status": "blocked",
                "qualification_sequence": list(FULL_LEAF_QUALIFICATION_SEQUENCE),
                "completed_stages": ["observability_freeze"],
                "current_stage": "evaluator_parity",
                "next_stage": "evaluator_parity",
                "protocol_tag": None,
                "blocking_run_id": run_id,
                "acceptance_accessed": False,
                "full_leaf_generation_allowed": False,
            },
        )
        raise


def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise EvaluatorParityError(f"{path} must contain a JSON object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Qualify deterministic and official-source evaluator parity"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/qualification")
    )
    parser.add_argument(
        "--model-inventory",
        type=Path,
        default=Path("artifacts/day1/model_inventory.json"),
    )
    parser.add_argument(
        "--judge-probe",
        type=Path,
        default=Path("artifacts/day1/judge_probe.json"),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    artifact = run_evaluator_parity(
        output_dir=args.output_dir,
        model_inventory=_load_json(args.model_inventory),
        judge_probe=_load_json(args.judge_probe),
        timeout=args.timeout,
    )
    print(json.dumps({"status": artifact["status"], "next_stage": artifact["next_stage"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
