.PHONY: test test-first protocol-check materialize-longmemeval-calibration qualify-evaluator-parity qualify-judge-repeatability

PYTHON ?= .venv/bin/python

test:
	$(PYTHON) -m pytest -q

test-first:
	$(PYTHON) -m pytest \
	  tests/unit/test_episode_schema.py \
	  tests/unit/test_seed_contract.py \
	  tests/unit/test_primary_budget_axis.py \
	  tests/unit/test_k_axis_contract.py \
	  tests/unit/test_plan_set_contract.py \
	  tests/unit/test_observability_contract.py \
	  tests/unit/test_observability_schemas.py \
	  tests/observability/test_contracts.py \
	  tests/regression/test_surrogate_token_semantics.py \
	  tests/regression/test_judge_repeatability_execution_contract.py \
	  tests/integration/test_no_leaves_before_gates.py \
	  tests/qualification/test_original_evaluator_parity.py \
	  tests/qualification/test_evaluator_parity_gate.py \
	  tests/qualification/test_judge_repeatability.py \
	  tests/qualification/test_judge_repeatability_gate.py \
	  tests/qualification/test_judge_repeatability_cli.py \
	  tests/statistics/test_power_uses_independent_episode_count.py \
	  tests/statistics/test_null_matches_r_run_mean.py \
	  -q

protocol-check: test

materialize-longmemeval-calibration:
	$(PYTHON) -m plan_robust_memory.materialize_longmemeval_calibration

qualify-evaluator-parity:
	$(PYTHON) -m plan_robust_memory.qualify_evaluator_parity

qualify-judge-repeatability:
	$(PYTHON) -m plan_robust_memory.qualify_judge_repeatability
