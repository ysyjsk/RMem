# Testing Principles v1

Source of authority: workplan.md Phase 1 and Proposal.md sections 9-10.

This protocol freezes the first-phase testing principles before any formal acceptance run.

## P1 Original Task Behavior First

Primary quality is benchmark task behavior: exact match, accuracy, F1, task success, or frozen judge label. Memory text similarity is diagnostic only.

## P2 Fixed-Leaf Single-Variable Topology

Primary topology comparison fixes episode, evidence order, leaf boundaries, C_leaf, leaf prompt/model/config, s_leaf=0, leaf bytes, merge prompt/model, B_merge, B_final, B_query, answer model, and evaluator. Only the reduction-tree parenthesization may change.

## P3 Order Preservation

All legal topology plans preserve original semantic time order and merge only contiguous spans.

## P4 Behavioral Equivalence

Different wording is not a failure. Query/task behavior and source-grounded audit define equivalence.

## P5 True Statistical Unit

The independent unit is episode/construction unit. Queries are aggregated within episode; repeated runs improve stochastic precision but do not increase independent sample count.

## P6 Dev/Cal/Acceptance Isolation

Development supports implementation. Calibration supports budget, judge, seed, and power qualification. Acceptance is sealed until protocol freeze and cannot be used to select data, budget, prompts, thresholds, or baselines.

Gold answers and supporting annotations are protected labels. Construction cannot
see queries/gold/support labels; answering cannot see gold/support labels; scoring
may load them only after run artifacts and answers are frozen and access is
logged.

## P7 Immutable Source of Truth

Raw evidence, leaves, merged nodes, answers, scores, prompts, configs, checksums, model snapshots, and cache keys must remain auditable.

Observability follows the same rule: raw `PlanNodeRaw`, `NodeArtifact`,
`ModelCallAttemptRaw`, `AcceptedOutputBindingRaw`, and `MergeEventRaw` are the
source of truth. Derived plan/merge/resource/support metrics must be rebuildable
after deleting derived tables. A cache source is represented by its creation
event; it is not copied into `NodeArtifact` as a second lineage field.

`AcceptedOutputBindingRaw` is specifically the unique truth for an accepted
generated API output. Cache and deterministic materializations establish
acceptance through their creation/materialization event and source artifact and
must not fabricate a binding or API attempt. Path contracts fail closed unless
they use `order_role_path_vector_root_to_leaf`,
`order_role_sequence_root_to_leaf`, and
`generative_merge_path_leaf_to_root` in the stated directions. A merge-event
row exposes `is_generative_merge`; only EvidenceExposure may expose
`generative_rewrite_depth`, equal to the length of its leaf-to-root generative
path.

## P8 Budget-Conditioned Reporting

All results are reported by budget. Primary sweep uses B_merge = B_final = B_query = B.

## P9 Auditable Evaluator

Judge model, provider route, requested/returned model, prompt hash, config hash, parser/cache key, and repeatability must be recorded. Silent fallback is prohibited.

Judge Repeatability is calibration-only and requires exactly 50 cases x 3 unique replicates with all frozen case categories. Empty, partial, duplicate, malformed, cross-run, model-drifted, or acceptance-derived inputs fail closed. Passing this Gate establishes output stability under the frozen wrapper; it does not establish human-label validity.

For every `ModelCallAttemptRaw`, `requested_model`, `provider`, and
`provider_route` are non-empty. `returned_model` and `request_id` keys are
present but may be null only for `failed_validation`, `failed_provider`, and
cancelled outcomes; accepted, successful-nonmaterialized, and parse-failed
provider responses require non-empty values. Placeholder identity strings are
invalid.

Provider usage and local surrogate token counts are recorded separately.
Accepted generated API output is defined by `AcceptedOutputBindingRaw`; missing
provider usage remains unknown, and cached input/reasoning subsets are never
counted twice. `local_surrogate_content_tokens`,
`local_surrogate_serialized_input_tokens`, and
`local_surrogate_output_content_tokens` are reproducible proxies under
`surrogate_regex_bytes_v1`, not exact model tokens. Before Q0, the existing
G-COST/Q0 entry condition requires either a frozen real tokenizer or measured
provider/tokenizer error, a justified safety margin, and evidence that admitted
inputs/outputs cannot exceed the real model budget. No such qualification is
presumed complete.

## P10 No Single Composite Score

Task Quality, Plan Robustness, and Lifecycle Cost are reported separately.

## P11 Falsifiability

The test set must allow null effects, underpowered designs, judge failure, retention dominance, online-balanced closure, or data-scope limitations.

## P12 Sequential NO-GO Protection

Formal NO-GO requires sufficient power, non-ceiling signal-bearing budget, primary and stress operator below delta_decision, judge qualification, and CI/equivalence excluding delta_decision.

## P13 Threshold Separation

delta_SESOI = 0.05 is fixed. delta_decision is selected before topology results from the frozen power artifact and must be at least 0.05.

## P14 Progress/Stall Escalation

Repeated Gate failure without new tests, artifacts, or exclusionary evidence requires a stall report and blocks the next milestone.

## P15 k-Axis Isolation

K_planned = {4,8,16}, k_primary = 8; split is independent of k. k-sweep uses common E_16.

## P16 Claim-Scoped Plan Sets

Pi_primary={left_deep, canonical_balanced}, Pi_diag={left_deep, canonical_balanced, right_deep}, and Pi_online={eager_left_deep, online_canonical_balanced}.

## P17 Backbone/Retriever as Explicit Dimensions

Primary topology comparison fixes backbone and retrieval. Backbone or embedding changes are separate replication/sensitivity axes.

## P18 Data Generality Requires Independent Sources

Cross-dataset claims require independent construction processes and true construction-unit counts.

## P19 Test-First Contract Evolution

Observability contract changes begin with failing validator/schema-parity and
raw-to-derived tests. The red tests must cover nullable failed-attempt provider
identity without placeholder strings, generated/cache/deterministic binding
boundaries, canonical path direction, event-versus-evidence rewrite semantics,
and surrogate-versus-provider token separation. Implementation and documentation
may be frozen only after those tests pass without retaining legacy parallel
fields.
