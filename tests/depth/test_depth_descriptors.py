from __future__ import annotations

from plan_robust_memory.depth import depth_descriptor
from plan_robust_memory.plans import generate_plan


def test_depth_descriptors_are_computed_from_plan() -> None:
    descriptor = depth_descriptor(generate_plan("left_deep", 4), {0, 3})
    assert descriptor.d_max >= descriptor.d_mean
    assert descriptor.n_supporting_leaves == 2

