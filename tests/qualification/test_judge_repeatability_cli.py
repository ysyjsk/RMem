from __future__ import annotations

import json
from pathlib import Path

import pytest

import plan_robust_memory.qualify_judge_repeatability as qualification


def test_cli_exposes_only_the_calibration_projection(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        qualification.main(["--help"])
    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--calibration-artifact" in help_text
    assert "--normalized-episodes" not in help_text
    assert "--day1-dir" in help_text
    assert "--evaluator-parity-run-state" in help_text


@pytest.mark.parametrize(
    ("calibration_contents", "expected_reason"),
    [
        (None, "No such file or directory"),
        ("{not-json", "valid JSON"),
    ],
)
def test_cli_preflight_failure_has_current_run_identity_and_stall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    calibration_contents: str | None,
    expected_reason: str,
) -> None:
    output_dir = tmp_path / "qualification"
    calibration_path = tmp_path / "calibration.json"
    dataset_path = tmp_path / "dataset.json"
    power_path = tmp_path / "power.json"
    dataset_path.write_text("{}", encoding="utf-8")
    power_path.write_text("{}", encoding="utf-8")
    if calibration_contents is not None:
        calibration_path.write_text(calibration_contents, encoding="utf-8")

    writes: list[dict] = []
    original_write = qualification._write_json

    def recording_write(path: Path, payload: dict) -> None:
        if path.name == "judge_repeatability_run_state.json":
            writes.append(dict(payload))
        original_write(path, payload)

    monkeypatch.setattr(qualification, "_write_json", recording_write)
    exit_code = qualification.main(
        [
            "--output-dir",
            str(output_dir),
            "--dataset-manifest",
            str(dataset_path),
            "--power-artifact",
            str(power_path),
            "--calibration-artifact",
            str(calibration_path),
        ]
    )

    assert exit_code == 2
    assert writes[0]["state"] == "preparing"
    run_state = json.loads(
        (output_dir / "judge_repeatability_run_state.json").read_text(
            encoding="utf-8"
        )
    )
    stall = json.loads(
        (output_dir / "judge_repeatability_stall.json").read_text(encoding="utf-8")
    )
    assert run_state["state"] == "blocked"
    assert run_state["run_id"] == writes[0]["run_id"] == stall["run_id"]
    assert run_state["completed_observations"] == 0
    assert run_state["acceptance_accessed"] is False
    assert run_state["full_leaf_generation_allowed"] is False
    assert expected_reason in stall["reason"]
    assert stall["failure_phase"] == "preparation"
    assert stall["next_stage"] == "judge_repeatability"


def test_preflight_does_not_claim_stale_canonical_artifacts(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "qualification"
    output_dir.mkdir()
    old_artifact = {
        "schema_version": "old",
        "run_id": "old-successful-run",
        "status": "passed",
    }
    canonical = output_dir / "judge_repeatability.json"
    canonical.write_text(json.dumps(old_artifact), encoding="utf-8")

    exit_code = qualification.main(
        [
            "--output-dir",
            str(output_dir),
            "--calibration-artifact",
            str(tmp_path / "missing.json"),
        ]
    )

    assert exit_code == 2
    assert json.loads(canonical.read_text(encoding="utf-8")) == old_artifact
    run_state = json.loads(
        (output_dir / "judge_repeatability_run_state.json").read_text(
            encoding="utf-8"
        )
    )
    entry = run_state["artifacts"]["judge_repeatability.json"]
    assert entry == {
        "state": "not_published_for_this_run",
        "run_id": run_state["run_id"],
    }
