# TASKS

## CURRENT BACKLOG — ordered, blockers named (2026-09-20)

The first full owner certification gate ran on 2026-09-20 and stopped at
stage 5 (`GATE_RESULT=tester_legs`). See
[docs/OWNER_DELIVERY.md](docs/OWNER_DELIVERY.md) for the account of record.
The real remaining work, in the order it must happen before any real money:

1. **[ ] OWNER: rebuild the gold #1 fixture with enough H1 history.**
   Blocker measured on the 2026-09-20 run: the 120-bar H1 fixture is too
   short — MT5 reserves preceding history for warm-up and logged
   "start time changed … to provide data at beginning" / "0 ticks, 0 bars
   generated". Until the fixture is long enough, three of the six stage-5
   legs cannot run.
2. **[ ] OWNER: get MT5 to write the `[Tester]` Report file.** Blocker:
   build 6184 wrote none, so the two gold #2 legs that ran to completion
   are BLOCKED_OWNER_ENVIRONMENT — a BLOCKED leg is **not** a pass, and
   there are no parsed backtest metrics anywhere. Needs a build/config
   that emits the report, or an alternate parse source.
3. **[ ] OWNER: run stage 5 to a real PASS**, including one leg with
   `InpDslBundleFile` pointing at a generated bundle — otherwise the
   tester only ever proves the compiled-in default strategy. The DSL
   bundle path has never been exercised in MT5.
4. **[ ] OWNER: run stage 8 reconciliation** (Python↔MQL5 executed trades,
   field by field). This is the binding parity claim of the whole
   architecture and has NEVER run; nothing is certified without it.
5. **[ ] OWNER: BTC denomination verdict** — `BTC:sizer.behaviour` and
   `BTC:tick_value_denomination` are still PENDING (excluded from stage 3).
   Do not size BTC trades until it exists.
6. **[ ] OWNER: let stages 9–10 (archive, certify) complete** — only a run
   ending `GATE_RESULT=certified` puts VERIFIED on anything.
7. **[ ] OWNER: ≥4 weeks demo, ≥30 trades** before any conclusion.
8. **[ ] OWNER: VPS deployment + uptime/recovery drill** (see
   `docs/DEPLOYMENT.md`) before connecting a real account. Never done.

The operator-experience layer (Telegram alerts + commands, Persian/RTL
console, guided strategy conversation) is **built and unit-tested but has
never run against a live system** — see `docs/ROADMAP_UX.md`.

---

> **STATUS BANNER — READ FIRST (2026-09-16).**
> **The section below is an ARCHIVAL checklist, NOT the current backlog.** It is the
> Phase 2.5 "Research Foundation Correction" plan from an earlier session
> (branch `arena/01a06cdc-mql5bot`). Its checkbox states are **frozen as
> written** and are deliberately **not** updated — a `[ ]` here does **not**
> mean open work.
>
> - **Phases 0–14 (research foundation) are CODE-COMPLETE.** The modules and
>   behaviours they describe are implemented and tested in the current tree
>   (`python/mql5bot/{specs,costs,dayclock,engine,optimizer,robustness,
>   metrics,ml_interfaces}.py`, etc.; 1593 passing tests). Do **not** treat
>   these unchecked boxes as a backlog.
> - **The ONLY genuinely-open items are the OWNER-PENDING "Reality Gate"
>   boxes at the bottom** (`[ ] OWNER: …`) — the Windows Owner Certification
>   Campaign. These are RUNTIME-PENDING, never simulated on Mac.
> - **Authoritative current status lives elsewhere:** `PROGRESS.md`
>   (CURRENT STATE block), `docs/DECISIONS.md` (newest on top), `HANDOFF.md`,
>   and the Windows handoff `docs/WINDOWS_OWNER_HANDOFF.md`.
>
> History below is preserved verbatim for provenance. Do not rewrite it.

---

# TASKS — AEGIS Phase 2.5 / Research Foundation Correction (HISTORICAL / ARCHIVAL)

Canonicalise the research/backtest engine BEFORE any ML / CPCV / Optuna /
portfolio-logic work. No NN/Transformer/LSTM/RL. No new trading strategies.
Branch `arena/01a06cdc-mql5bot`. After Phase 14 acceptance the earlier
AEGIS research-upgrade backlog (TASKS history) resumes.

## Phase 0 — Verify (done 2026-09-04)
- [x] git status clean; git log reviewed (5 hardening commits + tooling); remote == `1fc0289…`
- [x] pytest 143 passed; ruff clean on all new files (legacy findings untouched)
- [x] Read current backtest.py / sizer.py / symbolspec.py / optimizer.py /
      metrics.py / data.py / strategies.py — direct risk/(stop*contract)
      formula confirmed in `backtest.open_trade`; single-`pos` engine;
      calendar-date daily reset; concatenating WFA.

## Phase 1 — Canonical risk model
- [ ] shared cross-asset SymbolSpec fixtures module usable by Sizer /
      Backtester / risk tests (EURUSD, GBPUSD, USDJPY, XAUUSD, index CFD,
      crypto CFD) — python/mql5bot/specs.py + tests
- [ ] canonical engine sizes ONLY through sizer.size_position(spec,…)
      (tick value profit/loss, profit->deposit conversion, contract size,
      volume min/max/step/limit, stops/freeze, margin where injected)
- [ ] legacy direct formula removed from every canonical code path
- [ ] Python formula equivalence notes vs MQL5 SSymbolSpec/CRiskManager

## Phase 2 — Execution cost model
- [ ] explicit configurable costs: bid/ask spread, variable spread,
      slippage, commission, swap, gap, rejected execution (optional),
      stop/TP fills, pending-order behaviour — python/mql5bot/costs.py
- [ ] costs visible in trade log + equity; never hidden inside formulas
- [ ] tests incl. variable spread series and deterministic rejection

## Phase 3 — Daily loss / server time
- [ ] server-time day resets with configurable reset hour + DST-aware
      handling — python/mql5bot/dayclock.py
- [ ] daily loss measured from day-start equity (EA semantics)
- [ ] tests: midnight, non-midnight reset, weekend, DST transition

## Phase 4 — Multi-position backtester
- [ ] canonical portfolio engine (python/mql5bot/engine.py) replacing the
      single-`pos` core: multi-symbol, multi-strategy, simultaneous
      positions, per-strategy risk, max concurrent positions, per-symbol
      exposure, currency exposure, portfolio heat, correlation-group caps
- [ ] engine uses sizer + costs + dayclock; closed-bar signals; scheduled
      parameter switches (WFA enabler)
- [ ] backtest.py legacy run_backtest re-implemented as a thin canonical
      single-symbol wrapper (existing consumers/tests kept green; any test
      that pinned the old overshoot behaviour updated deliberately)
- [ ] Meta Layer explicitly NOT built

## Phase 5 — Netting / hedging simulation
- [ ] NETTING: one book position per symbol (merge same side; offset on
      opposite side), attribution by strategy
- [ ] HEDGING: multiple positions per symbol
- [ ] tests: BUY+BUY, BUY+SELL, partial close, full close, reverse, same
      symbol different strategies

## Phase 6 — Correct walk-forward
- [ ] continuous WFA: scheduled-parameter engine run over the full sample;
      capital/portfolio/costs/risk state carried forward; params frozen
      per OOS segment; per-window output: IS dates, OOS dates, selected
      params, IS metrics, OOS metrics, WFE, trade count, drawdown, cost,
      regime breakdown; aggregate OOS equity is the continuous run
- [ ] replace concatenating walk_forward internals (API kept)

## Phase 7 — WFA overlap / leakage control
- [ ] purge gap, embargo, lookback warm-up isolation
- [ ] automated leakage tests (never train on OOS-adjacent info)

## Phase 8 — Metrics upgrade
- [ ] keep CAGR/Sharpe/Sortino/Calmar/maxDD/PF/expectancy/win rate
- [ ] add recovery factor, ulcer index, downside deviation, avg/median
      trade, trade duration, exposure, turnover, max consecutive losses,
      return concentration, top-N trade contribution, monthly
      consistency, rolling Sharpe/expectancy stats, tail loss stats
- [ ] no single metric drives selection

## Phase 9 — Robust fitness
- [ ] grid_search API kept (sorts by one metric)
- [ ] research-grade composite score with explicit coefficients:
      OOS expectancy + risk-adjusted return + stability + cost resilience
      − drawdown − concentration − turnover − instability
- [ ] never optimise OOS repeatedly (documented budget)

## Phase 10 — Fast research architecture (only after 1–9)
- [ ] FAST engine (vectorised, cached, parallel) + TRUTH (real MT5 tester);
      FAST results never final certification

## Phase 11 — Optimization strategy (after 1–9)
- [ ] staged: cheap screen → robustness → CPCV → MT5 validation → OOS
      certification; Optuna only after deterministic correctness; early
      rejection, pruning, cache, warm-start, parallel, deterministic seeds

## Phase 12 — Research references (architecture only)
- [ ] read MegaJoctan/StrategyTester5, ranjeet867/Metatrader,
      Boschi404/mt5-mcp-server, lucasmos/GoldRegime_X,
      hudson-and-thames/mlfinlab, EarnForex/PositionSizer (no wholesale
      copying; note ideas in DECISIONS.md)

## Phase 13 — ML preparation only
- [ ] interfaces only: triple-barrier labels, meta-labeling, probability
      calibration, feature store; no live ML training; ML never removes
      SL / overrides Risk Engine / creates uncontrolled trades / raises
      hard risk limits

## Phase 14 — Acceptance (report ✅/❌ with evidence)
- [ ] backtester uses canonical Sizer; no direct contract-size risk
      formula in canonical path
- [ ] multi-position simulation works; netting works; hedging works
- [ ] daily reset server-time based; WFA continuous; leakage tests pass
- [ ] cost stress works; metrics expanded; robust scoring available
- [ ] all existing tests pass (updates only where a test pinned the
      removed over-risk behaviour — documented)
- [ ] MetaEditor compile stays VERIFIED / NOT VERIFIED (never guessed)
- [ ] final report: commit, files changed/added, tests, ruff, backtest
      benchmark, WFA benchmark, known limitations, safety gaps, next 3

---
## Final convergence closure (2026-09-06 branch state)

Done: audit doc, legacy classification, campaign manifest/lineage,
concentration/correlation APIs, entry chain + authority proofs,
approval hardening (evidence hash, policy version, human-role check),
UI research page + one-click intake, §75–§82 acceptance suites,
property suite, static scans, CI hardening, docs refresh.

Open (owner environment): MT5 compile, Strategy Tester scenario,
Python↔MT5 reconciliation, real multi-asset data basket, watchdog
external deployment harness.  These are BLOCKED_OWNER_ENVIRONMENT and
deliberately NOT simulated.

## Reality Gate (mission 6)
- [x] Gold Standard manifest + frozen identity (artifacts/gold)
- [x] Deterministic fixture (20-scenario map) + both-touch micro
- [x] Python reference trace + DSL trace, exact agreement
- [x] Indicator parity (EMA/ATR) vs MT5 transcription, WARMUP classified
- [x] Sizing parity (sizer vs GetLots), Meta seam, kill-switch seam
- [x] Allocation round-trip + staleness/tamper
- [x] Reconciliation artifacts with explicit PENDING_OWNER MT5 fields
- [x] Owner MT5 protocol (deterministic 9 steps)
- [ ] OWNER: compile gate (tools/compile.ps1 -Strict)
- [ ] OWNER: symbol-spec export + broker parity
- [ ] OWNER: Strategy Tester gold legs (M1-OHLC + Every tick)
- [ ] OWNER: golden-run reconciliation vs artifacts/gold
- [ ] OWNER: kill-switch + restart runtime proofs
- [ ] OWNER: ≥4-week demo (MT5_ROUNDTRIP SHADOW table)
