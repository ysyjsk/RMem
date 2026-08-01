from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import ContractError


def assert_no_cross_split_overlap(rows: Iterable[Mapping[str, Any]], field: str) -> None:
    seen: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        values = row.get(field)
        if values is None:
            continue
        if not isinstance(values, list):
            values = [values]
        for value in values:
            seen[str(value)].add(str(row["split"]))
    leaking = {value: splits for value, splits in seen.items() if len(splits) > 1}
    if leaking:
        raise ContractError(f"{field} overlaps across splits")

