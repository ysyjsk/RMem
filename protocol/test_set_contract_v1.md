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

The Day 1 model/embedding Gate is blocked by absent credentials/model access
and an unqualified local embedding environment. MemoryAgentBench, LoCoMo,
second-source qualification, judge repeatability, SATURATION-01, and all
acceptance experiments remain pending. Full leaf generation therefore remains
forbidden.
