# Protocol Qualification Report v1

Date: 2026-08-02

## Scope

This report qualifies the offline Phase 1 protocol harness built from workplan.md and Proposal.md. It covers executable contracts, synthetic fixtures, schema validation, metric/statistical functions, regression tests, and the first three real vertical Gate commands.

It does not claim that the provider-backed primary/judge/replication probes, judge repeatability, SATURATION-01, leaf construction, or acceptance experiments have passed. The local BGE-M3 embedding sub-Gate has passed; the aggregate Day 1 Gate and the remaining external Gates are still blocked or pending.

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

    222 passed

## Real Vertical Gate Results

- Day 1 command was rerun against the frozen `https://api.labforge.cc/v1` base URL and produced all eight required artifacts. The API credential was loaded from the environment and was not written to artifacts. Day 1 remains blocked: direct and `127.0.0.1:17897` `/models` requests both returned HTTP 400 with empty response bodies, so no authenticated inventory or different-family replication model was qualified; the full provider-priced cost upper bound is also not frozen. Minimal `/chat/completions` diagnostics using exactly one `user` message and no `system`/`developer` message produced the same empty-body HTTP 400 on both routes. The latest P14 stall report dated `2026-08-02T08:08:18Z` records embedding passed and API inventory blocked.
- BGE-M3 real-episode probe passed at frozen model/tokenizer revision `5617a9f61b028005a4858fdac845db406aefb181` using `torch 2.6.0+cu124`, fp16, and the local RTX 3090 Ti. The probe explicitly disables safetensors fallback and records official `pytorch_model.bin` SHA-256 `b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38`. It is checksum-bound to audit hash `bab30d495a11f8f1e4558ffadd16a6bf67cde74cb49eb5b03738ae297e792154` and selects only the frozen 20/30/50 development split. Episode `06db6396` included all 51 timestamped sessions and 133,100 surrogate tokens; the maximum encoded unit was 4,934 model tokens. Two runs produced identical 1024-dimensional normalized embedding output, ranking, and non-empty 4,096-token packing results (4,087 tokens selected). Mean single-episode latency was approximately 2.01 seconds and observed peak reserved VRAM was 1,337,982,976 bytes.
- The cache-root drift found during the latest aggregate Day 1 rerun has been corrected by using the repo-local offline Hugging Face cache. The current `embedding_probe.json` now passes again at the same frozen revision and official `pytorch_model.bin` SHA-256; the aggregate Day 1 Gate still remains blocked because the provider inventory and generation probes return HTTP 400 before any model can be qualified.
- Official LongMemEval-S cleaned revision `98d7416c24c778c2fee6e6f3006e7a073259d48f` was downloaded from the official Hugging Face URL. The recorded acquisition attempt is checksum-verified; the adapter's policy is official direct, then official `127.0.0.1:17897`, with no mirror fallback.
- Raw size is 277,383,467 bytes and SHA-256 is `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`.
- The adapter automatically writes a standard `checksums.sha256` manifest for both cleaned-S and the explicitly selected V2 adapter; the real cleaned-S manifest passes `sha256sum -c` against the absolute pinned source path.
- The real audit found 500 questions, 30 abstention items, 470 normalized non-abstention episodes, 30 explicit exclusions, and `no_silent_drop=true`. The primary KU/TR counts are `N_master=N4=N8=N16=199`. Twelve non-abstention episodes each contained one repeated source-session ID at a distinct timestamp; all were retained as distinct timestamped atomic items using deterministic evidence IDs. Exact duplicate `(source_id, timestamp, content)` rows remain excluded.
- Leakage connected components were assigned deterministically for all three preregistered split candidates. For 20/30/50, real primary E8 counts are development=40, calibration=60, acceptance=99.
- G-POWER-FEASIBILITY ran 1,000 estimator-matched Monte Carlo draws over real acceptance E8 evidence-layout strata. It froze 20/30/50, `delta_decision=0.10`, conservative power=0.869, Monte Carlo 95% lower bound=0.8466683584396694, and `hard_no_go_available=true` for the power Gate only.
- The current no-download rebuild is bound to audit hash `bab30d495a11f8f1e4558ffadd16a6bf67cde74cb49eb5b03738ae297e792154`; the power artifact is bound to that same input audit hash and has artifact hash `e1047377750b0ece33fb8162b7040f8b7510b9a2623abb15f9a77898e24136bc`.
- Every generated data/power artifact records `full_leaf_generation_allowed=false`. Full leaf generation remains forbidden because Day 1 is blocked.

## Pending External Gates

- G-NETWORK/API/provider-model qualification must be rerun after the provider/edge HTTP 400 condition is resolved; the credential is already present, and it must not be printed or persisted. The frozen BGE-M3 revision is locally resolvable through the repo-local offline cache and must remain unchanged during the next provider/API rerun.
- G-DATA MemoryAgentBench, LoCoMo, and second-source audits.
- G-EVAL project judge endpoint, cache, and 50 x 3 repeatability.
- G-BACKBONE-REPLICATION real different-family probe and budget.
- G-BUDGET SATURATION-01 with Full Context and Budget-Matched Retain.
- Protocol tag eval-protocol-v1.0 is not issued until all Gates pass.
