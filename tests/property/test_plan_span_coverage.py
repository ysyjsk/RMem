from __future__ import annotations

from plan_robust_memory.plans import generate_plan, validate_plan_descriptor


def test_plan_span_coverage_reaches_root() -> None:
    validate_plan_descriptor(generate_plan("left_deep", 8))
    validate_plan_descriptor(generate_plan("canonical_balanced", 8))

