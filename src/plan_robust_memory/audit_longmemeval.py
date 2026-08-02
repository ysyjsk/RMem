from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping

from .hashing import stable_hash
from .partition import token_balanced_partition
from .token_accounting import TokenizerSpec, count_tokens


DEFAULT_REVISION = "f152293e235517d504809563c833d7190b8c713b"
DEFAULT_REPOSITORY = "xiaowu0162/longmemeval-v2"
CLEANED_REVISION = "98d7416c24c778c2fee6e6f3006e7a073259d48f"
CLEANED_REPOSITORY = "xiaowu0162/longmemeval-cleaned"
CLEANED_FILENAME = "longmemeval_s_cleaned.json"
PRIMARY_CATEGORIES = ("knowledge-update", "temporal-reasoning")
SPLIT_CANDIDATES = (
    ("20_30_50", {"development": 0.20, "calibration": 0.30, "acceptance": 0.50}),
    ("15_25_60", {"development": 0.15, "calibration": 0.25, "acceptance": 0.60}),
    ("10_20_70", {"development": 0.10, "calibration": 0.20, "acceptance": 0.70}),
)
REQUIRED_FILES = ("questions.jsonl", "haystacks/lme_v2_small.json", "trajectories.jsonl")
TOKENIZER_SPEC = TokenizerSpec(
    tokenizer_id="surrogate:labforge-compatible",
    tokenizer_revision="surrogate-regex-v1-2026-08-01",
    serialization_version="longmemeval-trajectory-json-v1",
    safety_margin=0.10,
)


class AuditError(RuntimeError):
    pass


def _token_accounting_record() -> dict[str, Any]:
    return {
        "tokenizer_id": TOKENIZER_SPEC.tokenizer_id,
        "tokenizer_revision": TOKENIZER_SPEC.tokenizer_revision,
        "serialization_version": TOKENIZER_SPEC.serialization_version,
        "estimator": TOKENIZER_SPEC.estimator,
        "safety_margin": TOKENIZER_SPEC.safety_margin,
        "measurement_kind": "surrogate_estimate",
        "provider_exact": False,
    }


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    path.write_text(body, encoding="utf-8")


def _write_checksum_manifest(
    path: Path, entries: Iterable[tuple[Path, str]]
) -> None:
    resolved_entries = sorted(
        ((source.resolve(), digest) for source, digest in entries),
        key=lambda entry: str(entry[0]),
    )
    for source, digest in resolved_entries:
        if "\n" in str(source) or "\r" in str(source):
            raise AuditError(f"checksum path contains a line break: {source}")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise AuditError(f"invalid SHA-256 digest for {source}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{digest}  {source}\n" for source, digest in resolved_entries),
        encoding="utf-8",
    )


def _quantiles(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "p50": None, "p95": None, "max": None, "mean": None}
    ordered = sorted(values)
    def q(fraction: float) -> int:
        index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
        return ordered[index]
    return {"count": len(values), "min": ordered[0], "p50": q(0.5), "p95": q(0.95), "max": ordered[-1], "mean": fmean(values)}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AuditError(f"{path}:{line_number}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise AuditError(f"{path}:{line_number}: row must be an object")
            identifier = row.get("id") or row.get("question_id") or row.get("trajectory_id")
            if not isinstance(identifier, str) or not identifier:
                raise AuditError(f"{path}:{line_number}: missing stable id")
            if identifier in seen:
                raise AuditError(f"{path}:{line_number}: duplicate id {identifier}")
            seen.add(identifier)
            rows.append(row)
    return rows


def _trajectory_text(row: Mapping[str, Any]) -> str:
    if isinstance(row.get("messages"), list):
        return "\n".join(str(message.get("content", "")) for message in row["messages"] if isinstance(message, Mapping))
    if isinstance(row.get("states"), list):
        pieces: list[str] = []
        for state in row["states"]:
            if not isinstance(state, Mapping):
                continue
            for field in ("thought", "accessibility_tree", "action", "url"):
                if state.get(field) is not None:
                    pieces.append(str(state[field]))
        return "\n".join(pieces)
    return str(row.get("content") or row.get("goal") or "")


def _answer_evidence_ids(question: Mapping[str, Any]) -> list[str]:
    for field in ("answer_session_ids", "supporting_evidence_ids", "evidence_ids", "evidence_trajectory_ids"):
        value = question.get(field)
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return list(value)
    return []


def _is_abstention(question_id: str, question_type: str) -> bool:
    return question_id.endswith("_abs") or question_type.endswith("-abs") or question_type.endswith("_abs")


def _normalized_question(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()


def _leakage_groups(
    episodes: list[dict[str, Any]], records: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Build connected components from the pre-registered exact-match leakage rules."""
    parent = list(range(len(episodes)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        if left_root < right_root:
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    indexes_by_key: dict[tuple[str, str], list[int]] = {}
    for index, episode in enumerate(episodes):
        record = records[str(episode["episode_id"])]
        singleton_keys = {
            "base_question_id": [record["base_question_id"]],
            "normalized_question": [record["normalized_question_hash"]],
            "family": record["family_keys"],
            "answer_session": record["answer_session_ids"],
            "supporting_evidence_hash": record["supporting_evidence_hashes"],
        }
        for relation, values in singleton_keys.items():
            for value in values:
                if value:
                    indexes_by_key.setdefault((relation, str(value)), []).append(index)

    relation_by_root_candidate: dict[int, set[str]] = {}
    for (relation, _), indexes in sorted(indexes_by_key.items()):
        unique_indexes = sorted(set(indexes))
        if len(unique_indexes) < 2:
            continue
        anchor = unique_indexes[0]
        for index in unique_indexes[1:]:
            union(anchor, index)

    components: dict[int, list[int]] = {}
    for index in range(len(episodes)):
        components.setdefault(find(index), []).append(index)
    for (relation, _), indexes in indexes_by_key.items():
        unique_indexes = sorted(set(indexes))
        if len(unique_indexes) >= 2:
            relation_by_root_candidate.setdefault(find(unique_indexes[0]), set()).add(relation)

    groups: list[dict[str, Any]] = []
    for indexes in components.values():
        episode_ids = sorted(str(episodes[index]["episode_id"]) for index in indexes)
        group_id = "lmg-" + stable_hash({"episode_ids": episode_ids})[:16]
        root = find(indexes[0])
        groups.append(
            {
                "group_id": group_id,
                "episode_ids": episode_ids,
                "leakage_relations": sorted(relation_by_root_candidate.get(root, set())),
            }
        )
    return sorted(groups, key=lambda row: row["group_id"])


def _assign_grouped_split_candidates(
    episodes: list[dict[str, Any]], groups: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {str(row["episode_id"]): row for row in episodes}
    splits = ("development", "calibration", "acceptance")
    candidates: list[dict[str, Any]] = []
    for candidate_id, ratio in SPLIT_CANDIDATES:
        assigned_primary = {split: Counter() for split in splits}
        assigned_expanded = {split: Counter() for split in splits}
        assignment_rows: list[dict[str, Any]] = []
        category_totals = Counter(
            str(row["question_type"]) for row in episodes if bool(row["primary_eligible"])
        )
        primary_total = sum(category_totals.values())
        expanded_total = len(episodes)

        def ordered_group_key(group: Mapping[str, Any]) -> tuple[int, str]:
            primary_size = sum(bool(by_id[item]["primary_eligible"]) for item in group["episode_ids"])
            return (-primary_size, stable_hash({"candidate_id": candidate_id, "group_id": group["group_id"]}))

        for group in sorted(groups, key=ordered_group_key):
            group_episodes = [by_id[item] for item in group["episode_ids"]]
            group_categories = Counter(
                str(row["question_type"]) for row in group_episodes if bool(row["primary_eligible"])
            )
            group_primary = sum(group_categories.values())
            group_expanded = len(group_episodes)

            def assignment_score(split: str) -> tuple[float, str]:
                dimensions: list[tuple[float, float, float]] = [
                    (float(primary_total), float(assigned_primary[split]["N_master"]), float(group_primary)),
                    (float(expanded_total), float(assigned_expanded[split]["N_master"]), float(group_expanded)),
                ]
                dimensions.extend(
                    (
                        float(category_totals[category]),
                        float(assigned_primary[split][f"category:{category}"]),
                        float(count),
                    )
                    for category, count in group_categories.items()
                )
                score = 0.0
                for total, assigned, increment in dimensions:
                    if total <= 0 or increment <= 0:
                        continue
                    target = ratio[split] * total
                    score += (abs(target - assigned) - abs(target - assigned - increment)) / total
                tie_breaker = stable_hash(
                    {"candidate_id": candidate_id, "group_id": group["group_id"], "split": split}
                )
                return score, tie_breaker

            chosen_split = max(splits, key=assignment_score)
            for row in group_episodes:
                assigned_expanded[chosen_split]["N_master"] += 1
                for threshold in (4, 8, 16):
                    assigned_expanded[chosen_split][f"N{threshold}"] += int(
                        bool(row[f"eligible_for_k{threshold}"])
                    )
                if row["primary_eligible"]:
                    assigned_primary[chosen_split]["N_master"] += 1
                    assigned_primary[chosen_split][f"category:{row['question_type']}"] += 1
                    for threshold in (4, 8, 16):
                        assigned_primary[chosen_split][f"N{threshold}"] += int(
                            bool(row[f"eligible_for_k{threshold}"])
                        )
            assignment_rows.append(
                {
                    "group_id": group["group_id"],
                    "episode_ids": list(group["episode_ids"]),
                    "leakage_relations": list(group["leakage_relations"]),
                    "split": chosen_split,
                }
            )

        primary_counts = {
            split: {metric: int(assigned_primary[split][metric]) for metric in ("N_master", "N4", "N8", "N16")}
            for split in splits
        }
        expanded_counts = {
            split: {metric: int(assigned_expanded[split][metric]) for metric in ("N_master", "N4", "N8", "N16")}
            for split in splits
        }
        split_by_episode = {
            episode_id: assignment["split"]
            for assignment in assignment_rows
            for episode_id in assignment["episode_ids"]
        }
        acceptance_strata: Counter[tuple[str, str, str]] = Counter()
        for row in episodes:
            if (
                row["primary_eligible"]
                and row["eligible_for_k8"]
                and split_by_episode[str(row["episode_id"])] == "acceptance"
            ):
                evidence_layout = row["evidence_layout"]
                acceptance_strata[
                    (
                        str(row["question_type"]),
                        str(evidence_layout["support_leaf_class"]),
                        str(evidence_layout["evidence_position_bin"]),
                    )
                ] += 1
        strata_rows = [
            {
                "question_type": key[0],
                "support_leaf_class": key[1],
                "evidence_position_bin": key[2],
                "count": count,
            }
            for key, count in sorted(acceptance_strata.items())
        ]
        assignment_rows.sort(key=lambda row: row["group_id"])
        candidates.append(
            {
                "candidate_id": candidate_id,
                "ratio": dict(ratio),
                "assignment_algorithm": "deterministic-stratified-connected-components-v1",
                "group_count": len(groups),
                "primary_counts": primary_counts,
                "expanded_counts": expanded_counts,
                "acceptance_primary_e8_evidence_layout_strata": strata_rows,
                "assignments": assignment_rows,
                "assignment_hash": stable_hash(
                    {"candidate_id": candidate_id, "ratio": ratio, "assignments": assignment_rows}
                ),
            }
        )
    return candidates


def _download_one(url: str, destination: Path, *, route: str, timeout: float) -> dict[str, Any]:
    proxy_url = "http://127.0.0.1:17897"
    handler = urllib.request.ProxyHandler({} if route == "direct" else {"http": proxy_url, "https": proxy_url})
    opener = urllib.request.build_opener(handler)
    request = urllib.request.Request(url, headers={"User-Agent": "plan-robust-memory-audit/1.0"})
    started = time.monotonic()
    temporary = destination.with_suffix(destination.suffix + ".partial")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with opener.open(request, timeout=timeout) as response, temporary.open("wb") as handle:
            shutil.copyfileobj(response, handle, length=1024 * 1024)
            status = int(getattr(response, "status", 200))
        os.replace(temporary, destination)
        return {"route": route, "url": url, "success": True, "http_status": status, "elapsed_seconds": round(time.monotonic() - started, 3), "size_bytes": destination.stat().st_size, "sha256": _sha256(destination)}
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        code = exc.code if isinstance(exc, urllib.error.HTTPError) else None
        return {"route": route, "url": url, "success": False, "http_status": code, "elapsed_seconds": round(time.monotonic() - started, 3), "error_type": type(exc).__name__, "error": str(exc)[:500]}


def fetch_official_files(source_root: Path, *, revision: str = DEFAULT_REVISION, timeout: float = 30.0, include_trajectories: bool = True) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    files = REQUIRED_FILES if include_trajectories else REQUIRED_FILES[:2]
    for relative in files:
        destination = source_root / relative
        if destination.exists():
            attempts.append({"file": relative, "route": "local_existing", "success": True, "size_bytes": destination.stat().st_size, "sha256": _sha256(destination)})
            continue
        encoded = relative.replace("/", "/")
        bases = [
            ("official_direct", f"https://huggingface.co/datasets/{DEFAULT_REPOSITORY}/resolve/{revision}/{encoded}", "direct"),
            ("official_proxy_17897", f"https://huggingface.co/datasets/{DEFAULT_REPOSITORY}/resolve/{revision}/{encoded}", "proxy_17897"),
        ]
        downloaded = False
        for label, url, route in bases:
            attempt = _download_one(url, destination, route=route, timeout=timeout)
            attempt.update({"file": relative, "source_route": label})
            attempts.append(attempt)
            if attempt["success"]:
                downloaded = True
                break
        if not downloaded:
            break
    return attempts


def fetch_cleaned_official_file(source_root: Path, *, revision: str = CLEANED_REVISION, timeout: float = 30.0) -> list[dict[str, Any]]:
    if revision != CLEANED_REVISION:
        raise AuditError(f"cleaned-s download revision is frozen at {CLEANED_REVISION}")
    destination = source_root / CLEANED_FILENAME
    if destination.exists():
        return [{"file": CLEANED_FILENAME, "route": "local_existing", "source_route": "local_existing", "success": True, "size_bytes": destination.stat().st_size, "sha256": _sha256(destination)}]
    attempts: list[dict[str, Any]] = []
    bases = [
        ("official_direct", f"https://huggingface.co/datasets/{CLEANED_REPOSITORY}/resolve/{revision}/{CLEANED_FILENAME}", "direct"),
        ("official_proxy_17897", f"https://huggingface.co/datasets/{CLEANED_REPOSITORY}/resolve/{revision}/{CLEANED_FILENAME}", "proxy_17897"),
    ]
    for label, url, route in bases:
        attempt = _download_one(url, destination, route=route, timeout=timeout)
        attempt.update({"file": CLEANED_FILENAME, "source_route": label})
        attempts.append(attempt)
        if attempt["success"]:
            break
    return attempts


def audit_cleaned_dataset(
    raw_path: Path,
    output_dir: Path,
    *,
    revision: str = CLEANED_REVISION,
    retrieval_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw_path = raw_path.resolve()
    output_dir = output_dir.resolve()
    if not raw_path.exists():
        raise AuditError(f"missing official cleaned-S file: {raw_path}")
    rows = json.loads(raw_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise AuditError("cleaned-S root must be a JSON array")

    seen: set[str] = set()
    type_counts: Counter[str] = Counter()
    abs_counts: Counter[str] = Counter()
    normalized: list[dict[str, Any]] = []
    conversion: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    answer_mapping: list[dict[str, Any]] = []
    session_counts: list[int] = []
    episode_tokens: list[int] = []
    layout: Counter[tuple[str, str, str]] = Counter()
    primary_layout: Counter[tuple[str, str, str]] = Counter()
    leakage_records: dict[str, dict[str, Any]] = {}

    for row_index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise AuditError(f"cleaned-S row {row_index} must be an object")
        qid = row.get("question_id")
        if not isinstance(qid, str) or not qid:
            raise AuditError(f"cleaned-S row {row_index} lacks question_id")
        if qid in seen:
            raise AuditError(f"duplicate question_id: {qid}")
        seen.add(qid)
        qtype = str(row.get("question_type", "unknown"))
        type_counts[qtype] += 1
        abstention = _is_abstention(qid, qtype)
        if abstention:
            abs_counts[qtype] += 1

        evidence_ids = row.get("haystack_session_ids")
        dates = row.get("haystack_dates")
        sessions = row.get("haystack_sessions")
        support_ids = row.get("answer_session_ids", [])
        mapping_status = "available" if support_ids else "not_provided_by_source"
        reason: str | None = None
        if not isinstance(evidence_ids, list) or not all(isinstance(item, str) for item in evidence_ids):
            reason = "invalid_haystack_session_ids"
            evidence_ids = []
        if not isinstance(dates, list) or not isinstance(sessions, list) or len(evidence_ids) != len(dates) or len(evidence_ids) != len(sessions):
            reason = "parallel_haystack_fields_mismatch"
            dates = dates if isinstance(dates, list) else []
            sessions = sessions if isinstance(sessions, list) else []
        if not isinstance(support_ids, list) or not all(isinstance(item, str) for item in support_ids):
            reason = "invalid_answer_session_ids"
            support_ids = []
            mapping_status = "invalid_answer_session_ids"
        if any(item not in evidence_ids for item in support_ids):
            reason = "answer_session_not_in_haystack"
            mapping_status = "answer_session_not_in_haystack"
        source_session_counts = Counter(evidence_ids)
        if any(source_session_counts[item] > 1 for item in support_ids):
            reason = "ambiguous_answer_session_id"
            mapping_status = "ambiguous_answer_session_id"
        if len(evidence_ids) == len(dates) == len(sessions):
            atomic_keys = [
                (source_id, str(event_time), stable_hash(session))
                for source_id, event_time, session in zip(
                    evidence_ids, dates, sessions, strict=True
                )
            ]
            if len(atomic_keys) != len(set(atomic_keys)):
                reason = "exact_duplicate_atomic_evidence"
        if abstention:
            reason = "abstention_secondary_only"
        elif len(evidence_ids) < 4:
            reason = "fewer_than_four_atomic_evidence"
        elif not row.get("question") or row.get("answer") is None:
            reason = "unrecoverable_query_or_gold"

        session_counts.append(len(evidence_ids))
        answer_mapping.append(
            {
                "question_id": qid,
                "source_answer_session_ids": support_ids,
                "answer_session_ids": [],
                "mapping_status": mapping_status,
                "normalization_status": "excluded" if reason is not None else "normalized",
                "exclusion_reason": reason,
            }
        )
        if reason is not None:
            excluded.append({"question_id": qid, "question_type": qtype, "reason": reason})
            conversion.append({"question_id": qid, "status": "excluded", "reason": reason})
            continue

        source_evidence_ids = list(evidence_ids)
        evidence_ids = [
            (
                f"{qid}:evidence:{sequence_index:03d}:"
                f"{stable_hash({'source_session_id': source_id, 'event_time': event_time, 'session': session})[:12]}"
            )
            for sequence_index, (source_id, event_time, session) in enumerate(
                zip(source_evidence_ids, dates, sessions, strict=True)
            )
        ]
        evidence_rows: list[dict[str, Any]] = []
        token_total = 0
        for sequence_index, (evidence_id, source_session_id, event_time, session) in enumerate(
            zip(evidence_ids, source_evidence_ids, dates, sessions, strict=True)
        ):
            serialized = json.dumps(session, ensure_ascii=False, sort_keys=True)
            token_count = count_tokens(serialized, TOKENIZER_SPEC)
            token_total += token_count
            evidence_rows.append(
                {
                    "evidence_id": evidence_id,
                    "source_session_id": source_session_id,
                    "sequence_index": sequence_index,
                    "event_time": event_time,
                    "token_count": token_count,
                    "raw_sha256": stable_hash(session),
                }
            )
        episode_tokens.append(token_total)
        support_positions = [source_evidence_ids.index(item) for item in support_ids]
        normalized_support_ids = [evidence_ids[index] for index in support_positions]
        answer_mapping[-1]["answer_session_ids"] = normalized_support_ids
        partition_spans: list[dict[str, int]] = []
        supporting_leaf_indices: list[int] = []
        if len(evidence_ids) >= 8:
            spans = token_balanced_partition(
                [int(item["token_count"]) for item in evidence_rows], 8
            )
            partition_spans = [
                {"leaf_index": leaf_index, "start": span.start, "end": span.end}
                for leaf_index, span in enumerate(spans)
            ]
            supporting_leaf_indices = sorted(
                {
                    leaf_index
                    for position_index in support_positions
                    for leaf_index, span in enumerate(spans)
                    if span.start <= position_index <= span.end
                }
            )
            support_class = (
                "multiple"
                if len(supporting_leaf_indices) > 1
                else "single"
                if supporting_leaf_indices
                else "unknown"
            )
        else:
            support_class = "not_applicable"
        position = "unknown"
        if support_positions:
            center = fmean(support_positions) / max(1, len(evidence_ids) - 1)
            position = "early" if center < 1 / 3 else "middle" if center < 2 / 3 else "late"
        if len(evidence_ids) >= 8:
            layout[(qtype, support_class, position)] += 1
        primary_eligible = qtype in PRIMARY_CATEGORIES
        if primary_eligible and len(evidence_ids) >= 8:
            primary_layout[(qtype, support_class, position)] += 1
        family_keys = [
            f"{field}:{row[field]}"
            for field in ("family_id", "template_id", "source_family")
            if row.get(field) is not None and str(row[field])
        ]
        supporting_evidence_hashes = [
            evidence_rows[index]["raw_sha256"] for index in support_positions
        ]
        leakage_records[qid] = {
            "base_question_id": str(row.get("base_question_id") or qid.removesuffix("_abs")),
            "family_keys": family_keys,
            "answer_session_ids": list(support_ids),
            "normalized_question_hash": stable_hash(_normalized_question(row["question"])),
            "supporting_evidence_hashes": supporting_evidence_hashes,
        }
        episode = {
            "dataset_id": "longmemeval-s-cleaned",
            "dataset_version_or_commit": revision,
            "episode_id": qid,
            "construction_unit_id": qid,
            "family_id": str(row.get("family_id") or qid.removesuffix("_abs")),
            "question_type": qtype,
            "primary_eligible": primary_eligible,
            "query": {"query_id": qid, "question_text": row["question"], "gold_answer": row["answer"], "evaluator_id": "longmemeval-compatible"},
            "question_date": row.get("question_date"),
            "ordered_evidence_ids": evidence_ids,
            "atomic_evidence_count": len(evidence_ids),
            "eligible_for_k4": len(evidence_ids) >= 4,
            "eligible_for_k8": len(evidence_ids) >= 8,
            "eligible_for_k16": len(evidence_ids) >= 16,
            "evidence": evidence_rows,
            "answer_session_ids": normalized_support_ids,
            "source_answer_session_ids": support_ids,
            "total_evidence_tokens": token_total,
            "evidence_layout": {
                "k": 8,
                "partition_algorithm": "token_balanced_v1",
                "partition_spans": partition_spans,
                "supporting_leaf_indices": supporting_leaf_indices,
                "n_supporting_leaves": len(supporting_leaf_indices),
                "support_leaf_class": support_class,
                "evidence_position_bin": position,
            },
        }
        normalized.append(episode)
        conversion.append(
            {
                "question_id": qid,
                "status": "normalized",
                "episode_id": qid,
                "duplicate_source_session_ids_disambiguated": sum(
                    count > 1 for count in source_session_counts.values()
                ),
                "artifact_hash": stable_hash(episode),
            }
        )

    counts = {
        "question_total": len(rows),
        "normalized_total": len(normalized),
        "excluded_total": len(excluded),
        "abs_count": sum(abs_counts.values()),
        "N_master": len(normalized),
        "N4": sum(item["eligible_for_k4"] for item in normalized),
        "N8": sum(item["eligible_for_k8"] for item in normalized),
        "N16": sum(item["eligible_for_k16"] for item in normalized),
        "primary_N_master": sum(item["primary_eligible"] for item in normalized),
        "primary_N4": sum(item["primary_eligible"] and item["eligible_for_k4"] for item in normalized),
        "primary_N8": sum(item["primary_eligible"] and item["eligible_for_k8"] for item in normalized),
        "primary_N16": sum(item["primary_eligible"] and item["eligible_for_k16"] for item in normalized),
    }
    leakage_groups = _leakage_groups(normalized, leakage_records)
    split_candidates = _assign_grouped_split_candidates(normalized, leakage_groups)
    split_counts = split_candidates[0]["primary_counts"]
    expanded_split = split_candidates[0]["expanded_counts"]
    strata = [{"question_type": key[0], "support_leaf_class": key[1], "evidence_position_bin": key[2], "count": value} for key, value in sorted(primary_layout.items())]
    expanded_strata = [{"question_type": key[0], "support_leaf_class": key[1], "evidence_position_bin": key[2], "count": value} for key, value in sorted(layout.items())]
    raw_checksums = {CLEANED_FILENAME: {"present": True, "size_bytes": raw_path.stat().st_size, "sha256": _sha256(raw_path)}}
    token_accounting = _token_accounting_record()
    session_distribution = {**_quantiles(session_counts), "measurement_kind": "exact_source_count"}
    token_distribution = {
        **_quantiles(episode_tokens),
        "measurement_kind": "surrogate_estimate",
        "provider_exact": False,
    }
    status = "qualified" if not excluded else "qualified_with_exclusions"
    if counts["primary_N_master"] == 0:
        status = "blocked"
    result = {
        "schema_version": "plan-robust-memory.longmemeval-audit.v1",
        "created_at": _now(),
        "status": status,
        "source_kind": "official-longmemeval-s-cleaned",
        "source_root": str(raw_path.parent),
        "source_revision": revision,
        "retrieval_attempts": retrieval_attempts or [],
        "raw_checksums": raw_checksums,
        "question_type_counts": dict(sorted(type_counts.items())),
        "abs_counts": dict(sorted(abs_counts.items())),
        "counts": counts,
        "grouped_split_counts": split_counts,
        "expanded_grouped_split_counts": expanded_split,
        "split_candidates": split_candidates,
        "leakage_groups": leakage_groups,
        "eligible_primary_categories": sorted({item["question_type"] for item in normalized if item["primary_eligible"]}),
        "session_count_distribution": session_distribution,
        "episode_token_distribution": token_distribution,
        "token_accounting": token_accounting,
        "evidence_layout_strata": strata,
        "expanded_evidence_layout_strata": expanded_strata,
        "normalized_episodes": normalized,
        "answer_session_mapping": answer_mapping,
        "conversion_log": conversion,
        "excluded_items": excluded,
        "no_silent_drop": len(conversion) == len(rows),
        "full_leaf_generation_allowed": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {key: value for key, value in result.items() if key not in {"normalized_episodes", "answer_session_mapping", "conversion_log", "excluded_items"}}
    _write_json(output_dir / "longmemeval_data_audit.json", summary)
    _write_json(output_dir / "raw_checksums.json", raw_checksums)
    _write_checksum_manifest(
        output_dir / "checksums.sha256",
        [(raw_path, raw_checksums[CLEANED_FILENAME]["sha256"])],
    )
    _write_json(output_dir / "normalized_episodes.json", normalized)
    _write_jsonl(output_dir / "answer_session_mapping.jsonl", answer_mapping)
    _write_jsonl(output_dir / "conversion_log.jsonl", conversion)
    _write_jsonl(output_dir / "excluded_items.jsonl", excluded)
    manifest = {"source_kind": result["source_kind"], "source_revision": revision, "raw_checksums": raw_checksums, "counts": counts, "grouped_split_counts": split_counts, "expanded_grouped_split_counts": expanded_split, "split_candidates": split_candidates, "leakage_groups": leakage_groups, "eligible_primary_categories": result["eligible_primary_categories"], "evidence_layout_strata": strata, "expanded_evidence_layout_strata": expanded_strata, "token_accounting": token_accounting, "status": status, "no_silent_drop": result["no_silent_drop"]}
    manifest["audit_hash"] = stable_hash(manifest)
    _write_json(output_dir / "dataset_manifest.json", manifest)
    return result


def audit_dataset(source_root: Path, output_dir: Path, *, revision: str = DEFAULT_REVISION, retrieval_attempts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    source_root = source_root.resolve()
    output_dir = output_dir.resolve()
    questions_path = source_root / "questions.jsonl"
    haystacks_path = source_root / "haystacks/lme_v2_small.json"
    trajectories_path = source_root / "trajectories.jsonl"
    if not questions_path.exists() or not haystacks_path.exists():
        raise AuditError("questions.jsonl and haystacks/lme_v2_small.json are required")

    questions = _read_jsonl(questions_path)
    mapping = json.loads(haystacks_path.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict):
        raise AuditError("haystack mapping must be an object")
    if set(mapping) != {str(row.get("id")) for row in questions}:
        raise AuditError("question/haystack coverage mismatch")
    trajectories = _read_jsonl(trajectories_path) if trajectories_path.exists() else []
    trajectory_by_id = {str(row["id"]): row for row in trajectories}

    type_counts: Counter[str] = Counter()
    abs_counts: Counter[str] = Counter()
    normalized: list[dict[str, Any]] = []
    conversion: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    answer_mapping: list[dict[str, Any]] = []
    session_counts_all: list[int] = []
    episode_token_counts: list[int] = []
    evidence_layout: Counter[tuple[str, str, str]] = Counter()
    primary_evidence_layout: Counter[tuple[str, str, str]] = Counter()
    evidence_metadata_cache: dict[str, dict[str, Any]] = {}

    for question in questions:
        qid = str(question["id"])
        qtype = str(question.get("question_type", "unknown"))
        type_counts[qtype] += 1
        if _is_abstention(qid, qtype):
            abs_counts[qtype] += 1
        evidence_ids_raw = mapping[qid]
        if not isinstance(evidence_ids_raw, list) or not all(isinstance(item, str) for item in evidence_ids_raw):
            raise AuditError(f"invalid haystack for {qid}")
        evidence_ids = list(evidence_ids_raw)
        session_counts_all.append(len(evidence_ids))

        reason: str | None = None
        missing = [item for item in evidence_ids if item not in trajectory_by_id]
        if _is_abstention(qid, qtype):
            reason = "abstention_secondary_only"
        elif missing:
            reason = "missing_trajectory:" + ",".join(missing[:5])
        elif len(evidence_ids) < 4:
            reason = "fewer_than_four_atomic_evidence"
        elif not question.get("question") or question.get("answer") is None or not question.get("eval_function"):
            reason = "unrecoverable_query_gold_or_evaluator"

        support_ids = _answer_evidence_ids(question)
        if support_ids and any(item not in evidence_ids for item in support_ids):
            reason = "answer_evidence_not_in_episode"
        if reason is not None:
            excluded.append({"question_id": qid, "question_type": qtype, "reason": reason, "missing_evidence_count": len(missing)})
            conversion.append({"question_id": qid, "status": "excluded", "reason": reason})
            continue

        evidence_rows = []
        total_tokens = 0
        for sequence_index, evidence_id in enumerate(evidence_ids):
            trajectory = trajectory_by_id[evidence_id]
            if evidence_id not in evidence_metadata_cache:
                raw_text = _trajectory_text(trajectory)
                evidence_metadata_cache[evidence_id] = {
                    "event_time": trajectory.get("current_time") or trajectory.get("event_time"),
                    "token_count": count_tokens(raw_text, TOKENIZER_SPEC),
                    "raw_sha256": stable_hash(trajectory),
                }
            metadata = evidence_metadata_cache[evidence_id]
            tokens = int(metadata["token_count"])
            total_tokens += tokens
            evidence_rows.append({
                "evidence_id": evidence_id,
                "sequence_index": sequence_index,
                "event_time": metadata["event_time"],
                "token_count": tokens,
                "raw_sha256": metadata["raw_sha256"],
            })
        episode_token_counts.append(total_tokens)
        support_positions = [evidence_ids.index(item) for item in support_ids if item in evidence_ids]
        support_class = "multiple" if len(set(support_positions)) > 1 else "single_or_unknown"
        position = "unknown"
        if support_positions:
            center = fmean(support_positions) / max(1, len(evidence_ids) - 1)
            position = "early" if center < 1 / 3 else "middle" if center < 2 / 3 else "late"
        evidence_layout[(qtype, support_class, position)] += 1
        primary_eligible = qtype in PRIMARY_CATEGORIES
        if primary_eligible:
            primary_evidence_layout[(qtype, support_class, position)] += 1
        family_id = str(question.get("family_id") or f"{question.get('domain','unknown')}:{question.get('environment','unknown')}:{qid}")
        episode = {
            "dataset_id": "longmemeval-v2-small",
            "dataset_version_or_commit": revision,
            "episode_id": qid,
            "construction_unit_id": qid,
            "family_id": family_id,
            "question_type": qtype,
            "primary_eligible": primary_eligible,
            "query": {"query_id": qid, "question_text": question["question"], "gold_answer": question["answer"], "evaluator_id": question["eval_function"]},
            "ordered_evidence_ids": evidence_ids,
            "atomic_evidence_count": len(evidence_ids),
            "eligible_for_k4": len(evidence_ids) >= 4,
            "eligible_for_k8": len(evidence_ids) >= 8,
            "eligible_for_k16": len(evidence_ids) >= 16,
            "evidence": evidence_rows,
            "answer_session_ids": support_ids,
            "total_evidence_tokens": total_tokens,
        }
        normalized.append(episode)
        answer_mapping.append({"question_id": qid, "answer_session_ids": support_ids, "mapping_status": "available" if support_ids else "not_provided_by_source"})
        conversion.append({"question_id": qid, "status": "normalized", "episode_id": qid, "artifact_hash": stable_hash(episode)})

    counts = {
        "question_total": len(questions),
        "normalized_total": len(normalized),
        "excluded_total": len(excluded),
        "abs_count": sum(abs_counts.values()),
        "N_master": len(normalized),
        "N4": sum(row["eligible_for_k4"] for row in normalized),
        "N8": sum(row["eligible_for_k8"] for row in normalized),
        "N16": sum(row["eligible_for_k16"] for row in normalized),
        "primary_N_master": sum(row["primary_eligible"] for row in normalized),
        "primary_N4": sum(row["primary_eligible"] and row["eligible_for_k4"] for row in normalized),
        "primary_N8": sum(row["primary_eligible"] and row["eligible_for_k8"] for row in normalized),
        "primary_N16": sum(row["primary_eligible"] and row["eligible_for_k16"] for row in normalized),
    }
    n = counts["primary_N_master"]
    dev = round(n * 0.2)
    cal = round(n * 0.3)
    split_counts = {"development": dev, "calibration": cal, "acceptance": n - dev - cal}
    expanded_n = counts["N_master"]
    expanded_dev = round(expanded_n * 0.2)
    expanded_cal = round(expanded_n * 0.3)
    expanded_split_counts = {"development": expanded_dev, "calibration": expanded_cal, "acceptance": expanded_n - expanded_dev - expanded_cal}
    checksums = {}
    for relative in REQUIRED_FILES:
        path = source_root / relative
        checksums[relative] = {"present": path.exists(), "size_bytes": path.stat().st_size if path.exists() else None, "sha256": _sha256(path) if path.exists() else None}
    strata = [{"question_type": key[0], "support_leaf_class": key[1], "evidence_position_bin": key[2], "count": value} for key, value in sorted(primary_evidence_layout.items())]
    expanded_strata = [{"question_type": key[0], "support_leaf_class": key[1], "evidence_position_bin": key[2], "count": value} for key, value in sorted(evidence_layout.items())]
    status = "qualified" if not excluded else "qualified_with_exclusions"
    if not trajectories_path.exists() or counts["primary_N_master"] == 0:
        status = "blocked"
    result = {
        "schema_version": "plan-robust-memory.longmemeval-audit.v1",
        "created_at": _now(),
        "status": status,
        "source_root": str(source_root),
        "source_revision": revision,
        "retrieval_attempts": retrieval_attempts or [],
        "raw_checksums": checksums,
        "question_type_counts": dict(sorted(type_counts.items())),
        "abs_counts": dict(sorted(abs_counts.items())),
        "counts": counts,
        "grouped_split_counts": split_counts,
        "expanded_grouped_split_counts": expanded_split_counts,
        "eligible_primary_categories": sorted({row["question_type"] for row in normalized if row["primary_eligible"]}),
        "session_count_distribution": _quantiles(session_counts_all),
        "episode_token_distribution": _quantiles(episode_token_counts),
        "evidence_layout_strata": strata,
        "expanded_evidence_layout_strata": expanded_strata,
        "normalized_episodes": normalized,
        "answer_session_mapping": answer_mapping,
        "conversion_log": conversion,
        "excluded_items": excluded,
        "no_silent_drop": len(conversion) == len(questions),
        "full_leaf_generation_allowed": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "longmemeval_data_audit.json", {key: value for key, value in result.items() if key not in {"normalized_episodes", "answer_session_mapping", "conversion_log", "excluded_items"}})
    _write_json(output_dir / "raw_checksums.json", checksums)
    _write_checksum_manifest(
        output_dir / "checksums.sha256",
        [
            (source_root / relative, str(checksums[relative]["sha256"]))
            for relative in REQUIRED_FILES
            if checksums[relative]["present"]
        ],
    )
    _write_json(output_dir / "normalized_episodes.json", normalized)
    _write_jsonl(output_dir / "answer_session_mapping.jsonl", answer_mapping)
    _write_jsonl(output_dir / "conversion_log.jsonl", conversion)
    _write_jsonl(output_dir / "excluded_items.jsonl", excluded)
    _write_json(output_dir / "dataset_manifest.json", {"source_revision": revision, "raw_checksums": checksums, "counts": counts, "grouped_split_counts": split_counts, "expanded_grouped_split_counts": expanded_split_counts, "eligible_primary_categories": result["eligible_primary_categories"], "evidence_layout_strata": strata, "expanded_evidence_layout_strata": expanded_strata, "status": status, "no_silent_drop": result["no_silent_drop"], "audit_hash": stable_hash({"checksums": checksums, "counts": counts, "strata": strata, "expanded_strata": expanded_strata})})
    return result


def _retrieval_stalled(attempts: Iterable[Mapping[str, Any]]) -> bool:
    failures_by_file: dict[str, set[str]] = {}
    for attempt in attempts:
        if attempt.get("success"):
            continue
        file_name = str(attempt.get("file", "unknown"))
        failures_by_file.setdefault(file_name, set()).add(str(attempt.get("route", "unknown")))
    return any({"direct", "proxy_17897"}.issubset(routes) for routes in failures_by_file.values())


def _write_stall_report(
    output_dir: Path,
    *,
    dataset: str,
    revision: str,
    attempts: list[dict[str, Any]],
    error: str,
) -> Path:
    stall_dir = output_dir / "stall_reports"
    stall_dir.mkdir(parents=True, exist_ok=True)
    path = stall_dir / f"stall_report_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.md"
    title = "LongMemEval-S download and audit" if dataset == "cleaned-s" else "LongMemEval-V2-Small download and audit"
    lines = [
        f"# Stall Report: {title}",
        "",
        f"- Current stage: {title}",
        f"- Dataset selector: `{dataset}`",
        f"- Frozen source revision: `{revision}`",
        f"- Error: `{error}`",
        f"- Attempt count: {len(attempts)}",
        "- Most likely cause: both official access routes failed or the required official file remains unavailable",
        "- Recommended decision: restore official Hugging Face access or provide the checksum-verified pinned file, then rerun this Gate",
        "- Next milestone: blocked; full leaf generation remains forbidden",
        "",
        "## Attempts",
        "",
    ]
    for index, attempt in enumerate(attempts, 1):
        lines.extend(
            [
                f"### Attempt {index}",
                "",
                f"- file: `{attempt.get('file')}`",
                f"- source route: `{attempt.get('source_route')}`",
                f"- route: `{attempt.get('route')}`",
                f"- success: `{attempt.get('success')}`",
                f"- HTTP status: `{attempt.get('http_status')}`",
                f"- error type: `{attempt.get('error_type')}`",
                f"- result: `{attempt.get('error', 'no additional error text')}`",
                "",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download and audit real official LongMemEval data")
    parser.add_argument("--dataset", choices=("cleaned-s", "v2-small"), default="cleaned-s")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/longmemeval"))
    parser.add_argument("--revision", help="Optional revision override; cleaned-s only accepts its frozen official revision")
    parser.add_argument("--download-timeout", type=float, default=30.0)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--skip-trajectories-download", action="store_true")
    args = parser.parse_args(argv)
    if args.dataset == "cleaned-s":
        revision = args.revision or CLEANED_REVISION
        if revision != CLEANED_REVISION:
            parser.error(f"cleaned-s revision is frozen at {CLEANED_REVISION}")
        source_root = args.source_root or Path("data/raw/longmemeval-cleaned")
    else:
        revision = args.revision or DEFAULT_REVISION
        source_root = args.source_root or Path("data/raw/longmemeval-v2-official")
    attempts: list[dict[str, Any]] = []
    if not args.no_download:
        if args.dataset == "cleaned-s":
            attempts = fetch_cleaned_official_file(
                source_root, revision=revision, timeout=args.download_timeout
            )
        else:
            attempts = fetch_official_files(
                source_root,
                revision=revision,
                timeout=args.download_timeout,
                include_trajectories=not args.skip_trajectories_download,
            )
    elif (args.output_dir / "longmemeval_data_audit.json").exists():
        previous = json.loads((args.output_dir / "longmemeval_data_audit.json").read_text(encoding="utf-8"))
        attempts = list(previous.get("retrieval_attempts", []))
    try:
        if args.dataset == "cleaned-s":
            result = audit_cleaned_dataset(
                source_root / CLEANED_FILENAME,
                args.output_dir,
                revision=revision,
                retrieval_attempts=attempts,
            )
        else:
            result = audit_dataset(
                source_root,
                args.output_dir,
                revision=revision,
                retrieval_attempts=attempts,
            )
    except AuditError as exc:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        stall_path = None
        if _retrieval_stalled(attempts):
            stall_path = _write_stall_report(
                args.output_dir,
                dataset=args.dataset,
                revision=revision,
                attempts=attempts,
                error=str(exc),
            )
        blocked = {"schema_version": "plan-robust-memory.longmemeval-audit.v1", "created_at": _now(), "status": "blocked", "dataset": args.dataset, "source_revision": revision, "error": str(exc), "retrieval_attempts": attempts, "stall_report": str(stall_path) if stall_path else None, "full_leaf_generation_allowed": False}
        _write_json(args.output_dir / "longmemeval_data_audit.json", blocked)
        print(json.dumps(blocked, ensure_ascii=False, sort_keys=True, indent=2))
        return 2
    print(json.dumps({"status": result["status"], "counts": result["counts"], "output_dir": str(args.output_dir)}, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
