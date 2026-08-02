from __future__ import annotations

import hashlib
import json
from pathlib import Path

from plan_robust_memory.audit_longmemeval import audit_dataset


def _write_fixture(root: Path) -> None:
    (root / "haystacks").mkdir(parents=True)
    questions = [
        {"id": "q1", "domain": "web", "environment": "fixture", "question_type": "knowledge-update", "question": "q", "answer": "a", "eval_function": "exact"},
        {"id": "q2_abs", "domain": "web", "environment": "fixture", "question_type": "temporal-reasoning-abs", "question": "q", "answer": "a", "eval_function": "exact"},
        {"id": "q3", "domain": "web", "environment": "fixture", "question_type": "other", "question": "q", "answer": "a", "eval_function": "exact"},
        {"id": "q4", "domain": "web", "environment": "fixture", "question_type": "other", "question": "q", "answer": "a", "eval_function": "exact"},
    ]
    (root / "questions.jsonl").write_text("".join(json.dumps(row) + "\n" for row in questions), encoding="utf-8")
    trajectories = [
        {"id": "t1", "session_uuid": "s1", "current_time": "2026-01-01", "messages": [{"role": "user", "content": "one"}]},
        {"id": "t2", "session_uuid": "s2", "current_time": "2026-01-02", "messages": [{"role": "user", "content": "two"}]},
        {"id": "t3", "session_uuid": "s3", "current_time": "2026-01-03", "messages": [{"role": "user", "content": "three"}]},
        {"id": "t4", "session_uuid": "s4", "current_time": "2026-01-04", "messages": [{"role": "user", "content": "four"}]},
    ]
    (root / "trajectories.jsonl").write_text("".join(json.dumps(row) + "\n" for row in trajectories), encoding="utf-8")
    mapping = {"q1": ["t1", "t2", "t3", "t4"], "q2_abs": ["t1"], "q3": ["t1", "t2", "t3", "t4"], "q4": ["missing"]}
    (root / "haystacks" / "lme_v2_small.json").write_text(json.dumps(mapping), encoding="utf-8")


def test_real_adapter_preserves_counts_checksums_and_exclusions(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    result = audit_dataset(tmp_path, tmp_path / "out")
    assert result["status"] == "qualified_with_exclusions"
    assert result["counts"]["question_total"] == 4
    assert result["counts"]["N_master"] == 2
    assert result["counts"]["N4"] == 2
    assert result["counts"]["N8"] == 0
    assert result["counts"]["primary_N_master"] == 1
    assert result["counts"]["primary_N4"] == 1
    assert result["counts"]["abs_count"] == 1
    assert result["raw_checksums"]["questions.jsonl"]["sha256"]
    assert len(result["normalized_episodes"]) == 2
    assert {row["episode_id"] for row in result["normalized_episodes"]} == {"q1", "q3"}
    excluded = {row["question_id"]: row["reason"] for row in result["excluded_items"]}
    assert "q4" in excluded and "missing_trajectory" in excluded["q4"]
    assert "q2_abs" in excluded and "abstention" in excluded["q2_abs"]
    assert len(result["conversion_log"]) == 4
    checksum_lines = (tmp_path / "out" / "checksums.sha256").read_text(
        encoding="utf-8"
    ).splitlines()
    source_paths = sorted(
        [
            tmp_path / "questions.jsonl",
            tmp_path / "haystacks" / "lme_v2_small.json",
            tmp_path / "trajectories.jsonl",
        ],
        key=lambda path: str(path.resolve()),
    )
    assert checksum_lines == [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.resolve()}"
        for path in source_paths
    ]
