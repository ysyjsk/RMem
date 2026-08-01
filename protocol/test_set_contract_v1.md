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

Real LongMemEval, MemoryAgentBench, LoCoMo, model probes, judge repeatability, and API/GPU-dependent checks are represented by executable validation contracts in this phase. The Gates remain pending until real artifacts are produced.

