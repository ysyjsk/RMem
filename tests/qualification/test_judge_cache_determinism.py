from __future__ import annotations

from plan_robust_memory.evaluator import judge_cache_key


def test_judge_cache_key_is_deterministic() -> None:
    kwargs = {
        "question_id": "q",
        "reference_answer_hash": "r",
        "candidate_answer_hash": "c",
        "judge_prompt_hash": "p",
        "judge_model": "gpt-5.5-2026-08-01",
        "decoding_config_hash": "d",
        "output_schema_version": "v1",
    }
    assert judge_cache_key(**kwargs) == judge_cache_key(**kwargs)

