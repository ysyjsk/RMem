from __future__ import annotations

from plan_robust_memory.execution import validate_endpoint_probe


def test_project_judge_endpoint_probe_artifact_is_complete() -> None:
    validate_endpoint_probe({"requested_model": "gpt-5.5", "returned_model": "gpt-5.5-2026-08-01", "provider": "labforge", "base_url": "https://api.labforge.cc/v1", "success": True})

