from __future__ import annotations

from plan_robust_memory.depth import depth_descriptor
from plan_robust_memory.plans import generate_plan


def test_single_leaf_support_is_not_assumed_zero_topology_effect() -> None:
    descriptor = depth_descriptor(generate_plan("canonical_balanced", 4), {1})
    assert not descriptor.evidence_spans_multiple_leaves
    assert not descriptor.topology_insensitive

