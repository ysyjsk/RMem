from __future__ import annotations

from plan_robust_memory.plans import generate_plan


def test_generated_plans_preserve_inorder_spans() -> None:
    plan = generate_plan("canonical_balanced", 8)
    assert all(op.span[0] <= op.span[1] for op in plan.ordered_merge_operations)
    assert plan.ordered_merge_operations[-1].span == (0, 7)

