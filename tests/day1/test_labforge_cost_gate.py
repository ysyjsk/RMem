from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from plan_robust_memory.day1_cost import (
    COST_BUDGET_ENVELOPE,
    CostContractError,
    build_full_experiment_cost_inputs,
    fetch_labforge_pricing_snapshot,
    parse_labforge_pricing_snapshot,
)
from plan_robust_memory.probe_day1 import _build_cost_upper_bound


FORMULA_EVIDENCE = {
    "pricing_formula_bundle_url": "https://labforge.cc/static/js/async/7214.80b6263a1a.js",
    "pricing_formula_bundle_sha256": "5fd20fe3af70ced3e2dba4896e1bbc1490c3baf17a5b4a53983e96cc20021edb",
    "currency_formula_bundle_url": "https://labforge.cc/static/js/index.c108bd6748.js",
    "currency_formula_bundle_sha256": "d2e23bf3a9c1b2ae53b74e32b7067d18834a5451f14dbb7ff6ffb950ffc4cbe8",
    "upstream_formula_url": "https://github.com/QuantumNous/new-api/commit/0ab02020603d22e5613bc4cf46bfab06f8567769",
    "formula_id": "new-api-token-quota-v1",
}


def _pricing_payload() -> dict:
    return {
        "success": True,
        "pricing_version": "a42d372ccf0b5dd13ecf71203521f9d2",
        "group_ratio": {"default": 1, "GPT": 1, "GPT Pro": 2},
        "supported_endpoint": {
            "openai": {"path": "/v1/chat/completions", "method": "POST"}
        },
        "data": [
            {
                "model_name": "gpt-5.6-sol",
                "quota_type": 0,
                "model_ratio": 0.5,
                "completion_ratio": 6,
                "enable_groups": ["default", "GPT", "GPT Pro"],
                "supported_endpoint_types": ["openai"],
            },
            {
                "model_name": "gpt-5.5",
                "quota_type": 0,
                "model_ratio": 0.5,
                "completion_ratio": 6,
                "enable_groups": ["default", "GPT", "GPT Pro"],
                "supported_endpoint_types": ["openai"],
            },
            {
                "model_name": "gpt-5.4",
                "quota_type": 0,
                "model_ratio": 0.25,
                "completion_ratio": 6,
                "enable_groups": ["default", "GPT", "GPT Pro"],
                "supported_endpoint_types": ["openai"],
            },
        ],
    }


def _status_payload() -> dict:
    return {
        "success": True,
        "data": {
            "quota_per_unit": 500_000,
            "usd_exchange_rate": 7.3,
            "price": 7.3,
            "server_address": "https://api.labforge.cc",
            "system_name": "LabForge",
        },
    }


def _snapshot() -> dict:
    return parse_labforge_pricing_snapshot(
        json.dumps(_pricing_payload()).encode(),
        json.dumps(_status_payload()).encode(),
        formula_evidence=FORMULA_EVIDENCE,
        route="direct",
        fetched_at="2026-08-03T10:00:00Z",
    )


def _write_sources(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    counts = {
        "N_master": 470,
        "N4": 470,
        "N8": 470,
        "N16": 470,
        "primary_N_master": 199,
        "primary_N4": 199,
        "primary_N8": 199,
        "primary_N16": 199,
    }
    grouped = {
        "development": {name: 40 for name in ("N_master", "N4", "N8", "N16")},
        "calibration": {name: 60 for name in ("N_master", "N4", "N8", "N16")},
        "acceptance": {name: 99 for name in ("N_master", "N4", "N8", "N16")},
    }
    manifest = {
        "status": "qualified_with_exclusions",
        "source_revision": "98d7416c24c778c2fee6e6f3006e7a073259d48f",
        "raw_checksums": {
            "longmemeval_s_cleaned.json": {
                "present": True,
                "sha256": "d" * 64,
                "size_bytes": 277_383_467,
            }
        },
        "counts": counts,
        "grouped_split_counts": grouped,
        "eligible_primary_categories": ["knowledge-update", "temporal-reasoning"],
        "token_accounting": {"measurement_kind": "surrogate_estimate"},
        "audit_hash": "a" * 64,
    }
    power = {
        "status": "passed",
        "R_pilot": 3,
        "R_formal": 5,
        "delta_decision": 0.1,
        "split_assignment_hash": "b" * 64,
        "grouped_split_counts": grouped,
    }
    replication = {
        "status": "passed",
        "artifact_state": "completed",
        "run_id": "day1-fixture",
        "requested_model": "gpt-5.4",
        "returned_model": "gpt-5.4",
    }
    inventory = {
        "status": "passed",
        "artifact_state": "completed",
        "run_id": "day1-fixture",
        "returned_model_ids": ["gpt-5.6-sol", "gpt-5.5", "gpt-5.4"],
    }
    paths = tuple(
        tmp_path / name
        for name in ("manifest.json", "power.json", "replication.json", "inventory.json")
    )
    for path, value in zip(paths, (manifest, power, replication, inventory), strict=True):
        path.write_text(json.dumps(value), encoding="utf-8")
    return paths


def test_labforge_snapshot_derives_conservative_rates_from_public_evidence() -> None:
    snapshot = _snapshot()

    assert snapshot["status"] == "passed"
    assert snapshot["api_base_url"] == "https://api.labforge.cc/v1"
    assert snapshot["pricing_source_url"] == "https://labforge.cc/api/pricing"
    assert snapshot["status_source_url"] == "https://labforge.cc/api/status"
    assert len(snapshot["pricing_response_sha256"]) == 64
    assert len(snapshot["status_response_sha256"]) == 64
    assert snapshot["pricing_version"] == "a42d372ccf0b5dd13ecf71203521f9d2"
    assert snapshot["quota_per_unit"] == 500_000
    assert snapshot["selected_group_ratio"] == 2
    assert snapshot["selected_group_ratio_policy"] == "maximum_enabled_group_ratio"
    assert snapshot["rates_usd_per_million_tokens"] == {
        "gpt-5.6-sol": {"input": "2", "output": "12"},
        "gpt-5.5": {"input": "2", "output": "12"},
        "gpt-5.4": {"input": "1", "output": "6"},
    }
    assert snapshot["usd_exchange_rate_role"] == "display_only_not_applied_to_usd_rates"
    assert snapshot["formula_evidence"] == FORMULA_EVIDENCE


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda pricing, status: pricing["data"].pop(), "gpt-5.4"),
        (lambda pricing, status: pricing["group_ratio"].clear(), "group_ratio"),
        (lambda pricing, status: status["data"].pop("quota_per_unit"), "quota_per_unit"),
        (lambda pricing, status: status["data"].update(quota_per_unit=250_000), "quota_per_unit"),
        (
            lambda pricing, status: pricing["supported_endpoint"]["openai"].update(
                path="/v1/responses"
            ),
            "chat/completions",
        ),
        (lambda pricing, status: pricing["data"][0].update(quota_type=1), "quota_type"),
    ],
)
def test_labforge_snapshot_fails_closed_on_incomplete_evidence(mutation, match) -> None:
    pricing = _pricing_payload()
    status = _status_payload()
    mutation(pricing, status)

    with pytest.raises(CostContractError, match=match):
        parse_labforge_pricing_snapshot(
            json.dumps(pricing).encode(),
            json.dumps(status).encode(),
            formula_evidence=FORMULA_EVIDENCE,
            route="direct",
            fetched_at="2026-08-03T10:00:00Z",
        )


def test_labforge_snapshot_requires_the_deployed_formula_evidence() -> None:
    evidence = dict(FORMULA_EVIDENCE)
    evidence["pricing_formula_bundle_sha256"] = "0" * 64

    with pytest.raises(CostContractError, match="formula evidence"):
        parse_labforge_pricing_snapshot(
            json.dumps(_pricing_payload()).encode(),
            json.dumps(_status_payload()).encode(),
            formula_evidence=evidence,
            route="direct",
            fetched_at="2026-08-03T10:00:00Z",
        )


def test_labforge_pricing_fetch_stops_after_direct_then_proxy(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def failing_fetch(url: str, *, route: str, timeout: float) -> bytes:
        calls.append((route, url))
        raise OSError("fixture route failure")

    monkeypatch.setattr("plan_robust_memory.day1_cost._fetch_public_bytes", failing_fetch)

    with pytest.raises(CostContractError, match="direct and proxy_17897"):
        fetch_labforge_pricing_snapshot(timeout=0.01)

    assert [route for route, _ in calls] == ["direct", "proxy_17897"]
    assert len(calls) == 2


def test_real_manifest_builds_a_recomputable_full_experiment_upper_bound(
    tmp_path: Path,
) -> None:
    manifest, power, replication, inventory = _write_sources(tmp_path)
    inputs = build_full_experiment_cost_inputs(
        dataset_manifest_path=manifest,
        power_artifact_path=power,
        replication_probe_path=replication,
        model_inventory_path=inventory,
        pricing_snapshot=_snapshot(),
    )
    artifact = _build_cost_upper_bound(inputs)

    assert artifact["status"] == "passed"
    assert artifact["dataset_checksum"] == "d" * 64
    assert artifact["workload_contract"]["budget_envelope_tokens"] == list(
        COST_BUDGET_ENVELOPE
    )
    assert artifact["workload_contract"]["budget_selection_frozen"] is False
    assert artifact["workload_contract"]["actual_budget_must_be_subset"] is True
    assert artifact["workload_contract"]["max_billable_attempts_per_logical_call"] == 2
    assert artifact["workload_contract"]["input_bound_policy"]["kind"] == (
        "client_stop_cap_plus_provider_usage_guard"
    )
    assert set(artifact["components"]) == {
        "primary",
        "replication",
        "SATURATION",
        "D_leaf",
        "future_k_sweep",
    }
    assert artifact["components"]["D_leaf"]["logical_call_upper_bound"] == 1700
    assert artifact["components"]["D_leaf"]["call_upper_bound"] == 3400
    assert all(
        isinstance(component[field], int) and component[field] > 0
        for component in artifact["components"].values()
        for field in (
            "logical_call_upper_bound",
            "call_upper_bound",
            "input_token_upper_bound",
            "output_token_upper_bound",
            "monetary_upper_bound_microusd",
        )
    )
    assert artifact["monetary_upper_bound_microusd"] == sum(
        component["monetary_upper_bound_microusd"]
        for component in artifact["components"].values()
    )
    assert artifact["monetary_upper_bound"] == pytest.approx(
        artifact["monetary_upper_bound_microusd"] / 1_000_000
    )
    assert artifact["pricing_snapshot"]["rates_usd_per_million_tokens"] == (
        _snapshot()["rates_usd_per_million_tokens"]
    )
    assert {row["model"] for row in artifact["workload_rows"]} == {
        "gpt-5.6-sol",
        "gpt-5.5",
        "gpt-5.4",
    }
    assert all(
        {
            "component",
            "stage",
            "role",
            "model",
            "split",
            "k",
            "budget_tokens",
            "plan",
            "repeat_count",
            "workload_source_hash",
        }.issubset(row)
        for row in artifact["workload_rows"]
    )
    assert all(row["call_upper_bound"] == row["logical_call_upper_bound"] * 2 for row in artifact["workload_rows"])


@pytest.mark.parametrize("bad_value", [0.5, True, -1, math.nan, math.inf])
def test_cost_builder_rejects_tampered_or_non_integer_workload(
    tmp_path: Path, bad_value: object
) -> None:
    paths = _write_sources(tmp_path)
    inputs = build_full_experiment_cost_inputs(
        dataset_manifest_path=paths[0],
        power_artifact_path=paths[1],
        replication_probe_path=paths[2],
        model_inventory_path=paths[3],
        pricing_snapshot=_snapshot(),
    )
    tampered = copy.deepcopy(inputs)
    tampered["workload_rows"][0]["call_upper_bound"] = bad_value

    artifact = _build_cost_upper_bound(tampered)

    assert artifact["status"] == "blocked"
    assert artifact["monetary_upper_bound"] is None
    assert artifact["unknown_cost_not_zero"] is True


def test_cost_builder_recomputes_money_instead_of_trusting_caller(
    tmp_path: Path,
) -> None:
    paths = _write_sources(tmp_path)
    inputs = build_full_experiment_cost_inputs(
        dataset_manifest_path=paths[0],
        power_artifact_path=paths[1],
        replication_probe_path=paths[2],
        model_inventory_path=paths[3],
        pricing_snapshot=_snapshot(),
    )
    inputs["components"]["primary"]["monetary_upper_bound"] = 0

    artifact = _build_cost_upper_bound(inputs)

    assert artifact["status"] == "blocked"
    assert artifact["monetary_upper_bound"] is None
