# META REALISM AUDIT — pre-ML production gate (Phase 1)

Trace of `python/mql5bot/meta_portfolio.py` (commit `61d55ab`) along
data → signals → as-of statistics → Meta factors → weights → schedule →
portfolio → sizing → costs → fills → PnL → attribution → next rebalance,
with the honest simplification register. Nothing here is assumed to be
production-equivalent; each item states the disposition in this mission.

## Simplification register

| # | Surface | State at audit | Disposition |
|---|---|---|---|
| 1 | **Symbol identity** | ONE shared frame, symbol `"GEN"`, all specs trade the same series | REMOVED this mission: `InstrumentContext` per (symbol, strategy), per-symbol data; engine duplicate-line rule documented |
| 2 | **Broker specification** | One synthetic `SymbolSpec` built inside the engine (point/contract from instrument dict); stats runs via `run_backtest` legacy kwargs | REMOVED: context carries an explicit `SymbolSpec` + `CostConfig` per symbol; the SAME spec object feeds the portfolio run; no generic fallback on the production path (legacy synthetic path retained, explicitly labelled diagnostic) |
| 3 | **Regime** | Hard-coded `"TREND_UP"` with allowed=preferred={TREND_UP} — a research stub | REMOVED: causal `regime_feed` (7 labels, as-of, versioned `regime_version`/`regime_as_of` in every journal) |
| 4 | **Drift** | `drift_score=0.0, drift_available=True` — "no drift, always" | REMOVED: `DriftSnapshot` per strategy computed as-of from trade ledgers (expectancy/PF/winrate/execution/regime components; HEALTHY/MILD/SEVERE/UNKNOWN; UNKNOWN ⇒ layer's conservative MISSING fallback) |
| 5 | **Correlation** | As-of and simultaneous, but ids were bare strategy names on one symbol | EXTENDED: ids are strategy×symbol book ids — same-strategy cross-asset, cross-strategy same-asset and cross-strategy cross-asset pairs all penalize; conventions documented (Phase 12) |
| 6 | **Execution** | Bar-open fills, spread/slippage/commission/swap/gap-reject via `CostConfig`; no latency/partial fills (Python) | UNCHANGED by design: live-path execution is the MQL5 audited path (MT5_EXECUTION_AUDIT); documented, not simulated |
| 7 | **Margin** | `Instrument.margin_calc` hook; sizer down-scales/rejects vs equity basis; engine models free margin ≈ equity (not broker margin accounting) | PINNED this mission: shared-account margin interaction test (first trade consumes margin ⇒ later entries reduced/rejected); simplification documented |
| 8 | **Currency conversion** | `profit_to_deposit=1.0` for everything (single USD-quoted symbol) | REMOVED: explicit per-context conversion; equal currencies ⇒ identity 1.0 justified; differing currencies WITHOUT an explicit conversion ⇒ context INELIGIBLE (safe failure, journaled) — never a fake 1.0 |
| 9 | **Portfolio heat** | `portfolio_heat_max`/per-symbol/currency/corr-group notional shares exist in `RunConfig` but were untested across symbols | PINNED: cross-symbol heat test (two USD-correlated symbols share a corr group; cap binds across symbols, not per symbol) |
| 10 | **Certification surface** | All inputs VERIFIED | EXTENDED: `certified` set keyed on book id; UNCERTIFIED ⇒ hard zero in the portfolio (pinned) |

## Non-simplifications (verified real)

* ONE shared account per policy: cash, equity, drawdown, daily-loss
  state, position caps and heat are portfolio-level in
  `engine.PortfolioEngine` (books/legs with per-strategy attribution).
* Weights are causal (`as_of_stats_exclusive`, bars strictly before the
  decision bar's open) and apply to NEW entries only.
* EW control runs the identical mechanics — only the policy differs.
* The equity-blend path (`meta_replay`) is diagnostic only.

## MQL5 seam cross-reference (Phase 28 trace)

Live path: strategy signal → allocation consumer (`Allocation.mqh`,
digest-verified, unknown-id⇒0 under FRESH) → `RiskManager.GetLots`
(stop-distance sizing, min-stop, margin via `OrderCalcMargin`, floor to
grid) → Meta `ScaleLots` (reduce-only multiply) → floor-and-drop to
broker step (below-min ⇒ NO TRADE) → `TradeManager` (single attempts,
RetryQueue, SlGuard).  The Meta layer sits strictly after the Risk
Engine and before execution and can only shrink; it has no order, SL,
TP, kill-switch, daily-loss, drawdown or margin API (structurally
pinned by `test_meta_risk_invariants.py` + `test_mql5_sources.py`).

## Feed versions (pinned by tests/test_doc_consistency.py)

- causal regime feed: `regime_feed.REGIME_VERSION = "asof-1.1"`
- causal drift feed: `drift_feed.DRIFT_VERSION = "asof-1.0"`
- drift ladder: `DRIFT_MILD=0.10`, `DRIFT_BLOCK=0.50`,
  `DRIFT_MISSING=0.5` (never 1.0, never neutral)
- correlation minimum observations: `CORR_MIN_OBS = 30`

## Multi-asset determinism findings (Phase 24 metamorphic round)

- **Book-id sort order is run identity.** The engine canonicalizes the
  context list to `sorted(strategy_id)`; that order arbitrates
  shared-account budget consumption across lines (who is evaluated
  first when heat/margin/caps bind).  Reordering the input list is
  normalized away (pinned by `test_input_order_normalized_to_sorted_book_ids`),
  but a book RENAME that changes the sorted order is a NEW run —
  trades can differ when caps bind (pinned 837 vs 834 trades in the
  discovery run).  Renames must therefore bump the run manifest.
- **Restart equivalence holds exactly**: a `MetaLayer` restarted from
  the runtime state (final weights + zero reasons + activation) after
  decision *k* reproduces the decision suffix bit-for-bit
  (`test_restart_at_rebalance_reproduces_suffix`).
- **Unrelated-symbol independence is causal-input-level**: removing a
  symbol leaves the remaining books' stats/regime/drift inputs
  identical; weights may still move through the correlation matrix —
  that coupling is the documented cross-book mechanism, not leakage
  (`test_unrelated_symbol_does_not_change_book_inputs`).

## Failure matrix — multi-asset injections (Phase 25)

| # | Injection | Behavior | Test |
|---|-----------|----------|------|
| F1 | NaN bar in a book frame | context REFUSED (journaled INELIGIBLE, `non-finite OHLC`); remaining books run; NaN never reaches the tick math (`round(NaN)` crash verified pre-gate) | `test_f1_nan_bar_frame_is_refused_not_crashed` |
| F1b | missing OHLC column | refused at context construction (`missing OHLC columns`) | `test_f1b_missing_ohlc_column_is_refused` |
| F2 | flat-line frame (zero vol) | no valid stop ⇒ that book never trades; other books unaffected (documented baseline) | `test_f2_flat_frame_trades_nothing_baseline_stands` |
| F3 | broker margin always refused | SAFE HOLD: zero entries, equity flat at initial capital, sizing seam exercised | `test_f3_margin_always_refused_is_safe_hold` |
| F4 | profit-currency conversion missing | journaled INELIGIBLE (never fake 1.0); run continues on remaining books | `test_f4_missing_conversion_is_journaled_ineligible` |
| F5 | regime feed starved (< VOL_WINDOW+2 bars) | label UNKNOWN; decisions still produced | `test_f5_regime_starved_symbol_is_unknown_not_fatal` |
| F6 | all decision sources missing at t | GLOBAL source failure ⇒ equal-weight fallback over eligible books (documented safe baseline, never full-risk concentration) | `test_f6_no_trade_books_yield_equal_weight_fallback` |
| F7 | empty drift ledger | feed UNKNOWN (score 0.0); layer applies DRIFT_MISSING=0.5 ladder value; weights produced | `test_f7_empty_drift_ledger_is_missing_fallback_baseline` |

## Red team round 2 (Phase 31) — multi-asset surface

| # | Severity | Finding | Disposition |
|---|----------|---------|-------------|
| R1 | — | same-currency book with a bogus `conversion=5.0` | already safe: identity wins, `profit_to_deposit==1.0`; pinned `test_r1_same_currency_bogus_conversion_is_ignored` |
| R2 | MEDIUM | duplicate `(symbol, engine_strategy)` books surfaced as a raw engine ValueError late in the run | FIXED: construction-time pre-validation naming the offending lines; pinned `test_r2_duplicate_execution_line_named_at_construction` |
| R3 | LOW (latent) | `drift_snapshots` received symbol-keyed labels but looks up by strategy_id ⇒ current regime always missing | FIXED: the engine passes per-book labels; pinned `test_r3_drift_receives_per_book_regime_labels` (no numeric change today — the regime component is conservative 0.0 until regime-history wiring, Phase 21+ decision recorded in REGIME_MATRIX) |
| R4 | LOW | pathological `conversion=1e-9` (explicit input) inflates raw lot math | bounded: max_lots/volume_max caps hold; pinned `test_r4_absurd_conversion_sizing_stays_capped` |
| R5 | INFO | `_realized_corr` with no closed books | NaN (honest "not measurable" per conventions, never fake 0.0); pinned `test_r5_realized_corr_honest_nan_without_books` |
