# Protocol Qualification Report v1

Date: 2026-08-02

## Scope

This report qualifies the offline Phase 1 protocol harness built from workplan.md and Proposal.md. It covers executable contracts, synthetic fixtures, schema validation, metric/statistical functions, regression tests, and the first three real vertical Gate commands.

It does not claim that model probes, judge repeatability, SATURATION-01, leaf construction, or acceptance experiments have passed. Those Gates require additional real artifacts and remain blocked or pending.

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

    200 passed

## Real Vertical Gate Results

- Day 1 command executed and produced all eight required artifacts. The Gate is blocked: direct and `127.0.0.1:17897` model-inventory requests both returned HTTP 401, credentials were absent, no different-family replication model was qualified, and the BGE-M3/CUDA environment was not qualified. The P14 stall report is present. No model probe is represented as passed.
- Official LongMemEval-S cleaned revision `98d7416c24c778c2fee6e6f3006e7a073259d48f` was downloaded from the official Hugging Face URL. The recorded acquisition attempt is checksum-verified; the adapter's policy is official direct, then official `127.0.0.1:17897`, with no mirror fallback.
- Raw size is 277,383,467 bytes and SHA-256 is `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`.
- The adapter automatically writes a standard `checksums.sha256` manifest for both cleaned-S and the explicitly selected V2 adapter; the real cleaned-S manifest passes `sha256sum -c` against the absolute pinned source path.
- The real audit found 500 questions, 30 abstention items, 470 normalized non-abstention episodes, 30 explicit exclusions, and `no_silent_drop=true`. The primary KU/TR counts are `N_master=N4=N8=N16=199`. Twelve non-abstention episodes each contained one repeated source-session ID at a distinct timestamp; all were retained as distinct timestamped atomic items using deterministic evidence IDs. Exact duplicate `(source_id, timestamp, content)` rows remain excluded.
- Leakage connected components were assigned deterministically for all three preregistered split candidates. For 20/30/50, real primary E8 counts are development=40, calibration=60, acceptance=99.
- G-POWER-FEASIBILITY ran 1,000 estimator-matched Monte Carlo draws over real acceptance E8 evidence-layout strata. It froze 20/30/50, `delta_decision=0.10`, conservative power=0.869, Monte Carlo 95% lower bound=0.8466683584396694, and `hard_no_go_available=true` for the power Gate only.
- The current no-download rebuild is bound to audit hash `bab30d495a11f8f1e4558ffadd16a6bf67cde74cb49eb5b03738ae297e792154`; the power artifact is bound to that same input audit hash and has artifact hash `e1047377750b0ece33fb8162b7040f8b7510b9a2623abb15f9a77898e24136bc`.
- Every generated data/power artifact records `full_leaf_generation_allowed=false`. The aggregate leaf guard remains closed because Day 1 is blocked.

## Pending External Gates

- G-NETWORK/API/model/embedding qualification must be rerun after credentials and the explicit BGE-M3 environment are available.
- G-DATA MemoryAgentBench, LoCoMo, and second-source audits.
- G-EVAL project judge endpoint, cache, and 50 x 3 repeatability.
- G-BACKBONE-REPLICATION real different-family probe and budget.
- G-BUDGET SATURATION-01 with Full Context and Budget-Matched Retain.
- Protocol tag eval-protocol-v1.0 is not issued until all Gates pass.
