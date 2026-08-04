# Metric Specification v1

## Aggregation

Query scores are first macro-averaged within episode, then macro-averaged across episodes, then averaged across registered repeated runs:

S(e,k,B,T,r) = mean_q s(e,k,B,T,r,q)
Q(k,B,T,r)   = mean_e S(e,k,B,T,r)
Q_T(k,B)     = mean_r Q(k,B,T,r)

The independent inference unit remains episode/construction unit.

## Task Quality

For an explicit plan set P:

Q_mean(P,k,B)  = mean over T in P of Q_T(k,B)
Q_worst(P,k,B) = min over T in P of Q_T(k,B)
Q_best(P,k,B)  = max over T in P of Q_T(k,B)

Q_worst always means worst tested-plan quality for the named plan set.

## Plan Robustness

Confirmatory primary contrast:

Delta_primary(k,B) = Q_canonical_balanced(k,B) - Q_left_deep(k,B)

Diagnostic range:

D_diag(k,B) = max over Pi_diag Q_T(k,B) - min over Pi_diag Q_T(k,B)

right_deep is diagnostic-only and cannot enter the headline primary statistic.

## Statistical Tests

Primary test is a two-sided paired permutation over episode blocks. For each episode, repeated runs are paired by replicate and averaged into one canonical_balanced - left_deep difference before sign-flip permutation. Same-plan seed null is diagnostic only and preserves the same R-run averaging structure.

## Thresholds

delta_SESOI = 0.05
delta_decision in {0.05, 0.075, 0.10, 0.125, 0.15}
R_pilot = 3
R_formal = 5

delta_decision must be frozen by G-POWER-FEASIBILITY before topology results.

## Lifecycle Cost

C_life = C_construct + C_query

Costs are stratified by backbone x k x budget x plan. Missing cost is unknown, never silent zero.

## Raw/Derived Boundary

The execution source of truth is the raw artifact set. The existing objects are
refined in place; no parallel observability schema is introduced:

| Existing object | Raw responsibility |
| --- | --- |
| Plan | plan header plus `PlanNodeRaw` child edges |
| ViewNode/leaf artifact | `NodeArtifact` materialization |
| Run | executor configuration, accepted bindings, and merge events |
| Cost/API log | `ModelCallAttemptRaw` |
| Metrics | derived `PlanMetrics`, `MergeEventMetrics`, `EvidenceExposure`, and `AnnotatedSupportExposure` |

`PlanNodeRaw` contains only `logical_node_id`, `plan_id`, `node_type`, the
applicable leaf or child IDs, and `covered_span`. Descendant leaves, depth,
role paths, height, merge count, and critical path are reconstructed from child
edges. `deterministic_plan_hash` is a derived checksum, not a second topology
source of truth.

`NodeArtifact.content_artifact_id` is a stable content reference and must be
resolvable. `creation_event_id` is the lineage source. `NodeArtifact` never
contains `cache_source_artifact_id`; cache lineage is represented by the
creation event/`MergeEventRaw`. Materialization source is exactly one of
`generated`, `cache`, or `deterministic`.

## Accepted Output And Usage

`AcceptedOutputBindingRaw` is the only truth for an accepted generated API
output. A successful binding references exactly one accepted attempt, and an
attempt can be referenced by at most one successful binding. The optional
`ModelCallAttemptRaw.accepted_attempt` field is only a consistency cache.
Bindings cover generated API outputs at the leaf, merge, answer, and judge
stages. Cache and deterministic materializations instead establish acceptance
through their creation/materialization event and source artifact; they never
fabricate an accepted API binding.

Every API stage uses the same `ModelCallAttemptRaw` fields. `requested_model`,
`provider`, and `provider_route` are present as non-empty strings for every
attempt. The `returned_model` and `request_id` keys are also always present, but
their values are nullable when the provider did not return the corresponding
identity. They must be non-empty strings for `accepted_materialized`,
`successful_nonmaterialized`, and `failed_parse`; they may be null for
`failed_validation`, `failed_provider`, `cancelled_before_start`, and
`cancelled_after_start`. Any non-null value remains a non-empty string. Sentinel
strings such as `"unknown"` or `"None"` are invalid substitutes for null.

The current local fields are
`local_surrogate_content_tokens`,
`local_surrogate_serialized_input_tokens`, and
`local_surrogate_output_content_tokens`. They use the frozen
`surrogate_regex_bytes_v1` accounting rule and support deterministic
partitioning, relative-length comparisons, and reproducible pressure proxies;
they are not exact model-token measurements. Provider fields are operational
observations and are never populated from local surrogate counts.
`provider_usage_source` is `provider_exact`, `provider_estimated`, or `missing`.
When it is `missing`, all provider token fields are null and the corresponding
provider resource metric is `unknown`.

`provider_cached_input_tokens_subset` is a subset of total input and
`provider_reasoning_tokens_subset` is a subset of total output. Therefore:

```text
uncached_input_tokens = provider_input_tokens_total
                         - provider_cached_input_tokens_subset
```

Cached input is never added to total input a second time. A
`successful_nonmaterialized` attempt and a failed attempt that reached the
provider remain in observed operational work, but neither enters materialized
lineage. Cache hits have no fabricated API attempt and do not increase
EvidenceExposure `generative_rewrite_depth`.

Accepted-path work contains the accepted leaf/merge/answer attempts.
Observed operational work additionally contains successful nonmaterialized and
provider-executed failed attempts. Judge usage and latency are retained in a
separate judge-overhead block and are not folded into memory lifecycle cost.

## Judge Repeatability Qualification

The qualification set is the immutable calibration-only 50-case manifest from
the frozen 20/30/50 split. Each case has exactly three unique replicates, so a
valid metric input contains exactly 150 observations and all seven frozen case
categories. Malformed, missing, duplicate, or extra observations are contract
errors rather than implicit zeros.

```text
unanimity_rate     = unanimous cases / 50
pairwise_flip_rate = flipped unordered replicate pairs / 150
parse_success_rate = successfully parsed observations / 150
```

There are three unordered replicate pairs per case. A valid parsed label is the
integer `0` or `1`; JSON booleans, numeric strings, additional JSON keys, and
free text are invalid. The Gate requires `unanimity_rate >= 0.95`,
`pairwise_flip_rate <= 0.05`, and `parse_success_rate == 1.00`.
`AcceptedOutputBindingRaw` remains the only accepted-generated-API-output truth.
Raw transport, model-attempt, binding, and output artifacts are kept separate
from the derived observation table and metrics.

This Gate measures repeatability only. Expected case-construction labels are
descriptive audit fields and do not enter the decision; agreement with human
correctness judgments is outside `eval-protocol-v1.0`.

## Mechanism Diagnostics

The following are preregistered descriptive secondary diagnostics; they do not
alter the benchmark, plan sets, workload, primary outcomes, or top-level gates.

For a generated merge, let `L` and `R` be child
`local_surrogate_content_tokens`, let `O` be output
`local_surrogate_content_tokens`, and let `B_merge` be the configured
model-token output budget:

```text
content_to_budget_pressure = (L + R) / B_merge
actual_compression_ratio   = O / (L + R)
output_budget_utilization  = O / B_merge
payload_to_budget_ratio    = local_surrogate_serialized_input_tokens / B_merge
token_imbalance_abs        = abs(L - R) / (L + R)
token_imbalance_signed     = (L - R) / (L + R), when the order contract allows it
```

Because their numerators currently use the surrogate counter, these ratios are
reproducible local pressure/compression proxies, not exact model-token pressure
or proof of capacity safety. Before Q0, the existing G-COST/Q0 entry condition
must freeze either (a) the real model tokenizer at an immutable revision, or
(b) provider/tokenizer comparison evidence, a justified safety margin, and a
test showing that the admitted capacity cannot exceed the real model budget.
The current repository has not yet established that evidence or margin.

`content_to_budget_pressure` is a structural exposure proxy; it does not claim
semantic retention. Canonical path names and directions are:

```text
order_role_path_vector_root_to_leaf    # PlanMetrics, root -> leaf
order_role_sequence_root_to_leaf       # EvidenceExposure, root -> leaf
generative_merge_path_leaf_to_root     # EvidenceExposure, leaf -> root
```

Each MergeEventMetrics row uses only `is_generative_merge: bool` for the
per-event indicator. `generative_rewrite_depth` exists only in EvidenceExposure
and equals `len(generative_merge_path_leaf_to_root)`; it is unaffected by
retries, failed attempts, or cache hits. Earlier/later roles are determined by
frozen evidence order and covered spans, never by timestamps. The legacy
directionless path/sequence names and per-event `generative_rewrite_depth` are
not parallel compatibility fields.

Mechanism rows are aggregated within episode-plan-run before topology contrasts.
Evidence rows are not independent observations, topology merge index `n` is not
paired across topologies, and mechanism diagnostics report only
episode-clustered bootstrap intervals. They do not produce confirmatory
p-values and never enter GO/NO-GO decisions.

## State And Support Boundaries

State cost is split into:

1. deployment state (`deployment_memory_tokens`, metadata bytes, capability
   profile, and a frozen measurement point);
2. shared source state (`shared_leaf_tokens`, raw evidence bytes); and
3. experiment artifact footprint (`artifact_cache_bytes`).

Artifact footprint is an audit/reproduction resource, not deployment lifecycle
cost. Phase 1 primary offline uses `FINAL_QUERY_ONLY`; online runs must declare
one common capability profile for all compared topologies.

Protected gold answers and supporting labels are unavailable to construction and
answer views. Only the scoring view may load them after run artifacts and
answers are frozen and an access log is written. Support is mapped explicitly as
`session -> atomic evidence -> chunk -> leaf` with status `exact`,
`expanded_to_chunks`, or `unresolved`. Summary fields use unique supporting
leaves and the canonical names `annotated_support_rewrite_mean/max`,
`annotated_support_pressure_mean/max`, and
`annotated_support_order_role_summary`.

## Execution Comparability

Formal topology runs freeze executor mode, concurrency, cold-cache mode,
retry/rate-limit policies, and provider route. Run identity also records the
provider observation window, replication index, and topology execution order.
Stage wall-clock starts at the first scheduled logical operation and ends at the
last required artifact being validated and persisted. Leaf, merge, answer, and
judge boundaries are recorded separately. Cumulative attempt latency,
critical-path elapsed latency, and `parallelism_factor` are distinct derived
quantities.

## Pricing Manifest

USD is optional and derived only from a run-level `PricingManifest`. Rates are
normalized to USD per 1M tokens and the manifest records provider, model, route,
usage schema, effective date, source access time, and source snapshot hash. A
missing manifest makes estimated USD `unavailable`, never zero; scientific
resource metrics remain valid without a pricing manifest.
