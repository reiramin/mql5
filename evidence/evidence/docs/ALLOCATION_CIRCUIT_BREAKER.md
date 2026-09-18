# Allocation Circuit Breaker (mission §41/§79–§80)

**Status: IMPLEMENTED.**

`discovery/safety.py:AllocationCircuitBreaker` + `AllocationProposal`.

## What it watches (per rebalance)

- gross allocation jump vs previous > `max_allocation_jump_pct` (default 25pp)
- strategy-count collapse ≥ `max_strategy_count_drop` (5 → 1 = anomaly)
- candidate explosion (candidate_count > `max_candidate_explosion`)
- per-strategy weight teleport (|Δ| > 0.75 in one proposal)

## On anomaly

1. FREEZE: `FROZEN_KEEP_LAST_SAFE` — the LAST SAFE allocation is returned as effective (kept, not unwound).
2. Cooldown for `cooldown_rebalances` rebalances (even sane proposals stay frozen).
3. Alert + human review: `reset(actor, reason)` is required (empty actor/reason raise — attack 16), recorded with the reset reason.

## Boundaries

- NOT the kill switch: no position is closed, no trading stopped; capital keeps being managed at last safe weights.
- The governor adds a second layer of capping: per-strategy delta ≤ `max_strategy_delta` and portfolio gross/risk delta caps per rebalance (§79) — splitting one huge jump into many small ones is bounded by the same caps (attack 25).
- Death-by-a-thousand-cuts: freeze windows plus governor caps bound the total drift rate; budgets are never silently raised for tests (§62).
