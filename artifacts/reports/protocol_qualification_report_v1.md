# Protocol Qualification Report v1

Date: 2026-08-04

## Scope

This report qualifies the offline Phase 1 protocol harness built from workplan.md and Proposal.md. It covers executable contracts, synthetic fixtures, schema validation, metric/statistical functions, regression tests, the first three real vertical Gate commands, and real Evaluator Parity qualification.

It does not claim that judge repeatability, cache qualification, SATURATION-01, leaf construction, or acceptance experiments have passed. The provider-backed Day 1 Gate, local BGE-M3 sub-Gate, and Evaluator Parity have passed; later qualification Gates remain pending.

## Completed Offline Gates

- M0 pytest skeleton and Make targets are present.
- Schema contracts cover episode/evidence, protected scoring query,
  PlanNodeRaw, NodeArtifact (the in-place ViewNode replacement), run/bindings/
  merge events, score/support mapping, cost/API attempts, backbone bundle, and
  retrieval config without a parallel observability schema.
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
- Benchmark Observability is frozen into T0/T6/T7/T9, G-PLAN/G-COST/G-REPRO,
  the existing schemas, metric specification, and tests. Raw-to-derived rebuild,
  accepted binding, cache lineage, provider/local usage, state-cost separation,
  protected-label views, executor comparability, and full-leaf entry-order tests
  pass.

## Test Result

Command:

    .venv/bin/python -m pytest -q

Result:

    375 passed

## Real Vertical Gate Results

- Day 1 is passed for run `day1-383db20a02f9473294b2b632784e13b4` against the frozen `https://api.labforge.cc/v1` base URL and produced all eight required artifacts. The API credential was loaded from the environment and was not written to artifacts. Inventory, primary 115K, primary 4096-output, judge, `gpt-5.4` replication, BGE-M3, and the direct/proxy network probe are passed. The cost artifact was refreshed without re-running any passed gate; its LabForge public pricing/status snapshot records response hashes, formula bundle hashes, and the maximum enabled group ratio (`2`) because the API-key group is not auditable.
- Evaluator Parity is passed for run `evaluator-parity-cdc9dc290e214da2bab361283dd163bd`. The command fetched the pinned LongMemEval evaluator at commit `9e0b455f4ef0e2ab8f2e582289761153549043fc` and MemoryAgentBench evaluator at commit `455306dcabc3842526eb83cd4e225e5d486c5c5d` directly from their official GitHub repositories; both observed source hashes equal the frozen hashes. Six deterministic normalization/exact/substring cases and five task-specific LongMemEval prompt hashes passed. The official `gpt-4o-2024-08-06` snapshot is absent from the already-passed Day 1 inventory, so this is recorded as an unavailable external compatibility limitation: no compatibility model call was made, no rolling alias was used, and the project judge remains `gpt-5.5`. Judge Repeatability remains pending, as does Cache Qualification.
- Judge Repeatability was attempted once under run `judge-repeatability-4c37b7794c664566a4d9dbfba4ef27f9` after the calibration-only projection and all TDD/provenance checks passed. The process completed and recorded a same-run stall: the first logical call received HTTP 403 on both `direct` and `proxy_17897`, producing zero accepted observations and zero provider outputs. This is an external access block, not a passed or failed repeatability estimate; no retry, model fallback, or Cache Qualification was performed.
- The immutable calibration projection is `normalized_calibration_20_30_50.json` (141 episodes), bound to power artifact hash `e1047377750b0ece33fb8162b7040f8b7510b9a2623abb15f9a77898e24136bc` and manifest hash `2109d9818fcccc528207724545bffc3e19a099e95d0843ecb79d4525453345ee`. Its materialization log records `acceptance_payload_exported=false`; the qualification runner did not open the combined normalized store.
- BGE-M3 real-episode probe passed at frozen model/tokenizer revision `5617a9f61b028005a4858fdac845db406aefb181` using `torch 2.6.0+cu124`, fp16, and the local RTX 3090 Ti. The probe explicitly disables safetensors fallback and records official `pytorch_model.bin` SHA-256 `b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38`. It is checksum-bound to audit hash `bab30d495a11f8f1e4558ffadd16a6bf67cde74cb49eb5b03738ae297e792154` and selects only the frozen 20/30/50 development split. Episode `06db6396` included all 51 timestamped sessions and 133,100 surrogate tokens; the maximum encoded unit was 4,934 model tokens. Two runs produced identical 1024-dimensional normalized embedding output, ranking, and non-empty 4,096-token packing results (4,087 tokens selected). Mean single-episode latency was approximately 2.01 seconds and observed peak reserved VRAM was 1,337,982,976 bytes.
- The cache-root drift found during the earlier aggregate Day 1 rerun remains corrected by using the repo-local offline Hugging Face cache. The current `embedding_probe.json` passes at the same frozen revision and official `pytorch_model.bin` SHA-256.
- Official LongMemEval-S cleaned revision `98d7416c24c778c2fee6e6f3006e7a073259d48f` was downloaded from the official Hugging Face URL. The recorded acquisition attempt is checksum-verified; the adapter's policy is official direct, then official `127.0.0.1:17897`, with no mirror fallback.
- Raw size is 277,383,467 bytes and SHA-256 is `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`.
- The adapter automatically writes a standard `checksums.sha256` manifest for both cleaned-S and the explicitly selected V2 adapter; the real cleaned-S manifest passes `sha256sum -c` against the absolute pinned source path.
- The real audit found 500 questions, 30 abstention items, 470 normalized non-abstention episodes, 30 explicit exclusions, and `no_silent_drop=true`. The primary KU/TR counts are `N_master=N4=N8=N16=199`. Twelve non-abstention episodes each contained one repeated source-session ID at a distinct timestamp; all were retained as distinct timestamped atomic items using deterministic evidence IDs. Exact duplicate `(source_id, timestamp, content)` rows remain excluded.
- Leakage connected components were assigned deterministically for all three preregistered split candidates. For 20/30/50, real primary E8 counts are development=40, calibration=60, acceptance=99.
- G-POWER-FEASIBILITY ran 1,000 estimator-matched Monte Carlo draws over real acceptance E8 evidence-layout strata. It froze 20/30/50, `delta_decision=0.10`, conservative power=0.869, Monte Carlo 95% lower bound=0.8466683584396694, and `hard_no_go_available=true` for the power Gate only.
- The current no-download rebuild is bound to audit hash `bab30d495a11f8f1e4558ffadd16a6bf67cde74cb49eb5b03738ae297e792154`; the power artifact is bound to that same input audit hash and has artifact hash `e1047377750b0ece33fb8162b7040f8b7510b9a2623abb15f9a77898e24136bc`.
- Every generated data/power artifact records `full_leaf_generation_allowed=false`.
  Full leaf generation remains forbidden.
  The executable guard also requires the frozen sequence `Observability Freeze ->
  Evaluator Parity -> Judge Repeatability -> Cache Qualification -> SATURATION-01
  -> Final Judge/Budget Freeze -> eval-protocol-v1.0 -> Q0/D_leaf micro-run ->
  Full Leaves`. Only the first two steps are complete; a passed Day 1,
  Observability Freeze, or Evaluator Parity does not authorize leaves.

## Pending External Gates

- G-DATA MemoryAgentBench, LoCoMo, and second-source audits.
- G-EVAL Judge Repeatability (50 x 3) and Cache Qualification. The project judge endpoint and Evaluator Parity are passed.
- G-BUDGET SATURATION-01 with Full Context and Budget-Matched Retain.
- Protocol tag eval-protocol-v1.0 is not issued until all Gates pass.
