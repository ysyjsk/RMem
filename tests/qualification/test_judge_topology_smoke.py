from __future__ import annotations

import json
from pathlib import Path

import pytest

from plan_robust_memory.contracts import ContractError
from plan_robust_memory.qualify_judge_repeatability import CHAT_COMPLETIONS_URL
from plan_robust_memory.judge_topology_smoke import run_judge_topology_smoke


def _calibration_artifact() -> dict:
    return {
        "schema_version": "plan-robust-memory.longmemeval-calibration-split.v1",
        "source_split": "calibration",
        "acceptance_payload_exported": False,
        "episodes": [
            {
                "episode_id": "ep-001",
                "question_type": "knowledge-update",
                "query": {
                    "query_id": "q-001",
                    "question_text": "Where do I keep my old sneakers now?",
                    "gold_answer": "in a shoe rack in my closet",
                },
            }
        ],
    }


def _response(label: int, request_id: str) -> tuple[dict, dict]:
    response = {
        "id": request_id,
        "model": "gpt-5.6-luna",
        "choices": [
            {
                "message": {"content": json.dumps({"label": label})},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 3,
            "prompt_tokens_details": {"cached_tokens": 0},
        },
    }
    return response, {
        "http_status": 200,
        "request_id": request_id,
        "response_hash": "a" * 64,
    }


def test_smoke_uses_pure_chat_completions_user_payload(tmp_path: Path) -> None:
    captured: list[tuple[str, dict, str]] = []

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        del headers, timeout
        captured.append((url, payload, route))
        prompt = payload["messages"][0]["content"]
        label = 0 if "UNRELATED_TO_REFERENCE" in prompt else 1
        return _response(label, f"request-{len(captured)}")

    artifact = run_judge_topology_smoke(
        calibration_artifact=_calibration_artifact(),
        output_dir=tmp_path,
        api_key="secret",
        request_fn=request,
        now_fn=lambda: "2026-08-04T00:00:00Z",
    )

    assert artifact["status"] == "completed"
    assert artifact["candidate_pair_count"] == 1
    assert artifact["summary"]["paired_effect_proxy"] == 1.0
    assert artifact["next_stage"] == "judge_repeatability"
    assert artifact["full_leaf_generation_allowed"] is False
    assert artifact["interpretation_limit"] == "diagnostic_smoke_not_gate"

    assert len(captured) == 2
    for url, payload, route in captured:
        assert url == CHAT_COMPLETIONS_URL
        assert route == "direct"
        assert payload["model"] == "gpt-5.6-luna"
        assert payload["stream"] is False
        assert payload["max_tokens"] == 128
        assert "response_format" not in payload
        assert list(payload) == ["model", "messages", "temperature", "max_tokens", "stream"]
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"
        assert "system" not in {message.get("role") for message in payload["messages"]}
        assert "developer" not in {message.get("role") for message in payload["messages"]}

    written = json.loads((tmp_path / "judge_topology_smoke.json").read_text())
    assert written["run_id"] == artifact["run_id"]
    assert written["request_contract"]["message_contract"] == (
        "exactly_one_user_message_no_system_or_developer_message"
    )


def test_smoke_can_override_judge_model_without_system_prompt(tmp_path: Path) -> None:
    captured: list[dict] = []

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        del url, headers, route, timeout
        captured.append(payload)
        prompt = payload["messages"][0]["content"]
        label = 0 if "UNRELATED_TO_REFERENCE" in prompt else 1
        response = {
            "id": f"request-{len(captured)}",
            "model": payload["model"],
            "choices": [
                {
                    "message": {"content": json.dumps({"label": label})},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 3,
                "prompt_tokens_details": {"cached_tokens": 0},
            },
        }
        return response, {
            "http_status": 200,
            "request_id": response["id"],
            "response_hash": "b" * 64,
        }

    artifact = run_judge_topology_smoke(
        calibration_artifact=_calibration_artifact(),
        output_dir=tmp_path,
        api_key="secret",
        request_fn=request,
        now_fn=lambda: "2026-08-04T00:00:00Z",
        judge_model="5.6Luna",
    )

    assert {payload["model"] for payload in captured} == {"5.6Luna"}
    assert all(len(payload["messages"]) == 1 for payload in captured)
    assert all(payload["messages"][0]["role"] == "user" for payload in captured)
    assert artifact["request_contract"]["model"] == "5.6Luna"
    assert {row["requested_model"] for row in artifact["attempts"]} == {"5.6Luna"}
    assert {row["requested_model"] for row in artifact["observations"]} == {"5.6Luna"}
    assert {row["returned_model"] for row in artifact["observations"]} == {"5.6Luna"}


def test_smoke_records_direct_failure_then_proxy_success(tmp_path: Path) -> None:
    calls: list[str] = []

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        del url, payload, headers, timeout
        calls.append(route)
        if route == "direct":
            raise OSError("direct unavailable")
        label = 0 if len(calls) <= 2 else 1
        return _response(label, f"request-{len(calls)}")

    artifact = run_judge_topology_smoke(
        calibration_artifact=_calibration_artifact(),
        output_dir=tmp_path,
        api_key="secret",
        request_fn=request,
        now_fn=lambda: "2026-08-04T00:00:00Z",
    )

    assert calls == ["direct", "proxy_17897", "direct", "proxy_17897"]
    assert [row["status"] for row in artifact["transport_attempts"]] == [
        "failed",
        "completed",
        "failed",
        "completed",
    ]
    failed = [row for row in artifact["attempts"] if row["attempt_outcome"] == "failed_provider"]
    assert len(failed) == 2
    assert all(row["returned_model"] is None for row in failed)
    assert all(row["request_id"] is None for row in failed)
    assert all(row["provider_route"] == "direct" for row in failed)


def test_smoke_rejects_non_calibration_or_acceptance_export() -> None:
    artifact = _calibration_artifact()
    artifact["source_split"] = "acceptance"
    with pytest.raises(ContractError, match="calibration-only"):
        run_judge_topology_smoke(
            calibration_artifact=artifact,
            output_dir=Path("/tmp/not-used"),
            api_key="secret",
            request_fn=lambda *args: _response(1, "request"),
        )


def test_smoke_selects_only_answerable_calibration_episodes(tmp_path: Path) -> None:
    artifact = _calibration_artifact()
    artifact["episodes"].insert(
        0,
        {
            "episode_id": "ep-000",
            "question_type": "knowledge-update",
            "query": {
                "query_id": "q-000",
                "question_text": "Missing answer case",
                "gold_answer": "",
            },
        },
    )

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        del url, headers, route, timeout
        prompt = payload["messages"][0]["content"]
        label = 0 if "UNRELATED_TO_REFERENCE" in prompt else 1
        return _response(label, "request-ok")

    result = run_judge_topology_smoke(
        calibration_artifact=artifact,
        output_dir=tmp_path,
        api_key="secret",
        request_fn=request,
    )

    assert result["candidate_pair_count"] == 1
    assert result["source_episode_count"] == 2
    assert result["eligible_episode_count"] == 1
    assert result["skipped_episode_count"] == 1
