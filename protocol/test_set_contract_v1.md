# Test Set Contract v1

## Unit Hierarchy

1. Episode/construction unit: split, leaf, plan, and cluster unit.
2. Query: task score unit, aggregated within episode.
3. Operation item: v1.1 schema-only audit category, not a v1.0 Gate.

## Primary Dataset Contract

Primary v1.0 targets LongMemEval-S knowledge-update and temporal-reasoning, excluding _abs queries. Actual counts must come from file manifests and checksums, not issue threads or papers.

## Synthetic Fixture Test Set

The repository includes deterministic fixtures only for protocol testing. They are not acceptance data and must not be reported as experimental evidence.

Fixture coverage:

- legal episode schema and illegal missing construction unit;
- k eligibility masks for 4, 8, and 16 leaves;
- fixed-leaf cache reuse across budget/topology;
- budget mismatch and query-budget sweep failures;
- split leakage examples;
- judge repeatability/cache examples;
- no-go, ceiling-control, and underpowered-null regression cases.

## Acceptance Protection

Acceptance query/gold content is unavailable to normal tests. Loading acceptance requires RUN_MODE=acceptance and a frozen protocol tag; every load is append-only logged.

## External Gate Status

The official LongMemEval-S cleaned file at revision
`98d7416c24c778c2fee6e6f3006e7a073259d48f` has been downloaded and audited.
Its frozen raw SHA-256 is
`d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`.
The primary test-set manifest contains 199 eligible non-abstention
knowledge-update/temporal-reasoning episodes. The 20/30/50 leakage-grouped
candidate assigns primary `N_master/N4/N8/N16` counts of 40/40/40/40,
60/60/60/60, and 99/99/99/99 to development, calibration, and acceptance.

Repeated source session IDs with distinct timestamps are represented as
distinct normalized atomic evidence IDs; exact duplicate timestamp/content
rows are explicitly excluded and listed in `excluded_items.jsonl`.

G-POWER-FEASIBILITY passed from this real manifest with
`delta_decision=0.10`; this does not constitute a topology result.

BGE-M3 local embedding qualification passed at the frozen model/tokenizer
revision `5617a9f61b028005a4858fdac845db406aefb181` on the local RTX 3090 Ti.
The real development episode `06db6396` covered all 51 timestamped sessions
(133,100 surrogate tokens); two fp16 encode runs produced identical embedding,
ranking, and packing hashes without exceeding the 8,192-token unit limit.

Day 1 remains blocked: direct and `127.0.0.1:17897` model-inventory requests
both returned HTTP 400 with empty response bodies. The provider credential is present
and was loaded from the environment without being written to artifacts, but no
authenticated inventory was returned, no different-family replication model is
frozen, and the full provider-priced cost upper bound is not frozen. A subsequent offline rerun resolved the same frozen BGE-M3 weight from the repo-local
cache and restored the current embedding artifact to passed without changing the
model revision or SHA-256. MemoryAgentBench, LoCoMo, second-source qualification, judge
repeatability, SATURATION-01, and all acceptance experiments remain pending.
Full leaf generation therefore remains forbidden.
