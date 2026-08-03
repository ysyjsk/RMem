"""Refresh only the blocked Day 1 cost artifact from public LabForge evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .day1_cost import (
    CostContractError,
    build_full_experiment_cost_inputs,
    fetch_labforge_pricing_snapshot,
)
from .probe_day1 import refresh_day1_cost_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day1-dir", type=Path, default=Path("artifacts/day1"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("artifacts/longmemeval/dataset_manifest.json"),
    )
    parser.add_argument(
        "--power",
        type=Path,
        default=Path("artifacts/power/power_feasibility.json"),
    )
    parser.add_argument(
        "--replication-probe",
        type=Path,
        default=Path("artifacts/day1/replication_model_probe.json"),
    )
    parser.add_argument(
        "--model-inventory",
        type=Path,
        default=Path("artifacts/day1/model_inventory.json"),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    try:
        pricing = fetch_labforge_pricing_snapshot(timeout=args.timeout)
        inputs = build_full_experiment_cost_inputs(
            dataset_manifest_path=args.manifest,
            power_artifact_path=args.power,
            replication_probe_path=args.replication_probe,
            model_inventory_path=args.model_inventory,
            pricing_snapshot=pricing,
        )
        result = refresh_day1_cost_artifact(args.day1_dir, full_cost_inputs=inputs)
    except (CostContractError, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
