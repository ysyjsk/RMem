from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import urllib.error

import pytest

import plan_robust_memory.qualify_judge_repeatability as judge_module
from plan_robust_memory.contracts import ContractError
from plan_robust_memory.evaluator import JUDGE_REPEATABILITY_CATEGORY_COUNTS
from plan_robust_memory.hashing import stable_hash
from plan_robust_memory.observability import validate_accepted_output_bindings
from plan_robust_memory.qualify_judge_repeatability import (
    build_case_manifest,
    derive_repeatability_observations,
    main,
    materialize_calibration_split,
    prepare_and_run_judge_repeatability,
    run_judge_repeatability,
    validate_calibration_split_artifact,
    validate_case_manifest,
)


def _audit_and_episodes() -> tuple[dict, list[dict]]:
    episodes: list[dict] = []
    assignments: list[dict] = []
    task_cycle = (
        "single-session-user",
        "single-session-assistant",
        "multi-session",
        "single-session-preference",
        "temporal-reasoning",
        "knowledge-update",
    )
    for index in range(90):
        episode_id = f"ep-{index:03d}"
        task = task_cycle[index % len(task_cycle)]
        episodes.append(
            {
                "episode_id": episode_id,
                "question_type": task,
                "query": {
                    "query_id": episode_id,
                    "question_text": f"Question {index}?",
                    "gold_answer": f"answer part {index}, second detail {index}",
                    "evaluator_id": "longmemeval-compatible",
                },
                "primary_eligible": task in {"temporal-reasoning", "knowledge-update"},
            }
        )
        assignments.append(
            {
                "group_id": f"group-{index:03d}",
                "episode_ids": [episode_id],
                "leakage_relations": [],
                "split": "calibration",
            }
        )
    episodes.append(
        {
            "episode_id": "acceptance-secret",
            "question_type": "knowledge-update",
            "query": {
                "query_id": "acceptance-secret",
                "question_text": "SECRET ACCEPTANCE QUESTION",
                "gold_answer": "SECRET ACCEPTANCE ANSWER",
                "evaluator_id": "longmemeval-compatible",
            },
            "primary_eligible": True,
        }
    )
    assignments.append(
        {
            "group_id": "group-acceptance",
            "episode_ids": ["acceptance-secret"],
            "leakage_relations": [],
            "split": "acceptance",
        }
    )
    audit = {
        "schema_version": "plan-robust-memory.longmemeval-audit.v1",
        "status": "qualified_with_exclusions",
        "no_silent_drop": True,
        "source_revision": "fixture-revision",
        "raw_checksums": {"fixture.json": {"sha256": "a" * 64}},
        "split_candidates": [
            {
                "candidate_id": "20_30_50",
                "ratio": {"development": 0.2, "calibration": 0.3, "acceptance": 0.5},
                "assignment_hash": "b" * 64,
                "assignments": assignments,
            }
        ],
    }
    audit["audit_hash"] = stable_hash(audit)
    return audit, episodes


def _power(audit: dict) -> dict:
    artifact = {
        "schema_version": "plan-robust-memory.power-gate.v2",
        "status": "passed",
        "input_audit_hash": audit["audit_hash"],
        "split_ratio": {"development": 0.2, "calibration": 0.3, "acceptance": 0.5},
        "split_assignment_hash": "b" * 64,
        "primary_eligible_categories": ["knowledge-update", "temporal-reasoning"],
        "delta_decision": 0.1,
        "hard_no_go_available": True,
    }
    artifact["artifact_hash"] = stable_hash(artifact)
    return artifact


def _manifest() -> dict:
    audit, episodes = _audit_and_episodes()
    return build_case_manifest(
        audit=audit,
        power_artifact=_power(audit),
        normalized_episodes=episodes[:-1],
    )


def _inventory() -> dict:
    return {
        "artifact_name": "model_inventory.json",
        "status": "passed",
        "artifact_state": "completed",
        "run_id": "day1-run",
        "returned_model_ids": ["gpt-5.5", "gpt-5.6-sol"],
    }


def _judge_probe() -> dict:
    return {
        "artifact_name": "judge_probe.json",
        "status": "passed",
        "artifact_state": "completed",
        "run_id": "day1-run",
        "requested_model": "gpt-5.5",
        "returned_model": "gpt-5.5",
        "provider": "labforge",
        "base_url": "https://api.labforge.cc/v1",
        "endpoint": "https://api.labforge.cc/v1/chat/completions",
        "message_contract": "exactly_one_user_message_no_system_or_developer_message",
        "parser_success_rate": 1.0,
    }


def _parity() -> dict:
    return {
        "schema_version": "plan-robust-memory.evaluator-parity.v1",
        "status": "passed",
        "evaluator_parity_passed": True,
        "run_id": "parity-run",
        "project_judge": {
            "requested_model": "gpt-5.5",
            "returned_model": "gpt-5.5",
            "day1_run_id": "day1-run",
            "endpoint": "https://api.labforge.cc/v1/chat/completions",
            "message_contract": "exactly_one_user_message_no_system_or_developer_message",
            "day1_artifact_hash": stable_hash(_judge_probe()),
        },
        "official_compatibility": {
            "inventory_run_id": "day1-run",
            "inventory_artifact_hash": stable_hash(_inventory()),
        },
        "next_stage": "judge_repeatability",
    }


def _protocol_state() -> dict:
    return {
        "schema_version": "plan-robust-memory.protocol-qualification-state.v1",
        "status": "in_progress",
        "qualification_sequence": [
            "observability_freeze",
            "evaluator_parity",
            "judge_repeatability",
            "cache_qualification",
            "saturation_01",
            "final_judge_budget_freeze",
            "eval_protocol_v1_0",
            "q0_d_leaf_micro_run",
        ],
        "completed_stages": ["observability_freeze", "evaluator_parity"],
        "next_stage": "judge_repeatability",
        "acceptance_accessed": False,
        "full_leaf_generation_allowed": False,
        "artifacts": {
            "evaluator_parity": "fixture",
            "evaluator_parity_run_id": "parity-run",
            "evaluator_parity_sha256": "d" * 64,
        },
    }


def _day1_run_state() -> dict:
    names = [
        "proxy_probe.json",
        "model_inventory.json",
        "primary_115k_probe.json",
        "primary_output_probe.json",
        "judge_probe.json",
        "replication_model_probe.json",
        "embedding_probe.json",
        "cost_upper_bound.json",
    ]
    return {
        "schema_version": "plan-robust-memory.day1-run-state.v1",
        "state": "completed",
        "status": "passed",
        "run_id": "day1-run",
        "artifact_names": names,
    }


def _day1_artifacts() -> dict[str, dict]:
    names = _day1_run_state()["artifact_names"]
    result = {
        name: {
            "artifact_name": name,
            "artifact_state": "completed",
            "status": "passed",
            "run_id": "day1-run",
        }
        for name in names
    }
    result["model_inventory.json"] = _inventory()
    result["judge_probe.json"] = _judge_probe()
    return result


def _parity_run_state() -> dict:
    return {
        "schema_version": "plan-robust-memory.evaluator-parity-run-state.v1",
        "state": "completed",
        "run_id": "parity-run",
        "artifacts": {
            "evaluator_parity.json": {
                "state": "completed",
                "run_id": "parity-run",
                "sha256": "d" * 64,
            }
        },
    }


def _upstream_kwargs(*, judge_probe: dict | None = None, protocol_state: dict | None = None) -> dict:
    return {
        "day1_run_state": _day1_run_state(),
        "day1_artifacts": _day1_artifacts(),
        "evaluator_parity_run_state": _parity_run_state(),
        "evaluator_parity_sha256": "d" * 64,
    }


def _response(label: int, call_number: int) -> tuple[dict, dict]:
    content = json.dumps({"label": label}, separators=(",", ":"))
    response = {
        "id": f"request-{call_number}",
        "model": "gpt-5.5",
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 5},
    }
    return response, {
        "http_status": 200,
        "request_id": response["id"],
        "response_hash": hashlib.sha256(
            json.dumps(response, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_preflight_inputs(root: Path) -> dict[str, Path]:
    longmemeval_dir = root / "longmemeval"
    power_dir = root / "power"
    qualification_dir = root / "qualification-input"
    day1_dir = root / "day1"
    for directory in (longmemeval_dir, power_dir, qualification_dir, day1_dir):
        directory.mkdir(parents=True, exist_ok=True)

    audit, episodes = _audit_and_episodes()
    power = _power(audit)
    calibration = materialize_calibration_split(
        audit=audit,
        power_artifact=power,
        normalized_episodes=episodes,
        source_normalized_sha256="c" * 64,
    )
    paths = {
        "audit": longmemeval_dir / "dataset_manifest.json",
        "power": power_dir / "power_feasibility.json",
        "calibration": longmemeval_dir / "normalized_calibration_20_30_50.json",
        "parity": qualification_dir / "evaluator_parity.json",
        "parity_state": qualification_dir / "evaluator_parity_run_state.json",
        "protocol": qualification_dir / "protocol_qualification_state.json",
        "day1_state": day1_dir / "day1_run_state.json",
        "day1_dir": day1_dir,
    }
    for name, payload in (
        ("audit", audit),
        ("power", power),
        ("calibration", calibration),
        ("parity", _parity()),
        ("day1_state", _day1_run_state()),
    ):
        paths[name].write_text(
            json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
        )
    parity_sha256 = hashlib.sha256(paths["parity"].read_bytes()).hexdigest()
    parity_state = _parity_run_state()
    parity_state["artifacts"]["evaluator_parity.json"]["sha256"] = parity_sha256
    paths["parity_state"].write_text(
        json.dumps(parity_state, sort_keys=True) + "\n", encoding="utf-8"
    )
    protocol = _protocol_state()
    protocol["artifacts"]["evaluator_parity_sha256"] = parity_sha256
    paths["protocol"].write_text(
        json.dumps(protocol, sort_keys=True) + "\n", encoding="utf-8"
    )
    for artifact_name, artifact in _day1_artifacts().items():
        (day1_dir / artifact_name).write_text(
            json.dumps(artifact, sort_keys=True) + "\n", encoding="utf-8"
        )
    return paths


def _preflight_kwargs(paths: dict[str, Path], output_dir: Path) -> dict:
    return {
        "output_dir": output_dir,
        "dataset_manifest_path": paths["audit"],
        "calibration_artifact_path": paths["calibration"],
        "power_artifact_path": paths["power"],
        "evaluator_parity_path": paths["parity"],
        "evaluator_parity_run_state_path": paths["parity_state"],
        "protocol_state_path": paths["protocol"],
        "day1_run_state_path": paths["day1_state"],
        "day1_dir": paths["day1_dir"],
    }


def test_manifest_is_calibration_only_fixed_and_covers_all_frozen_categories() -> None:
    manifest = _manifest()
    validate_case_manifest(manifest)
    assert manifest["case_count"] == 50
    assert manifest["replicate_count"] == 3
    assert manifest["source_split"] == "calibration"
    assert manifest["split_candidate_id"] == "20_30_50"
    assert manifest["category_counts"] == JUDGE_REPEATABILITY_CATEGORY_COUNTS
    assert len({row["case_id"] for row in manifest["cases"]}) == 50
    assert len({row["episode_id"] for row in manifest["cases"]}) == 50
    assert all(row["source_split"] == "calibration" for row in manifest["cases"])
    assert "SECRET ACCEPTANCE" not in json.dumps(manifest)
    assert manifest["manifest_hash"] == stable_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )


def test_manifest_builder_rejects_a_combined_split_input_before_case_selection() -> None:
    audit, episodes = _audit_and_episodes()
    with pytest.raises(ContractError, match="calibration-only input"):
        build_case_manifest(
            audit=audit,
            power_artifact=_power(audit),
            normalized_episodes=episodes,
        )


def test_trusted_split_materializer_exports_only_calibration_and_binds_source() -> None:
    audit, episodes = _audit_and_episodes()
    artifact = materialize_calibration_split(
        audit=audit,
        power_artifact=_power(audit),
        normalized_episodes=episodes,
        source_normalized_sha256="c" * 64,
    )
    validate_calibration_split_artifact(
        artifact,
        audit=audit,
        power_artifact=_power(audit),
    )
    assert artifact["source_split"] == "calibration"
    assert artifact["episode_count"] == 90
    assert artifact["source_power_artifact_hash"] == _power(audit)["artifact_hash"]
    assert artifact["acceptance_payload_exported"] is False
    assert artifact["source_combined_store_scanned"] is True
    assert "SECRET ACCEPTANCE" not in json.dumps(artifact)


def test_cli_exposes_only_the_materialized_calibration_input(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--help"])
    help_text = capsys.readouterr().out
    assert "--calibration-artifact" in help_text
    assert "--normalized-episodes" not in help_text


def test_preparing_state_is_written_before_the_first_input_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "qualification-output"
    state_at_first_read: dict = {}

    def fail_on_first_read(path: Path) -> dict:
        del path
        state_at_first_read.update(
            json.loads(
                (output_dir / "judge_repeatability_run_state.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        raise OSError("fixture first-read failure")

    monkeypatch.setattr(judge_module, "_load_json_object", fail_on_first_read)
    missing = tmp_path / "not-read.json"
    with pytest.raises(ContractError, match="preflight"):
        prepare_and_run_judge_repeatability(
            output_dir=output_dir,
            dataset_manifest_path=missing,
            calibration_artifact_path=missing,
            power_artifact_path=missing,
            evaluator_parity_path=missing,
            evaluator_parity_run_state_path=missing,
            protocol_state_path=missing,
            day1_run_state_path=missing,
            day1_dir=tmp_path,
            api_key="secret",
            request_fn=lambda *args: pytest.fail("preflight must not call the provider"),
            now_fn=lambda: "2026-08-04T10:00:00Z",
        )

    assert state_at_first_read["state"] == "preparing"
    assert state_at_first_read["current_stage"] == "preflight"
    assert state_at_first_read["completed_observations"] == 0


@pytest.mark.parametrize("failure_kind", ["missing", "invalid-json"])
def test_preflight_input_failure_publishes_current_run_identity_without_requests(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    paths = _write_preflight_inputs(tmp_path / "inputs")
    if failure_kind == "missing":
        paths["calibration"].unlink()
    else:
        paths["calibration"].write_text("{not-json", encoding="utf-8")
    output_dir = tmp_path / "qualification-output"
    request_count = 0

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        nonlocal request_count
        del url, payload, headers, route, timeout
        request_count += 1
        return _response(1, request_count)

    with pytest.raises(ContractError, match="preflight"):
        prepare_and_run_judge_repeatability(
            **_preflight_kwargs(paths, output_dir),
            api_key="secret",
            request_fn=request,
            now_fn=lambda: "2026-08-04T10:00:00Z",
        )

    assert request_count == 0
    run_state = json.loads(
        (output_dir / "judge_repeatability_run_state.json").read_text(
            encoding="utf-8"
        )
    )
    stall = json.loads(
        (output_dir / "judge_repeatability_stall.json").read_text(encoding="utf-8")
    )
    assert run_state["state"] == "blocked"
    assert run_state["current_stage"] == "preflight"
    assert run_state["completed_observations"] == 0
    assert run_state["run_id"] == stall["run_id"]
    assert stall["failure_stage"] == "preflight"
    assert stall["completed_observations"] == 0
    assert stall["transport_attempt_count"] == 0
    assert run_state["artifacts"]["judge_repeatability.json"] == {
        "state": "not_published_for_this_run",
        "run_id": run_state["run_id"],
    }
    assert not (output_dir / "judge_repeatability.json").exists()
    assert "secret" not in "".join(
        path.read_text(encoding="utf-8")
        for path in output_dir.rglob("*")
        if path.is_file()
    )


def test_preflight_rejects_parity_checksum_drift_without_advancing_protocol(
    tmp_path: Path,
) -> None:
    paths = _write_preflight_inputs(tmp_path / "inputs")
    parity_state = json.loads(paths["parity_state"].read_text(encoding="utf-8"))
    parity_state["artifacts"]["evaluator_parity.json"]["sha256"] = "e" * 64
    paths["parity_state"].write_text(
        json.dumps(parity_state, sort_keys=True) + "\n", encoding="utf-8"
    )
    protocol_before = paths["protocol"].read_bytes()
    output_dir = tmp_path / "qualification-output"
    request_count = 0

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        nonlocal request_count
        del url, payload, headers, route, timeout
        request_count += 1
        return _response(1, request_count)

    with pytest.raises(ContractError, match="checksum"):
        prepare_and_run_judge_repeatability(
            **_preflight_kwargs(paths, output_dir),
            api_key="secret",
            request_fn=request,
            now_fn=lambda: "2026-08-04T10:00:00Z",
        )

    assert request_count == 0
    assert paths["protocol"].read_bytes() == protocol_before
    run_state = json.loads(
        (output_dir / "judge_repeatability_run_state.json").read_text(
            encoding="utf-8"
        )
    )
    stall = json.loads(
        (output_dir / "judge_repeatability_stall.json").read_text(encoding="utf-8")
    )
    assert run_state["state"] == "blocked"
    assert run_state["current_stage"] == "preflight"
    assert run_state["run_id"] == stall["run_id"]
    assert stall["failure_stage"] == "preflight"


def test_preflight_rejects_day1_artifact_checksum_drift_without_requests(
    tmp_path: Path,
) -> None:
    paths = _write_preflight_inputs(tmp_path / "inputs")
    day1_state = json.loads(paths["day1_state"].read_text(encoding="utf-8"))
    day1_state["artifacts"] = {
        name: {
            "state": "completed",
            "run_id": day1_state["run_id"],
            "sha256": hashlib.sha256(
                (paths["day1_dir"] / name).read_bytes()
            ).hexdigest(),
        }
        for name in day1_state["artifact_names"]
    }
    paths["day1_state"].write_text(
        json.dumps(day1_state, sort_keys=True) + "\n", encoding="utf-8"
    )
    (paths["day1_dir"] / "embedding_probe.json").write_text(
        json.dumps({"tampered": True}), encoding="utf-8"
    )
    request_count = 0

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        nonlocal request_count
        del url, payload, headers, route, timeout
        request_count += 1
        return _response(1, request_count)

    with pytest.raises(ContractError, match="Day 1 artifact checksum"):
        prepare_and_run_judge_repeatability(
            **_preflight_kwargs(paths, tmp_path / "qualification-output"),
            api_key="secret",
            request_fn=request,
            now_fn=lambda: "2026-08-04T10:00:00Z",
        )
    assert request_count == 0


def test_preparation_identity_is_reused_by_the_successful_runner(tmp_path: Path) -> None:
    paths = _write_preflight_inputs(tmp_path / "inputs")
    output_dir = tmp_path / "qualification-output"
    first_request_run_state: dict | None = None
    request_count = 0

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        nonlocal first_request_run_state, request_count
        del url, payload, headers, route, timeout
        request_count += 1
        if first_request_run_state is None:
            first_request_run_state = json.loads(
                (output_dir / "judge_repeatability_run_state.json").read_text(
                    encoding="utf-8"
                )
            )
        return _response(1, request_count)

    artifact = prepare_and_run_judge_repeatability(
        **_preflight_kwargs(paths, output_dir),
        api_key="secret",
        request_fn=request,
        now_fn=lambda: "2026-08-04T10:00:00Z",
    )

    assert request_count == 150
    assert first_request_run_state is not None
    assert first_request_run_state["state"] == "running"
    assert first_request_run_state["run_id"] == artifact["run_id"]
    final_run_state = json.loads(
        (output_dir / "judge_repeatability_run_state.json").read_text(
            encoding="utf-8"
        )
    )
    assert final_run_state["state"] == "completed"
    assert final_run_state["run_id"] == artifact["run_id"]


def test_calibration_artifact_rejects_power_gate_content_hash_drift() -> None:
    audit, episodes = _audit_and_episodes()
    power = _power(audit)
    artifact = materialize_calibration_split(
        audit=audit,
        power_artifact=power,
        normalized_episodes=episodes,
        source_normalized_sha256="c" * 64,
    )
    drifted_power = deepcopy(power)
    drifted_power["delta_decision"] = 0.2
    with pytest.raises(ContractError, match="power artifact_hash"):
        validate_calibration_split_artifact(
            artifact,
            audit=audit,
            power_artifact=drifted_power,
        )


def test_manifest_rejects_acceptance_or_tampered_contents() -> None:
    manifest = _manifest()
    bad_split = deepcopy(manifest)
    bad_split["cases"][0]["source_split"] = "acceptance"
    bad_split["manifest_hash"] = stable_hash(
        {key: value for key, value in bad_split.items() if key != "manifest_hash"}
    )
    with pytest.raises(ContractError, match="calibration"):
        validate_case_manifest(bad_split)

    tampered = deepcopy(manifest)
    tampered["cases"][0]["candidate_answer"] = "tampered"
    with pytest.raises(ContractError, match="manifest_hash"):
        validate_case_manifest(tampered)


def test_runner_uses_one_user_message_direct_then_proxy_and_advances_only_one_stage(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict]] = []

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        del headers, timeout
        calls.append((route, payload))
        assert url == "https://api.labforge.cc/v1/chat/completions"
        assert payload["model"] == "gpt-5.5"
        assert payload["temperature"] == 0
        assert payload["max_tokens"] == 128
        assert payload["stream"] is False
        assert payload["messages"] == [
            {"role": "user", "content": payload["messages"][0]["content"]}
        ]
        if len(calls) == 1 and route == "direct":
            raise OSError("fixture direct failure")
        return _response(1, len(calls))

    artifact = run_judge_repeatability(
        output_dir=tmp_path,
        case_manifest=_manifest(),
        evaluator_parity=_parity(),
        protocol_state=_protocol_state(),
        model_inventory=_inventory(),
        judge_probe=_judge_probe(),
        **_upstream_kwargs(),
        api_key="secret",
        request_fn=request,
        now_fn=lambda: "2026-08-03T16:00:00Z",
    )

    assert len(calls) == 151
    assert [route for route, _ in calls[:2]] == ["direct", "proxy_17897"]
    assert all(route == "direct" for route, _ in calls[2:])
    assert artifact["status"] == "passed"
    assert artifact["metrics"]["observation_count"] == 150
    assert artifact["metrics"]["parse_success_rate"] == 1.0
    assert artifact["next_stage"] == "cache_qualification"
    assert artifact["acceptance_accessed"] is False
    run_state = json.loads(
        (tmp_path / "judge_repeatability_run_state.json").read_text(encoding="utf-8")
    )
    assert run_state["state"] == "completed"
    assert run_state["run_id"] == artifact["run_id"]
    assert run_state["artifacts"]["judge_repeatability.json"]["run_id"] == artifact["run_id"]
    attempts = _jsonl(
        Path(run_state["run_directory"]) / "judge_repeatability_attempts.jsonl"
    )
    bindings = _jsonl(tmp_path / "judge_repeatability_output_bindings.jsonl")
    outputs = _jsonl(tmp_path / "judge_repeatability_outputs.jsonl")
    transport = _jsonl(tmp_path / "judge_repeatability_transport_attempts.jsonl")
    assert len(attempts) == 151
    assert len(bindings) == len(outputs) == 150
    assert len(transport) == 151
    validate_accepted_output_bindings(attempts, bindings)
    assert all(row["stage"] == "judge" for row in attempts)
    assert attempts[0]["attempt_outcome"] == "failed_provider"
    assert attempts[0]["accepted_attempt"] is False
    assert attempts[0]["returned_model"] is None
    assert attempts[0]["request_id"] is None
    assert attempts[0]["provider_usage_source"] == "missing"
    assert attempts[0]["http_status"] is None
    assert all(row["binding_status"] == "succeeded" for row in bindings)
    assert all(row["run_id"] == artifact["run_id"] for row in outputs)
    assert transport[0]["status"] == "failed"
    assert transport[1]["status"] == "completed"
    state = json.loads(
        (tmp_path / "protocol_qualification_state.json").read_text(encoding="utf-8")
    )
    assert state["completed_stages"] == [
        "observability_freeze",
        "evaluator_parity",
        "judge_repeatability",
    ]
    assert state["next_stage"] == "cache_qualification"
    assert state["full_leaf_generation_allowed"] is False
    assert not (tmp_path / "judge_repeatability_stall.json").exists()
    assert "secret" not in "".join(
        path.read_text(encoding="utf-8") for path in tmp_path.rglob("*") if path.is_file()
    )


def test_runner_stops_on_parse_failure_and_publishes_current_run_stall(
    tmp_path: Path,
) -> None:
    call_count = 0

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        nonlocal call_count
        del url, payload, headers, route, timeout
        call_count += 1
        response, metadata = _response(1, call_count)
        response["choices"][0]["message"]["content"] = "yes"
        return response, metadata

    with pytest.raises(ContractError, match="strict JSON"):
        run_judge_repeatability(
            output_dir=tmp_path,
            case_manifest=_manifest(),
            evaluator_parity=_parity(),
            protocol_state=_protocol_state(),
            model_inventory=_inventory(),
            judge_probe=_judge_probe(),
            **_upstream_kwargs(),
            api_key="secret",
            request_fn=request,
            now_fn=lambda: "2026-08-03T16:00:00Z",
        )

    assert call_count == 1
    stall = json.loads(
        (tmp_path / "judge_repeatability_stall.json").read_text(encoding="utf-8")
    )
    run_state = json.loads(
        (tmp_path / "judge_repeatability_run_state.json").read_text(encoding="utf-8")
    )
    assert stall["run_id"] == run_state["run_id"]
    assert stall["completed_observations"] == 0
    assert run_state["state"] == "blocked"
    assert not (tmp_path / "judge_repeatability.json").exists()


def test_runner_uses_exactly_two_routes_then_stalls_on_access_failure(
    tmp_path: Path,
) -> None:
    routes: list[str] = []

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        del url, payload, headers, timeout
        routes.append(route)
        raise OSError(f"fixture secret {route} failure")

    with pytest.raises(ContractError, match="direct and proxy_17897"):
        run_judge_repeatability(
            output_dir=tmp_path,
            case_manifest=_manifest(),
            evaluator_parity=_parity(),
            protocol_state=_protocol_state(),
            model_inventory=_inventory(),
            judge_probe=_judge_probe(),
            **_upstream_kwargs(),
            api_key="secret",
            request_fn=request,
            now_fn=lambda: "2026-08-03T16:00:00Z",
        )
    assert routes == ["direct", "proxy_17897"]
    run_state = json.loads(
        (tmp_path / "judge_repeatability_run_state.json").read_text(encoding="utf-8")
    )
    attempts = _jsonl(
        Path(run_state["run_directory"]) / "judge_repeatability_attempts.jsonl"
    )
    assert len(attempts) == 2
    assert all(row["attempt_outcome"] == "failed_provider" for row in attempts)
    assert all(row["returned_model"] is None for row in attempts)
    assert all(row["request_id"] is None for row in attempts)
    assert all(row["accepted_attempt"] is False for row in attempts)
    stall = json.loads(
        (tmp_path / "judge_repeatability_stall.json").read_text(encoding="utf-8")
    )
    assert stall["attempt_order"] == ["direct", "proxy_17897"]
    assert "secret" not in "".join(
        path.read_text(encoding="utf-8") for path in tmp_path.rglob("*") if path.is_file()
    )


def test_runner_treats_http_error_status_as_route_failure_before_proxy(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        del url, payload, headers, timeout
        calls.append(route)
        response, metadata = _response(1, len(calls))
        if len(calls) == 1:
            metadata["http_status"] = 503
        return response, metadata

    artifact = run_judge_repeatability(
        output_dir=tmp_path,
        case_manifest=_manifest(),
        evaluator_parity=_parity(),
        protocol_state=_protocol_state(),
        model_inventory=_inventory(),
        judge_probe=_judge_probe(),
        **_upstream_kwargs(),
        api_key="secret",
        request_fn=request,
        now_fn=lambda: "2026-08-03T16:00:00Z",
    )

    assert artifact["status"] == "passed"
    assert calls[:2] == ["direct", "proxy_17897"]
    transport = _jsonl(tmp_path / "judge_repeatability_transport_attempts.jsonl")
    assert transport[0]["status"] == "failed"
    assert transport[1]["status"] == "completed"
    attempts = _jsonl(tmp_path / "judge_repeatability_attempts.jsonl")
    assert attempts[0]["attempt_outcome"] == "failed_provider"
    assert attempts[0]["http_status"] == 503
    assert attempts[0]["returned_model"] == "gpt-5.5"
    assert attempts[0]["request_id"] == "request-1"


def test_runner_preserves_http_error_status_and_provider_request_id(
    tmp_path: Path,
) -> None:
    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        del payload, headers, timeout
        raise urllib.error.HTTPError(
            url,
            403,
            "Forbidden",
            {"x-request-id": f"request-{route}"},
            None,
        )

    with pytest.raises(ContractError, match="direct and proxy_17897"):
        run_judge_repeatability(
            output_dir=tmp_path,
            case_manifest=_manifest(),
            evaluator_parity=_parity(),
            protocol_state=_protocol_state(),
            model_inventory=_inventory(),
            judge_probe=_judge_probe(),
            **_upstream_kwargs(),
            api_key="secret",
            request_fn=request,
            now_fn=lambda: "2026-08-03T16:00:00Z",
        )

    run_state = json.loads(
        (tmp_path / "judge_repeatability_run_state.json").read_text(encoding="utf-8")
    )
    run_dir = Path(run_state["run_directory"])
    attempts = _jsonl(run_dir / "judge_repeatability_attempts.jsonl")
    transport = _jsonl(run_dir / "judge_repeatability_transport_attempts.jsonl")
    assert [row["http_status"] for row in attempts] == [403, 403]
    assert [row["request_id"] for row in attempts] == [
        "request-direct",
        "request-proxy_17897",
    ]
    assert [row["returned_model"] for row in attempts] == [None, None]
    assert [row["attempt_id"] for row in attempts] == [
        row["transport_attempt_id"] for row in transport
    ]


@pytest.mark.parametrize("invalid_model", [None, 123, "None", "unknown"])
def test_runner_records_invalid_returned_model_as_null_without_placeholder(
    tmp_path: Path, invalid_model: object,
) -> None:
    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        del url, payload, headers, route, timeout
        response, metadata = _response(1, 1)
        response["model"] = invalid_model
        return response, metadata

    with pytest.raises(ContractError, match="returned model"):
        run_judge_repeatability(
            output_dir=tmp_path,
            case_manifest=_manifest(),
            evaluator_parity=_parity(),
            protocol_state=_protocol_state(),
            model_inventory=_inventory(),
            judge_probe=_judge_probe(),
            **_upstream_kwargs(),
            api_key="secret",
            request_fn=request,
            now_fn=lambda: "2026-08-03T16:00:00Z",
        )

    run_state = json.loads(
        (tmp_path / "judge_repeatability_run_state.json").read_text(encoding="utf-8")
    )
    attempts = _jsonl(
        Path(run_state["run_directory"]) / "judge_repeatability_attempts.jsonl"
    )
    assert len(attempts) == 1
    assert attempts[0]["attempt_outcome"] == "failed_validation"
    assert attempts[0]["returned_model"] is None
    assert attempts[0]["request_id"] == "request-1"


@pytest.mark.parametrize("invalid_request_id", [None, "None", "unknown"])
def test_runner_records_missing_request_id_as_failed_validation(
    tmp_path: Path, invalid_request_id: object,
) -> None:
    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        del url, payload, headers, route, timeout
        response, metadata = _response(1, 1)
        response["id"] = invalid_request_id
        metadata["request_id"] = invalid_request_id
        return response, metadata

    with pytest.raises(ContractError, match="request_id"):
        run_judge_repeatability(
            output_dir=tmp_path,
            case_manifest=_manifest(),
            evaluator_parity=_parity(),
            protocol_state=_protocol_state(),
            model_inventory=_inventory(),
            judge_probe=_judge_probe(),
            **_upstream_kwargs(),
            api_key="secret",
            request_fn=request,
            now_fn=lambda: "2026-08-03T16:00:00Z",
        )

    run_state = json.loads(
        (tmp_path / "judge_repeatability_run_state.json").read_text(encoding="utf-8")
    )
    attempts = _jsonl(
        Path(run_state["run_directory"]) / "judge_repeatability_attempts.jsonl"
    )
    assert len(attempts) == 1
    assert attempts[0]["attempt_outcome"] == "failed_validation"
    assert attempts[0]["returned_model"] == "gpt-5.5"
    assert attempts[0]["request_id"] is None


def test_runner_fails_closed_on_model_drift_and_keeps_previous_prefix(
    tmp_path: Path,
) -> None:
    old_artifact = {
        "schema_version": "old",
        "run_id": "old-successful-run",
        "status": "passed",
    }
    (tmp_path / "judge_repeatability.json").write_text(
        json.dumps(old_artifact), encoding="utf-8"
    )

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        del url, payload, headers, route, timeout
        response, metadata = _response(1, 1)
        response["model"] = "gpt-5.5-latest"
        return response, metadata

    with pytest.raises(ContractError, match="returned model"):
        run_judge_repeatability(
            output_dir=tmp_path,
            case_manifest=_manifest(),
            evaluator_parity=_parity(),
            protocol_state=_protocol_state(),
            model_inventory=_inventory(),
            judge_probe=_judge_probe(),
            **_upstream_kwargs(),
            api_key="secret",
            request_fn=request,
            now_fn=lambda: "2026-08-03T16:00:00Z",
        )

    run_state = json.loads(
        (tmp_path / "judge_repeatability_run_state.json").read_text(encoding="utf-8")
    )
    stall = json.loads(
        (tmp_path / "judge_repeatability_stall.json").read_text(encoding="utf-8")
    )
    state = json.loads(
        (tmp_path / "protocol_qualification_state.json").read_text(encoding="utf-8")
    )
    assert run_state["state"] == "blocked"
    assert stall["run_id"] == run_state["run_id"]
    assert state["completed_stages"] == ["observability_freeze", "evaluator_parity"]
    assert state["next_stage"] == "judge_repeatability"
    assert state["full_leaf_generation_allowed"] is False
    assert json.loads(
        (tmp_path / "judge_repeatability.json").read_text(encoding="utf-8")
    ) == old_artifact
    current_entry = run_state["artifacts"]["judge_repeatability.json"]
    assert current_entry["state"] == "not_published_for_this_run"
    assert current_entry["run_id"] == run_state["run_id"]
    assert "sha256" not in current_entry


def test_runner_rejects_cross_run_day1_or_wrong_protocol_prefix_without_calls(
    tmp_path: Path,
) -> None:
    call_count = 0

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        nonlocal call_count
        del url, payload, headers, route, timeout
        call_count += 1
        return _response(1, call_count)

    probe = _judge_probe()
    probe["run_id"] = "different-day1-run"
    with pytest.raises(ContractError, match="same Day 1 run"):
        run_judge_repeatability(
            output_dir=tmp_path / "cross-run",
            case_manifest=_manifest(),
            evaluator_parity=_parity(),
            protocol_state=_protocol_state(),
            model_inventory=_inventory(),
            judge_probe=probe,
            **_upstream_kwargs(),
            api_key="secret",
            request_fn=request,
            now_fn=lambda: "2026-08-03T16:00:00Z",
        )

    state = _protocol_state()
    state["completed_stages"] = ["observability_freeze"]
    with pytest.raises(ContractError, match="ordered qualification prefix"):
        run_judge_repeatability(
            output_dir=tmp_path / "wrong-prefix",
            case_manifest=_manifest(),
            evaluator_parity=_parity(),
            protocol_state=state,
            model_inventory=_inventory(),
            judge_probe=_judge_probe(),
            **_upstream_kwargs(),
            api_key="secret",
            request_fn=request,
            now_fn=lambda: "2026-08-03T16:00:00Z",
        )
    assert call_count == 0


def test_runner_requires_completed_day1_and_parity_run_state_checksum_binding(
    tmp_path: Path,
) -> None:
    calls = 0

    def request(url: str, payload: dict, headers: dict, route: str, timeout: float):
        nonlocal calls
        del url, payload, headers, route, timeout
        calls += 1
        return _response(1, calls)

    upstream = _upstream_kwargs()
    upstream["evaluator_parity_sha256"] = "e" * 64
    with pytest.raises(ContractError, match="Parity.*checksum"):
        run_judge_repeatability(
            output_dir=tmp_path / "parity-sha",
            case_manifest=_manifest(),
            evaluator_parity=_parity(),
            protocol_state=_protocol_state(),
            model_inventory=_inventory(),
            judge_probe=_judge_probe(),
            **upstream,
            api_key="secret",
            request_fn=request,
            now_fn=lambda: "2026-08-03T16:00:00Z",
        )

    upstream = _upstream_kwargs()
    upstream["day1_artifacts"].pop("embedding_probe.json")
    with pytest.raises(ContractError, match="eight frozen artifacts"):
        run_judge_repeatability(
            output_dir=tmp_path / "day1-set",
            case_manifest=_manifest(),
            evaluator_parity=_parity(),
            protocol_state=_protocol_state(),
            model_inventory=_inventory(),
            judge_probe=_judge_probe(),
            **upstream,
            api_key="secret",
            request_fn=request,
            now_fn=lambda: "2026-08-03T16:00:00Z",
        )
    assert calls == 0


def test_derived_observations_resolve_binding_attempt_and_raw_output(
    tmp_path: Path,
) -> None:
    artifact = run_judge_repeatability(
        output_dir=tmp_path,
        case_manifest=_manifest(),
        evaluator_parity=_parity(),
        protocol_state=_protocol_state(),
        model_inventory=_inventory(),
        judge_probe=_judge_probe(),
        **_upstream_kwargs(),
        api_key="secret",
        request_fn=lambda url, payload, headers, route, timeout: _response(1, 1),
        now_fn=lambda: "2026-08-03T16:00:00Z",
    )
    attempts = _jsonl(tmp_path / "judge_repeatability_attempts.jsonl")
    bindings = _jsonl(tmp_path / "judge_repeatability_output_bindings.jsonl")
    outputs = _jsonl(tmp_path / "judge_repeatability_outputs.jsonl")
    observations = derive_repeatability_observations(
        case_manifest=_manifest(),
        attempts=attempts,
        bindings=bindings,
        outputs=outputs,
    )
    assert observations == artifact["observations"]

    outputs[0]["response_text"] = '{"label":0}'
    with pytest.raises(ContractError, match="content hash"):
        derive_repeatability_observations(
            case_manifest=_manifest(),
            attempts=attempts,
            bindings=bindings,
            outputs=outputs,
        )
