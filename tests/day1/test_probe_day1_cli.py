from __future__ import annotations

import json
import subprocess
import sys
import threading
import tomllib
import urllib.error
from pathlib import Path

import pytest

import plan_robust_memory.probe_day1 as day1
from plan_robust_memory.probe_day1 import (
    ARTIFACT_NAMES,
    BGE_M3_EMBEDDING_DIMENSION,
    BGE_M3_MODEL,
    BGE_M3_REVISION,
    CHAT_COMPLETIONS_PATH,
    DEFAULT_BASE_URL,
    DEFAULT_HF_HUB_CACHE,
    JUDGE_MODEL,
    PRIMARY_MODEL,
    _embedding_qualified,
    _default_weight_resolver,
    _judge_probe,
    load_real_episode_probe,
    probe_huggingface_connectivity,
    probe_embedding,
    inspect_day1_run,
    run_day1_probe,
)
from plan_robust_memory.hashing import stable_hash


def _canonical_embedding_fixture(model: str, revision: str | None) -> dict:
    return {
        "status": "passed",
        "model": model,
        "revision": revision or "fixture-revision",
        "tokenizer_revision": revision or "fixture-revision",
        "model_snapshot": f"{model}@{revision or 'fixture-revision'}",
        "tokenizer_snapshot": f"{model}@{revision or 'fixture-revision'}",
        "precision": "fp16",
        "similarity": "cosine_over_normalized_vectors",
        "torch_version": "fixture-torch",
        "sentence_transformers_version": "fixture-sentence-transformers",
        "cuda_runtime_version": "fixture-cuda",
        "cuda_available": True,
        "device_name": "NVIDIA GeForce RTX 3090 Ti",
        "model_parameter_dtype": "torch.float16",
        "embedding_dimension": BGE_M3_EMBEDDING_DIMENSION,
        "normalized_vectors_verified": True,
        "embedding_output_sha256_runs": ["a" * 64, "a" * 64],
        "embedding_executed": True,
        "encode_run_count": 2,
        "ranking_deterministic": True,
        "packing_deterministic": True,
        "packing_nonempty": True,
        "packing_budget_tokens": 4096,
        "packing_token_totals_runs": [[12], [12]],
        "real_episode_probe": True,
        "episode_id": "fixture-episode",
        "session_count": 4,
        "episode_unit_count": 4,
        "surrogate_token_count": 16,
        "max_unit_surrogate_tokens": 4,
        "episode_batch_size": 1,
        "single_episode_embedding_latency_seconds": 0.01,
        "estimated_500_instance_index_seconds": 5.0,
        "peak_vram_bytes": 24 * 1024**3,
        "raw_sha256": "b" * 64,
        "normalized_episode_sha256": "c" * 64,
        "episode_selection": {
            "split": "development",
            "candidate_id": "20_30_50",
            "manifest_audit_hash": "d" * 64,
        },
        "weight_filename": "pytorch_model.bin",
        "weight_sha256": "e" * 64,
        "use_safetensors": False,
    }


def _full_cost_inputs() -> dict:
    return {
        "dataset_source": "official-longmemeval-s-cleaned",
        "dataset_checksum": "a" * 64,
        "pricing_source": "provider-pricing-2026-08-01",
        "currency": "USD",
        "components": {
            name: {
                "call_upper_bound": index + 1,
                "input_token_upper_bound": (index + 1) * 1000,
                "output_token_upper_bound": (index + 1) * 100,
                "monetary_upper_bound": (index + 1) * 1.25,
            }
            for index, name in enumerate(
                ("primary", "replication", "SATURATION", "D_leaf", "future_k_sweep")
            )
        },
    }


def _json_label_for_prompt(prompt: str) -> int:
    if "Candidate: 5" in prompt or "Candidate: Rome" in prompt:
        return 0
    if "Candidate: 4" in prompt or "Candidate: Paris" in prompt:
        return 1
    return 0


def _successful_request_fixture():
    counter = 0
    lock = threading.Lock()

    def fake_request(url, *, method="GET", payload=None, headers=None, route="direct", timeout=0):
        nonlocal counter
        with lock:
            counter += 1
            request_id = f"fixture-{counter}"
        if url.endswith("/models"):
            return {
                "data": [{"id": PRIMARY_MODEL}, {"id": JUDGE_MODEL}, {"id": "replica-1"}]
            }, {
                "status": 200,
                "route": route,
                "request_id": request_id,
                "elapsed_seconds": 0.01,
                "ttft_seconds": 0.005,
                "response_sha256": "b" * 64,
            }
        assert url == f"{DEFAULT_BASE_URL}{CHAT_COMPLETIONS_PATH}"
        assert set(payload["messages"][0]) == {"role", "content"}
        assert payload["messages"][0]["role"] == "user"
        assert len(payload["messages"]) == 1
        assert "input" not in payload
        assert "max_output_tokens" not in payload
        assert all(message["role"] not in {"system", "developer"} for message in payload["messages"])
        prompt = str(payload["messages"][0]["content"])
        if payload.get("model") == JUDGE_MODEL:
            output_text = json.dumps({"label": _json_label_for_prompt(prompt)})
        else:
            # The 115K probe appends a unique sentinel to the request and requires it back.
            output_text = prompt[-512:]
        return {
            "id": request_id,
            "model": payload.get("model", PRIMARY_MODEL),
            "choices": [{"message": {"role": "assistant", "content": output_text}}],
            "usage": {"prompt_tokens": 115000, "completion_tokens": 32},
        }, {
            "status": 200,
            "route": route,
            "request_id": request_id,
            "elapsed_seconds": 0.01,
            "ttft_seconds": 0.005,
            "response_sha256": "a" * 64,
        }

    return fake_request


def test_all_vertical_commands_are_module_executable() -> None:
    for module in ("probe_day1", "audit_longmemeval", "power_gate"):
        result = subprocess.run(
            [sys.executable, "-m", f"plan_robust_memory.{module}", "--help"],
            cwd=Path(__file__).resolve().parents[2],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def test_day1_generation_contract_is_frozen_to_clean_chat_completions() -> None:
    assert DEFAULT_BASE_URL == "https://api.labforge.cc/v1"
    assert CHAT_COMPLETIONS_PATH == "/chat/completions"


def test_day1_replaces_stale_artifacts_before_inventory_completes(tmp_path: Path) -> None:
    stale_payload = {
        "status": "blocked",
        "run_id": "stale-run",
        "attempts": [{"http_status": 400}],
    }
    for name in ARTIFACT_NAMES:
        (tmp_path / name).write_text(json.dumps(stale_payload), encoding="utf-8")

    inventory_started = threading.Event()
    release_inventory = threading.Event()
    successful = _successful_request_fixture()

    def blocking_inventory_request(url, **kwargs):
        if url == day1.HUGGINGFACE_PROBE_URL:
            return {}, {
                "status": 200,
                "route": kwargs.get("route", "direct"),
                "request_id": "hf-fixture",
                "elapsed_seconds": 0.01,
            }
        if url.endswith("/models"):
            inventory_started.set()
            if not release_inventory.wait(timeout=10):
                raise TimeoutError("test did not release inventory request")
        return successful(url, **kwargs)

    outcome: dict[str, object] = {}

    def run_probe() -> None:
        try:
            outcome["result"] = run_day1_probe(
                tmp_path,
                request_fn=blocking_inventory_request,
                api_key="test-key",
                replication_model="replica-1",
                embedding_revision="fixture-revision",
                embedding_probe_fn=_canonical_embedding_fixture,
                full_cost_inputs=_full_cost_inputs(),
            )
        except BaseException as exc:  # pragma: no cover - re-raised in the test thread
            outcome["error"] = exc

    worker = threading.Thread(target=run_probe, daemon=True)
    worker.start()
    assert inventory_started.wait(timeout=5)
    try:
        run_state = json.loads(
            (tmp_path / "day1_run_state.json").read_text(encoding="utf-8")
        )
        assert run_state["state"] == "running"
        assert run_state["run_id"] != "stale-run"

        inventory = json.loads(
            (tmp_path / "model_inventory.json").read_text(encoding="utf-8")
        )
        assert inventory["status"] == "pending"
        assert inventory["artifact_state"] == "pending"
        assert inventory["run_id"] == run_state["run_id"]
        assert "attempts" not in inventory

        for name in ARTIFACT_NAMES:
            payload = json.loads((tmp_path / name).read_text(encoding="utf-8"))
            assert payload["run_id"] == run_state["run_id"]
    finally:
        release_inventory.set()
        worker.join(timeout=10)

    assert not worker.is_alive()
    if error := outcome.get("error"):
        raise error


def test_day1_publishes_current_inventory_before_generation_finishes(tmp_path: Path) -> None:
    for name in ARTIFACT_NAMES:
        (tmp_path / name).write_text(
            json.dumps({"status": "blocked", "run_id": "stale-run"}),
            encoding="utf-8",
        )

    generation_started = threading.Event()
    release_generation = threading.Event()
    block_lock = threading.Lock()
    blocked_once = False
    successful = _successful_request_fixture()

    def blocking_generation_request(url, **kwargs):
        nonlocal blocked_once
        if url == day1.HUGGINGFACE_PROBE_URL:
            return {}, {
                "status": 200,
                "route": kwargs.get("route", "direct"),
                "request_id": "hf-fixture",
                "elapsed_seconds": 0.01,
            }
        should_block = False
        if url.endswith(CHAT_COMPLETIONS_PATH):
            with block_lock:
                if not blocked_once:
                    blocked_once = True
                    should_block = True
        if should_block:
            generation_started.set()
            if not release_generation.wait(timeout=10):
                raise TimeoutError("test did not release generation request")
        return successful(url, **kwargs)

    outcome: dict[str, object] = {}

    def run_probe() -> None:
        try:
            outcome["result"] = run_day1_probe(
                tmp_path,
                request_fn=blocking_generation_request,
                api_key="test-key",
                replication_model="replica-1",
                embedding_revision="fixture-revision",
                embedding_probe_fn=_canonical_embedding_fixture,
                full_cost_inputs=_full_cost_inputs(),
            )
        except BaseException as exc:  # pragma: no cover - re-raised in the test thread
            outcome["error"] = exc

    worker = threading.Thread(target=run_probe, daemon=True)
    worker.start()
    assert generation_started.wait(timeout=5)
    try:
        run_state = json.loads(
            (tmp_path / "day1_run_state.json").read_text(encoding="utf-8")
        )
        inventory = json.loads(
            (tmp_path / "model_inventory.json").read_text(encoding="utf-8")
        )
        assert run_state["state"] == "running"
        assert inventory["status"] == "passed"
        assert inventory["artifact_state"] == "completed"
        assert inventory["run_id"] == run_state["run_id"]
        assert inventory["artifact_completed_at"] is not None
        assert inventory["attempts"][0]["http_status"] == 200
    finally:
        release_generation.set()
        worker.join(timeout=10)

    assert not worker.is_alive()
    if error := outcome.get("error"):
        raise error

    final_state = json.loads(
        (tmp_path / "day1_run_state.json").read_text(encoding="utf-8")
    )
    assert final_state["state"] == "completed"
    assert final_state["status"] == "passed"
    for name in ARTIFACT_NAMES:
        artifact = json.loads((tmp_path / name).read_text(encoding="utf-8"))
        assert artifact["run_id"] == final_state["run_id"]
        assert artifact["artifact_state"] == "completed"


def test_day1_inspection_refuses_stale_or_incomplete_artifact_sets(tmp_path: Path) -> None:
    for name in ARTIFACT_NAMES:
        (tmp_path / name).write_text(
            json.dumps({"status": "blocked", "run_id": "stale-run"}),
            encoding="utf-8",
        )
    assert inspect_day1_run(tmp_path)["reason"] == "missing_run_state"

    (tmp_path / "day1_run_state.json").write_text(
        json.dumps({"state": "running", "run_id": "current-run"}),
        encoding="utf-8",
    )
    running = inspect_day1_run(tmp_path)
    assert running["evidence_status"] == "unknown"
    assert running["reason"] == "run_not_completed"

    (tmp_path / "day1_run_state.json").write_text(
        json.dumps({"state": "completed", "status": "blocked", "run_id": "current-run"}),
        encoding="utf-8",
    )
    mismatched = inspect_day1_run(tmp_path)
    assert mismatched["evidence_status"] == "unknown"
    assert mismatched["reason"] == "artifact_set_not_coherent"
    assert set(mismatched["mismatched_run_id_artifacts"]) == set(ARTIFACT_NAMES)

    for name in ARTIFACT_NAMES:
        (tmp_path / name).write_text(
            json.dumps(
                {
                    "status": "blocked",
                    "artifact_state": "completed",
                    "run_id": "current-run",
                }
            ),
            encoding="utf-8",
        )
    verified = inspect_day1_run(tmp_path)
    assert verified["evidence_status"] == "verified"
    assert verified["run_id"] == "current-run"


def test_http_error_attempt_records_empty_body_hash() -> None:
    exc = urllib.error.HTTPError(
        "https://api.labforge.cc/v1/models",
        400,
        "Bad Request",
        hdrs={},
        fp=None,
    )
    attempt = day1._error_attempt("direct", "https://api.labforge.cc/v1/models", exc, 0.01)

    assert attempt["http_status"] == 400
    assert attempt["response_body_bytes"] == 0
    assert attempt["response_hash"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_day1_default_base_url_ignores_stale_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_urls: list[str] = []

    def failing_request(url, **kwargs):
        observed_urls.append(url)
        raise OSError("stop after recording URL")

    monkeypatch.setenv("OPENAI_BASE_URL", "https://stale-provider.invalid/v1")
    run_day1_probe(
        tmp_path,
        request_fn=failing_request,
        embedding_probe_fn=_canonical_embedding_fixture,
    )

    assert f"{DEFAULT_BASE_URL}/models" in observed_urls
    assert all("stale-provider.invalid" not in url for url in observed_urls)


def test_day1_rejects_noncanonical_base_url(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical base URL"):
        run_day1_probe(
            tmp_path,
            base_url="https://other-provider.invalid/v1",
            request_fn=_successful_request_fixture(),
            embedding_probe_fn=_canonical_embedding_fixture,
        )


def test_day1_generation_artifacts_record_response_hash_and_route(tmp_path: Path) -> None:
    run_day1_probe(
        tmp_path,
        request_fn=_successful_request_fixture(),
        api_key="test-key",
        replication_model="replica-1",
        embedding_revision="fixture-revision",
        embedding_probe_fn=_canonical_embedding_fixture,
    )

    primary = json.loads((tmp_path / "primary_115k_probe.json").read_text(encoding="utf-8"))
    assert primary["endpoint"] == f"{DEFAULT_BASE_URL}{CHAT_COMPLETIONS_PATH}"
    assert primary["request_protocol"] == "openai_compatible_chat_completions"
    assert all(call["route"] == "direct" for call in primary["calls"])
    assert all(call["response_hash"] == "a" * 64 for call in primary["calls"])

    judge = json.loads((tmp_path / "judge_probe.json").read_text(encoding="utf-8"))
    assert all(case["route"] == "direct" for case in judge["cases"])
    assert all(case["response_hash"] == "a" * 64 for case in judge["cases"])

    blocked = run_day1_probe(
        tmp_path / "blocked",
        request_fn=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")),
        embedding_probe_fn=_canonical_embedding_fixture,
    )
    assert blocked["status"] == "blocked"
    blocked_primary = json.loads(
        (tmp_path / "blocked" / "primary_115k_probe.json").read_text(encoding="utf-8")
    )
    assert blocked_primary["endpoint"] == f"{DEFAULT_BASE_URL}{CHAT_COMPLETIONS_PATH}"


def test_day1_blocked_run_writes_all_artifacts_and_stall_report(tmp_path: Path) -> None:
    def failing_request(*args, **kwargs):
        raise OSError("network unavailable")

    result = run_day1_probe(
        tmp_path,
        request_fn=failing_request,
        embedding_probe_fn=_canonical_embedding_fixture,
    )

    assert result["status"] == "blocked"
    assert result["routes"] == ["direct", "proxy_17897"]
    for name in ARTIFACT_NAMES:
        artifact = tmp_path / name
        assert artifact.exists()
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert payload["status"] in {"blocked", "failed", "passed"}
    stalls = list((tmp_path / "stall_reports").glob("*.md"))
    assert len(stalls) == 1
    report = stalls[0].read_text(encoding="utf-8")
    assert "direct" in report
    assert "proxy_17897" in report
    for required_section in (
        "Models used",
        "Error classification",
        "Cumulative calls",
        "Cumulative tokens",
        "Cumulative cost",
        "Most likely root cause",
        "Sub-Gate status",
        "Candidate paths",
        "User decision required",
    ):
        assert required_section in report
    assert "embedding: passed" in report
    assert "Freeze a different-family replication snapshot and the BAAI/bge-m3" not in report

    inventory = json.loads((tmp_path / "model_inventory.json").read_text(encoding="utf-8"))
    assert inventory["blocking_reason"] == (
        "model inventory failed through direct and proxy_17897 routes"
    )

    cost = json.loads((tmp_path / "cost_upper_bound.json").read_text(encoding="utf-8"))
    assert cost["status"] == "blocked"
    assert cost["scope"] == "full_experiment_upper_bound"
    assert set(cost["components"]) == {
        "primary",
        "replication",
        "SATURATION",
        "D_leaf",
        "future_k_sweep",
    }
    assert all(component["status"] == "unknown" for component in cost["components"].values())
    assert cost["monetary_upper_bound"] is None
    assert cost["unknown_cost_not_zero"] is True


def test_day1_model_probes_record_canonical_115k_metrics_but_unknown_full_cost_blocks(
    tmp_path: Path,
) -> None:
    result = run_day1_probe(
        tmp_path,
        request_fn=_successful_request_fixture(),
        api_key="test-key",
        replication_model="replica-1",
        embedding_revision="fixture-revision",
        embedding_probe_fn=_canonical_embedding_fixture,
    )
    assert result["status"] == "blocked"
    inventory = json.loads((tmp_path / "model_inventory.json").read_text(encoding="utf-8"))
    assert inventory["returned_model_ids"] == ["gpt-5.5", "gpt-5.6-sol", "replica-1"]
    probe = json.loads((tmp_path / "primary_115k_probe.json").read_text(encoding="utf-8"))
    assert probe["status"] == "passed"
    assert probe["warmup"]["excluded_from_success_count"] is True
    assert probe["concurrency_levels"] == [1, 2, 4]
    assert {run["concurrency"] for run in probe["concurrency_runs"]} == {1, 2, 4}
    assert all(run["required_success_count"] == 5 for run in probe["concurrency_runs"])
    assert all(run["success_count"] == 5 for run in probe["concurrency_runs"])
    assert probe["canonical_checks"] == {
        "success_5_of_5": True,
        "context_length_errors_zero": True,
        "silent_truncation_zero": True,
        "usage_available": True,
        "p95_latency_lte_180_seconds": True,
        "concurrency_4_error_rate_lte_0_05": True,
    }
    for call in probe["calls"]:
        assert call["usage"]["input_tokens"] == 115000
        assert call["ttft_seconds"] == 0.005
        assert call["http_status"] == 200
        assert call["retry_count"] == 0
        assert call["context_length_error"] is False
        assert call["silent_truncation_detected"] is False


def test_day1_can_pass_only_with_real_full_experiment_component_costs(tmp_path: Path) -> None:
    result = run_day1_probe(
        tmp_path,
        request_fn=_successful_request_fixture(),
        api_key="test-key",
        replication_model="replica-1",
        embedding_revision="fixture-revision",
        embedding_probe_fn=_canonical_embedding_fixture,
        full_cost_inputs=_full_cost_inputs(),
    )

    assert result["status"] == "passed"
    cost = json.loads((tmp_path / "cost_upper_bound.json").read_text(encoding="utf-8"))
    assert cost["status"] == "passed"
    assert cost["dataset_checksum"] == "a" * 64
    assert cost["pricing_source"] == "provider-pricing-2026-08-01"
    assert cost["monetary_upper_bound"] == 18.75
    assert all(component["status"] == "frozen" for component in cost["components"].values())


def test_115k_http_success_without_returned_sentinel_is_blocked(tmp_path: Path) -> None:
    successful = _successful_request_fixture()

    def drops_sentinel(url, **kwargs):
        response, metadata = successful(url, **kwargs)
        payload = kwargs.get("payload") or {}
        if url.endswith(CHAT_COMPLETIONS_PATH) and payload.get("model") == PRIMARY_MODEL:
            response["choices"][0]["message"]["content"] = (
                "response omitted the requested end sentinel"
            )
        return response, metadata

    run_day1_probe(
        tmp_path,
        request_fn=drops_sentinel,
        api_key="test-key",
        replication_model="replica-1",
        embedding_revision="fixture-revision",
        embedding_probe_fn=_canonical_embedding_fixture,
    )
    probe = json.loads((tmp_path / "primary_115k_probe.json").read_text(encoding="utf-8"))
    assert probe["status"] == "blocked"
    assert probe["silent_truncation_count"] > 0
    assert probe["canonical_checks"]["silent_truncation_zero"] is False


def test_115k_context_error_is_classified_and_blocks_canonical_gate(tmp_path: Path) -> None:
    successful = _successful_request_fixture()

    def context_error(url, **kwargs):
        payload = kwargs.get("payload") or {}
        if url.endswith(CHAT_COMPLETIONS_PATH) and payload.get("model") == PRIMARY_MODEL:
            raise RuntimeError("maximum context length exceeded")
        return successful(url, **kwargs)

    run_day1_probe(
        tmp_path,
        request_fn=context_error,
        api_key="test-key",
        replication_model="replica-1",
        embedding_revision="fixture-revision",
        embedding_probe_fn=_canonical_embedding_fixture,
        full_cost_inputs=_full_cost_inputs(),
    )
    probe = json.loads((tmp_path / "primary_115k_probe.json").read_text(encoding="utf-8"))
    assert probe["status"] == "blocked"
    assert probe["context_length_error_count"] == 15
    assert probe["canonical_checks"]["context_length_errors_zero"] is False
    assert all(call["context_length_error"] is True for call in probe["calls"])


def test_115k_proxy_success_records_one_retry_and_http_status(tmp_path: Path) -> None:
    successful = _successful_request_fixture()

    def direct_fails(url, **kwargs):
        if url.endswith(CHAT_COMPLETIONS_PATH) and kwargs.get("route") == "direct":
            raise OSError("direct route unavailable")
        return successful(url, **kwargs)

    run_day1_probe(
        tmp_path,
        request_fn=direct_fails,
        api_key="test-key",
        replication_model="replica-1",
        embedding_revision="fixture-revision",
        embedding_probe_fn=_canonical_embedding_fixture,
        full_cost_inputs=_full_cost_inputs(),
    )
    probe = json.loads((tmp_path / "primary_115k_probe.json").read_text(encoding="utf-8"))
    assert probe["status"] == "passed"
    assert all(call["route"] == "proxy_17897" for call in probe["calls"])
    assert all(call["retry_count"] == 1 for call in probe["calls"])
    assert all(call["http_status"] == 200 for call in probe["calls"])


def test_judge_http_success_with_non_json_output_is_blocked() -> None:
    def fake_request(url, *, method="GET", payload=None, headers=None, route="direct", timeout=0):
        return {
            "model": JUDGE_MODEL,
            "output_text": "label=1",
            "usage": {"input_tokens": 20, "output_tokens": 3},
        }, {"status": 200, "route": route, "request_id": "judge-1", "elapsed_seconds": 0.01}

    result = _judge_probe(
        request_fn=fake_request,
        base_url="https://example.invalid/v1",
        headers={},
        timeout=1,
    )

    assert result["status"] == "blocked"
    assert result["parser_probe_success"] is False
    assert result["parser_success_rate"] == 0.0
    assert all(case["http_success"] is True for case in result["cases"])
    assert all(case["parser_success"] is False for case in result["cases"])


def test_judge_parses_json_labels_and_checks_fixed_expected_cases() -> None:
    def fake_request(url, *, method="GET", payload=None, headers=None, route="direct", timeout=0):
        assert url.endswith(CHAT_COMPLETIONS_PATH)
        assert payload["messages"] == [
            {"role": "user", "content": payload["messages"][0]["content"]}
        ]
        prompt = str(payload["messages"][0]["content"])
        return {
            "model": JUDGE_MODEL,
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({"label": _json_label_for_prompt(prompt)}),
                        }
                    ],
                }
            ],
            "usage": {"input_tokens": 20, "output_tokens": 3},
        }, {"status": 200, "route": route, "request_id": "judge-1", "elapsed_seconds": 0.01}

    result = _judge_probe(
        request_fn=fake_request,
        base_url="https://example.invalid/v1",
        headers={},
        timeout=1,
    )

    assert result["status"] == "passed"
    assert result["parser_probe_success"] is True
    assert result["parser_success_rate"] == 1.0
    assert all(case["parser_success"] is True for case in result["cases"])
    assert all(case["expected_match"] is not False for case in result["cases"])


def test_judge_parsed_but_wrong_fixed_labels_do_not_pass() -> None:
    def fake_request(url, *, method="GET", payload=None, headers=None, route="direct", timeout=0):
        return {
            "model": JUDGE_MODEL,
            "output_text": json.dumps({"label": 1}),
            "usage": {"input_tokens": 20, "output_tokens": 3},
        }, {"status": 200, "route": route, "request_id": "judge-1", "elapsed_seconds": 0.01}

    result = _judge_probe(
        request_fn=fake_request,
        base_url="https://example.invalid/v1",
        headers={},
        timeout=1,
    )

    assert result["parser_probe_success"] is True
    assert result["status"] == "blocked"
    assert any(case["expected_match"] is False for case in result["cases"])


class _FakeCuda:
    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def get_device_name(index: int) -> str:
        return "NVIDIA GeForce RTX 3090 Ti"

    @staticmethod
    def get_device_properties(index: int):
        return type("Properties", (), {"total_memory": 24 * 1024**3})()


class _FakeTorch:
    __version__ = "2.8.0+cu128"
    version = type("Version", (), {"cuda": "12.8"})()
    float16 = "torch.float16"
    cuda = _FakeCuda()


class _DeterministicSentenceTransformer:
    package_version = "5.1.0"
    last_cache_folder: str | None = None
    last_model_kwargs: dict | None = None

    def __init__(
        self,
        model: str,
        *,
        cache_folder: str,
        revision: str,
        device: str,
        trust_remote_code: bool,
        local_files_only: bool,
        model_kwargs: dict,
        tokenizer_kwargs: dict,
        config_kwargs: dict,
    ):
        self.model = model
        self.cache_folder = cache_folder
        self.revision = revision
        self.device = device
        self.trust_remote_code = trust_remote_code
        self.local_files_only = local_files_only
        self.model_kwargs = model_kwargs
        type(self).last_model_kwargs = model_kwargs
        type(self).last_cache_folder = cache_folder
        self.encode_calls = 0

    def parameters(self):
        yield type("Parameter", (), {"dtype": "torch.float16"})()

    def encode(self, texts, **kwargs):
        self.encode_calls += 1
        vectors = []
        for text in texts:
            if "alpha" in text:
                vectors.append([1.0, 0.0] + [0.0] * (BGE_M3_EMBEDDING_DIMENSION - 2))
            elif "beta" in text:
                vectors.append([0.0, 1.0] + [0.0] * (BGE_M3_EMBEDDING_DIMENSION - 2))
            else:
                vectors.append([2**-0.5, 2**-0.5] + [0.0] * (BGE_M3_EMBEDDING_DIMENSION - 2))
        return vectors


class _NondeterministicSentenceTransformer(_DeterministicSentenceTransformer):
    def encode(self, texts, **kwargs):
        vectors = super().encode(texts, **kwargs)
        if self.encode_calls % 2 == 0:
            vectors[0], vectors[1] = vectors[1], vectors[0]
        return vectors


def test_embedding_micro_probe_is_diagnostic_even_when_deterministic() -> None:
    result = probe_embedding(
        revision="explicit-fixture-revision",
        torch_module=_FakeTorch(),
        sentence_transformer_cls=_DeterministicSentenceTransformer,
        weight_resolver=lambda model, revision: {
            "weight_filename": "pytorch_model.bin",
            "weight_sha256": "f" * 64,
        },
    )

    assert result["status"] == "diagnostic_only"
    assert result["embedding_executed"] is True
    assert result["encode_run_count"] == 2
    assert result["ranking_deterministic"] is True
    assert result["packing_deterministic"] is True
    # A synthetic micro-probe must never be labelled as a real LongMemEval episode.
    assert result["single_episode_embedding_latency_seconds"] is None
    assert result["estimated_500_instance_index_seconds"] is None
    assert result["real_episode_probe"] is False
    assert result["tokenizer_revision"] == "explicit-fixture-revision"
    assert result["vram_bytes"] == 24 * 1024**3
    assert result["precision"] == "fp16"
    assert result["similarity"] == "cosine_over_normalized_vectors"
    assert result["torch_version"] == "2.8.0+cu128"
    assert result["sentence_transformers_version"] == "5.1.0"
    assert result["cuda_runtime_version"] == "12.8"
    assert result["embedding_dimension"] == BGE_M3_EMBEDDING_DIMENSION
    assert result["normalized_vectors_verified"] is True
    assert len(result["embedding_output_sha256_runs"]) == 2
    assert len(set(result["embedding_output_sha256_runs"])) == 1
    assert result["model_snapshot"] == "BAAI/bge-m3@explicit-fixture-revision"
    assert result["tokenizer_snapshot"] == "BAAI/bge-m3@explicit-fixture-revision"


def test_embedding_blocks_when_repeated_ranking_or_packing_changes() -> None:
    result = probe_embedding(
        revision="explicit-fixture-revision",
        torch_module=_FakeTorch(),
        sentence_transformer_cls=_NondeterministicSentenceTransformer,
        weight_resolver=lambda model, revision: {
            "weight_filename": "pytorch_model.bin",
            "weight_sha256": "f" * 64,
        },
    )

    assert result["status"] == "blocked"
    assert result["embedding_executed"] is True
    assert result["ranking_deterministic"] is False or result["packing_deterministic"] is False


def test_embedding_gate_rejects_self_reported_pass_without_runtime_provenance() -> None:
    incomplete = _canonical_embedding_fixture("BAAI/bge-m3", "explicit-revision")
    del incomplete["torch_version"]

    assert _embedding_qualified(incomplete) is False


def test_default_weight_resolver_uses_explicit_repo_cache_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    weight_path = tmp_path / "pytorch_model.bin"
    weight_path.write_bytes(b"frozen-weight-fixture")
    observed: dict[str, object] = {}

    def fake_download(**kwargs):
        observed.update(kwargs)
        return str(weight_path)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    result = _default_weight_resolver(
        BGE_M3_MODEL,
        BGE_M3_REVISION,
        cache_dir=DEFAULT_HF_HUB_CACHE,
    )

    assert DEFAULT_HF_HUB_CACHE == (
        Path(__file__).resolve().parents[2] / "cache" / "huggingface" / "hub"
    )
    assert observed == {
        "repo_id": BGE_M3_MODEL,
        "filename": "pytorch_model.bin",
        "revision": BGE_M3_REVISION,
        "cache_dir": str(DEFAULT_HF_HUB_CACHE),
        "local_files_only": True,
    }
    assert result["cache_hit_offline"] is True
    assert result["cache_dir"] == str(DEFAULT_HF_HUB_CACHE)
    assert result["resolved_path"] == str(weight_path.resolve())


def test_huggingface_connectivity_records_direct_then_proxy_success() -> None:
    def direct_fails(url, *, method="HEAD", payload=None, headers=None, route="direct", timeout=0):
        if route == "direct":
            raise TimeoutError("direct timeout")
        return {}, {
            "status": 200,
            "route": route,
            "request_id": "hf-proxy",
            "elapsed_seconds": 0.1,
        }

    result = probe_huggingface_connectivity(request_fn=direct_fails, timeout=1)

    assert result["status"] == "passed"
    assert result["successful_route"] == "proxy_17897"
    assert [attempt["route"] for attempt in result["attempts"]] == [
        "direct",
        "proxy_17897",
    ]
    assert result["attempts"][0]["error_type"] == "TimeoutError"
    assert result["attempts"][1]["http_status"] == 200


def test_cli_defaults_to_frozen_bge_m3_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    def fake_run(output_dir: Path, **kwargs):
        observed.update(output_dir=output_dir, **kwargs)
        return {"status": "blocked"}

    monkeypatch.delenv("BGE_M3_REVISION", raising=False)
    monkeypatch.setattr(day1, "run_day1_probe", fake_run)

    assert day1.main(["--output-dir", str(tmp_path)]) == 2
    assert BGE_M3_REVISION == "5617a9f61b028005a4858fdac845db406aefb181"
    assert observed["embedding_revision"] == BGE_M3_REVISION
    assert observed["hf_cache_dir"] == DEFAULT_HF_HUB_CACHE


def test_embedding_optional_dependencies_are_exactly_pinned() -> None:
    project = tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    dependencies = project["optional-dependencies"]["embedding"]

    assert dependencies == [
        "numpy==2.2.6",
        "torch==2.6.0",
        "transformers==4.48.3",
        "huggingface-hub==0.28.1",
        "tokenizers==0.21.0",
        "safetensors==0.5.2",
        "sentencepiece==0.2.0",
        "sentence-transformers==3.4.1",
    ]


def test_real_episode_loader_reconstructs_all_timestamped_sessions_and_raw_hash(tmp_path: Path) -> None:
    raw_path = tmp_path / "longmemeval_s_cleaned.json"
    normalized_path = tmp_path / "normalized_episodes.json"
    raw_row = {
        "question_id": "ep-real",
        "question_type": "knowledge-update",
        "question": "What changed?",
        "answer": "the deadline",
        "answer_session_ids": ["session-1"],
        "haystack_dates": ["2024/01/01 10:00", "2024/01/02 10:00"],
        "haystack_session_ids": ["session-0", "session-1"],
        "haystack_sessions": [
            [{"role": "user", "content": "old deadline"}],
            [{"role": "assistant", "content": "deadline moved"}],
        ],
    }
    raw_path.write_text(json.dumps([raw_row]), encoding="utf-8")
    normalized_path.write_text(
        json.dumps(
            [
                {
                    "episode_id": "ep-real",
                    "primary_eligible": True,
                    "eligible_for_k8": True,
                    "ordered_evidence_ids": ["ev-0", "ev-1"],
                    "evidence": [
                        {"evidence_id": "ev-0", "sequence_index": 0, "token_count": 10},
                        {"evidence_id": "ev-1", "sequence_index": 1, "token_count": 11},
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    probe = load_real_episode_probe(
        raw_path=raw_path,
        normalized_path=normalized_path,
        manifest_path=None,
        episode_id="ep-real",
    )

    assert probe["episode_id"] == "ep-real"
    assert probe["raw_sha256"]
    assert probe["session_count"] == 2
    assert probe["unit_count"] == 2
    assert probe["surrogate_token_count"] == 21
    assert probe["max_unit_surrogate_tokens"] == 11
    assert [unit["sequence_index"] for unit in probe["units"]] == [0, 1]
    assert all(unit["text"] for unit in probe["units"])
    assert probe["query_text"] == "What changed?"


def test_real_episode_embedding_records_episode_qualification_contract(tmp_path: Path) -> None:
    raw_path = tmp_path / "longmemeval_s_cleaned.json"
    normalized_path = tmp_path / "normalized_episodes.json"
    raw_row = {
        "question_id": "ep-real",
        "question_type": "knowledge-update",
        "question": "What changed?",
        "answer": "the deadline",
        "answer_session_ids": ["session-1"],
        "haystack_dates": ["2024/01/01 10:00", "2024/01/02 10:00"],
        "haystack_session_ids": ["session-0", "session-1"],
        "haystack_sessions": [
            [{"role": "user", "content": "alpha old deadline"}],
            [{"role": "assistant", "content": "beta deadline moved"}],
        ],
    }
    raw_path.write_text(json.dumps([raw_row]), encoding="utf-8")
    normalized_path.write_text(
        json.dumps(
            [
                {
                    "episode_id": "ep-real",
                    "primary_eligible": True,
                    "eligible_for_k8": True,
                    "ordered_evidence_ids": ["ev-0", "ev-1"],
                    "evidence": [
                        {"evidence_id": "ev-0", "sequence_index": 0, "token_count": 3},
                        {"evidence_id": "ev-1", "sequence_index": 1, "token_count": 3},
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = probe_embedding(
        revision="explicit-fixture-revision",
        torch_module=_FakeTorch(),
        sentence_transformer_cls=_DeterministicSentenceTransformer,
        episode_probe=load_real_episode_probe(
            raw_path=raw_path,
            normalized_path=normalized_path,
            manifest_path=None,
            episode_id="ep-real",
        ),
        weight_resolver=lambda model, revision: {
            "weight_filename": "pytorch_model.bin",
            "weight_sha256": "f" * 64,
        },
    )

    assert result["status"] == "passed"
    assert result["real_episode_probe"] is True
    assert result["episode_id"] == "ep-real"
    assert result["episode_selection"]["split"] == "explicit_fixture"
    assert result["session_count"] == 2
    assert result["episode_unit_count"] == 2
    assert result["surrogate_token_count"] == 6
    assert result["max_unit_surrogate_tokens"] == 3
    assert result["episode_batch_size"] == 1
    assert result["packing_nonempty"] is True
    assert all(result["packing_runs"][0])
    assert result["single_episode_embedding_latency_seconds"] is not None
    assert result["estimated_500_instance_index_seconds"] is not None
    assert result["peak_vram_bytes"] == 24 * 1024**3
    assert result["weight_filename"] == "pytorch_model.bin"
    assert result["weight_sha256"] == "f" * 64
    assert result["use_safetensors"] is False
    assert _DeterministicSentenceTransformer.last_model_kwargs == {
        "torch_dtype": "torch.float16",
        "use_safetensors": False,
    }
    assert _DeterministicSentenceTransformer.last_cache_folder == str(DEFAULT_HF_HUB_CACHE)
    assert result["hf_cache_dir"] == str(DEFAULT_HF_HUB_CACHE)
    assert result["hf_cache_policy"] == "repo_local_offline_frozen_snapshot"
    assert _embedding_qualified(result) is False


def test_embedding_gate_rejects_real_episode_with_empty_packing() -> None:
    complete = _canonical_embedding_fixture("BAAI/bge-m3", "explicit-revision")
    complete["packing_nonempty"] = False

    assert _embedding_qualified(complete) is False


def test_embedding_gate_rejects_acceptance_episode_probe() -> None:
    complete = _canonical_embedding_fixture("BAAI/bge-m3", "explicit-revision")
    complete["episode_selection"]["split"] = "acceptance"

    assert _embedding_qualified(complete) is False


def test_real_episode_loader_fails_closed_without_split_manifest(tmp_path: Path) -> None:
    raw_path = tmp_path / "longmemeval_s_cleaned.json"
    normalized_path = tmp_path / "normalized_episodes.json"
    raw_path.write_text("[]", encoding="utf-8")
    normalized_path.write_text("[]", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="split manifest"):
        load_real_episode_probe(
            raw_path=raw_path,
            normalized_path=normalized_path,
            manifest_path=tmp_path / "missing_manifest.json",
        )


def test_real_episode_loader_rejects_raw_checksum_mismatch(tmp_path: Path) -> None:
    raw_path = tmp_path / "longmemeval_s_cleaned.json"
    normalized_path = tmp_path / "normalized_episodes.json"
    manifest_path = tmp_path / "dataset_manifest.json"
    raw_path.write_text(
        json.dumps(
            [
                {
                    "question_id": "ep-real",
                    "question_type": "knowledge-update",
                    "question": "What changed?",
                    "haystack_dates": ["2024/01/01 10:00"],
                    "haystack_session_ids": ["session-0"],
                    "haystack_sessions": [[{"role": "user", "content": "changed"}]],
                }
            ]
        ),
        encoding="utf-8",
    )
    normalized_path.write_text(
        json.dumps(
            [
                {
                    "episode_id": "ep-real",
                    "question_type": "knowledge-update",
                    "dataset_version_or_commit": "fixture-revision",
                    "primary_eligible": True,
                    "eligible_for_k8": True,
                    "evidence": [
                        {"evidence_id": "ev-0", "sequence_index": 0, "token_count": 2}
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    manifest = {
        "source_revision": "fixture-revision",
        "raw_checksums": {
            "longmemeval_s_cleaned.json": {"sha256": "0" * 64}
        },
        "split_candidates": [
            {
                "candidate_id": "20_30_50",
                "assignments": [
                    {"split": "development", "episode_ids": ["ep-real"]}
                ],
            }
        ],
    }
    manifest["audit_hash"] = stable_hash(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="checksum"):
        load_real_episode_probe(
            raw_path=raw_path,
            normalized_path=normalized_path,
            manifest_path=manifest_path,
        )


def test_real_episode_loader_rejects_tampered_manifest_audit_hash(tmp_path: Path) -> None:
    raw_path = tmp_path / "longmemeval_s_cleaned.json"
    normalized_path = tmp_path / "normalized_episodes.json"
    manifest_path = tmp_path / "dataset_manifest.json"
    raw_path.write_text("[]", encoding="utf-8")
    normalized_path.write_text("[]", encoding="utf-8")
    manifest_path.write_text(json.dumps({"audit_hash": "0" * 64}), encoding="utf-8")

    with pytest.raises(ValueError, match="audit hash"):
        load_real_episode_probe(
            raw_path=raw_path,
            normalized_path=normalized_path,
            manifest_path=manifest_path,
        )


def test_real_episode_loader_rejects_normalized_evidence_hash_mismatch(tmp_path: Path) -> None:
    raw_path = tmp_path / "longmemeval_s_cleaned.json"
    normalized_path = tmp_path / "normalized_episodes.json"
    manifest_path = tmp_path / "dataset_manifest.json"
    session = [{"role": "user", "content": "changed"}]
    raw_path.write_text(
        json.dumps(
            [
                {
                    "question_id": "ep-real",
                    "question_type": "knowledge-update",
                    "question": "What changed?",
                    "haystack_dates": ["2024/01/01 10:00"],
                    "haystack_session_ids": ["session-0"],
                    "haystack_sessions": [session],
                }
            ]
        ),
        encoding="utf-8",
    )
    normalized_path.write_text(
        json.dumps(
            [
                {
                    "episode_id": "ep-real",
                    "question_type": "knowledge-update",
                    "dataset_version_or_commit": "fixture-revision",
                    "primary_eligible": True,
                    "eligible_for_k8": True,
                    "ordered_evidence_ids": ["ev-0"],
                    "evidence": [
                        {
                            "evidence_id": "ev-0",
                            "source_session_id": "session-0",
                            "sequence_index": 0,
                            "token_count": 2,
                            "raw_sha256": "0" * 64,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    manifest = {
        "source_revision": "fixture-revision",
        "raw_checksums": {
            "longmemeval_s_cleaned.json": {
                "sha256": day1._sha256_file(raw_path),
            }
        },
        "split_candidates": [
            {
                "candidate_id": "20_30_50",
                "assignments": [
                    {"split": "development", "episode_ids": ["ep-real"]}
                ],
            }
        ],
    }
    manifest["audit_hash"] = stable_hash(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="evidence hash"):
        load_real_episode_probe(
            raw_path=raw_path,
            normalized_path=normalized_path,
            manifest_path=manifest_path,
        )
