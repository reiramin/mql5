# META OOS canonical protocol (Phase 19)

The canonical out-of-sample protocol for the Meta portfolio layer.
This file is the single source of truth for how META is compared to
EQUAL_WEIGHT and what may be concluded. Consistency is pinned by
`tests/test_doc_consistency.py`.

## Design

- **Walk-forward only.** Every Meta decision at `t` consumes
  statistics, regime labels and drift computed from data strictly
  before `t`. There is no training/hold split to game: the as-of
  snapshot IS the protocol.
- **Equal weight is the baseline and runs the identical event stream**
  through the identical execution mechanics — only the policy layer
  differs (EW same mechanics by construction).
- **Certification states never collapse**: VERIFIED / UNCERTIFIED are
  distinct inputs; UNCERTIFIED books sit at weight 0 (pinned).
- **Runtime state vs research knowledge**: only allocation state
  (weights, zero reasons, activation) crosses decision boundaries.

## Metrics and decision rule

For META vs EQUAL_WEIGHT report: net profit, Sharpe, max drawdown,
per-book/per-symbol attribution, and the statistical difference gate:

- bootstrap CI of ΔSharpe (equity-curve bootstrap, `meta_replay`)
- probability META > EW (PSR-style)
- Sharpe / return / drawdown differences

**Decision rule**: if the CI straddles zero, META is NOT promoted —
regardless of any single p-value. No single statistic is sufficient.

## Standing canonical result (prior gate, commit `61d55ab`)

| policy | net | Sharpe | maxDD |
|---|---|---|---|
| META | 1334.34 | 1.4505 | -5.47% |
| EQUAL_WEIGHT | 1414.28 | 1.1696 | -8.32% |

Bootstrap ΔSharpe CI **[-0.1121, +0.2173]** (straddles zero), PSR
0.4367 ⇒ **EW retained, Meta stays DISABLED** for production. The
risk-adjusted shape (lower DD, higher Sharpe on lower net) is noted
but does not clear the gate.

## Status

Meta is in certification state DISABLED. Empirical promotion requires,
in order: MT5 compile + roundtrip truth (owner), real-basket validation
(Phase 20 runner), shadow run, OOS rerun under this protocol, and the
utility decision by the owner. SOFTWARE_PASS of the realism gate does
not change production status.

## Multi-asset amendments (this gate)

- Canonical runs are multi-book (`symbol@strategy` books, shared
  account, explicit per-symbol specs + conversion).
- Regime and drift inputs are the causal feeds (`regime_feed`,
  `drift_feed`), journaled per decision (`regime_as_of`,
  `drift_as_of`).
- The regime matrix (`docs/REGIME_MATRIX.md`) is measurement, frozen
  config, and must not feed back into parameters (no-tuning rule).
