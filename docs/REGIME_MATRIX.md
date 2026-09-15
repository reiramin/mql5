# Regime matrix (Phases 21–23)

Frozen canonical config; decisions/trades partitioned by the regime label KNOWN at the covering decision (causal, as-of).  Measurement only — no tuning.

Run: 24 rebalances, 830 trades.

## Labels live per symbol (decision counts)

- **EURUSD**: HIGH_VOL=6, LOW_VOL=3, RANGE=6, TRANSITION=9
- **XAUUSD**: HIGH_VOL=2, LOW_VOL=4, RANGE=9, TRANSITION=8, TREND_UP=1

## Per-regime trade statistics

| regime | trades | pnl sum | pnl mean | hit rate | mean weight |
|---|---|---|---|---|---|
| HIGH_VOL | 29 | -14.36 | -0.5 | 0.5172 | 0.5134 |
| LOW_VOL | 204 | -2192.83 | -10.75 | 0.2647 | 0.4306 |
| RANGE | 278 | -3157.19 | -11.36 | 0.1007 | 0.7179 |
| TRANSITION | 319 | -3639.43 | -11.41 | 0.2006 | 0.6016 |

## Full manifest digest

- git_commit: `068cd08`
- regime_version: `asof-1.1`
- drift_version: `asof-1.0`
- config_hash: `3808da3ff7366e18`
