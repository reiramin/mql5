# AEGIS — Walk-Forward Contract

Plan Phase 6 deliverable. Defines the walk-forward analysis (WFA)
mathematically **as implemented** in `python/mql5bot/optimizer.py`
(`walk_forward`) on the continuous canonical engine, so that every
interval, freeze point, carry rule and aggregation is unambiguous and
testable.  Companion: `docs/STATE_MODEL.md` (which state carries and which
never does).

---

## 1. Vocabulary

| Term | Meaning |
|---|---|
| train (IS) interval | the bars a window is allowed to **fit/select** on |
| purge interval | trailing bars of the IS interval whose boundary-censored trades are dropped from selection metrics |
| embargo interval | bars immediately before an OOS start that selection never scores |
| warmup interval | initial bars run with registry defaults, excluded from OOS aggregates |
| test (OOS) interval | the bars a window is evaluated on |
| freeze point | the bar at which a window's selected params start governing entries |

---

## 2. Geometry (exact, implemented)

Inputs: `n` bars, `k = n_windows`, `f = train_fraction`,
`warmup_bars` (default 200), `embargo_bars` (default 0),
`purge_bars` (default 0).  Let `b0(w)`, `b1(w)` be window `w`'s OOS span:

```
L       = int((n - warmup_bars) / (k + f))          # segment length
is_len  = max(1, round(f * L))                      # IS bars per window
head    = warmup_bars + is_len                      # first OOS start b0(0)
b0(w)   = head + w * L
b1(w)   = head + (w + 1) * L,   b1(k-1) = n         # last absorbs remainder
```

Guards (raise `ValueError`): `L < 120`, `is_len < 60`,
`embargo_bars >= is_len - 59`, `embargo_bars + purge_bars >= is_len`,
`b0(0) < 1`, `b0(k-1) >= n`.

Per window `w`:

```
IS selection slice : df[b0(w) - is_len : b0(w) - embargo_bars]
  (embargoed)      : train_start = b0 - is_len, sel_end = b0 - embargo_bars
OOS test slice     : df[b0(w) : b1(w)]
warmup             : df[:head]  — registry-default params, never scored as OOS
```

`embargo_bars` bars `[b0 - embargo, b0)` exist in the released data but are
not scored by selection (their trades would be force-closed at an isolated
run's boundary).  With `purge_bars > 0`, selection metrics additionally
drop trades of the embargoed IS run that exit within the last
`purge_bars` bars (`exit_time >= index[sel_end - purge_bars]`) and truncate
the equity tail carrying them (`is_trades_purged` reports the count).

---

## 3. Optimization and freeze timing

1. On window `w`, run `grid_search` **only** on the embargoed IS slice
   (every candidate backtest starts from `initial_capital` inside the
   selection slice — selection is isolated by construction).
2. Pick the best candidate by the configured `metric`.
3. Freeze it: the engine schedule gets `(b0(w) - 1, best_params)` — the
   frozen params govern **entries from the OOS bar's open** onward.
4. Bars before the first schedule entry keep the base (registry-default)
   signal — that is the warmup run.

The schedule is applied to ONE continuous engine run over the full sample,
so params switch at freeze points without restarting the account.

## 4. State carry and position boundary policy

**Default: `CARRY_ALLOWED`.** The continuous run carries cash, realized
PnL, equity, open books (positions and their attribution legs), drawdown
peak, daily-loss state, cost state and timestamps across every `b0(w)`
boundary.  Nothing is force-closed at a boundary.

- A position crossing from window `N` into `N+1` stays open; its entry is
  never re-priced or re-labelled by the new window's params.
- Its exit obeys the frozen policy under which it is managed: signals are
  frozen per segment from `b0 - 1`, and run-wide management (SL/TP,
  trailing/breakeven/partial/max-bars, daily-loss/DD limits) is uniform
  `RunConfig` policy.  A later window's selected params influence only NEW
  decisions.
- `FORCE_FLAT` (forced flattening at boundaries) is **not implemented and
  never silently enabled**; if the project adopts it, it must be an
  explicit alternative mode with its own tests.

**Knowledge never carries:** `best_params`, IS metrics, feature-selection
decisions and any future ML fit are recomputed inside each training window
on that window's interval only.  Recorded per window for auditability:
`param_hash` (sha-1 of the selected params), `strategy_version`
(declared; "undeclared" for ad-hoc entries) and `dataset_version`
(content digest, or an explicit caller tag).

## 5. Feature warmup without leakage

All research features are causal-by-construction (prefix-immune): a frame
truncated at bar `p` or mutated after bar `p` leaves every feature/signal
value before `p` unchanged (pinned by `tests/test_leakage_features.py` for
EMA/SMA/rolling std/RSI/ATR/Bollinger/Donchian/MACD/highest/lowest/
crossover, every registered strategy, and per-span regime features).
Consequently a training window's indicator warmup never consumes test data
— the features it sees are computed only from its own released prefix.

## 6. Metric aggregation (continuous ledger, not concatenation)

- **Aggregate OOS metrics** are computed on the continuous equity slice
  `eq[head:]` with every trade whose ENTRY bar is `>= head` — one ledger,
  no independently restarted curves.
- **Per-window OOS metrics** are computed on the continuous slice
  `eq[b0 : b1]` with trades attributed to the window of their entry bar
  (`b0 <= entry < b1`), plus per-window `cost` (sum of the `costs` ledger
  column), `oos_max_drawdown_pct`, `wfe` (OOS total return / IS total
  return when IS > 0, else `None`) and a deterministic price-regime
  breakdown of the span.
- **Trade boundary rule**: a trade entered in window `w` but exited in
  `w+1` (carried position) is attributed to `w` (entry-bar attribution);
  its full PnL/cost belongs to `w`'s slice.  OOS trade counts therefore
  sum exactly to the aggregate ledger count (`oos_metrics["trades"]`).

## 7. Reproducibility

Identical inputs (frame, strategy + declared version, grid, config,
seeds) produce identical outputs — the walk is deterministic, grid search
is ordered, hashes and digests are stable (pinned by tests).  Report rows
carry `strategy`, `strategy_version`, `dataset_version`, geometry
(`bars`, `warmup_bars`, `is_bars`, `segment_bars`, `head_bars`,
`embargo_bars`, `purge_bars`, OOS span) and the per-window records above.

## 8. Out of scope today (later phases)

Explicit warmup-bars-as-configurable-isolation policy tuning, CPCV and
other robustness schemes (plan Phase 11), portfolio/meta-layer combination
of walk-forwards (Phases 12–13), and formal research-version metadata
bumping policy (Phase 17).  The per-window hash/version fields above are
the seed those phases build on.
