"""Strict, offline cost contracts for the Day 1 qualification gate.

The module deliberately does not fetch anything.  Callers pass the bytes
obtained from LabForge's public pricing/status endpoints and the immutable
evidence identifying the deployed pricing formula.  Keeping parsing and
workload construction pure makes the cost gate deterministic and testable.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.request
from decimal import Decimal, ROUND_CEILING, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


class CostContractError(ValueError):
    """Raised when pricing or workload evidence is incomplete or inconsistent."""


# This is a protocol-level envelope, not a selected experimental budget.  A
# later power gate may select a strict subset after calibration.
COST_BUDGET_ENVELOPE = (
    128,
    192,
    256,
    384,
    512,
    768,
    1024,
    1536,
    2048,
    3072,
    4096,
)

_PRICING_URL = "https://labforge.cc/api/pricing"
_STATUS_URL = "https://labforge.cc/api/status"
_API_BASE_URL = "https://api.labforge.cc/v1"
_CHAT_ENDPOINT = "/v1/chat/completions"
_REQUIRED_MODELS = ("gpt-5.6-sol", "gpt-5.5", "gpt-5.4")
_EXPECTED_FORMULA_EVIDENCE = {
    "pricing_formula_bundle_url": "https://labforge.cc/static/js/async/7214.80b6263a1a.js",
    "pricing_formula_bundle_sha256": "5fd20fe3af70ced3e2dba4896e1bbc1490c3baf17a5b4a53983e96cc20021edb",
    "currency_formula_bundle_url": "https://labforge.cc/static/js/index.c108bd6748.js",
    "currency_formula_bundle_sha256": "d2e23bf3a9c1b2ae53b74e32b7067d18834a5451f14dbb7ff6ffb950ffc4cbe8",
    "upstream_formula_url": "https://github.com/QuantumNous/new-api/commit/0ab02020603d22e5613bc4cf46bfab06f8567769",
    "formula_id": "new-api-token-quota-v1",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_COMPONENTS = ("primary", "replication", "SATURATION", "D_leaf", "future_k_sweep")


def _json_object(raw: Any, label: str) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        value = raw
    elif isinstance(raw, (bytes, bytearray, str)):
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CostContractError(f"{label} is not valid JSON") from exc
    else:
        raise CostContractError(f"{label} must be JSON bytes or an object")
    if not isinstance(value, Mapping):
        raise CostContractError(f"{label} must be a JSON object")
    return value


def _sha256(raw: Any) -> str:
    if isinstance(raw, str):
        raw = raw.encode()
    if not isinstance(raw, (bytes, bytearray)):
        raw = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(bytes(raw)).hexdigest()


def _fetch_public_bytes(url: str, *, route: str, timeout: float) -> bytes:
    proxy_handler = urllib.request.ProxyHandler(
        {} if route == "direct" else {"http": "http://127.0.0.1:17897", "https": "http://127.0.0.1:17897"}
    )
    opener = urllib.request.build_opener(proxy_handler)
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json, text/javascript, */*", "User-Agent": "plan-robust-memory-day1/1.0"},
    )
    with opener.open(request, timeout=timeout) as response:
        return response.read()


def fetch_labforge_pricing_snapshot(*, timeout: float = 30.0) -> dict[str, Any]:
    """Fetch public pricing evidence with the protocol's two-route fallback."""

    formula_urls = (
        (_EXPECTED_FORMULA_EVIDENCE["pricing_formula_bundle_url"], "pricing_formula_bundle_sha256"),
        (_EXPECTED_FORMULA_EVIDENCE["currency_formula_bundle_url"], "currency_formula_bundle_sha256"),
    )
    errors: list[dict[str, str]] = []
    for route in ("direct", "proxy_17897"):
        try:
            pricing_raw = _fetch_public_bytes(_PRICING_URL, route=route, timeout=timeout)
            status_raw = _fetch_public_bytes(_STATUS_URL, route=route, timeout=timeout)
            formula_raw: dict[str, bytes] = {}
            for url, hash_key in formula_urls:
                raw = _fetch_public_bytes(url, route=route, timeout=timeout)
                if _sha256(raw) != _EXPECTED_FORMULA_EVIDENCE[hash_key]:
                    raise CostContractError(f"deployed formula bundle hash mismatch for {url}")
                formula_raw[hash_key] = raw
            snapshot = parse_labforge_pricing_snapshot(
                pricing_raw,
                status_raw,
                formula_evidence=_EXPECTED_FORMULA_EVIDENCE,
                route=route,
                fetched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            snapshot["formula_bundle_response_sha256"] = {
                key: _sha256(raw) for key, raw in formula_raw.items()
            }
            snapshot["pricing_fetch_attempts"] = errors + [{"route": route, "status": "success"}]
            return snapshot
        except (CostContractError, OSError, urllib.error.URLError, TimeoutError) as exc:
            errors.append({"route": route, "status": "failed", "error_type": type(exc).__name__, "error": str(exc)[:240]})
    raise CostContractError(
        "LabForge pricing evidence failed through direct and proxy_17897 routes: "
        + json.dumps(errors, sort_keys=True)
    )


def _positive_number(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise CostContractError(f"{field} must be a positive number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise CostContractError(f"{field} must be a positive number") from exc
    if not number.is_finite() or number <= 0:
        raise CostContractError(f"{field} must be a positive number")
    return number


def _decimal_string(value: Decimal) -> str:
    # Fixed-point output avoids scientific notation in an auditable artifact.
    text = format(value, "f").rstrip("0").rstrip(".")
    return text or "0"


def _number_for_artifact(value: Decimal) -> int | float:
    """Use JSON-native numbers where the frozen value is integral."""
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _validate_formula_evidence(evidence: Any) -> dict[str, str]:
    if not isinstance(evidence, Mapping):
        raise CostContractError("formula evidence must be an object")
    if set(evidence) != set(_EXPECTED_FORMULA_EVIDENCE):
        raise CostContractError("formula evidence fields are incomplete")
    normalized = {str(key): str(value) for key, value in evidence.items()}
    if normalized != _EXPECTED_FORMULA_EVIDENCE:
        raise CostContractError("formula evidence does not match the deployed formula")
    for key in ("pricing_formula_bundle_sha256", "currency_formula_bundle_sha256"):
        value = normalized[key]
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise CostContractError("formula evidence contains an invalid SHA-256")
    return normalized


def parse_labforge_pricing_snapshot(
    pricing_raw: Any,
    status_raw: Any,
    *,
    formula_evidence: Mapping[str, Any],
    route: str,
    fetched_at: str,
) -> dict[str, Any]:
    """Parse and freeze the public LabForge pricing evidence.

    The public status endpoint exposes a display exchange rate while the
    provider's quota formula prices one quota unit directly in USD.  The
    exchange rate is therefore recorded for audit but intentionally not
    applied to the USD rates below.
    """

    if not isinstance(pricing_raw, (bytes, bytearray)) or not isinstance(status_raw, (bytes, bytearray)):
        raise CostContractError("pricing and status evidence must retain raw response bytes")
    pricing_bytes = pricing_raw
    status_bytes = status_raw
    pricing = _json_object(pricing_raw, "pricing response")
    status = _json_object(status_raw, "status response")
    evidence = _validate_formula_evidence(formula_evidence)

    if route not in {"direct", "proxy_17897", "proxy"}:
        raise CostContractError("route must identify direct or proxy_17897")
    if not isinstance(fetched_at, str) or not fetched_at.strip():
        raise CostContractError("fetched_at is required")

    for payload, label, expected_url in (
        (pricing, "pricing", _PRICING_URL),
        (status, "status", _STATUS_URL),
    ):
        for source_key in ("source_url", "source", "url"):
            if source_key in payload and payload[source_key] != expected_url:
                raise CostContractError(f"{label} source URL is not {expected_url}")
    if pricing.get("success") is not True:
        raise CostContractError("pricing response success field is false")
    if status.get("success") is not True:
        raise CostContractError("status response success field is false")
    pricing_version = pricing.get("pricing_version")
    if not isinstance(pricing_version, str) or not pricing_version.strip():
        raise CostContractError("pricing_version is required")

    endpoint = pricing.get("supported_endpoint")
    if not isinstance(endpoint, Mapping):
        raise CostContractError("supported_endpoint is required")
    openai_endpoint = endpoint.get("openai")
    if not isinstance(openai_endpoint, Mapping):
        raise CostContractError("openai chat/completions endpoint is required")
    if openai_endpoint.get("path") != _CHAT_ENDPOINT or str(openai_endpoint.get("method", "")).upper() != "POST":
        raise CostContractError("pricing must support the OpenAI chat/completions endpoint")

    groups = pricing.get("group_ratio")
    if not isinstance(groups, Mapping) or not groups:
        raise CostContractError("group_ratio is required")
    group_ratios: dict[str, Decimal] = {}
    for name, value in groups.items():
        group_ratios[str(name)] = _positive_number(value, f"group_ratio[{name}]")
    selected_group_ratio = max(group_ratios.values())

    status_data = status.get("data")
    if not isinstance(status_data, Mapping):
        raise CostContractError("status data is required")
    quota_per_unit_raw = status_data.get("quota_per_unit")
    quota_per_unit = _positive_number(quota_per_unit_raw, "quota_per_unit")
    if quota_per_unit != quota_per_unit.to_integral_value():
        raise CostContractError("quota_per_unit must be an integer")
    if Decimal(1_000_000) / quota_per_unit != Decimal(2):
        raise CostContractError("quota_per_unit is inconsistent with the deployed USD formula")
    usd_exchange_rate = _positive_number(status_data.get("usd_exchange_rate"), "usd_exchange_rate")

    rows = pricing.get("data")
    if not isinstance(rows, list):
        raise CostContractError("pricing data must be a list")
    by_model: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        name = row.get("model_name")
        if isinstance(name, str):
            by_model[name] = row

    rates: dict[str, dict[str, str]] = {}
    model_metadata: dict[str, dict[str, Any]] = {}
    for model in _REQUIRED_MODELS:
        row = by_model.get(model)
        if row is None:
            raise CostContractError(f"missing required model {model}")
        if row.get("quota_type") != 0:
            raise CostContractError(f"{model} quota_type must be 0")
        model_ratio = _positive_number(row.get("model_ratio"), f"{model}.model_ratio")
        completion_ratio = _positive_number(row.get("completion_ratio"), f"{model}.completion_ratio")
        endpoints = row.get("supported_endpoint_types")
        if not isinstance(endpoints, list) or "openai" not in endpoints:
            raise CostContractError(f"{model} does not support the openai endpoint")
        enabled = row.get("enable_groups")
        if not isinstance(enabled, list) or not enabled:
            raise CostContractError(f"{model}.enable_groups is required")
        enabled_ratios = [group_ratios.get(str(group)) for group in enabled]
        if any(value is None for value in enabled_ratios):
            raise CostContractError(f"{model} references an unknown group_ratio")
        # Unknown API-key group means the worst enabled multiplier is payable.
        model_group_ratio = max(value for value in enabled_ratios if value is not None)
        if model_group_ratio != selected_group_ratio:
            # Keep the global conservative policy explicit even where a model
            # advertises a narrower group set.
            model_group_ratio = selected_group_ratio
        unit_factor = Decimal(1_000_000) / quota_per_unit
        input_rate = model_ratio * model_group_ratio * unit_factor
        output_rate = input_rate * completion_ratio
        rates[model] = {
            "input": _decimal_string(input_rate),
            "output": _decimal_string(output_rate),
        }
        model_metadata[model] = {
            "model_ratio": _decimal_string(model_ratio),
            "completion_ratio": _decimal_string(completion_ratio),
            "enabled_groups": [str(group) for group in enabled],
        }

    return {
        "schema_version": "plan-robust-memory.labforge-pricing.v1",
        "status": "passed",
        "api_base_url": _API_BASE_URL,
        "chat_completions_endpoint": f"{_API_BASE_URL}/chat/completions",
        "pricing_source_url": _PRICING_URL,
        "status_source_url": _STATUS_URL,
        "pricing_response_sha256": _sha256(pricing_bytes if pricing_bytes is not None else pricing),
        "status_response_sha256": _sha256(status_bytes if status_bytes is not None else status),
        "pricing_version": pricing_version,
        "fetched_at": fetched_at,
        "route": route,
        "quota_per_unit": int(quota_per_unit),
        "usd_exchange_rate": _decimal_string(usd_exchange_rate),
        "usd_exchange_rate_role": "display_only_not_applied_to_usd_rates",
        "group_ratios": {name: _decimal_string(value) for name, value in group_ratios.items()},
        "selected_group_ratio": _number_for_artifact(selected_group_ratio),
        "selected_group_ratio_policy": "maximum_enabled_group_ratio",
        "model_metadata": model_metadata,
        "rates_usd_per_million_tokens": rates,
        "formula_evidence": evidence,
        "currency": "USD",
    }


def _read_source(path: Path, label: str) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CostContractError(f"{label} is missing: {path}") from exc
    return _json_object(raw, label)


def _require_int(value: Any, field: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CostContractError(f"{field} must be an integer >= {minimum}")
    return value


def _require_sha256(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise CostContractError(f"{field} must be a SHA-256")
    return value


def _check_grouped_counts(manifest: Mapping[str, Any], power: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    grouped = manifest.get("grouped_split_counts")
    if not isinstance(grouped, Mapping):
        raise CostContractError("manifest grouped_split_counts is required")
    expected_splits = ("development", "calibration", "acceptance")
    result: dict[str, dict[str, int]] = {}
    for split in expected_splits:
        row = grouped.get(split)
        if not isinstance(row, Mapping):
            raise CostContractError(f"missing grouped split {split}")
        result[split] = {name: _require_int(row.get(name), f"{split}.{name}") for name in ("N_master", "N4", "N8", "N16")}
    for name in ("N_master", "N4", "N8", "N16"):
        # Grouped rows are the primary-eligible strata (not the full cleaned
        # master population), therefore they must sum to primary_{name}.
        counts = manifest.get("counts")
        if not isinstance(counts, Mapping):
            raise CostContractError("manifest counts are required")
        expected = _require_int(
            counts.get(f"primary_{name}"),
            f"counts.primary_{name}",
        )
        if sum(result[split][name] for split in expected_splits) != expected:
            raise CostContractError(f"grouped counts do not sum to counts.primary_{name}")
    power_grouped = power.get("grouped_split_counts")
    if power_grouped != grouped:
        raise CostContractError("power grouped_split_counts do not match manifest")
    return result


def _ceil_microusd(tokens: int, rate_usd_per_million: str) -> int:
    value = Decimal(tokens) * Decimal(rate_usd_per_million) / Decimal(1_000_000) * Decimal(1_000_000)
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def build_full_experiment_cost_inputs(
    *,
    dataset_manifest_path: Path,
    power_artifact_path: Path,
    replication_probe_path: Path,
    model_inventory_path: Path,
    pricing_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate frozen sources and construct a recomputable full-run bound."""

    manifest = _read_source(Path(dataset_manifest_path), "dataset manifest")
    power = _read_source(Path(power_artifact_path), "power artifact")
    replication = _read_source(Path(replication_probe_path), "replication probe")
    inventory = _read_source(Path(model_inventory_path), "model inventory")
    if not isinstance(pricing_snapshot, Mapping) or pricing_snapshot.get("status") != "passed":
        raise CostContractError("pricing snapshot must be a passed snapshot")
    rates = pricing_snapshot.get("rates_usd_per_million_tokens")
    if not isinstance(rates, Mapping) or any(model not in rates for model in _REQUIRED_MODELS):
        raise CostContractError("pricing snapshot is missing required model rates")
    for model in _REQUIRED_MODELS:
        row = rates[model]
        if not isinstance(row, Mapping) or not row.get("input") or not row.get("output"):
            raise CostContractError(f"pricing snapshot rate for {model} is incomplete")
        _positive_number(row.get("input"), f"pricing rate {model}.input")
        _positive_number(row.get("output"), f"pricing rate {model}.output")

    if manifest.get("status") not in {"passed", "qualified_with_exclusions"}:
        raise CostContractError("dataset manifest is not qualified")
    if not isinstance(manifest.get("source_revision"), str) or not manifest["source_revision"].strip():
        raise CostContractError("dataset source_revision is required")
    _require_sha256(manifest.get("audit_hash"), "manifest.audit_hash")
    counts = manifest.get("counts")
    if not isinstance(counts, Mapping):
        raise CostContractError("manifest counts are required")
    total_master = _require_int(counts.get("N_master"), "counts.N_master")
    primary_count = _require_int(counts.get("primary_N_master"), "counts.primary_N_master")
    if primary_count != 199:
        raise CostContractError("primary eligible count must be the qualified 199")
    for name in ("N4", "N8", "N16"):
        if _require_int(counts.get(name), f"counts.{name}") != total_master:
            raise CostContractError(f"counts.{name} must match N_master")
        if _require_int(counts.get(f"primary_{name}"), f"counts.primary_{name}") != primary_count:
            raise CostContractError(f"counts.primary_{name} must match primary_N_master")
    raw_checksums = manifest.get("raw_checksums")
    checksum_row = (
        raw_checksums.get("longmemeval_s_cleaned.json")
        if isinstance(raw_checksums, Mapping)
        else None
    )
    if not isinstance(checksum_row, Mapping) or checksum_row.get("present") is not True:
        raise CostContractError("raw LongMemEval checksum evidence is missing")
    dataset_checksum = checksum_row.get("sha256")
    _require_sha256(dataset_checksum, "raw LongMemEval checksum")
    categories = manifest.get("eligible_primary_categories")
    if not isinstance(categories, list) or set(categories) != {"knowledge-update", "temporal-reasoning"}:
        raise CostContractError("eligible primary categories are not frozen")
    _check_grouped_counts(manifest, power)
    if power.get("status") != "passed" or power.get("R_pilot") != 3 or power.get("R_formal") != 5:
        raise CostContractError("power artifact must freeze R_pilot=3 and R_formal=5")
    _require_sha256(power.get("split_assignment_hash"), "power.split_assignment_hash")
    if replication.get("status") != "passed" or replication.get("artifact_state") != "completed":
        raise CostContractError("replication model probe is not passed")
    requested_model = replication.get("requested_model")
    returned_model = replication.get("returned_model")
    if requested_model != returned_model or returned_model != "gpt-5.4":
        raise CostContractError("replication model request/response is not the frozen gpt-5.4")
    if replication.get("run_id") and inventory.get("run_id") and replication.get("run_id") != inventory.get("run_id"):
        raise CostContractError("replication and inventory run_id do not match")
    if inventory.get("status") != "passed" or inventory.get("artifact_state") != "completed":
        raise CostContractError("model inventory is not passed")
    inventory_models = inventory.get("returned_model_ids")
    if not isinstance(inventory_models, list) or any(model not in inventory_models for model in _REQUIRED_MODELS):
        raise CostContractError("model inventory does not contain all frozen models")

    budget_count = len(COST_BUDGET_ENVELOPE)
    episodes = primary_count
    calibration_episodes = 60
    repeats = 5
    # Every component is an explicit logical-call count.  These are upper
    # bounds over all currently registered branches, not selected results.
    # Primary includes pilot, formal, stress, online and their judges; leaves
    # are counted once per fixed (episode, backbone, k) cache namespace.
    pilot_leaves = calibration_episodes * 8
    pilot_merges = calibration_episodes * 3 * budget_count * 3 * (8 - 1)
    pilot_answers = calibration_episodes * 3 * budget_count * 3
    formal_leaves = episodes * 8
    formal_merges = episodes * 3 * budget_count * repeats * (8 - 1)
    formal_answers = episodes * 3 * budget_count * repeats
    online_merges = episodes * 2 * budget_count * repeats * (8 * (8 - 1) // 2)
    online_answers = episodes * 2 * budget_count * repeats * 8
    primary_generation = pilot_leaves + pilot_merges + pilot_answers + formal_leaves + formal_merges + formal_answers + online_merges + online_answers
    primary_judges = pilot_answers + formal_answers * 2 + online_answers
    replication_generation = formal_leaves + episodes * 2 * budget_count * repeats * (8 - 1) + episodes * 2 * budget_count * repeats
    replication_judges = episodes * 2 * budget_count * repeats
    saturation_generation = calibration_episodes * (1 + budget_count) * repeats
    saturation_judges = saturation_generation
    future_leaves = episodes * (4 + 8 + 16)
    future_merges = episodes * 3 * budget_count * repeats * ((4 - 1) + (8 - 1) + (16 - 1))
    future_answers = episodes * 3 * 3 * budget_count * repeats
    future_generation = 2 * (future_leaves + future_merges + future_answers)
    future_judges = 2 * future_answers
    logical_counts = {
        "primary": (primary_generation, primary_judges),
        "replication": (replication_generation, replication_judges),
        "SATURATION": (saturation_generation, saturation_judges),
        "D_leaf": (1600, 100),
        "future_k_sweep": (future_generation, future_judges),
    }
    models_for_component = {
        "primary": ("gpt-5.6-sol", "gpt-5.5"),
        "replication": ("gpt-5.4", "gpt-5.5"),
        "SATURATION": ("gpt-5.6-sol", "gpt-5.5"),
        "D_leaf": ("gpt-5.6-sol", "gpt-5.5"),
        "future_k_sweep": ("gpt-5.6-sol", "gpt-5.5"),
    }
    input_tokens_per_call = {
        "primary": 1_000_000,
        "replication": 1_000_000,
        "SATURATION": 1_000_000,
        "D_leaf": 1_000_000,
        "future_k_sweep": 1_000_000,
    }
    output_tokens_per_call = {
        "primary": 4096,
        "replication": 4096,
        "SATURATION": 4096,
        "D_leaf": 4096,
        "future_k_sweep": 4096,
    }
    components: dict[str, dict[str, Any]] = {}
    workload_rows: list[dict[str, Any]] = []
    for component, (generation_logical, judge_logical) in logical_counts.items():
        generation_model, judge_model = models_for_component[component]
        component_rows: list[dict[str, Any]] = []
        for role, model, role_logical, output_cap in (
            ("generation", generation_model, generation_logical, output_tokens_per_call[component]),
            ("judge", judge_model, judge_logical, 128),
        ):
            billable = role_logical * 2
            input_cap = input_tokens_per_call[component]
            input_tokens = billable * input_cap
            output_tokens = billable * output_cap
            rate = rates[model]
            money_micro = _ceil_microusd(input_tokens, str(rate["input"])) + _ceil_microusd(output_tokens, str(rate["output"]))
            row = {
                "component": component,
                "stage": component,
                "role": role,
                "model": model,
                "backbone": "primary" if model == "gpt-5.6-sol" else ("replication" if model == "gpt-5.4" else "judge"),
                "split": "calibration" if component == "SATURATION" else "all_primary_eligible",
                "k": 8 if component != "future_k_sweep" else [4, 8, 16],
                "budget_tokens": list(COST_BUDGET_ENVELOPE),
                "plan": "frozen_plan_set_envelope",
                "repeat_count": repeats,
                "logical_call_upper_bound": role_logical,
                "call_upper_bound": billable,
                "input_token_upper_bound": input_tokens,
                "output_token_upper_bound": output_tokens,
                "input_tokens_per_billable_call": input_cap,
                "output_tokens_per_billable_call": output_cap,
                "monetary_upper_bound_microusd": money_micro,
                "monetary_upper_bound": money_micro / 1_000_000,
                "max_billable_attempts_per_logical_call": 2,
                "workload_source_hash": _sha256(json.dumps({"manifest": dict(manifest), "power": dict(power)}, sort_keys=True, separators=(",", ":"))),
            }
            workload_rows.append(row)
            component_rows.append(row)
        component_micro = sum(row["monetary_upper_bound_microusd"] for row in component_rows)
        components[component] = {
            "component": component,
            "status": "frozen",
            "logical_call_upper_bound": sum(row["logical_call_upper_bound"] for row in component_rows),
            "call_upper_bound": sum(row["call_upper_bound"] for row in component_rows),
            "input_token_upper_bound": sum(row["input_token_upper_bound"] for row in component_rows),
            "output_token_upper_bound": sum(row["output_token_upper_bound"] for row in component_rows),
            "monetary_upper_bound_microusd": component_micro,
            "monetary_upper_bound": component_micro / 1_000_000,
        }

    return {
        "status": "passed",
        "schema_version": "plan-robust-memory.full-experiment-cost-inputs.v1",
        "dataset_source": str(Path(dataset_manifest_path).resolve()),
        "dataset_checksum": dataset_checksum,
        "dataset_counts": dict(counts),
        "grouped_split_counts": manifest["grouped_split_counts"],
        "pricing_source": f"{pricing_snapshot.get('pricing_source_url')} + {pricing_snapshot.get('status_source_url')}",
        "pricing_snapshot": dict(pricing_snapshot),
        "currency": "USD",
        "max_billable_attempts_per_logical_call": 2,
        "workload_contract": {
            "budget_envelope_tokens": list(COST_BUDGET_ENVELOPE),
            "budget_selection_frozen": False,
            "actual_budget_must_be_subset": True,
            "max_billable_attempts_per_logical_call": 2,
            "input_bound_policy": {
                "kind": "client_stop_cap_plus_provider_usage_guard",
                "description": "billable attempts are capped at two; every attempt must remain below the one-million-token client stop cap and provider exact usage is recorded",
                "max_input_tokens_per_billable_call": 1_000_000,
                "provider_usage_required": True,
            },
            "conditional_branches": {
                "primary_stress_operator": "included",
                "online_gate": "included",
                "matched_capacity_sensitivity": "included_in_future_k_sweep",
                "judge_repeatability": "included_in_primary_judge_envelope",
            },
            "episode_axes": {
                "primary_eligible": 199,
                "calibration": 60,
                "acceptance": 99,
                "future_k_sweep": "E_16=primary_eligible",
            },
            "repeat_axes": {"R_pilot": 3, "R_formal": 5, "saturation_upper_bound": 5},
            "plan_axes": {
                "Pi_primary": ["left_deep", "canonical_balanced"],
                "Pi_diag": ["left_deep", "canonical_balanced", "right_deep"],
                "Pi_online": ["eager_left_deep", "online_canonical_balanced"],
            },
        },
        "components": components,
        "workload_rows": workload_rows,
        "recomputation": {
            "logical_call_sum": sum(row["logical_call_upper_bound"] for row in components.values()),
            "billable_call_sum": sum(row["call_upper_bound"] for row in components.values()),
            "billable_attempt_multiplier": 2,
            "D_leaf_logical_call_upper_bound": 1700,
            "D_leaf_billable_call_upper_bound": 3400,
        },
    }


def validate_full_experiment_cost_inputs(value: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute all cost totals and reject caller-supplied monetary shortcuts."""

    if not isinstance(value, Mapping) or value.get("status") != "passed":
        raise CostContractError("full cost inputs must be a passed mapping")
    _require_sha256(value.get("dataset_checksum"), "dataset checksum")
    if value.get("currency") != "USD":
        raise CostContractError("cost currency must be USD")
    pricing = value.get("pricing_snapshot")
    if not isinstance(pricing, Mapping) or pricing.get("status") != "passed":
        raise CostContractError("pricing snapshot is required")
    rates = pricing.get("rates_usd_per_million_tokens")
    if not isinstance(rates, Mapping):
        raise CostContractError("pricing rates are required")
    for model in _REQUIRED_MODELS:
        rate = rates.get(model)
        if not isinstance(rate, Mapping):
            raise CostContractError(f"pricing rate missing for {model}")
        _positive_number(rate.get("input"), f"{model}.input rate")
        _positive_number(rate.get("output"), f"{model}.output rate")

    contract = value.get("workload_contract")
    if not isinstance(contract, Mapping):
        raise CostContractError("workload_contract is required")
    if tuple(contract.get("budget_envelope_tokens", ())) != COST_BUDGET_ENVELOPE:
        raise CostContractError("budget envelope does not match frozen cost contract")
    if contract.get("budget_selection_frozen") is not False or contract.get("actual_budget_must_be_subset") is not True:
        raise CostContractError("budget subset contract is missing")
    if contract.get("max_billable_attempts_per_logical_call") != 2:
        raise CostContractError("billable attempt upper bound must equal 2")
    policy = contract.get("input_bound_policy")
    if not isinstance(policy, Mapping) or policy.get("kind") != "client_stop_cap_plus_provider_usage_guard":
        raise CostContractError("input token upper-bound policy is not frozen")

    rows = value.get("workload_rows")
    if not isinstance(rows, list) or not rows:
        raise CostContractError("workload_rows are required")
    grouped: dict[str, dict[str, int]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise CostContractError(f"workload row {index} is not an object")
        component = row.get("component")
        model = row.get("model")
        if component not in _REQUIRED_COMPONENTS or model not in _REQUIRED_MODELS:
            raise CostContractError(f"workload row {index} has an unknown component/model")
        logical = _require_int(row.get("logical_call_upper_bound"), f"workload row {index}.logical_call_upper_bound")
        billable = _require_int(row.get("call_upper_bound"), f"workload row {index}.call_upper_bound")
        if billable != logical * 2:
            raise CostContractError(f"workload row {index} billable calls do not equal two attempts")
        input_cap = _require_int(row.get("input_tokens_per_billable_call"), f"workload row {index}.input_tokens_per_billable_call")
        output_cap = _require_int(row.get("output_tokens_per_billable_call"), f"workload row {index}.output_tokens_per_billable_call")
        input_total = _require_int(row.get("input_token_upper_bound"), f"workload row {index}.input_token_upper_bound")
        output_total = _require_int(row.get("output_token_upper_bound"), f"workload row {index}.output_token_upper_bound")
        if input_total != billable * input_cap or output_total != billable * output_cap:
            raise CostContractError(f"workload row {index} token totals are inconsistent")
        expected_micro = _ceil_microusd(input_total, str(rates[model]["input"])) + _ceil_microusd(output_total, str(rates[model]["output"]))
        if row.get("monetary_upper_bound_microusd") != expected_micro:
            raise CostContractError(f"workload row {index} monetary total is not recomputable")
        supplied_money = row.get("monetary_upper_bound")
        if (
            isinstance(supplied_money, bool)
            or not isinstance(supplied_money, (int, float))
            or not math.isfinite(float(supplied_money))
            or float(supplied_money) != expected_micro / 1_000_000
        ):
            raise CostContractError(f"workload row {index} monetary value is invalid")
        _require_sha256(row.get("workload_source_hash"), f"workload row {index}.workload_source_hash")
        current = grouped.setdefault(component, {"logical": 0, "billable": 0, "input": 0, "output": 0, "money": 0})
        current["logical"] += logical
        current["billable"] += billable
        current["input"] += input_total
        current["output"] += output_total
        current["money"] += expected_micro

    if set(grouped) != set(_REQUIRED_COMPONENTS):
        raise CostContractError("every required cost component needs workload rows")
    components = value.get("components")
    if not isinstance(components, Mapping) or set(components) != set(_REQUIRED_COMPONENTS):
        raise CostContractError("component aggregate set is incomplete")
    normalized_components: dict[str, dict[str, Any]] = {}
    for component in _REQUIRED_COMPONENTS:
        aggregate = grouped[component]
        supplied = components[component]
        if not isinstance(supplied, Mapping) or supplied.get("status") != "frozen":
            raise CostContractError(f"{component} aggregate is not frozen")
        fields = {
            "logical_call_upper_bound": aggregate["logical"],
            "call_upper_bound": aggregate["billable"],
            "input_token_upper_bound": aggregate["input"],
            "output_token_upper_bound": aggregate["output"],
            "monetary_upper_bound_microusd": aggregate["money"],
        }
        for field, expected in fields.items():
            if supplied.get(field) != expected:
                raise CostContractError(f"{component} aggregate {field} does not match workload rows")
        expected_money = aggregate["money"] / 1_000_000
        if supplied.get("monetary_upper_bound") != expected_money:
            raise CostContractError(f"{component} aggregate monetary value is invalid")
        normalized_components[component] = {"status": "frozen", **fields, "monetary_upper_bound": expected_money}
    total_micro = sum(item["monetary_upper_bound_microusd"] for item in normalized_components.values())
    normalized = dict(value)
    normalized["components"] = normalized_components
    normalized["status"] = "passed"
    normalized["scope"] = "full_experiment_upper_bound"
    normalized["monetary_upper_bound_microusd"] = total_micro
    normalized["monetary_upper_bound"] = total_micro / 1_000_000
    normalized["unknown_cost_not_zero"] = True
    normalized["blocking_reasons"] = []
    normalized["required_inputs"] = []
    normalized["recomputation"] = {
        "logical_call_sum": sum(item["logical_call_upper_bound"] for item in normalized_components.values()),
        "billable_call_sum": sum(item["call_upper_bound"] for item in normalized_components.values()),
        "billable_attempt_multiplier": 2,
        "D_leaf_logical_call_upper_bound": 1700,
        "D_leaf_billable_call_upper_bound": 3400,
    }
    return normalized
