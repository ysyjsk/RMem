from __future__ import annotations

from plan_robust_memory.reproducibility import rebuild_manifest_hash


def test_manifest_rebuild_hash_is_stable() -> None:
    manifest = {"steps": ["normalize", "split"], "version": 1}
    assert rebuild_manifest_hash(manifest) == rebuild_manifest_hash({"version": 1, "steps": ["normalize", "split"]})

