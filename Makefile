.PHONY: test test-first protocol-check

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
	  tests/statistics/test_power_uses_independent_episode_count.py \
	  tests/statistics/test_null_matches_r_run_mean.py \
	  -q

protocol-check: test

