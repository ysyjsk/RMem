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

Primary test is a two-sided paired permutation over episode x replicate blocks, swapping only left-deep and canonical-balanced labels. Same-plan seed null is diagnostic only and preserves the same R-run averaging structure.

## Thresholds

delta_SESOI = 0.05
delta_decision in {0.05, 0.075, 0.10, 0.125, 0.15}
R_pilot = 3
R_formal = 5

delta_decision must be frozen by G-POWER-FEASIBILITY before topology results.

## Lifecycle Cost

C_life = C_construct + C_query

Costs are stratified by backbone x k x budget x plan. Missing cost is unknown, never silent zero.

