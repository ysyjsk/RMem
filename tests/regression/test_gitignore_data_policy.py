from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MAX_TRACKED_FILE_BYTES = 5 * 1024 * 1024
FORBIDDEN_TRACKED_SUFFIXES = {
    ".arrow",
    ".avro",
    ".bin",
    ".ckpt",
    ".csv",
    ".db",
    ".duckdb",
    ".faiss",
    ".feather",
    ".gguf",
    ".h5",
    ".hdf5",
    ".joblib",
    ".jsonl",
    ".ndjson",
    ".npy",
    ".npz",
    ".onnx",
    ".orc",
    ".parquet",
    ".pickle",
    ".pkl",
    ".pt",
    ".pth",
    ".safetensors",
    ".sqlite",
    ".sqlite3",
    ".tsv",
}


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _is_ignored(relative_path: str) -> bool:
    result = _git("check-ignore", "--no-index", "--quiet", "--", relative_path)
    assert result.returncode in {0, 1}, result.stderr
    return result.returncode == 0


@pytest.mark.parametrize(
    "relative_path",
    [
        ".env.local",
        ".cache/huggingface/hub/models--example/snapshot.bin",
        ".pytest_cache/v/cache/nodeids",
        "src/plan_robust_memory_protocol.egg-info/PKG-INFO",
        "data/raw/future-dataset/source.json",
        "data/future-dataset/samples.jsonl",
        "data/protected_acceptance/sealed.json",
        "artifacts/day1/model_inventory.json",
        "artifacts/future/normalized_episodes.json",
        "cache/leaves/episode.json",
        "logs/access/provider.jsonl",
        "datasets/downloaded/source.json",
        "downloads/archive.json",
        "raw/dataset.json",
        "processed/features.jsonl",
        "runs/experiment-001/result.json",
        "outputs/predictions.jsonl",
        "predictions/acceptance.jsonl",
        "checkpoints/model.ckpt",
        "samples.csv",
        "table.parquet",
        "embeddings.faiss",
        "weights.bin",
        "model.safetensors",
        "dataset.tar.zst",
        "node_modules/example/package.json",
    ],
)
def test_runtime_data_and_generated_outputs_are_ignored(relative_path: str) -> None:
    assert _is_ignored(relative_path), relative_path


@pytest.mark.parametrize(
    "relative_path",
    [
        ".env.example",
        "src/plan_robust_memory/future_module.py",
        "tests/unit/test_future_contract.py",
        "schemas/future.schema.json",
        "data/fixtures/future/synthetic.jsonl",
        "data/fixtures/future/synthetic.csv",
        "data/protected_acceptance/.gitkeep",
        "artifacts/reports/qualification.md",
        "artifacts/reports/archive/qualification.md",
        "cache/.gitkeep",
    ],
)
def test_source_contracts_synthetic_fixtures_and_reports_remain_trackable(
    relative_path: str,
) -> None:
    assert not _is_ignored(relative_path), relative_path


def test_tracked_files_contain_no_runtime_data_or_large_payloads() -> None:
    result = _git("ls-files", "-z")
    assert result.returncode == 0, result.stderr
    tracked = [Path(value) for value in result.stdout.split("\0") if value]

    forbidden: list[str] = []
    oversized: list[str] = []
    for relative in tracked:
        posix = relative.as_posix()
        if posix.startswith("data/") and not (
            posix.startswith("data/fixtures/")
            or posix == "data/protected_acceptance/.gitkeep"
        ):
            forbidden.append(posix)
        if posix.startswith("artifacts/") and not (
            posix.startswith("artifacts/reports/") and relative.suffix == ".md"
        ):
            forbidden.append(posix)
        if posix.startswith(
            (
                "checkpoints/",
                "datasets/",
                "downloads/",
                "evaluations/",
                "external/",
                "interim/",
                "outputs/",
                "predictions/",
                "processed/",
                "raw/",
                "results/",
                "runs/",
                "scratch/",
            )
        ):
            forbidden.append(posix)
        if (
            relative.suffix.lower() in FORBIDDEN_TRACKED_SUFFIXES
            and not posix.startswith("data/fixtures/")
        ):
            forbidden.append(posix)

        absolute = ROOT / relative
        if absolute.is_file() and absolute.stat().st_size > MAX_TRACKED_FILE_BYTES:
            oversized.append(f"{posix} ({absolute.stat().st_size} bytes)")

    assert forbidden == [], "runtime data is tracked: " + ", ".join(sorted(set(forbidden)))
    assert oversized == [], "tracked files exceed 5 MiB: " + ", ".join(oversized)
