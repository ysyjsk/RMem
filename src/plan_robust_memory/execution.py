from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import ContractError


def proxy_probe_result(port: int, attempts: int, status: str) -> Mapping[str, Any]:
    if port != 17897:
        raise ContractError("proxy probe must use port 17897")
    if attempts <= 0 or attempts > 3:
        raise ContractError("proxy probe must use finite retry attempts")
    return {"port": port, "attempts": attempts, "status": status}


def validate_endpoint_probe(artifact: Mapping[str, Any]) -> None:
    required = ("requested_model", "returned_model", "provider", "base_url", "success")
    for field in required:
        if field not in artifact:
            raise ContractError(f"{field} missing from endpoint probe")
    if str(artifact["returned_model"]).endswith("-latest"):
        raise ContractError("endpoint probe must not silently fallback to rolling alias")


def stall_blocks_next_milestone(report: Mapping[str, Any]) -> bool:
    return bool(report.get("p14_triggered") and report.get("reported_to_user") and report.get("next_milestone_blocked"))

