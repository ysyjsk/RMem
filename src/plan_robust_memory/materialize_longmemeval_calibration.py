from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .qualify_judge_repeatability import (
    _write_json,
    materialize_calibration_split,
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the frozen Q_cal projection used by Judge Repeatability. "
            "This is a data-steward transform, not an evaluator Gate."
        )
    )
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=Path("artifacts/longmemeval/dataset_manifest.json"),
    )
    parser.add_argument(
        "--power-artifact",
        type=Path,
        default=Path("artifacts/power/power_feasibility.json"),
    )
    parser.add_argument(
        "--normalized-episodes",
        type=Path,
        default=Path("artifacts/longmemeval/normalized_episodes.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "artifacts/longmemeval/normalized_calibration_20_30_50.json"
        ),
    )
    parser.add_argument(
        "--access-log",
        type=Path,
        default=Path(
            "artifacts/longmemeval/calibration_split_materialization_log.json"
        ),
    )
    args = parser.parse_args(argv)
    source_bytes = args.normalized_episodes.read_bytes()
    artifact = materialize_calibration_split(
        audit=_load(args.dataset_manifest),
        power_artifact=_load(args.power_artifact),
        normalized_episodes=_load(args.normalized_episodes),
        source_normalized_sha256=hashlib.sha256(source_bytes).hexdigest(),
    )
    _write_json(args.output, artifact)
    _write_json(
        args.access_log,
        {
            "schema_version": "plan-robust-memory.calibration-split-materialization-log.v1",
            "operation": "trusted_split_projection",
            "source_path": str(args.normalized_episodes),
            "source_sha256": artifact["source_normalized_sha256"],
            "source_power_artifact_hash": artifact[
                "source_power_artifact_hash"
            ],
            "output_path": str(args.output),
            "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            "source_split": "calibration",
            "split_candidate_id": "20_30_50",
            "acceptance_routing_metadata_read": True,
            "acceptance_payload_exported": False,
            "normalization_or_prompt_calls": 0,
        },
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "output": str(args.output),
                "episode_count": artifact["episode_count"],
                "artifact_hash": artifact["artifact_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
