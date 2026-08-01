from __future__ import annotations

from plan_robust_memory.depth import depth_identifiability_gate


def test_depth_identifiability_can_downgrade_to_descriptive() -> None:
    descriptors = [{"plan_id": "left_deep", "d_mean": 2.0, "depth_plan_collinear": True}]
    assert depth_identifiability_gate(descriptors) == "descriptive_only"


def test_depth_identifiability_passes_with_variation() -> None:
    descriptors = [
        {"plan_id": "left_deep", "d_mean": 2.0, "depth_plan_collinear": False},
        {"plan_id": "right_deep", "d_mean": 3.0, "depth_plan_collinear": False},
    ]
    assert depth_identifiability_gate(descriptors) == "identifiable"

