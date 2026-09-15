# AEGIS — State Model (python research engine)

Plan Phase 4 deliverable. Canonical for **what state exists** in the Python
research stack (`python/mql5bot/engine.py`, `optimizer.py`, `backtest.py`)
and **how it is allowed to move**. The MQL5 EA remains the live execution
and risk authority; its persistence lives in the EA's `StateStore.mqh` /
`MagicMap.mqh` — this document covers the research layer only (the engine
the Factory uses to produce decisions).

Companion documents: `docs/WFA_CONTRACT.md` (interval geometry and carry
rules across walk-forward windows), `docs/CV_STATE_CONTRACT.md` (what
may cross a CPCV/WFA boundary — normative for purged CV),
`docs/SPEC.md` (canonical WHAT),
`HANDOFF.md` (process/state of the project).

---

## 0. Ground rule

**Account/market state may carry across walk-forward OOS boundaries only
when the boundary policy allows it. Research/training knowledge never
crosses an OOS boundary.** A research artifact must be re-runnable from
`initial_capital` with no hidden carry; when carry is wanted it is always
explicit (one continuous engine run).

---

## 1. A. MARKET / ACCOUNT STATE (runtime, per run)

Produced and owned by `PortfolioEngine.run(instruments)`; every field lives
for exactly one `run()` call:

| State | Code location | Notes |
|---|---|---|
| cash (deposit currency) | local `cash` in `PortfolioEngine.run` | realized PnL and fees enter cash exactly once per trade row; rejected orders never mutate it |
| equity curve | `EngineResult.equity` (per bar) | cash + unrealized PnL of open books, valued at bar close; sub-tick PnL zeroed; tick-rounded fills |
| notional curve | `EngineResult.notional` | per-bar gross notional (caps/heat accounting) |
| open positions | list of `_Book` | one book per symbol in `netting` mode (≥1 `_Leg`); one book per independent position in `hedging` mode |
| position legs (attribution) | `_Book.legs: list[_Leg]` | each leg: strategy, lots, entry price/index, entry fee, swap share |
| entry price / SL / TP | `_Book.entry_price/sl/tp` | lots-weighted average entry; every book always has an SL |
| realized PnL | `EngineResult.trades["pnl"]` | net of that row's fees/costs; row-level `fees` and `costs` ledger columns decompose it |
| day-start equity | computed per server day | daily-loss limit is measured from the day's start equity using the `DayClock` server-local day ID |
| permanent DD peak | engine risk state | `max_drawdown_pct` kill switch is permanent within a run (never intra-run reset) |
| exposure / risk counters | `RunConfig` caps + runtime books | max total positions, per-symbol/currency/corr-group notional shares, portfolio heat |
| pending/reject events | `EngineResult.events` | rejects, gap skips, freeze-zone violations are recorded, never partially traded |

**Cash/equity invariants (tested):** realized PnL enters cash exactly once
(FIFO offset attribution on merged books); fees enter cash exactly once
(`fees` column = entry+exit commission shares + allocated swap; `costs` =
`fees` + tick-valued spread/slippage drag); equity reconciles as cash +
unrealized; rejected orders have zero accounting impact; there is exactly
one accounting engine (the canonical engine — `run_backtest` is a thin
wrapper that delegates, it contains no accounting).

---

## 2. B. STRATEGY STATE (runtime, per instrument)

| State | Code location | Notes |
|---|---|---|
| strategy identity | `Instrument.strategy` | stable name; registry `STRATEGIES` key; Magic derivation is EA-side |
| per-strategy attribution | `_Leg.strategy` | pro-rata shares survive netting merges, offsets, reversals |
| per-strategy risk overrides | `RunConfig.strategy_risk: dict[str, StrategyRisk]` | mode/value/max_lots/max_open_positions per strategy |
| run-wide signal params | `Instrument.params` | merge order: registry defaults < run-wide params < schedule segments |
| frozen per-segment params | `Instrument.schedule` | walk-forward param freeze (see WFA contract) |

Strategy-specific cooldowns/counters are **not implemented** in the python
engine today; if added they belong to this class and are reset per run.

---

## 3. C. RESEARCH / TRAINING STATE (never transferred)

| State | Code location | Notes |
|---|---|---|
| selected parameters | `walk_forward` per-window `best_params` + `param_hash` | chosen only from that window's train interval |
| IS metrics | per-window `is_metrics` | embargo/purge applied before scoring |
| strategy version | `STRATEGY_VERSIONS` (strategies.py) | declared; registry entries without a declaration report "undeclared" |
| dataset version | `dataset_version` | content digest of the frame unless the caller passes an explicit tag |
| feature-selection / scaler / calibration / ML fits | — | none exist in the research layer; the first ML phase must keep them inside the training window (plan Phase 14+) |

None of class C may influence a later OOS window. In the implementation
each training window recomputes its own selection on its own interval.

---

## 4. Lifecycle and restart semantics (python, documented)

- The engine is **stateless across runs by design**: every `run()` starts
  from `cfg.initial_capital` with empty books. Research results are
  reproducible from their recorded inputs (params, versions, digest).
- Within one run, daily-loss state and the DD peak reset **only** when the
  run restarts — they are not reset by anything else; day rollovers use
  the `DayClock` **server-local day ID** (configurable reset hour,
  DST-aware), never a raw UTC calendar substitute.
- Across *process* restarts the python research engine resets by design
  (it is not a live trading process). The EA, which is the live risk
  authority, persists daily-loss/DD-peak/attribution state through its
  `StateStore`; EA restart semantics are verified in the owner round-trip,
  not guessed here.

---

## 5. What is explicitly NOT state

- Execution costs (`CostConfig`, profiles) and broker specs (`SymbolSpec`)
  are **run parameters**, not state.
- The registry defaults (`STRATEGIES`) are code, not state.
- `EngineResult.equity/notional/trades/events` are **outputs** (ledger),
  never inputs of the same run.
