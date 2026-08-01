# Protocol Qualification Report v1

Date: 2026-08-01

## Scope

This report qualifies the offline Phase 1 protocol harness built from workplan.md and Proposal.md. It covers executable contracts, synthetic fixtures, schema validation, metric/statistical functions, and regression tests for the first TDD layer.

It does not claim that external data, model probes, judge repeatability, or acceptance experiments have passed. Those Gates require real artifacts and remain pending.

## Completed Offline Gates

- M0 pytest skeleton and Make targets are present.
- Schema contracts cover episode, evidence, query, leaf/view node, plan, run, score, cost, backbone bundle, and retrieval config.
- Testing principles are frozen in protocol/testing_principles_v1.md.
- Test-set contract is frozen in protocol/test_set_contract_v1.md with fixture-only status.
- Metrics are frozen in protocol/metric_spec_v1.md.
- Statistical protocol is frozen in protocol/statistical_protocol_v1.md.
- Fixed constants are executable: K_planned={4,8,16}, k_primary=8, R_pilot=3, R_formal=5, delta_SESOI=0.05.
- Primary budget-axis equality is enforced: B_merge = B_final = B_query = B.
- Primary plan statistic excludes right_deep; diagnostic range includes right_deep.
- Same-plan seed null remains diagnostic only.
- Power validation rejects pseudo-replication and fraction_multiple_leaves x n shortcuts.
- Formal NO-GO requires stress prompt, sufficient power, CI/equivalence, judge qualification, non-ceiling signal, and online Gate handling.

## Test Result

Command:

    .venv/bin/python -m pytest -q

Result:

    100 passed

## Pending External Gates

- G-NETWORK real 17897 proxy/API probe.
- G-DATA real LongMemEval, MemoryAgentBench, LoCoMo, and second-source audits.
- G-POWER-FEASIBILITY estimator-matched simulation with real grouped counts.
- G-EVAL project judge endpoint, cache, and 50 x 3 repeatability.
- G-BACKBONE-REPLICATION real different-family probe and budget.
- G-BUDGET SATURATION-01 with Full Context and Budget-Matched Retain.
- Protocol tag eval-protocol-v1.0 is not issued until all Gates pass.

