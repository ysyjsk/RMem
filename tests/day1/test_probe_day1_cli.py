from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

from plan_robust_memory.probe_day1 import (
    ARTIFACT_NAMES,
    JUDGE_MODEL,
    PRIMARY_MODEL,
    _judge_probe,
    probe_embedding,
    run_day1_probe,
)


def _canonical_embedding_fixture(model: str, revision: str | None) -> dict:
    return {
        "status": "passed",
        "model": model,
        "revision": revision or "fixture-revision",
        "tokenizer_revision": revision or "fixture-revision",
        "embedding_executed": True,
        "encode_run_count": 2,
        "ranking_deterministic": True,
        "packing_deterministic": True,
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
            }
        prompt = str(payload.get("input", ""))
        if payload.get("model") == JUDGE_MODEL:
            output_text = json.dumps({"label": _json_label_for_prompt(prompt)})
        else:
            # The 115K probe appends a unique sentinel to the request and requires it back.
            output_text = prompt[-512:]
        return {
            "id": request_id,
            "model": payload.get("model", PRIMARY_MODEL),
            "output_text": output_text,
            "usage": {"input_tokens": 115000, "output_tokens": 32},
        }, {
            "status": 200,
            "route": route,
            "request_id": request_id,
            "elapsed_seconds": 0.01,
            "ttft_seconds": 0.005,
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


def test_day1_blocked_run_writes_all_artifacts_and_stall_report(tmp_path: Path) -> None:
    def failing_request(*args, **kwargs):
        raise OSError("network unavailable")

    result = run_day1_probe(tmp_path, request_fn=failing_request)

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
        "Candidate paths",
        "User decision required",
    ):
        assert required_section in report

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
        if url.endswith("/responses") and payload.get("model") == PRIMARY_MODEL:
            response["output_text"] = "response omitted the requested end sentinel"
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
        if url.endswith("/responses") and payload.get("model") == PRIMARY_MODEL:
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
        if url.endswith("/responses") and kwargs.get("route") == "direct":
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
        prompt = str(payload["input"])
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
    cuda = _FakeCuda()


class _DeterministicSentenceTransformer:
    def __init__(self, model: str, *, revision: str, device: str):
        self.model = model
        self.revision = revision
        self.device = device
        self.encode_calls = 0

    def encode(self, texts, **kwargs):
        self.encode_calls += 1
        vectors = []
        for text in texts:
            if "alpha" in text:
                vectors.append([1.0, 0.0])
            elif "beta" in text:
                vectors.append([0.0, 1.0])
            else:
                vectors.append([0.5, 0.5])
        return vectors


class _NondeterministicSentenceTransformer(_DeterministicSentenceTransformer):
    def encode(self, texts, **kwargs):
        vectors = super().encode(texts, **kwargs)
        if self.encode_calls % 2 == 0:
            vectors[0], vectors[1] = vectors[1], vectors[0]
        return vectors


def test_embedding_pass_requires_real_encode_ranking_and_packing_determinism() -> None:
    result = probe_embedding(
        revision="explicit-fixture-revision",
        torch_module=_FakeTorch(),
        sentence_transformer_cls=_DeterministicSentenceTransformer,
    )

    assert result["status"] == "passed"
    assert result["embedding_executed"] is True
    assert result["encode_run_count"] == 2
    assert result["ranking_deterministic"] is True
    assert result["packing_deterministic"] is True
    assert result["single_episode_embedding_latency_seconds"] is not None
    assert result["estimated_500_instance_index_seconds"] is not None
    assert result["tokenizer_revision"] == "explicit-fixture-revision"
    assert result["vram_bytes"] == 24 * 1024**3


def test_embedding_blocks_when_repeated_ranking_or_packing_changes() -> None:
    result = probe_embedding(
        revision="explicit-fixture-revision",
        torch_module=_FakeTorch(),
        sentence_transformer_cls=_NondeterministicSentenceTransformer,
    )

    assert result["status"] == "blocked"
    assert result["embedding_executed"] is True
    assert result["ranking_deterministic"] is False or result["packing_deterministic"] is False
