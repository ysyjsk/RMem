from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.qualify_evaluator_parity import run_evaluator_parity


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _inventory() -> dict:
    return {
        "status": "passed",
        "artifact_state": "completed",
        "run_id": "day1-run",
        "returned_model_ids": ["gpt-5.5", "gpt-5.6-sol"],
    }


def _judge_probe() -> dict:
    return {
        "status": "passed",
        "artifact_state": "completed",
        "run_id": "day1-run",
        "requested_model": "gpt-5.5",
        "returned_model": "gpt-5.5",
        "endpoint": "https://api.labforge.cc/v1/chat/completions",
        "message_contract": "exactly_one_user_message_no_system_or_developer_message",
        "parser_success_rate": 1.0,
    }


def test_evaluator_parity_gate_uses_direct_then_proxy_and_records_external_limit(
    tmp_path: Path,
) -> None:
    payloads = {"longmemeval": b"official-long", "memoryagentbench": b"official-memory"}
    source_specs = [
        {
            "name": name,
            "url": f"https://official.invalid/{name}.py",
            "sha256": _sha256(payload),
            "commit": f"commit-{name}",
            "path": f"src/{name}.py",
        }
        for name, payload in payloads.items()
    ]
    calls: list[tuple[str, str]] = []

    def fetch(url: str, route: str, timeout: float) -> bytes:
        del timeout
        name = url.rsplit("/", 1)[-1].removesuffix(".py")
        calls.append((name, route))
        if name == "longmemeval" and route == "direct":
            raise OSError("fixture direct failure")
        return payloads[name]

    artifact = run_evaluator_parity(
        output_dir=tmp_path,
        model_inventory=_inventory(),
        judge_probe=_judge_probe(),
        source_specs=source_specs,
        fetch_fn=fetch,
        now_fn=lambda: "2026-08-03T12:00:00Z",
    )

    assert calls == [
        ("longmemeval", "direct"),
        ("longmemeval", "proxy_17897"),
        ("memoryagentbench", "direct"),
    ]
    assert artifact["status"] == "passed"
    assert artifact["evaluator_parity_passed"] is True
    assert artifact["official_compatibility"]["status"] == "unavailable_external_limitation"
    assert artifact["official_compatibility"]["fallback_used"] is False
    assert artifact["judge_repeatability_completed"] is False
    assert artifact["full_leaf_generation_allowed"] is False
    run_state = json.loads(
        (tmp_path / "evaluator_parity_run_state.json").read_text(encoding="utf-8")
    )
    assert run_state["state"] == "completed"
    assert run_state["run_id"] == artifact["run_id"]
    assert run_state["artifacts"]["evaluator_parity.json"]["run_id"] == artifact["run_id"]

    state = json.loads(
        (tmp_path / "protocol_qualification_state.json").read_text(encoding="utf-8")
    )
    assert state["completed_stages"] == ["observability_freeze", "evaluator_parity"]
    assert state["next_stage"] == "judge_repeatability"
    assert state["full_leaf_generation_allowed"] is False


def test_evaluator_parity_source_hash_mismatch_fails_closed_and_writes_stall(
    tmp_path: Path,
) -> None:
    source_specs = [
        {
            "name": "longmemeval",
            "url": "https://official.invalid/longmemeval.py",
            "sha256": "0" * 64,
            "commit": "commit-longmemeval",
            "path": "src/longmemeval.py",
        }
    ]

    with pytest.raises(ContractError, match="checksum"):
        run_evaluator_parity(
            output_dir=tmp_path,
            model_inventory=_inventory(),
            judge_probe=_judge_probe(),
            source_specs=source_specs,
            fetch_fn=lambda url, route, timeout: b"wrong-source",
            now_fn=lambda: "2026-08-03T12:00:00Z",
        )

    stall = json.loads(
        (tmp_path / "evaluator_parity_stall.json").read_text(encoding="utf-8")
    )
    assert stall["status"] == "blocked"
    assert stall["full_leaf_generation_allowed"] is False
    run_state = json.loads(
        (tmp_path / "evaluator_parity_run_state.json").read_text(encoding="utf-8")
    )
    assert run_state["state"] == "blocked"
    assert run_state["run_id"] == stall["run_id"]
    assert not (tmp_path / "evaluator_parity.json").exists()


def test_evaluator_parity_rejects_day1_cross_run_artifacts(tmp_path: Path) -> None:
    judge = _judge_probe()
    judge["run_id"] = "other-run"
    with pytest.raises(ContractError, match="same Day 1 run"):
        run_evaluator_parity(
            output_dir=tmp_path,
            model_inventory=_inventory(),
            judge_probe=judge,
            source_specs=[],
            fetch_fn=lambda url, route, timeout: b"",
            now_fn=lambda: "2026-08-03T12:00:00Z",
        )
