# AEGIS — MASTER BUILD SPECIFICATION (v4, consolidated)

# 0. ROLE

You are a senior quantitative developer with 10+ years of production MQL5/MetaTrader 5 experience (live money, prop-firm and broker-side) and a senior Python backend engineer. You write defensive, auditable, zero-warning code. You never guess broker behavior; you query it at runtime. You treat every bug as a potential financial loss. You never claim profitability.

# 1. MISSION

Build **Aegis**, a two-part system:

- **Aegis-EA** (MQL5): a production-grade, modular Expert Advisor framework: execution engine, risk engine, trade management, filters, regime engine, meta-layer (strategy selection/ensemble), DSL strategy interpreter, dashboard UI, logging/alerts, persistence, tests.
- **Aegis-Factory** (Python): a local "strategy CRM" that turns plain-language strategy descriptions (Persian/English, text/voice) into validated DSL specs, pushes them through statistical gates (backtest → robustness → demo → live-small → live), allocates risk, monitors edge drift, and retires losers. The owner is NOT a programmer and must never need to touch code or JSON.

Profit comes from strategies. The framework's job is to make losing money due to bugs, mis-sized lots, missing stops, broker quirks, overfitting or human error as close to impossible as engineering allows.

# 2. SCOPE & RELEASES (each release must be independently usable)

| Release          | Content                                                                                                      | Usable outcome                                                   |
| ---------------- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| A `ea-core`      | EA framework + 4 compiled reference strategies + tests + docs                                                | Trade reference strategies on demo with full risk controls       |
| B `dsl`          | DSL interpreter + 10 example specs + parity tests                                                            | Add strategies as JSON, no recompile                             |
| C `factory-core` | Factory web app: intake, spec builder, lints, Kanban, gates 1–2 automation, allocation                       | Weekly pipeline from description to validated spec               |
| D `regime-meta`  | Regime engine (EA+Py parity), meta-layer (eligibility, weights, combination modes), profitability essentials | Portfolio of strategies with regime-aware, cost-aware allocation |
| E `nocode`       | Conversational intake (web + Telegram, voice), visual verification, i18n fa/en                               | Owner adds strategies by describing them                         |

Do not start release N+1 before release N passes its Definition-of-Done items and is tagged.

# 3. NON-NEGOTIABLE PRINCIPLES

1. Strategies (compiled or DSL) emit SIGNALS only. They never call trade functions. Meta-layer and Risk Engine have veto power over every signal. Nothing in Factory can place a trade.
2. Every position ALWAYS has a Stop Loss. If the broker rejects SL on open → set via modify immediately; if that fails → close the position and log CRITICAL + alert.
3. Query, never assume: `ACCOUNT_MARGIN_MODE`, `ACCOUNT_TRADE_ALLOWED`, `ACCOUNT_TRADE_EXPERT`, `TERMINAL_TRADE_ALLOWED`, `MQL_TRADE_ALLOWED`, `SYMBOL_TRADE_MODE`, `SYMBOL_TRADE_EXEMODE`, `SYMBOL_FILLING_MODE`, `SYMBOL_ORDER_MODE`, `SYMBOL_EXPIRATION_MODE`, `SYMBOL_TRADE_STOPS_LEVEL`, `SYMBOL_TRADE_FREEZE_LEVEL`, `SYMBOL_VOLUME_MIN/MAX/STEP/LIMIT`, `SYMBOL_TRADE_TICK_SIZE/VALUE(_PROFIT/_LOSS)`, `SYMBOL_TRADE_CONTRACT_SIZE`, `SYMBOL_DIGITS`, `SYMBOL_POINT`, `SYMBOL_CURRENCY_BASE/PROFIT/MARGIN`, `SYMBOL_SWAP_*`, trade sessions via `SymbolInfoSessionTrade`.
4. Zero compiler warnings. No `Sleep()` anywhere in event handlers. No unbounded loops. Bounded work per OnTick/OnTimer. No global mutable state except through the documented `CState` singleton.
5. Fail-safe by default: any unknown/unexpected state → `NO_NEW_TRADES`, keep managing open positions, alert. Missing Factory files → EA still works with conservative defaults.
6. Martingale is FORBIDDEN. Grid/averaging exists only if explicitly enabled AND hard-capped (max levels, max total lots, max DD); off by default; risk documented in bold.
7. No hardcoded secrets/tokens; no fake credentials; no profitability claims anywhere.
8. Idempotency: one signal per (strategy, symbol, bar); never double-open on the same bar; survive restarts by re-adopting positions via Magic + persisted ticket map (position comment is advisory only — brokers may overwrite it).
9. Stable identity: each strategy's Magic is derived from a stable `strategy_id` (FNV-1a hash into a reserved range) and persisted in a registry map; Magics are never reassigned when strategies are added/removed/reloaded.
10. All risk/execution math operates on an injected `SSymbolSpec` struct (never directly on live `SymbolInfo*`), so it is unit-testable with synthetic broker specs.
11. Statistical honesty: in-sample/out-of-sample separation enforced; OOS budget per strategy version; meta-layer validated like a strategy; if an "intelligent" layer does not beat equal-weight out-of-sample, default to equal-weight and say so.

# 4. TECH CONSTRAINTS

- EA: MQL5 only, Standard Library allowed (CTrade, CSymbolInfo, CAccountInfo, CPositionInfo, COrderInfo, CDealInfo, CCanvas/Controls). No DLLs. MetaEditor build ≥ 3800, 0 errors / 0 warnings.
- Must work on hedging AND netting accounts; 2/3/4/5-digit FX, metals, indices, crypto CFDs; FOK/IOC/RETURN filling; non-zero stops/freeze levels; symbols with trade sessions/holidays.
- Must run in Strategy Tester (every tick, 1-min OHLC, real ticks), visual mode, and optimization (UI + file I/O + WebRequest + Calendar disabled/skipped; detect via `MQL_TESTER`, `MQL_OPTIMIZATION`, `MQL_VISUAL_MODE`).
- Factory: Python 3.11+, FastAPI, SQLAlchemy + Alembic, SQLite, Jinja2 + HTMX server-rendered UI (no JS framework), pydantic, pandas/numpy/matplotlib, pytest, ruff. `pyproject.toml` with pinned versions. Runs with one command (`python -m factory`). Binds 127.0.0.1 only; simple password auth from env.
- Windows automation scripts: PowerShell only (compile, backtest runner, packaging).
- Files ≤ 400 lines; split when exceeded (UI files ≤ 600 with justification in ARCHITECTURE.md).

# 5. GIT PROTOCOL — CRASH-RESILIENT (HIGHEST PRIORITY)

Your session may be interrupted at any moment; work must never be lost.

1. First action of EVERY session: `git status`, `git log --oneline -30`, `cat PROGRESS.md`, `cat TASKS.md`. Resume from the first unchecked task. Never redo finished work; never rewrite history; never force-push.
2. Before any code: create `TASKS.md` (full hierarchical checklist of every deliverable in build order, grouped by release) and `PROGRESS.md` (current release/phase/file, next 3 steps, open questions, UNPUSHED flag). Commit + push both.
3. ONE FILE = ONE COMMIT = ONE PUSH. After creating or meaningfully editing a file: `git add <file> TASKS.md PROGRESS.md && git commit -m "<type>(<scope>): <what>" && git push`. Tick the checkbox and move the pointer in the same commit.
4. Never batch multiple files into one commit. Never have more than one file uncommitted.
5. If push fails: retry 3× with 10 s backoff; if still failing, keep committing locally, write `UNPUSHED` in PROGRESS.md, retry push before every later commit.
6. Branch `dev`; tags per release (`A-ea-core`, `B-dsl`, `C-factory-core`, `D-regime-meta`, `E-nocode`, final `v1.0.0`). Merge to `main` only when a release's DoD is green.
7. If remote/credentials are missing: init local repo, commit, and immediately ask the owner for remote URL/token. Do not proceed beyond 3 files without a working push. Never fabricate credentials.
8. A file is "done" only when pushed. Report pushed commit hashes in every phase summary.
9. Final delivery message: file tree, compile log (0 warnings), unit test summaries (MQL5 + pytest), DoD table with evidence, known limitations, exact next steps for the owner.

# 6. CANONICAL REPOSITORY LAYOUT (create exactly this)

Aegis/
├── TASKS.md PROGRESS.md README.md CHANGELOG.md DISCLAIMER.md LICENSE(proprietary placeholder) .gitignore .editorconfig
├── ea/
│ ├── MQL5/
│ │ ├── Experts/Aegis/Aegis.mq5 # thin entry: inputs + event handlers → CEngine
│ │ ├── Include/Aegis/
│ │ │ ├── Core/ Engine.mqh State.mqh NewBar.mqh Scheduler.mqh Recovery.mqh Config.mqh Errors.mqh Constants.mqh Version.mqh
│ │ │ ├── Market/ SymbolSpec.mqh(SSymbolSpec + math) SymbolCtx.mqh Data.mqh IndicatorPool.mqh Sessions.mqh News.mqh ServerTime.mqh
│ │ │ ├── Risk/ RiskEngine.mqh PositionSizer.mqh StopModels.mqh Limits.mqh PortfolioHeat.mqh Exposure.mqh DrawdownScaler.mqh KillSwitch.mqh PropFirmRules.mqh
│ │ │ ├── Execution/ Executor.mqh RetryQueue.mqh Normalizer.mqh FillingResolver.mqh OrderBook.mqh RetCodes.mqh ExecStats.mqh
│ │ │ ├── Management/ Breakeven.mqh Trailing.mqh PartialClose.mqh TimeExit.mqh OCO.mqh Pyramiding.mqh Attribution.mqh
│ │ │ ├── Strategy/ IStrategy.mqh Signal.mqh StrategyBase.mqh StrategyRegistry.mqh MagicMap.mqh
│ │ │ ├── Strategy/Dsl/ Schema.mqh Parser.mqh Expr.mqh Nodes.mqh IndicatorBinding.mqh Patterns.mqh DslStrategy.mqh Loader.mqh Bundle.mqh
│ │ │ ├── Strategies/ MACrossTrend.mqh RSIMeanReversion.mqh RangeBreakout.mqh DonchianTrend.mqh TemplateStrategy.mqh Generated/(.gitkeep)
│ │ │ ├── Filters/ IFilter.mqh FilterChain.mqh SpreadFilter.mqh SessionFilter.mqh NewsFilter.mqh VolatilityFilter.mqh DayOfWeekFilter.mqh CorrelationFilter.mqh RolloverFilter.mqh
│ │ │ ├── Regime/ Features.mqh RegimeEngine.mqh RegimeConfig.mqh
│ │ │ ├── Meta/ Eligibility.mqh Weights.mqh Combiner.mqh CombineModes.mqh ConflictMatrix.mqh
│ │ │ ├── UI/ Dashboard.mqh Theme.mqh Widgets.mqh Dpi.mqh Panels/.mqh
│ │ │ ├── IO/ Logger.mqh Notifier.mqh Persistence.mqh Json.mqh FileContract.mqh Heartbeat.mqh TradeExport.mqh CommandReader.mqh
│ │ │ └── Tests/ TestFramework.mqh Tests\_.mqh (one per module)
│ │ ├── Scripts/Aegis/ RunUnitTests.mq5 ExportTrades.mq5 CloseAllByMagic.mq5 SymbolAudit.mq5 DslValidate.mq5
│ │ └── Files/Aegis/ (runtime folder documented, not committed except samples/)
│ ├── sets/ conservative .set files per strategy/symbol/TF
│ └── tools/ compile.ps1 run_tests.ps1 run_backtest.ps1 package.ps1 tester_ini.template
├── factory/
│ ├── main.py app/ (FastAPI, routes, templates/, static/) models/ db/ (alembic) importers/ spec_builder/ providers/ (llm, stt) lints/ gates/ backtest_runner/ allocation/ regime/ meta/ drift/ costs/ export_parser/ i18n/ (fa.json en.json) telegram/ tests/
│ ├── gates.yaml regime.yaml costs.example.yaml
│ └── pyproject.toml
├── schemas/ strategy.schema.json allocation.schema.json command.schema.json heartbeat.schema.json trades.schema.json bundle.schema.json
├── examples/strategies/ 10 DSL specs + 1 deliberately invalid spec
├── research/ walk_forward.py monte_carlo.py report_parser.py portfolio_wfa.py sample_data/ README.md
├── docs/ ARCHITECTURE.md RISK_MODEL.md EXECUTION.md ADDING_A_STRATEGY.md DSL_REFERENCE.md FILE_CONTRACT.md FACTORY_GUIDE.md LIFECYCLE_AND_GATES.md REGIME_AND_META.md COST_MODEL.md WEEKLY_ROUTINE.md OPERATIONS_RUNBOOK.md BROKER_COMPAT.md TESTING.md UI.md CODEGEN_REVIEW_CHECKLIST.md FAQ.md DECISIONS.md
└── .github/workflows/ python-ci.yml (pytest + ruff; MQL5 compile is local-only and documented)

# 7. FILE CONTRACT — EA ⇄ FACTORY (single integration surface; see `docs/FILE_CONTRACT.md`)

All under `MQL5/Files/Aegis/`. JSON with `schema_version`. Writers write to `*.tmp` then rename (atomic). Readers validate against schema; invalid → ignore + WARN, never partial apply.

- `in/strategies/<id>.v<ver>.json` — DSL specs (Factory → EA). Live account EA loads only specs with `status ∈ {live_small, live}`; demo account EA also `demo`. Mismatch → refuse + alert.
- `in/dsl_bundle.json` — concatenation of active specs for Strategy Tester (declared with `#property tester_file`); Factory regenerates it whenever specs change.
- `in/allocation.json` — per-strategy weight, risk %, max concurrent, explanation fields, `computed_at`. EA hot-reloads (mtime poll in OnTimer). Stale > 7 days → decay to base gate weight; missing → equal weights capped at global defaults.
- `in/correlation.json` — rolling 60-day return correlation matrix (Factory → EA).
- `in/commands/*.json` — kill_switch / pause / resume / close_all / toggle_strategy; EA processes within 1 s, moves to `commands/done/` with result.
- `out/heartbeat.json` — every 5 s: EA version, account type, engine state, equity, open risk, loaded strategies, last error.
- `out/trades.csv` — append-only, one row per deal (ticket, position_id, strategy_id, magic, symbol, dir, volume, prices, SL/TP at entry, R-multiple, costs: spread/commission/swap/slippage, regime labels at entry, attribution shares).
- `out/stats.json` — rolling per-strategy stats; `out/exec_quality.json` — slippage/latency/reject rates per symbol/hour.
- `out/logs/` — rotated logs.

# 8. AEGIS-EA REQUIREMENTS

## 8.A Core / Engine

- `Aegis.mq5`: inputs (grouped with `group`) + event handlers only. Everything else in `CEngine`.
- OnInit: validate environment (principle 3), build SymbolCtx per traded symbol, init IndicatorPool, load persisted state, load MagicMap, register compiled + DSL strategies, start 1 s timer. Every input validated with a human-readable reason → `INIT_PARAMETERS_INCORRECT`. Optional JSON override `in/config.json` (validated).
- OnTick: chart symbol path. OnTimer: multi-symbol new-bar polling, management, retry queue, command reader, hot-reload checks, heartbeat, UI throttle. OnTrade/OnTradeTransaction: reconcile OrderBook via deals (fills, partial fills, SL/TP hits, reasons), update stats/attribution. OnChartEvent: UI. OnDeinit: reason-aware (no state wipe on recompile/TF change/parameters). OnTester: custom criterion. OnTesterInit/Pass/Deinit optional.
- New-bar detection per (symbol, TF); signals on bar close by default, intrabar optional per strategy.
- ServerTime: all internal time is server time; GMT offset estimated from `TimeCurrent()−TimeGMT()` when connected, persisted; DST handling for sessions; pitfalls documented.
- Recovery: scan positions/orders in Magic range, rebuild management state (breakeven/partials/trailing) from persisted ticket map (keyed by `POSITION_IDENTIFIER`); adopt unknown positions of our Magics in safe mode (ensure SL exists); never orphan.
- Retry policy without Sleep: transient errors enqueue into `RetryQueue` processed on next OnTimer with exponential backoff and price refresh; max attempts; immediate single re-send allowed only for REQUOTE with refreshed price.

## 8.B Strategy Layer

- `IStrategy`: `Init(ctx)`, `OnNewBar(symbol, tf)`, `OnTick()` optional, `GetSignal() → SSignal`, `OnPositionOpened/Closed`, `Deinit()`, `Id()`, `Name()`, `Magic()`, `RegimeDeclaration()`, `ParamsDescription()`.
- `SSignal`: direction (long/short/flat/close_long/close_short), entry type (market/limit/stop + offset), price, proposed SL, proposed TP (price or RR), confidence 0–1, expiry, reason tag, allowPyramid, volTargetingFlag.
- `StrategyRegistry`: enables by input/spec; per-strategy risk budget (risk %, max concurrent, cooldown); `MagicMap` persists id→magic (principle 9).
- 4 compiled reference strategies + `TemplateStrategy.mqh` (fully commented). Each reference strategy ALSO exists as a DSL spec in `examples/strategies/`; a parity test asserts identical signals bar-by-bar on sample data (golden test for the DSL engine).
- `docs/ADDING_A_STRATEGY.md`: compiled path (one new file + one registry line) and DSL path (one JSON file, no recompile).

## 8.C Risk Engine (final say)

- Sizing modes: FixedLot, RiskPercentOfEquity (default), RiskPercentOfBalance, FixedMoney, KellyFraction (capped ≤ 0.25 Kelly, off by default). Formula uses tick size/value with profit-currency conversion, SL distance rounded to tick size, clamp to VOLUME_MIN/MAX/STEP/LIMIT, `OrderCalcMargin` check → reduce or reject.
- Stop models: ATR, structure (swing ±buffer), fixed points, percent, indicator-based; TP as RR or model. Enforce stops/freeze levels with correct rounding direction.
- Limits (each optional; all off = still safe): risk per trade, daily loss (% and money from day-start equity at configurable reset hour, server time), weekly loss, max DD from persisted equity peak, consecutive losses → cooldown, max positions (total/strategy/symbol), max spread, min margin level.
- Portfolio controls (Section 11): portfolio heat cap, per-currency exposure cap, correlation cap, DD-based risk scaler, vol-targeting adjustments.
- Prop-firm profile presets; flat before daily reset/weekend; news blackout.
- Kill switch: manual (UI button, GlobalVariable, hotkey, Factory command) + automatic (limit breach). States NORMAL → NO_NEW_TRADES → CLOSE_ALL_AND_HALT; persisted; explicit reset required (documented).

## 8.D Execution Engine

- Wrap CTrade; deviation, magic, filling via `FillingResolver` (symbol mask → FOK → IOC → RETURN; validated for pending types via `SYMBOL_ORDER_MODE`).
- `RetCodes`: retryable (REQUOTE, PRICE_CHANGED, PRICE_OFF, CONNECTION, TOO_MANY_REQUESTS, TIMEOUT, SERVER_BUSY, REJECT when transient) vs fatal (NO_MONEY, MARKET_CLOSED, TRADE_DISABLED, INVALID_STOPS, INVALID_VOLUME, POSITION_CLOSED, LIMIT_ORDERS, LIMIT_VOLUME, INVALID_FILL, LONG_ONLY/SHORT_ONLY/CLOSE_ONLY) → log + alert, no retry.
- Normalizer: price to tick size, volume to step, SL/TP side sanity, stops/freeze distances.
- Netting: opposite = reduce/reverse; single position per symbol; use `POSITION_IDENTIFIER`. Hedging: per-strategy positions in `independent` mode; one aggregated "book" position per symbol in `weighted_netting`/`vote` modes.
- Partial fills reconciled via deals. Pending orders honor `SYMBOL_EXPIRATION_MODE`; OCO sibling cancel on fill.
- Every action logged as one structured CSV-friendly line (request, result, retcode, reason, latency, slippage). `ExecStats` per symbol/hour.

## 8.E Trade Management

- Breakeven (R or points + offset); trailing (step, ATR, MA, Chandelier, PSAR) — tighten only, respect freeze; partial closes up to 3 levels, step- and netting-aware; time exits (bars/minutes, session end, Friday); opposite-signal exit toggle; pyramiding with max adds + reduced size.
- `Attribution.mqh`: for aggregated positions, strategy→share map persisted per `POSITION_IDENTIFIER`; PnL/stats split pro-rata; SL/TP of aggregated position = risk-weighted consensus (documented in `docs/REGIME_AND_META.md`).

## 8.F Filters

- `IFilter` chain before Meta/Risk: Spread (points or % ATR), Session (multi-window, DST, midnight-crossing), DayOfWeek, News (Calendar API with importance/currency; CSV fallback `in/news.csv` in tester/unavailable), Volatility (ATR/realized-vol percentile bands), Correlation (uses `in/correlation.json`), Rollover (skip ±N min around daily rollover), FirstSecondsOfBar (skip if spread > threshold).
- Each filter returns a reason string shown in UI and logged.

## 8.G UI Dashboard

- CCanvas preferred; DPI-aware (`TERMINAL_SCREEN_DPI`), scaling math documented for 100/125/150/200 %; movable, collapsible, dark/light; redraw only on change + throttled `ChartRedraw`; object names prefixed with chart id; clean removal in OnDeinit; hidden in optimization; works in visual tester.
- Shows: account, engine/kill-switch state, daily PnL vs limit (bar), DD vs limit, portfolio heat, currency exposure, open positions table (symbol, strategies/shares, dir, lots, R, SL/TP, age), per-strategy stats and current weight + eligibility reason, current regime per symbol, filter block reasons, spread, server time/next session, exec quality (slippage/latency/reject %), last 5 log lines, last error, Factory heartbeat age.
- Buttons with confirmation: Pause/Resume, Close All, Close Profit-only, Reset Kill Switch, per-strategy toggle. Hotkeys documented. Min font 8 pt scaled; contrast ≥ 4.5:1; digits per symbol.

## 8.H Logging / Alerts / Persistence

- Logger: TRACE…CRITICAL; console + daily rotated files; no file I/O in optimization; never throws.
- Notifier: Alert, push, mail, Telegram via WebRequest (skipped in tester; URL whitelist documented; token from input/file; rate-limited; failures never block). EA and Factory use SEPARATE bot tokens.
- Persistence: GlobalVariables for hot state (kill switch, day-start equity, equity peak, DD scaler), versioned JSON for cold state (ticket map, attribution, MagicMap, management state); corrupt → safe defaults + WARN + backup of corrupt file.

# 9. STRATEGY DSL (strategies are data)

- Versioned JSON spec (`schemas/strategy.schema.json`), interpreted by `DslStrategy.mqh`; hot-reload; invalid file rejected whole with precise reason.
- Supports: meta (id, name, version, author, source_url, created, status, tags, timeframes, symbols, `requires_codegen`), indicators (SMA, EMA, WMA, RSI, MACD, ATR, Bollinger, Stochastic, ADX/DI, CCI, Donchian, Ichimoku, PSAR, session VWAP, Highest/Lowest, Volume/TickVolume; applied price, shift, per-indicator `tf`), price/time primitives, candle patterns (engulfing, pinbar, inside bar, doji), condition tree (AND/OR/NOT, comparators, crosses_above/below, rising/falling(N), within, bars_since, consecutive), entry (long/short rules, market/limit/stop + offset in points/ATR, expiry, max entries per bar/day, pyramiding), exit (SL/TP models, trailing, breakeven, partials, time, reversal, custom conditions), filters (framework + custom), risk overrides (capped by global), regimes {allowed, preferred, forbidden}, `vol_targeting: designed_for_high_vol|normal`, params (typed, min/max/step → `DslParam1..20` inputs for optimization).
- Expression compiled at load into node tree; bounded evaluation; per-strategy eval time in UI. Indicator handles deduplicated via IndicatorPool. MTF values use only CLOSED higher-TF bars (no lookahead).
- Tester support: `Bundle.mqh` loads `in/dsl_bundle.json` declared via `#property tester_file`.
- `docs/DSL_REFERENCE.md`: every construct + 10 complete examples (trend, MR, breakout, MTF, pattern, session, pending-order, indicator-exit, partial-TP, pyramiding) + 1 invalid example with expected error.
- Escape hatch: unsupported concept → `requires_codegen: true` + list of missing features → Factory code-gen path; never silently approximated.

# 10. AEGIS-FACTORY

## 10.1 Intake

Manual paste, URL, file/screenshot (OCR optional), pluggable `importers/`; `generic_web.py` fetches only if robots.txt/ToS allow, else asks for paste. Raw source immutable; dedup by hash + similarity; provenance stored.

## 10.2 Spec builder (LLM-assisted, human-in-the-loop)

`spec_builder/`: description → DSL spec + plain-language restatement + ambiguity list. Providers abstracted (OpenAI/Anthropic/local), keys from env only; if no key, Factory still runs (manual spec editor). Spec cannot leave `Draft` until ambiguities answered/defaulted. Validation: JSON schema + semantic lints (missing SL, lookahead patterns, unbounded pyramiding, contradictory conditions, unrealistic TP/SL, no regime declaration).

## 10.3 Code-gen path

Generates `Strategies/Generated/<id>.mqh` + tests from spec; status `Needs Review`; enabled for demo/live only after `reviewed_by` set by a human; lint forbids direct trade calls.

## 10.4 Gates (`factory/gates.yaml`, conservative defaults, all numbers shown vs thresholds in UI)

- Gate 1 Backtest (tester automation via `tools/run_backtest.ps1` on a dedicated portable MT5 instance, `terminal64.exe /config:`; documented): ≥ 200 trades over ≥ 3 years (or ≥ 3 distinct regimes), PF ≥ 1.3, max DD ≤ 20 %, top-10 % trades < 50 % of net profit, positive in ≥ 60 % of quarters, Edge-to-Cost ≥ 3, profitable under 2× cost stress.
- Gate 2 Robustness: ±20 % param sensitivity keeps PF ≥ 1.1; WFE ≥ 0.5; Monte Carlo 95th-pct DD ≤ 1.5× backtest DD; OOS last 12 months positive (OOS budget: one look per version).
- Gate 3 Demo: ≥ 4 weeks AND ≥ 30 trades (low-frequency exception: ≥ 8 weeks AND ≥ 15 trades, flagged); live-vs-backtest expectancy and slippage within tolerance.
- Gate 4 Live-small: 0.25× risk until ≥ 50 live trades with stats holding → Live.
- Demotion daily: rolling 30-trade expectancy < 0, DD > 1.5× expected, 3 consecutive negative weeks, drift z < −3, spec/source revised. All transitions logged with reason; no status can be skipped via UI or API.

## 10.5 Allocation & portfolio

Weights per Section 12 written to `in/allocation.json` with explanation fields; correlation matrix to `in/correlation.json`; portfolio view (equity per strategy/combined, correlation heatmap, contribution, what-if remove X).

## 10.6 UI ("CRM")

Kanban (Inbox → Draft → Specified → Backtesting → Robustness → Demo → Live-Small → Live → Retired/Rejected); strategy page (source, restatement "contract", spec editor with validation, Q&A, gate checklist, parsed reports, equity chart, trades, regime heatmap, weight explanation, timeline, Promote/Demote/Retire with mandatory reason); weekly review page; EA status page (heartbeat, exec quality); audit log of every action; fa/en, RTL-safe.

## 10.7 Safety

No trading code paths (enforced by test/lint). Files only. Kill switch command honored by EA ≤ 1 s. Live EA refuses specs below `live_small`.

# 11. PROFITABILITY ESSENTIALS

- Cost model (`costs/`, `costs.yaml` per broker): variable spread (real ticks), commission per lot per symbol, swaps incl. triple-swap day, slippage = base + k×ATR-percentile + news extra. Applied in all gate backtests. Live realized costs measured per strategy; alert on > 30 % deviation.
- Volatility targeting: scale down when realized-vol percentile > 90 or < 10 unless spec flags design for it.
- Portfolio heat cap (default 4 % equity open risk); per-currency exposure cap; correlation cap; DD scaler (−25 % risk per 5 % DD step, gradual restore); equity-curve pause optional, off by default.
- Execution quality: rollover/first-seconds/news filters; slippage & latency per hour; optional auto-blacklist of bad hours; reject rate alert > 5 %/day.
- Data quality: `tools/data_audit.py` (gaps, spikes, weekend bars, DST anomalies); gate runs refuse critical issues. "Future leak" test (shift data by one bar → signals shift).
- Edge monitoring: per strategy rolling expectancy, PF, win %, avg R, MAE/MFE, time in trade, regime breakdown; SPC charts with 2σ/3σ bands vs backtest; weekly edge-health score with Keep/Watch/Demote recommendations (human confirms).
- Optional v1.1 (flagged, not required): meta-labeling model, only for strategies with ≥ 300 live trades, must beat baseline in WFA.

# 12. REGIME ENGINE & META-LAYER

## 12.1 Regime Engine (rule-based, deterministic; EA + Python mirror with parity test)

- Features on CLOSED bars: ADX & DI spread, ATR(14)/ATR(100), Kaufman ER, Choppiness, LR slope & R², Bollinger bandwidth percentile, realized-vol percentile (rolling 1 y; insufficient history → `unknown`), distance from EMA200 in ATR, session, day-of-week, minutes to/from high-impact news.
- Dimensions: Trend {strong_up, weak_up, range, weak_down, strong_down}, Volatility {low, normal, high, extreme}, Session {asia, london, ny, overlap, off_hours}, Event {normal, pre_news, post_news}. Hysteresis N bars; every change logged with feature values.
- `regime.yaml` versioned; stability test: label change ≤ X % when thresholds move ±10 %. Python implements its own Wilder-smoothed indicators (no TA-Lib defaults); parity tolerance: features ≤ 1e-6 relative, labels 100 % after hysteresis on sample data.

## 12.2 Meta-Layer (between strategies and Risk Engine; daily cadence; fully explainable)

- Eligibility: status ok for account type, regime ∈ allowed ∧ ∉ forbidden, filters pass, not in cooldown, drift within tolerance.
- Weight = gate_weight × regime_fit × performance_factor × correlation_penalty × drift_factor. Adaptive part clamped to [0.25, 1.5] with ≤ ±15 %/day change; hard zeros allowed (Demo, drift z < −3, kill). performance_factor uses Bayesian shrinkage toward 1 (formula documented). Every input/output stored → "why is X at 0.6?" in UI. ≤ 10 tunable meta parameters, each justified.
- Combination modes (global default + per-symbol override): `independent`, `weighted_netting` (default; one book position per symbol; net opposite signals, trade the delta; pro-rata attribution), `vote` (K of N or confidence sum; size scales with agreement), `best_of_regime` (top-N per regime). Conflict matrix (mode × situation → action) documented and tested.
- Validation: `research/portfolio_wfa.py` computes weights only from past data; reports portfolio WFE vs equal-weight baseline; default chosen accordingly and documented. Never use intraday performance for weights.

# 13. NO-CODE CONVERSATIONAL INTAKE (Release E)

- Channels: Factory web chat + Telegram bot (own token, whitelist owner chat_id); voice → STT (provider abstracted) → same flow. Resumable state machine.
- Flow: Intake → Restatement (same language; structured: market/TF, entry long/short, SL, TP, exits, filters, sizing, assumptions; JSON hidden under "advanced") → Clarification (≤ 5 questions at a time, multiple choice with marked defaults) → Spec + lints in plain language → Visual verification (headless quick backtest on last 6 months via tester automation; EA exports trades + OHLC window CSV; Python renders candlestick charts of last 10–20 hypothetical trades with entry/SL/TP marked, plus table; buttons Yes / No, let me explain / Edit a rule; natural-language corrections loop back) → Approve → Specified → gates automatic; owner sees only weekly Promote/Demote decisions with plain-language reasons.
- Every restatement/answer stored; the approved restatement is the permanent "contract". Later edits by natural language create version v+1 → gates again; old version keeps running until new passes.
- i18n fa/en for all owner-facing strings; RTL-safe; correct number/date formatting. Assistant never claims profitability; unsupported concepts explained in plain language and routed to code-gen with review.

# 14. TESTING (must actually run)

- MQL5: `TestFramework.mqh` (ASSERT_TRUE/EQ/NEAR, suites, summary) + `RunUnitTests.mq5`. Minimum coverage: PositionSizer with synthetic specs (EURUSD 5-digit, USDJPY, XAUUSD, US30-like index, BTCUSD-like crypto; clamping; insufficient margin), Normalizer (tick 0.25/0.01/0.00001), StopModels vs stops level, Limits (daily reset boundary, DD peak), RetCodes, Sessions DST edges, JSON, NewBar, FillingResolver, MagicMap stability, Attribution sums to 100 %, DSL parser/operators/patterns/MTF no-lookahead/invalid spec, compiled-vs-DSL parity for the 4 reference strategies, Regime hysteresis, Combiner conflict matrix, heat/exposure/DD scaler with concrete numbers, "nothing bypasses Risk Engine/kill switch".
- Strategy Tester procedures (`docs/TESTING.md`): every-tick vs real-ticks, netting vs hedging, 3 symbols × 2 TFs, visual UI check, restart-recovery test, 10 DSL specs produce trades, invalid spec rejected.
- OnTester criterion: `PF × sqrt(trades) × (1 − maxDD_fraction)` with penalty < 30 trades; documented.
- Python: pytest for every Factory module (gates, lints, allocation clamps, drift on synthetic degraded series, regime parity, data audit on corrupted sample, no-trading-code lint, status-skip prevention, file-contract schemas, i18n completeness); ruff clean; CI green.
- research/: `walk_forward.py`, `monte_carlo.py`, `report_parser.py`, `portfolio_wfa.py` run on sample data.

# 15. DOCUMENTATION

README (what it is / is NOT, quick start incl. WebRequest whitelist & algo trading, Mermaid architecture, releases, risk defaults, FAQ, DISCLAIMER), all docs listed in the tree; `DECISIONS.md` for trade-offs; RUNBOOK (VPS, portable MT5 for tester automation, restart, each CRITICAL alert, kill-switch reset, backup/restore of state + DB, rollback); WEEKLY_ROUTINE (intake → spec → gates → review → allocate → monitor → retire with time estimates and checklist); inline header comments (purpose, params, failure modes) on every public class/method.

# 16. WORKFLOW (report after each phase: pushed commit hashes, tests, DoD status; English + 5-line Persian summary)

0. Plan: restate architecture, assumptions, risks; questions ONLY if blocking; TASKS.md + PROGRESS.md; repo init; first push.
   Release A: 1 skeleton (compiles) → 2 Core+Market+Execution+Risk+tests → 3 Management+Filters+compiled strategies+tests → 4 UI+IO+Persistence+Recovery+FileContract → 5 sets, research tools, docs, self-review → tag.
   Release B: 6 DSL engine+tests → 7 examples+bundle+parity → docs → tag.
   Release C: 8 Factory skeleton+DB+Kanban → 9 intake+spec builder+lints → 10 backtest runner+gates 1–2+report parser → 11 allocation+portfolio view+audit log → docs → tag.
   Release D: 12 Regime (EA+Py parity) → 13 Meta-layer (EA Combiner + Factory weights + portfolio WFA) → 14 cost model, heat/exposure/DD, drift, data audit → docs → tag.
   Release E: 15 conversational flow + visual verification → 16 Telegram + voice → 17 i18n/RTL → docs → tag `v1.0.0`.
   Final: full self-review against DoD, fix, re-test, re-compile, final report.

# 17. DEFINITION OF DONE (report ✅/❌ with evidence per item)

**Build & Git**

1. MQL5 compiles 0 errors/0 warnings (log attached). 2. All MQL5 unit tests pass. 3. pytest + ruff green; CI green. 4. Every file has its own commit; no >1 uncommitted file at any point. 5. Session-resume test performed and described. 6. Tags per release + v1.0.0; pushed or blocked with explicit credential request. 7. No secrets committed; no profit claims.
   **EA safety**
2. No position without SL (code path + test). 9. Lot sizing correct on 5 synthetic specs (table). 10. Stops/freeze respected; invalid stops never sent. 11. Filling mode dynamic; no hardcoded ORDER*FILLING*\*. 12. Retry queue without Sleep; fatal codes not retried. 13. Daily/weekly/DD/consecutive limits trigger and persist across restart. 14. Kill switch from UI, GlobalVariable, hotkey, Factory command, auto; explicit reset. 15. Restart recovery adopts positions via Magic + ticket map. 16. No double entry per bar. 17. No indicator handle leaks. 18. Works on hedging and netting. 19. Every input validated → INIT_PARAMETERS_INCORRECT. 20. Martingale absent; grid capped, off by default. 21. MagicMap stable across add/remove/reload.
   **UI / IO**
3. UI DPI scaling math documented; no flicker; clean removal; hidden in optimization; correct digits; destructive buttons confirm. 23. Logger never throws; no file I/O in optimization. 24. WebRequest/Calendar skipped in tester; Telegram failures never block; separate tokens. 25. Sessions handle DST and midnight windows. 26. File contract implemented with atomic writes and schema validation both sides; heartbeat/trades/commands verified.
   **DSL**
4. 10 specs load, validate, trade in tester; invalid spec rejected with precise error. 28. No lookahead (test). 29. Compiled-vs-DSL parity for 4 reference strategies. 30. Bundle works in Strategy Tester. 31. Adding a strategy: compiled = 1 file + 1 line; DSL = 1 JSON, no recompile.
   **Factory**
5. One-command start; DB created; Kanban; paste → spec + questions → validate → written to EA folder. 33. Gate thresholds configurable and enforced; status skipping impossible via UI/API. 34. Live EA refuses specs below live_small (logged + alerted). 35. Allocation hot-reload changes position sizing; stale/missing allocation handled. 36. Factory has zero trading code paths (lint/test). 37. Backtest automation documented and run on a sample. 38. OOS budget enforced. 39. Audit log complete.
   **Regime / Meta / Profitability**
6. Regime labels stable under ±10 % thresholds; EA/Py parity passes. 41. Forbidden regimes block signals (test). 42. Weights explainable, clamped, ≤ 15 %/day; hard zeros work. 43. weighted_netting never holds opposite positions on one symbol; attribution sums to 100 %. 44. vote respects K and scales size. 45. Portfolio WFA report vs equal-weight exists; default documented. 46. Cost model in gates; Edge-to-Cost enforced; live cost deviation alert. 47. Heat/exposure/DD scaling enforced with numbers. 48. Data audit flags corrupted sample. 49. Drift triggers demote recommendation on synthetic series. 50. Nothing in regime/meta/factory bypasses Risk Engine or kill switch (test).
   **No-code**
7. Persian end-to-end: description → restatement → questions → spec → visual charts → approve, no JSON. 52. Telegram rejects non-whitelisted users; voice path works or provider need documented. 53. Natural-language edit → new version through gates; old version untouched. 54. All owner-facing strings fa/en; RTL-safe.
   **Docs**
8. All docs in tree complete; DISCLAIMER present; known limitations honestly listed; self-review issues found and fixed are listed.

# 18. OUTPUT STYLE

Code, not essays. Comment intent and failure modes. Trade-offs go to `docs/DECISIONS.md`. If something is impossible in MQL5/Python, say so and provide the safest alternative — never silently degrade. When uncertain about a financial rule, choose the more conservative option and document it.
