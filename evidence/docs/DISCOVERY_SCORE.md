# Discovery Score (mission §27–§29/§94)

**Status: IMPLEMENTED.**

## Definition

16 components (`score.py:COMPONENTS`): oos_survival, profit_factor, drawdown_quality, expectancy, trade_count_confidence, parameter_robustness, wfa_survival, cpcv_pbo_evidence, monte_carlo_stability, cost_robustness, regime_stability, drift_health, execution_realism, portfolio_diversification, shadow_evidence, live_evidence. Each raw value is normalized by a declared (lo, hi, higher_is_better) mapping to [0,1]; the score is the weight-normalized sum. Weights live in `factory/policies/discovery.yaml` (`discovery_score.weights`); changing them changes `policy_hash`, which is persisted with every score (§98 reproducibility).

## SCORE ≠ PERMISSION (§28)

The score answers "how attractive is this QUALIFIED candidate relative to others". It never answers "may this trade". Enforcements:
- `AllocationGovernor` computes weight only for ELIGIBLE entries (lifecycle carries live allocation + human approval + gates PASS + kill switch NORMAL + evidence bound) — a 0.999 score with `lifecycle_state=DRAFT` yields weight 0.0 (test: `test_governor_scores_rank_but_only_eligible_get_weight`).
- Governor output contains NO lots/risk semantics; lots come only from the existing Risk engine after Meta weights (§65).
- The operator UI renders score rows but the approval buttons route through `store.transition`, which re-validates the state machine and evidence — not the score.

## Missing evidence

A component without a measured value is `unavailable`: it contributes 0 and is listed in `DiscoveryScore.unavailable` and rendered as `MISSING EVIDENCE` in `explain()`. Missing evidence NEVER becomes an invented neutral pass.

## Vocabulary (§94)

There is no "best strategy" anywhere in code or docs. The strongest stage-eligible candidate by current evidence score is the top-ranked challenger; the currently allocated set are incumbents. `grep -ri "best strateg" python/ tests/ docs/` → no matches (checked at delivery).

## Ranking eligibility (§29)

`DiscoveryOrchestrator.rank_candidates` ranks only `OOS_SURVIVOR` and beyond. Shadow/live evidence components are simply unavailable below those stages — unequal evidence is never compared as equal.
