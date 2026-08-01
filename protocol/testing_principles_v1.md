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

## P7 Immutable Source of Truth

Raw evidence, leaves, merged nodes, answers, scores, prompts, configs, checksums, model snapshots, and cache keys must remain auditable.

## P8 Budget-Conditioned Reporting

All results are reported by budget. Primary sweep uses B_merge = B_final = B_query = B.

## P9 Auditable Evaluator

Judge model, provider route, requested/returned model, prompt hash, config hash, parser/cache key, and repeatability must be recorded. Silent fallback is prohibited.

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

