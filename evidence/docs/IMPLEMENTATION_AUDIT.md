# Aegis — Implementation Audit (evidence-based)

Audited against `docs/SPEC.md` (v4, consolidated, sections 0–18) on branch
`arena/01a06cdc-mql5bot` at commit `817d20d441317872e8b1222f7c4eccce5bf5646b`
("Update merging instructions in HANDOFF.md"). Baseline verified in this
environment: `pytest tests/` → **39 passed** (Python 3.11, clean venv).

Reading order used: SPEC.md (complete) → HANDOFF.md → README.md →
CHANGELOG.md → all MQL5 sources → all Python sources → all tests → CI config.

> Note: the repo's SPEC.md has sections 0–18 only. HANDOFF.md §4.17 refers to
> a "SPEC §19" (external reference repositories / charting licensing). That
> section is not present in the committed SPEC; the policy text lives in
> HANDOFF.md §4.17 and in the work-session brief. Flagged for reconciliation.
> Also, HANDOFF.md §6/§9 still claims `docs/SPEC.md`, `TASKS.md`, `PROGRESS.md`
> and all code are *missing* — that state description is stale: SPEC.md and the
> whole Mql5Bot codebase are committed on `main`. Repo state wins.

---

## 1. Current architecture

Two-layer, single-repo **pre-Aegis foundation** named "Mql5Bot" (v1.0.0):

| Layer | Location | Role |
|---|---|---|
| EA (MQL5) | `mql5/Experts/Mql5Bot/Mql5Bot.mq5` + `mql5/Include/Mql5Bot/*.mqh` (8 headers) | Single-chart EA: 1 active strategy at a time, one position at a time |
| Toolkit (Python) | `python/mql5bot/*.py` (11 modules) | Vectorised strategy twins, event-driven backtester, metrics, optimiser, reports, dashboard, telemetry bridge, CSV/synthetic data |
| Deploy tool | `scripts/install_mql5.py` | Copies EA/include/presets into an MT5 data folder |
| CI | `.github/workflows/ci.yml` | pytest on Python 3.10–3.12 + CLI smoke |

MQL5 runtime flow (single file `Mql5Bot.mq5`): `OnInit` builds globals →
`OnTick` detects chart-symbol new bar (`iTime` compare, line 415–428) →
`OnNewBar()` → daily rollover / `CRiskManager.CheckLimits` →
`CPositionGuard.Review` exits → session filter → `CSignalEngine.Evaluate`
(one of 5, chosen by enum input `InpStrategy`, index 0–4) → size via
`CRiskManager.GetLots` → `CTradeManager.SendMarket`/`SendPending` →
`OnTradeTransaction` logs deals of the single input magic.

Architecture vs SPEC §6 canonical layout: **entirely different tree** (`ea/`,
`factory/`, `schemas/`, `examples/`, `research/`, per-module `Aegis/` include
folders are absent). SPEC §8.A engine/state/scheduler/recovery classes,
§8.C–8.H subsystem families, DSL (§9), Factory (§10), regime/meta (§12) do
not exist as such. This audit therefore treats the committed Mql5Bot stack as
**Release-A seed material** and grades SPEC Release-A behaviour on the actual
code paths above.

## 2. Existing implemented features (with evidence)

### MQL5
- **Risk sizing** (risk-% of equity over stop distance): `RiskManager.mqh:95-118` — `lossPerLot = stopDist/tickSize * SYMBOL_TRADE_TICK_VALUE`, volume normalised to `SYMBOL_VOLUME_STEP/MIN/MAX`, `NormalizeLots` clamp `Config.mqh:40-54`.
- **Daily loss limit + drawdown kill switch + spread guard**: `RiskManager.mqh:56-94` (`CheckLimits`), `:119-127` (`IsSpreadOK`); wired in `Mql5Bot.mq5:277-302` (limit breach closes bot positions and pauses/returns).
- **Market + pending-stop execution with bounded retries**: `TradeManager.mqh` (`SendMarket` 139–179, `SendPending` 186–254, `ClosePosition` 311–349, `ModifySLTP` 353–380); FOK→IOC fallback `:97-110`; retryable-code classification `Config.mqh:58-74`; verify-before-resend on TIMEOUT/RETRY via `FindRecentDeal` `TradeManager.mqh:71-95`.
- **Trade management on closed bars**: ATR trailing, breakeven, partial scale-out (`PositionGuard.mqh` `Review` 113–174; applied `Mql5Bot.mq5:306-335`), max-bars timeout `Mql5Bot.mq5:337-345`.
- **5 compiled strategies** on completed bars only (shift ≥ 1): `SignalEngine.mqh` (EMA 151–165, RSI 168–195, Donchian 198–222, Bollinger 225–241, MACD 244–259); presets in `mql5/Presets/Mql5Bot/*.set` (5).
- **Session/time filter**: `Session.mqh` (day-of-week bitmask + intraday window incl. overnight `:33-40`).
- **Leveled file+terminal logger**: `Logger.mqh`.
- **HTTP telemetry** (heartbeat/trade/alert via `WebRequest`): `Telemetry.mqh`.
- **Deal logging**: `Mql5Bot.mq5:437-467` (magic-filtered `DEAL_ADD`).
- **MT5 data export script**: `mql5/Scripts/Mql5Bot/Mql5BotDownloadData.mq5`.

### Python
- **Indicator library** aligned with MQL5 semantics (EMA seed = SMA of first period, Wilder RSI/ATR): `python/mql5bot/indicators.py`.
- **5 vectorised strategy twins** on closed bars: `python/mql5bot/strategies.py`.
- **Event-driven backtester**: entries at next open after signal bar (no-lookahead by construction, `backtest.py:214-223`), intrabar SL/TP with conservative stop-first rule, half-spread + slippage + round-trip commission, risk-based sizing, trailing/breakeven/partial, daily-loss halt, DD kill switch: `python/mql5bot/backtest.py`.
- **Metrics**: `python/mql5bot/metrics.py`.
- **Grid search + walk-forward** (OOS windows kept out of training): `python/mql5bot/optimizer.py`.
- **HTML reports + dashboard + telemetry bridge + CLI**: `report.py`, `dashboard.py`, `telemetry_bridge.py`, `cli.py`.
- **Data**: CSV (comma/semicolon, MT5-export compatible), deterministic regime-switching synthetic OHLC, optional live MT5 bridge: `data.py`.

### Tests
- 39 pytest tests across `tests/` (see §3). Green baseline measured.

## 3. Existing tests

| File | Tests | Covers |
|---|---|---|
| `tests/test_backtest.py` | 12 | engine sanity; **hard no-lookahead oracle** (`test_no_lookahead_on_perfect_signal`); exact commission accounting; risk scaling; daily-loss halt; DD kill switch; no-short; partial close; trade-log consistency; metrics; validation errors |
| `tests/test_data.py` | 8 | OHLC consistency, reproducibility, timeframes, CSV round-trip/semicolon, validation, split |
| `tests/test_indicators.py` | 9 | SMA/EMA seeding, RSI bounds/Wilder, ATR, Bollinger symmetry, Donchian current-bar exclusion, MACD identity, crossover |
| `tests/test_strategies_optimizer.py` | 7 | signals for all 5 strategies, defaults, grid ranking/minimize, walk-forward OOS, docs |
| `tests/test_install.py` | 3 | installer into fake MT5 data folder, idempotency, error path |
| `tests/test_slguard.py` | 13 | SL-verdict matrix on the five synthetic broker specs (present/wrong-side/stops-level, half-tick tolerance) + pump-threshold invariants |
| `tests/test_failsafe.py` | 16 | state-machine transitions (rollover/reset/trip never softens halt), `AEGIS_STATE v1` row codec round-trip, quarantine + malformed-row semantics |
| `tests/test_retryqueue.py` | 11 | backoff schedule (500 ms × 2^n capped 10 s), dedupe without attempt-cap reset, earliest-due pop, 32-slot bound |

Verified: `39 passed in 1.50s` (clean venv, `pip install -e ".[dev]"`).
Update (Phase-1 batch, this branch): suite is now **120 passed** — the
three new mirror test files above extend the 80-test baseline.
Doc drift: CHANGELOG.md says "36-test suite"; README says 39 (actual: 120).
MQL5: **no unit-test harness exists** (`RunUnitTests`, `TestFramework.mqh`
absent); no compile verification possible in this sandbox (no MetaEditor).

## 4. Current release readiness

SPEC §2 releases A–E; nothing is tagged. Grade per release (evidence-based):

| Release | Grade | Reason |
|---|---|---|
| A `ea-core` | **≈25–30 %** | Working single-symbol EA + risk basics exist, but most DoD items and §3 principles are unmet (see §5/§8). No persistence/recovery, no per-strategy identity, no injectable symbol spec, Sleep in handlers, no OnTimer/command path, no dashboard, no OnTester, no restart-safe limits. |
| B `dsl` | 0 % | No schema, no `DslStrategy`, no bundle, no parity. |
| C `factory-core` | 0 % | No factory app, gates, Kanban, allocation. |
| D `regime-meta` | 0 % | No regime engine, meta-layer, cost model, drift/SPC, data audit. |
| E `nocode` | 0 % | No conversational intake, Telegram, i18n, visual verification. |

Note the naming clash: CHANGELOG/`Mql5Bot.mq5`/`Config.mqh` label this
codebase "1.0.0" while SPEC reserves `v1.0.0` for the end of Release E
(SPEC §5.6, §16). Version claim refers to the Mql5Bot seed, not Aegis.

## 5. Missing SPEC requirements (release-grouped, key items)

### Release A gaps (most are §3 principles + §8 subsystems)
1. **Stable identity / magic map** (§3.9): magic is one user input shared by all strategies (`Mql5Bot.mq5:73` `InpMagic=20240904`; passed to `CTradeManager` `:230`); strategy selected by enum index (`InpStrategy`, `Config.mqh:22-34`); no FNV-1a derivation, no registry, no persistence, no per-strategy isolation.
2. **SSymbolSpec injection** (§3.10): risk math calls live `SymbolInfoDouble(_Symbol, …)` directly (`RiskManager.mqh:99-114`) → not unit-testable with synthetic specs; same pattern throughout `TradeManager.mqh`, `SignalEngine.mqh`.
3. **SL enforcement guarantee** (§3.2): after a successful open there is **no verification that the position actually carries an SL** and **no remediation path** (modify → close + CRITICAL + alert). If the broker accepts the deal without SL, the bot trades unprotected.
4. **No Sleep in event handlers** (§3.4): 4 `Sleep()` call sites inside retry loops invoked synchronously from `OnNewBar` ← `OnTick` (`TradeManager.mqh:174,247,345,380`). No `RetryQueue`/OnTimer backoff design (§8.A).
5. **Persistence & restart recovery** (§3.8/§8.A): nothing persisted (no GlobalVariables, no files). Consequences: day-start equity reset on re-init (`Mql5Bot.mq5:243`, `RiskManager.mqh:44-52`), kill switch **cleared** on every restart (`ResetDayAndPeak` sets `m_killSwitch=false`), daily-loss/drawdown limits bypassable by EA restart; no ticket map, no adoption of orphaned positions, no management-state rebuild (breakeven/trailing/partial).
6. **Broker specification coverage** (§3.3): no query/validation of `ACCOUNT_TRADE_ALLOWED/EXPERT`, `TERMINAL_TRADE_ALLOWED`, `SYMBOL_TRADE_MODE/EXEMODE`, `SYMBOL_ORDER_MODE`, `SYMBOL_EXPIRATION_MODE`, `SYMBOL_TRADE_FREEZE_LEVEL`, `SYMBOL_VOLUME_LIMIT`, `SYMBOL_TRADE_TICK_VALUE_PROFIT/LOSS`, contract size, margin currency; no runtime environment validation on `OnInit`.
7. **Margin checking** (§8.C): no `OrderCalcMargin` reduce/reject step in sizing.
8. **Limits suite** (§8.C): only daily-loss %, DD % and spread guard exist. Missing: weekly loss, consecutive-loss cooldown, max positions (total/strategy/symbol), min margin level, risk-per-trade money cap, portfolio heat, currency exposure, correlation, DD scaler (§11, Release D mostly).
9. **Sizing modes** (§8.C): only RiskPercentOfEquity. Missing FixedLot, RiskPercentOfBalance, FixedMoney, capped Kelly; no profit-currency conversion handling; rounding via `MathRound(lots/step)` (`Config.mqh:46`) can exceed intended risk — needs floor-to-step; no VOLUME_LIMIT.
10. **Filling resolver** (§8.D): hardcoded FOK→IOC (`TradeManager.mqh:97-110`); no symbol-mask-driven resolution, no `ORDER_TYPE_*`-vs-`SYMBOL_ORDER_MODE` validation for pendings, expiration always GTC (`:211`) regardless of `SYMBOL_EXPIRATION_MODE`.
11. **Execution stats / structured logs** (§8.D): no latency/slippage/reject accounting; logs not CSV-structured rows.
12. **Partial-fill reconciliation** (§8.D): deal-based bookkeeping absent; position volume assumed from request.
13. **Netting-aware aggregated book** (§8.D/§12.2): EA is strictly one-position-per-chart-symbol with a single magic; no `POSITION_IDENTIFIER` concept, no attribution, no netting of opposite signals, no hedging multi-position management (`CurrentExposure` collapses to ±1/0, `Mql5Bot.mq5:144-162`).
14. **Recovery scan** (§8.A): none (see 5).
15. **Multi-symbol / OnTimer scheduler** (§8.A): chart symbol only; no timer, no cross-symbol polling, no retry queue processing, no command reader, no hot reload.
16. **Kill switch inputs** (§8.C): only in-code flag. Missing: UI button, GlobalVariable, hotkey, Factory command, persisted state + explicit reset.
17. **Filters** (§8.F): only session filter. Missing spread-as-ATR%, day-of-week standalone, news (Calendar/CSV), volatility, correlation, rollover, first-seconds-of-bar chains with reasons.
18. **UI dashboard** (§8.G): none in MQL5 (Python `dashboard.py` is a backtest dashboard, not an EA control panel).
19. **Tester compatibility** (§4/§8.A/§8.H): no `MQL_TESTER/MQL_OPTIMIZATION/MQL_VISUAL_MODE` guards anywhere (grep: 0 hits); WebRequest telemetry would fire in tester; logger writes files in optimization; no `OnTester` criterion; `#property tester_file` unused.
20. **Input validation → `INIT_PARAMETERS_INCORRECT`** (§8.A): none performed; `OnInit` only checks indicator handles.
21. **Management per position** (§8.E): `PositionGuard.mqh` keeps **one global** `m_barsInitiated` counter (`:24`, reset `:109`); partial/breakeven/trailing state is not keyed by ticket → multi-position or restart scenarios corrupt behaviour; `FirstBotPosition()` (`Mql5Bot.mq5:164-174`) manages only the first position.
22. **News, sessions DST** (§8.F/§8.H): session filter has no DST/midnight-crossing handling beyond a simple overnight window (`Session.mqh:33-40`); no `TimeGMT` offset estimation.
23. **Logging rules** (§8.H): logger can throw nothing by design but has no tester/optimization suppression and no rotation; CRITICAL level missing (only ERROR).
24. **Notifier** (§8.H): only WebRequest telemetry; no Alert()/push/mail/Telegram separation, no rate limiting, no tester skip, no separate EA/Factory token concept.

### Release B–E gaps: see §10–§14 (all absent).

## 6. Broken / incomplete requirements in existing code

- `Config.mqh:46` `MathRound` volume normalisation can round risk **up** past the configured risk % (should floor to step then clamp).
- `RiskManager.mqh:91-96` — drawdown breach sets kill switch **after** `CheckLimits` returns; equity-peak and kill-switch are memory-only (`ResetDayAndPeak` re-arms on init).
- Daily-loss reset uses `day_of_year` (`Mql5Bot.mq5:278-290`) — server-time rollover without configurable reset hour; restart clears the day's losses (see §5.5).
- `PositionGuard.mqh` partial path clears TP to 0.0 then returns `EXIT_MODIFY_SLTP|EXIT_CLOSE_PARTIAL` (`:155-158,171-174`); the EA then calls `ModifySLTP(sl, tp=0.0)` *before* the partial close (`Mql5Bot.mq5:315-321`) — TP removal and SL move race the partial-fill; also relies on magic-only identity for the partial volume. This guard logic is single-position-only (see §5.21).
- `TradeManager.mqh:313-349` `ClosePosition` with `volume` partial on a netting account closes from the net position — fine, but nothing re-syncs after a partial fill; `OnTradeTransaction` only logs.
- No SL/TP *presence* check after `TRADE_ACTION_DEAL` success (see §5.3) — the single most safety-critical gap.
- Python `backtest.py` sizing uses `stop_dist * contract_size` as risk-per-lot (price units × contract), whereas the EA uses `stopDist/tickSize * tickValue`; on symbols where `tickValue ≠ tickSize × contract_size` (index/crypto CFDs) the Python twin silently diverges from the EA. Parity claim in README is therefore only exact for classic FX with `point=tick_size` and `tick_value=point×contract`.
- Python cost model charges commission round-trip up-front (`backtest.py:203-205`) and computes exit PnL gross; documented, but swap/rollover and dynamic spread are absent (Release-D cost model).
- `data.py:24-30` `TIMEFRAMES` lacks `H2/H3/H6/H8/H12/MN1` used by real MT5 exports; `load_csv` treats first row as header only.
- CHANGELOG claims "36-test suite" (actual 39); README claims dashboard "growing bar feed" — present.
- `pyproject.toml` pins nothing (SPEC §4 requires pinned versions for the Factory; applies to future factory, noted).
- CI matrix uses Python 3.10–3.12 while SPEC requires 3.11+; runs only on push/PR to any branch — fine, but no ruff job (SPEC §14 requires ruff for factory code later).

## 7. Technical debt

1. All EA state in file-scope globals (`Mql5Bot.mq5:97-112`) — no `CEngine`/`CState`; SPEC §3.4 requires the documented `CState` singleton.
2. Strategy enum switch (`SignalEngine.mqh:264-276`) + shared `SBotParams` — not an `IStrategy` registry; adding a strategy touches the enum, params struct, engine switch, and EA inputs.
3. Positions selected by chart symbol + one magic (repeated loops `Mql5Bot.mq5:130-187`) — no position-index helper abstraction.
4. Formatting/level inconsistencies: `LOG_LEVEL_*` lacks CRITICAL; retcode string table is a subset (`Config.mqh:76-97`).
5. Python modules exceed nothing, but the EA+backtest twin logic is duplicated across two languages with no parity tests beyond strategy signals (no sizer parity, no guard parity).
6. No `docs/` other than SPEC/HANDOFF/README/CHANGELOG; no DECISIONS.md (SPEC §6/§24 requires it).
7. Installer/test knowledge duplicated in README and `scripts/`; no packaging.

## 8. Safety-critical gaps (ranked)

| # | Gap | Consequence | Where |
|---|---|---|---|
| S1 | No post-open SL verification + remediation | Position can run without SL after a "successful" fill; violates non-negotiable rule #2 | `TradeManager.mqh:139-179` + `Mql5Bot.mq5:376-410` |
| S2 | No persistence of kill switch, day-start equity, equity peak | Limits reset on EA restart → loss controls bypassable by restart | `RiskManager.mqh:44-52`, `Mql5Bot.mq5:243` |
| S3 | `Sleep()` in tick path | EA UI freeze, tester slowdowns, missed ticks, watchdog kills in worst case | `TradeManager.mqh:174,247,345,380` |
| S4 | No margin check before sizing | Margin call on over-sized orders possible (only broker-side reject) | `RiskManager.mqh:95-118` |
| S5 | Volume rounding can exceed risk budget | Larger-than-intended exposure per trade | `Config.mqh:46` |
| S6 | Magic not per-strategy / not stable | Restart or strategy switch reuses one magic; cannot attribute; future DSL strategies collide | `Mql5Bot.mq5:73`, `Config.mqh:22-34` |
| S7 | No unknown-state fail-safe | Corrupted/unknown conditions just continue or return; no explicit `NO_NEW_TRADES` state machine | whole EA |
| S8 | Single-position guard state | Partial/trailing misapplied if a second position appears (e.g. manual reopen after flip) | `PositionGuard.mqh:24` |
| S9 | No freeze/volume-limit awareness; stops distance uses `level*point + spread` approximation | `INVALID_STOPS` loops; freeze-level ignored on modify | `TradeManager.mqh:48-57` |
| S10 | Risk math not injectable/testable | Broker-math bugs undetected pre-live (spec explicitly requires synthetic-spec tests) | `RiskManager.mqh` |
| S11 | Tester/optimization not detected | Telemetry WebRequest + file I/O in tester/optimization runs | grep: 0 tester guards |

## 9. File contract gaps

SPEC §7 contract (all artifacts under `MQL5/Files/Aegis/`, atomic writes,
schema validation, versioned) — **entirely absent**:
- No `in/strategies/*.json`, `in/dsl_bundle.json`, `in/allocation.json`,
  `in/correlation.json`, `in/commands/*.json`, `out/heartbeat.json`,
  `out/trades.csv`, `out/stats.json`, `out/exec_quality.json`.
- No `schemas/*.json` (6 schemas), no `docs/FILE_CONTRACT.md`, no atomic-write
  helper anywhere (Python `_write_json` in `cli.py:296-304` writes in place —
  non-atomic).
- EA cannot hot-reload anything; telemetry is outbound HTTP only
  (`Telemetry.mqh`) — no inbound command/heartbeat-file channel, no ≤1 s
  command processing (needs OnTimer — absent).

## 10. DSL gaps

SPEC §9 — **absent**: no `schemas/strategy.schema.json`, no `DslStrategy.mqh`
/ parser / expression tree / indicator binding / bundle loader, no
`in/dsl_bundle.json`, no `#property tester_file`, no 10 example specs + 1
invalid, no hot reload, no invalid-spec-rejection path, no DSL
reference docs, no compiled-vs-DSL parity test, no per-strategy eval time.
Reference strategies exist only compiled (`SignalEngine.mqh`) — the DSL twin
of each must be authored when Release B starts.

## 11. Factory gaps

SPEC §10 — **absent** (0 %): no `factory/` app (FastAPI, SQLAlchemy/Alembic,
SQLite, Jinja2+HTMX), no Kanban lifecycle, no intake/importers, no spec
builder/restatement/ambiguity/LLM-provider abstraction (env-only keys,
no-key fallback), no lints (missing SL / contradictions / lookahead /
pyramiding / TP-SL realism / regime refs / param ranges), no codegen path,
no `factory/gates.yaml`, no Gate 1–4 automation, no OOS budget, no demotion
rules, no allocation/correlation writer, no portfolio views, no drift/SPC
monitoring (SPEC §11/§16), no data audit tool, no weekly edge-health score.
Python repo currently is a quant toolkit, not a CRM. Existing reusable seeds:
backtest engine + metrics (gate inputs), optimizer WFE (Gate 2 input),
`dashboard.py`/`telemetry_bridge.py` (monitoring seeds), `data.py` synthetic
generator (tests), `indicators.py` (regime features will need Wilder
implementations — RSI/ATR already are Wilder).

## 12. Regime gaps

SPEC §12.1 — **absent**: no features (ADX/DI, ATR ratios, Kaufman ER,
Choppiness, LR slope/R², BB bandwidth percentile, realized-vol percentile,
EMA200 distance, session/dow), no dimensions (Trend/Volatility/Session/
Event), no `regime.yaml`, no hysteresis, no EA/Python parity, no stability
test under ±10 % threshold moves.

## 13. Meta-layer gaps

SPEC §12.2 — **absent**: no eligibility, weight model
(gate×regime_fit×perf×corr×drift), adaptive clamp [0.25, 1.5] with ≤ ±15 %/day,
hard zeros, Bayesian shrinkage, combination modes (independent /
weighted_netting / vote / best_of_regime), conflict matrix, one-book-per-symbol
netting with attribution, portfolio WFA vs equal-weight, ≤10 tunable
parameters. Nothing executes either side of it.

## 14. UI gaps

MQL5 dashboard UI: none. Factory web UI: none. Python `dashboard.py` is a
standalone backtest dashboard (std-lib HTTP server, no auth) — useful seed,
but not the SPEC §10.6 CRM (Kanban, strategy page, gate checklist, regime
heatmap, allocation explanations, audit log, EA status) and not i18n/RTL.

## 15. Deployment gaps

SPEC §4/§23 — no Docker/Windows-container tooling (optional), no
PowerShell scripts (compile/backtest-runner/package — SPEC §4 requires them;
`tools/compile.ps1` etc. absent), no `tester_ini.template`, no
`run_backtest.ps1` automation for gates, no RUNBOOK/docs, no FA/en i18n
assets. Installer exists (`scripts/install_mql5.py`, tested). CI runs Python
only — matches SPEC (MQL5 compile local-only) but no local compile log exists
anywhere (owner must produce).

## 16. Testing gaps

Python: no tests for sizer/broker math, magic identity, file-contract
schemas, status-skip prevention, i18n completeness, drift/SPC, data audit,
regime parity, allocation clamps, no-trading-code lint (all SPEC §14/§21).
CI has no ruff stage. No MQL5 test framework (`TestFramework.mqh`,
`RunUnitTests.mq5`), no synthetic-spec position sizing tests, no
normalizer/stops tests, no tester-procedure docs (`docs/TESTING.md` absent).
No MQL5 compile verification possible in this sandbox — MetaEditor is not
available; owner-side `tools/compile.ps1` needed (HANDOFF §10).

## 17. Exact recommended implementation order

Preserve the working Mql5Bot stack; extend it toward Aegis release-by-release,
with each batch Python-testable in this sandbox wherever the twin exists.
DoD items (SPEC §17) and §3 principles are the acceptance tests.

1. **Session 1 (this batch)** — Audit + foundations, no EA behaviour change:
   1. `docs/IMPLEMENTATION_AUDIT.md` (this file).
   2. `docs/DECISIONS.md` (layout-preservation decision, external-repo policy, Python-first canonical models, missing SPEC §19 note).
   3. Python canonical **broker-symbol spec + normaliser + FNV-1a magic identity** module + tests (5 synthetic specs: EURUSD 5-digit, USDJPY, XAUUSD, US30-like, BTCUSD-like) — Release-A DoD #9/#10/#21 seed; defines the exact contract the MQL5 `SSymbolSpec` port must match.
   4. Python canonical **risk sizer** (injected spec; modes FixedLot / RiskPercentOfEquity / RiskPercentOfBalance / FixedMoney / capped Kelly; floor-to-step volume; VOLUME_LIMIT; margin-callback reduce/reject) + tests (clamping, margin rejection, tick-size rounding).
   5. Update `README.md` + `CHANGELOG.md`; run pytest.
2. **Session 2 — MQL5 Release-A hardening, batch 1** (needs owner compile round-trip on Windows; every file compile-verified before the next):
   - `Errors.mqh`-style retcode completeness + CRITICAL logging level; `NewBar` timer scheduler; remove `Sleep` → `RetryQueue` in OnTimer.
   - `SSymbolSpec` builder from runtime queries + environment validation on `OnInit` (SPEC §3.3 list) → `INIT_PARAMETERS_INCORRECT`.
   - Port sizer/normaliser/magic-map from the canonical Python models; per-strategy magic FNV-1a + persisted registry; input magic becomes strategy-id.
   - **S1 fix**: post-fill SL verification + modify → close + CRITICAL + alert.
   - Persistence (GlobalVariables + versioned JSON; kill switch, day-start equity, peak, ticket map) + restart recovery scan; S2 fixed.
3. **Session 3 — MQL5 Release-A hardening, batch 2**: management state per `POSITION_IDENTIFIER`; hedging/netting position book; filling resolver from `SYMBOL_FILLING_MODE`; deal-based reconciliation; exec stats; filters chain; kill-switch external inputs (GlobalVariable/command); OnTester criterion; tester guards; `out/trades.csv` + heartbeat file writer (contract start).
4. **Release A finish**: MQL5 unit tests (`Tests/*.mqh` + `RunUnitTests.mq5`), tester procedures doc, `docs/` set for Release A, compile 0/0 log, tag `A-ea-core` (SPEC §5.6).
5. **Release B (dsl)**: `schemas/strategy.schema.json` + Python validator tests → MQL5 DSL engine (`DslStrategy.mqh`, bundle) → 10 example specs (4 reference twins first) → parity tests → tag `B-dsl`.
6. **Release C (factory-core)**: `factory/` app skeleton + DB + Kanban → intake + spec builder + lints → gates 1–2 + report parser + `gates.yaml` → allocation + portfolio + audit log → tag `C-factory-core`.
7. **Release D (regime-meta)**: Wilder-based regime features + `regime.yaml` + parity → meta-layer (weights, combiners, conflict matrix) → cost model + drift/SPC/data audit → tag `D-regime-meta`.
8. **Release E (nocode)**: conversational intake fa/en + visual verification + Telegram + voice stub → i18n/RTL → tag `v1.0.0`.
9. Red-team review after each tag (HANDOFF §7/§8.3); `docs/FILE_CONTRACT.md`, `docs/TESTING.md`, schemas, and remaining docs produced inside their releases.

First batch below (this session): files 1.1–1.5. Everything else stays
untouched until its session.

Update (Phase-1 MQL5 hardening batch, this branch): §17.2 batch-1 items 1–5
(Sleep removal → RetryQueue in OnTimer, SSymbolSpec builder + environment
validation, sizer/magic port, S1 post-fill SL fix, S2 persistence + restart
recovery) were implemented and wired into the EA — see §18. §16/§17 line
references to the old single-file EA flow are superseded by the OnTimer
architecture below; re-baseline after the owner compile round-trip.

---

## 18. Phase-1 MQL5 hardening batch — status (2026-09-04, this branch)

The canonical Python models (audit §17.1) are now ported to MQL5 and wired
into the EA. Landed as five named commits on top of the audit commits on
`arena/01a06cdc-mql5bot` (order as mandated):

| Commit | Topic (Phase-1 DoD) | MQL5 files | Python mirror / tests |
|---|---|---|---|
| `75c116c` | S4 SymbolSpec | `Include/Mql5Bot/SymbolSpec.mqh` | existing `symbolspec.py` synthetic-spec vectors |
| `d515164` | S5 MagicMap | `Include/Mql5Bot/MagicMap.mqh` | existing FNV-1a vectors + registry tests |
| `d0b9bff` | S1 SL remediation | `Include/Mql5Bot/SlGuard.mqh` | `python/mql5bot/slguard.py` + `tests/test_slguard.py` |
| `054283d` | S2 kill-switch persistence | `Config.mqh`, `StateStore.mqh`, `RiskManager.mqh`, `PositionGuard.mqh` | `python/mql5bot/failsafe.py` + `tests/test_failsafe.py` |
| final | S3 RetryQueue / Sleep removal | `RetryQueue.mqh`, `TradeManager.mqh` (rewrite), `Logger.mqh`, `Mql5Bot.mq5` (EA wiring) | `python/mql5bot/retryqueue.py` + `tests/test_retryqueue.py` |

Behaviour implemented (static review; details in commit messages):

- **No `Sleep()` anywhere in `mql5/`.** Every order is attempted ONCE per
  call; retryable server codes go to the bounded `CRetryQueue` (32 slots,
  exponential backoff 500 ms × 2^n capped at 10 s, hard attempt cap,
  same-operation dedupe that never resets the cap) and are pumped from
  `EventSetTimer(1)` with bounded work per tick. The only immediate
  re-sends inside one call: a single REQUOTE retry with a refreshed price
  and the bounded FOK→IOC→RETURN chain (SPEC §8.D resolver).
- **Verify-before-resend**: TIMEOUT/RETRY answers are checked against deal
  history (`FindRecentDeal`) before anything is re-sent — a fill can never
  be duplicated by a blind retry. Latency/slippage captured per send and
  reported in one structured `[mql5bot] EXEC|…` audit line per action.
- **S1 — post-fill SL enforcement**: every open and every restart adoption
  is verified with the pure `SlVerdict` (SL present, correct side, outside
  the broker stops level with a half-tick tolerance) and remediated with
  one modify → re-verify → close; a position that can neither be protected
  nor closed escalates to the caller: CRITICAL log + alert + `ENGINE_HALT`.
- **S2 — fail-safe state survives restarts** (DoD #13/#14): hot
  GlobalVariables carry engine state, reason, day key, day-start equity and
  equity peak; a strict `AEGIS_STATE v1` file carries the ticket registry
  with per-`POSITION_IDENTIFIER` flags (`partialDone`, `beDone`); corrupt
  files are quarantined, saves are delete-then-write. The daily-loss pause
  expires at the day rollover; the drawdown/guard kill switch clears only
  via the explicit one-shot reset (input + GlobalVariable ack); a daily
  breach never softens a pause or halt.
- **S5 — per-strategy magic**: FNV-1a 32-bit over `strategy_id` into the
  reserved range with a persisted `MAGICMAP v1` registry
  (`Mql5Bot/State/magicmap.txt`); the legacy input magic remains available
  only with the registry disabled.
- **EA wiring**: OnTimer scheduler (retry pump, orphan-pending cancellation
  after restart, ticket-registry sync, SL-protection pass, equity-limit
  checks, guard pump, state-file flush, 60 s telemetry heartbeat); kill-
  switch close attempts run at a 10 s cadence; new-bar entry gates chain:
  engine state → daily/drawdown flags → spread → pending/queue idle →
  trade mode → session window → signal → flip/entry → size on the injected
  spec → market/pending open → SL-guard enrolment.

Known residual gaps for the owner round-trip:

- **MQL5 COMPILE RESULT: COMPILE NOT VERIFIED — MetaEditor unavailable in
  this environment.** Every file still needs the owner-side compile with a
  zero-warning pass and a strategy-tester run (HANDOFF §10).
- Multi-position book: full trailing/BE/partial management currently
  applies to the EARLIEST open record only; every record is SL-protected
  and gets the max-bars timeout. Full per-`POSITION_IDENTIFIER` management
  and the hedging/netting position book are the next batch (audit §17.3).
- `NormalizeLots` (Config.mqh) now has no callers (kept for reference;
  remove in a later cleanup). `IsFatalRetcode` is a reference classifier;
  execution uses `IsRetryableRetcode`/`IsSuccessRetcode`.
- Audit §1/§2 line references and §5 gap wording predate this batch; they
  will be re-baselined against the final code after the compile round-trip.
