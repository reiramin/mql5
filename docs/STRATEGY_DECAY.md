# Strategy Decay & Recovery (mission §35–§36/§37)

**Status: IMPLEMENTED (controller); telemetry feed wiring PARTIAL.**

## Band decision

`discovery/governance.py:PerformanceDecayController` evaluates a `HealthSignals` record: rolling expectancy ratio (live/backtest), live-vs-backtest drawdown ratio, drift score (`drift_feed.py`), slippage vs assumption, regime mismatch, and a hard risk-breach flag. Demerits map to bands (configurable in `discovery.yaml:decay_bands`):

| Band | Multiplier | Pause |
|---|---|---|
| HEALTHY | 1.00 | no |
| MINOR_DEGRADATION | 0.80 | no |
| MODERATE_DEGRADATION | 0.55 | no |
| SEVERE_DEGRADATION | 0.25 | no |
| CRITICAL | 0.00 | yes |

Worst-signal-wins; a hard risk breach goes straight to CRITICAL. Bands and thresholds are policy, not code constants.

## Anti-churn guardrails (§35/§37)

- Fewer rolling trades than `min_rolling_trades` (default 10) → **HEALTHY regardless of the numbers**: one isolated loss can never demote (pinned: `test_decay_single_loss_never_demotes`).
- Multi-signal requirement: a single weak signal yields at most a mild band; demotions beyond MINOR need ≥2 weak signals or a hard breach.
- The multiplier feeds the governor: `effective = recommendation × decay × ramp × safety` — decay REDUCES allocation gradually (reversible), it never sells anything.

## Recovery (§36)

`CRITICAL` pauses. `RequalificationGate.may_requalify` requires: ≥`min_shadow_trades` (30), ≥`min_shadow_days` (14), shadow score ≥ 0.55 — and REFUSES anything previously `REJECTED` (a rejected candidate needs a NEW version through full validation, not revival). Recovery path: PAUSED → REQUALIFICATION → SHADOW → (evidence) → DEMO → LIVE_SMALL. A lucky recent streak never revives a failed strategy.
