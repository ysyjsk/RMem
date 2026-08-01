from __future__ import annotations

from plan_robust_memory.depth import depth_descriptor
from plan_robust_memory.plans import generate_plan


def test_cross_leaf_descriptor_flags_multiple_supporting_leaves() -> None:
    descriptor = depth_descriptor(generate_plan("canonical_balanced", 4), {1, 2})
    assert descriptor.evidence_spans_multiple_leaves

