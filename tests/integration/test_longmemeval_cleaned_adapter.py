from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import plan_robust_memory.audit_longmemeval as adapter
from plan_robust_memory.audit_longmemeval import (
    CLEANED_FILENAME,
    CLEANED_REVISION,
    audit_cleaned_dataset,
    fetch_cleaned_official_file,
    main,
)


def _episode(
    question_id: str,
    question_type: str,
    n: int,
    *,
    family_id: str | None = None,
    question: str | None = None,
) -> dict:
    ids = [f"{question_id}-s{i}" for i in range(n)]
    return {
        "question_id": question_id,
        "question_type": question_type,
        "question": question or f"question {question_id}",
        "answer": "answer",
        "question_date": "2026-01-31",
        "haystack_session_ids": ids,
        "haystack_dates": [f"2026-01-{i + 1:02d}" for i in range(n)],
        "haystack_sessions": [[{"role": "user", "content": f"{question_id} session {i}", "has_answer": i == n - 1}] for i in range(n)],
        "answer_session_ids": [ids[-1]],
        **({"family_id": family_id} if family_id is not None else {}),
    }


def test_cleaned_s_adapter_builds_real_episode_and_k_counts(tmp_path: Path) -> None:
    raw = tmp_path / "longmemeval_s_cleaned.json"
    raw.write_text(json.dumps([_episode("ku", "knowledge-update", 4), _episode("tr", "temporal-reasoning", 8), _episode("x_abs", "knowledge-update", 4)]), encoding="utf-8")
    result = audit_cleaned_dataset(raw, tmp_path / "out", revision="fixture-revision")
    assert result["status"] == "qualified_with_exclusions"
    assert result["counts"]["question_total"] == 3
    assert result["counts"]["primary_N_master"] == 2
    assert result["counts"]["primary_N4"] == 2
    assert result["counts"]["primary_N8"] == 1
    assert result["counts"]["primary_N16"] == 0
    assert result["counts"]["abs_count"] == 1
    assert len(result["normalized_episodes"]) == 2
    assert len(result["answer_session_mapping"]) == 3
    assert result["answer_session_mapping"][0]["mapping_status"] == "available"
    excluded_mapping = next(
        row for row in result["answer_session_mapping"] if row["question_id"] == "x_abs"
    )
    assert excluded_mapping["normalization_status"] == "excluded"
    assert excluded_mapping["exclusion_reason"] == "abstention_secondary_only"
    assert result["no_silent_drop"] is True
    checksum_manifest = (tmp_path / "out" / "checksums.sha256").read_text(
        encoding="utf-8"
    )
    assert hashlib.sha256(raw.read_bytes()).hexdigest() in checksum_manifest
    assert str(raw.resolve()) in checksum_manifest


def test_evidence_layout_uses_k8_leaf_mapping_not_support_session_count(
    tmp_path: Path,
) -> None:
    row = _episode("ku", "knowledge-update", 16)
    # With 16 equal-size sessions and k=8, sessions 0 and 1 share the first
    # token-balanced leaf. Counting supporting sessions would incorrectly call
    # this a multiple-support-leaf episode.
    row["answer_session_ids"] = row["haystack_session_ids"][:2]
    raw = tmp_path / CLEANED_FILENAME
    raw.write_text(json.dumps([row]), encoding="utf-8")

    result = audit_cleaned_dataset(raw, tmp_path / "out", revision="fixture-revision")

    episode = result["normalized_episodes"][0]
    assert episode["evidence_layout"]["k"] == 8
    assert episode["evidence_layout"]["supporting_leaf_indices"] == [0]
    assert episode["evidence_layout"]["n_supporting_leaves"] == 1
    assert episode["evidence_layout"]["support_leaf_class"] == "single"


def test_repeated_source_session_id_at_distinct_timestamps_is_disambiguated(
    tmp_path: Path,
) -> None:
    row = _episode("ku", "knowledge-update", 8)
    repeated_source_id = row["haystack_session_ids"][0]
    row["haystack_session_ids"][1] = repeated_source_id
    # A timestamped session is the atomic item. The official cleaned-S source
    # contains repeated filler IDs at distinct timestamps, so dropping the
    # whole episode would silently shrink the real benchmark.
    assert row["haystack_dates"][0] != row["haystack_dates"][1]
    row["answer_session_ids"] = [row["haystack_session_ids"][-1]]
    raw = tmp_path / CLEANED_FILENAME
    raw.write_text(json.dumps([row]), encoding="utf-8")

    result = audit_cleaned_dataset(raw, tmp_path / "out", revision="fixture-revision")

    assert result["counts"]["normalized_total"] == 1
    assert result["counts"]["excluded_total"] == 0
    episode = result["normalized_episodes"][0]
    assert len(episode["ordered_evidence_ids"]) == len(
        set(episode["ordered_evidence_ids"])
    )
    repeated_rows = [
        item
        for item in episode["evidence"]
        if item["source_session_id"] == repeated_source_id
    ]
    assert len(repeated_rows) == 2
    assert repeated_rows[0]["evidence_id"] != repeated_rows[1]["evidence_id"]
    assert result["conversion_log"][0]["duplicate_source_session_ids_disambiguated"] == 1
    assert result["session_count_distribution"]["measurement_kind"] == "exact_source_count"
    assert result["episode_token_distribution"]["measurement_kind"] == "surrogate_estimate"
    assert result["episode_token_distribution"]["provider_exact"] is False
    assert result["token_accounting"] == {
        "tokenizer_id": "surrogate:labforge-compatible",
        "tokenizer_revision": "surrogate-regex-v1-2026-08-01",
        "serialization_version": "longmemeval-trajectory-json-v1",
        "estimator": "surrogate_regex_bytes_v1",
        "safety_margin": 0.1,
        "measurement_kind": "surrogate_estimate",
        "provider_exact": False,
    }
    manifest = json.loads((tmp_path / "out" / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["token_accounting"] == result["token_accounting"]


def test_grouped_split_candidates_use_connected_leakage_components(tmp_path: Path) -> None:
    family_left = _episode("family-a", "knowledge-update", 8, family_id="shared-family")
    family_right = _episode("family-b", "temporal-reasoning", 8, family_id="shared-family")
    answer_left = _episode("answer-a", "knowledge-update", 8)
    answer_right = _episode("answer-b", "temporal-reasoning", 8)
    answer_right["haystack_session_ids"][-1] = answer_left["answer_session_ids"][0]
    answer_right["answer_session_ids"] = list(answer_left["answer_session_ids"])
    duplicate_left = _episode("duplicate-a", "knowledge-update", 8, question=" Exact  duplicate ")
    duplicate_right = _episode("duplicate-b", "temporal-reasoning", 8, question="Exact duplicate")
    evidence_left = _episode("evidence-a", "knowledge-update", 8)
    evidence_right = _episode("evidence-b", "temporal-reasoning", 8)
    evidence_right["haystack_sessions"][-1] = evidence_left["haystack_sessions"][-1]
    raw = tmp_path / CLEANED_FILENAME
    raw.write_text(
        json.dumps(
            [
                family_left,
                family_right,
                answer_left,
                answer_right,
                duplicate_left,
                duplicate_right,
                evidence_left,
                evidence_right,
            ]
        ),
        encoding="utf-8",
    )

    result = audit_cleaned_dataset(raw, tmp_path / "out", revision="fixture-revision")

    assert len(result["leakage_groups"]) == 4
    assert [candidate["ratio"] for candidate in result["split_candidates"]] == [
        {"development": 0.2, "calibration": 0.3, "acceptance": 0.5},
        {"development": 0.15, "calibration": 0.25, "acceptance": 0.6},
        {"development": 0.1, "calibration": 0.2, "acceptance": 0.7},
    ]
    for candidate in result["split_candidates"]:
        primary = candidate["primary_counts"]
        for metric in ("N_master", "N4", "N8", "N16"):
            assert sum(primary[split][metric] for split in primary) == result["counts"][f"primary_{metric}"]
        acceptance_e8 = candidate["acceptance_primary_e8_evidence_layout_strata"]
        assert sum(row["count"] for row in acceptance_e8) == primary["acceptance"]["N8"]
        split_by_episode = {
            episode_id: assignment["split"]
            for assignment in candidate["assignments"]
            for episode_id in assignment["episode_ids"]
        }
        for pair in (
            ("family-a", "family-b"),
            ("answer-a", "answer-b"),
            ("duplicate-a", "duplicate-b"),
            ("evidence-a", "evidence-b"),
        ):
            assert split_by_episode[pair[0]] == split_by_episode[pair[1]]
    assert result["grouped_split_counts"] == result["split_candidates"][0]["primary_counts"]
    manifest = json.loads((tmp_path / "out" / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["split_candidates"] == result["split_candidates"]


def test_cleaned_s_download_uses_only_official_direct_then_17897(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[tuple[str, str]] = []

    def fail_download(url: str, destination: Path, *, route: str, timeout: float) -> dict:
        observed.append((url, route))
        return {"route": route, "url": url, "success": False, "error": "fixture failure"}

    monkeypatch.setattr(adapter, "_download_one", fail_download)
    attempts = fetch_cleaned_official_file(tmp_path, timeout=0.01)

    assert [attempt["source_route"] for attempt in attempts] == [
        "official_direct",
        "official_proxy_17897",
    ]
    assert [route for _, route in observed] == ["direct", "proxy_17897"]
    assert all("huggingface.co/datasets/xiaowu0162/longmemeval-cleaned" in url for url, _ in observed)
    assert all(CLEANED_REVISION in url for url, _ in observed)
    assert not any("hf-mirror" in url for url, _ in observed)


def test_cli_defaults_to_cleaned_s_and_pinned_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "raw"
    output_dir = tmp_path / "artifacts"
    observed: dict[str, object] = {}

    def fake_fetch(root: Path, *, revision: str, timeout: float) -> list[dict]:
        observed.update(root=root, revision=revision, timeout=timeout)
        root.mkdir(parents=True)
        (root / CLEANED_FILENAME).write_text(
            json.dumps([_episode("ku", "knowledge-update", 4)]), encoding="utf-8"
        )
        return [{"source_route": "official_direct", "success": True}]

    monkeypatch.setattr(adapter, "fetch_cleaned_official_file", fake_fetch)
    exit_code = main(
        [
            "--source-root",
            str(source_root),
            "--output-dir",
            str(output_dir),
            "--download-timeout",
            "0.25",
        ]
    )

    assert exit_code == 0
    assert observed == {"root": source_root, "revision": CLEANED_REVISION, "timeout": 0.25}
    audit = json.loads((output_dir / "longmemeval_data_audit.json").read_text(encoding="utf-8"))
    assert audit["source_kind"] == "official-longmemeval-s-cleaned"
    assert audit["source_revision"] == CLEANED_REVISION


def test_cli_keeps_v2_small_as_an_explicit_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "v2"
    output_dir = tmp_path / "out"
    observed: dict[str, object] = {}

    def fake_fetch(
        root: Path, *, revision: str, timeout: float, include_trajectories: bool
    ) -> list[dict]:
        observed.update(
            fetched="v2-small",
            root=root,
            revision=revision,
            include_trajectories=include_trajectories,
        )
        return []

    def fake_audit(root: Path, out: Path, *, revision: str, retrieval_attempts: list[dict]) -> dict:
        observed.update(audited="v2-small", audit_root=root, output_dir=out)
        return {"status": "qualified", "counts": {"N_master": 1}}

    monkeypatch.setattr(adapter, "fetch_official_files", fake_fetch)
    monkeypatch.setattr(adapter, "audit_dataset", fake_audit)
    assert (
        main(
            [
                "--dataset",
                "v2-small",
                "--source-root",
                str(source_root),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    assert observed["fetched"] == "v2-small"
    assert observed["audited"] == "v2-small"


def test_cli_download_failure_writes_stall_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "missing"
    output_dir = tmp_path / "out"
    attempts = [
        {
            "file": CLEANED_FILENAME,
            "source_route": "official_direct",
            "route": "direct",
            "success": False,
            "error_type": "TimeoutError",
            "error": "direct timeout",
        },
        {
            "file": CLEANED_FILENAME,
            "source_route": "official_proxy_17897",
            "route": "proxy_17897",
            "success": False,
            "error_type": "URLError",
            "error": "proxy unavailable",
        },
    ]
    monkeypatch.setattr(adapter, "fetch_cleaned_official_file", lambda *args, **kwargs: attempts)

    assert main(["--source-root", str(source_root), "--output-dir", str(output_dir)]) == 2
    reports = list((output_dir / "stall_reports").glob("stall_report_*.md"))
    assert len(reports) == 1
    report = reports[0].read_text(encoding="utf-8")
    assert "LongMemEval-S download and audit" in report
    assert "official_direct" in report
    assert "official_proxy_17897" in report
    blocked = json.loads((output_dir / "longmemeval_data_audit.json").read_text(encoding="utf-8"))
    assert blocked["status"] == "blocked"
    assert blocked["stall_report"] == str(reports[0])


def test_cli_rejects_unpinned_cleaned_s_revision(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--dataset",
                "cleaned-s",
                "--revision",
                "moving-main",
                "--source-root",
                str(tmp_path),
                "--no-download",
            ]
        )
