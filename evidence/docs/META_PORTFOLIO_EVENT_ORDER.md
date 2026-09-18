# META PORTFOLIO EVENT ORDER — canonical sequence (meta-production gate)

Normative event order for the canonical Meta portfolio process
(`python/mql5bot/meta_portfolio.py` driving `python/mql5bot/engine.py`,
mirrored by the EA in `mql5/Experts/Mql5Bot/Mql5Bot.mq5`).  An
implementation that evaluates a later stage using information produced by
an even later stage in the same bar is INVALID.

## Bar sequence (per bar b, evaluated at b's OPEN unless stated)

| # | Stage | Python (engine) | EA (Mql5Bot.mq5) |
|---|---|---|---|
| 1 | timestamp normalization | shared DatetimeIndex validated (`_validate_instruments`: alignment enforced) | server time (`iTime`, bar-close gate `OnTick`→`OnNewBar`) |
| 2 | server-day transition | `rollover()`: swap accrual on carried books, day-start equity basis, daily state reset | `OnTimer` day-key rollover, persisted day state |
| 3 | risk-state update | kill-switch/daily-loss evaluation on prior-close basis (`CheckLimits` equivalent in engine loop) | `CheckLimits`, persisted kill switch |
| 4 | stop/TP processing | `manage()`: intrabar SL/TP on carried books (stop-first, gap-through at open) | broker-side SL/TP + SlGuard verify |
| 5 | position management | trailing/breakeven/partial on carried books (prev-close ATR) | `ManageOpenPositions` on closed bars only |
| 6 | strategy signal generation | `desired[bar-1]` — signals from bars ≤ b−1 only (closed bars; pinned by no-future-bars tests) | `g_signal.Evaluate` on completed bar |
| 7 | Meta eligibility | certification/state inputs (`StrategyMetaInput`) at decision time | allocation file state gate (FRESH/STALE/MISSING/MALFORMED) |
| 8 | Meta factor computation | `as_of_stats_exclusive` over bars **< t** (strictly before the decision bar's open) + correlation of prior returns | N/A (weights arrive via file; EA never recomputes) |
| 9 | Meta weight computation | `MetaLayer.decide(as_of=t)` on the immutable snapshot (prior weights from layer state) | N/A |
| 10 | signal combination | desired side per strategy (signals are never combined into synthetic orders) | per-strategy signals |
| 11 | portfolio action | `reconcile()` at b's open: flip/offset/merge/open per book model | `OnNewBar` entry logic |
| 12 | Risk Engine | `size_lots` → `sizer.size_position` (stop-distance sizing, min-stop, margin) — **final veto, evaluated AFTER Meta eligibility but BEFORE Meta scaling** | `RiskManager.GetLots` |
| 13 | Meta scaling (reduce-only) | `lots × weight(t)`, floor to volume step, DROP below volume_min (`meta_scale_dropped`) | `g_alloc.ScaleLots` + floor-and-drop |
| 14 | execution/fill | `open_order`: gap/reject guards, entry fill at open ± spread/slippage | `OpenMarket/OpenPending` (RetryQueue) |
| 15 | state update | books/legs/cash/fees mutation, events journal | state store / ticket registry |
| 16 | mark-to-market | bar-close marks per book | broker MTM |
| 17 | equity snapshot + journal | `equity[b]`; events/trades recorded with bar + strategy attribution | journal + telemetry |

## Ordering invariants (machine-pinned)

1. **Weights at t use information strictly before t** —
   `as_of_stats_exclusive` selects `index < as_of`;
   future-perturbation tests (OHLC, spread, reject-mask) prove decisions
   at the first/middle/final rebalance are unchanged.
2. **Meta scaling happens AFTER Risk-Engine sizing** (stage 12 → 13) and
   can only shrink: `final_lots ≤ approved_lots` for every weight in
   [0, 1]; below-minimum DROPS (never volume_min bump — the EA-parity fix).
3. **Signals are stage-6 outputs; they never depend on stages 11–16.**
4. **A decision at bar b never observes bar b's close** — fills are at
   b's open; statistics end at b−1.
5. **Existing positions are not retroactively resized** (see below).

## Rebalance semantics (Phases 16/17)

* The rebalance grid is fixed in advance (`rebalance_grid`: first bar of
  every Nth day after `min_history_bars`) — independent of outcomes.
* A weight effective at t applies to **new entries decided at bars with
  open ≥ t** only.  Existing books keep their size, entry price, SL/TP,
  strategy attribution and identity — weights never rewrite history.
  This mirrors the EA: the allocation file scales NEW orders; open
  positions are managed by their original stops and the PositionGuard.
* Same-bar weight change + same-bar signal: the weight effective at the
  entry bar's open applies (the latest schedule entry with
  `effective_from ≤ bar open`; `searchsorted` right-then-minus-one).

## State model (Phase 8 of the integration mission)

Runtime state carried across rebalances and the DEV→OOS boundary: cash,
open positions (books/legs with original attribution), realized PnL,
equity, drawdown peak, daily-loss state, prior allocation (layer state),
timestamps.  Research knowledge that never crosses: future OOS
performance, future correlations, future regime labels, future drift,
future trade outcomes, feature/model selection, calibration fits.
Every decision journal entry carries its `as_of`.
