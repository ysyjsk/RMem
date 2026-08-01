from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .hashing import stable_hash


def rebuild_manifest_hash(manifest: Mapping[str, Any]) -> str:
    return stable_hash(manifest)


def rebuild_power_artifact_hash(artifact: Mapping[str, Any]) -> str:
    return stable_hash(artifact)
