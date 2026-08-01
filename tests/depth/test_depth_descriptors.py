from __future__ import annotations

from plan_robust_memory.depth import depth_descriptor, joint_rewrite_distance
from plan_robust_memory.plans import generate_plan


def test_depth_descriptors_are_computed_from_plan() -> None:
    descriptor = depth_descriptor(generate_plan("left_deep", 4), {0, 3})
    assert descriptor.d_max >= descriptor.d_mean
    assert descriptor.n_supporting_leaves == 2


def test_joint_depth_is_lca_to_root_distance_for_left_deep_plan() -> None:
    plan = generate_plan("left_deep", 4)
    assert joint_rewrite_distance(plan, {0, 1}) == 2
    assert joint_rewrite_distance(plan, {2, 3}) == 0
    assert depth_descriptor(plan, {0, 1}).d_joint == 2


def test_joint_depth_is_lca_to_root_distance_for_balanced_plan() -> None:
    plan = generate_plan("canonical_balanced", 4)
    assert joint_rewrite_distance(plan, {0, 1}) == 1
    assert joint_rewrite_distance(plan, {2, 3}) == 1
    assert joint_rewrite_distance(plan, {0, 3}) == 0
