# Strategy Factory — Gap Analysis (mission §3)

Date: 2026-09-06 · Baseline: `ba672ff` (837 passed / 1 skipped, ruff clean)
Target contract: `docs/SPEC.md` v4 (Release B `dsl`, Release C `factory`,
Release E no-code conversational intake) + the AEGIS Strategy Factory
mission brief (§1–§80). Statuses: `EXISTS` / `PARTIAL` / `MISSING` /
`CONFLICTS_WITH_CURRENT_DESIGN`.

Legend: **[B]** Release B, **[C]** Release C, **[E]** Release E,
**[M]** mission-specific.

## 0. What the repository IS today (verified)

- **Python research engine** (complete, gate-hardened): canonical
  multi-position `PortfolioEngine` (`engine.py`) sized only through
  `sizer.size_position` with explicit `SymbolSpec`; cost model
  (`costs.py`); daily-loss/dayclock; metrics; WFA (`optimizer.walk_forward`);
  CPCV/PBO/DSR/PSR/White/HSPA/Monte-Carlo/perturbation
  (`robustness.py`); Optuna stage (optional extra, hardened);
  multi-asset `MetaPortfolioEngine` + causal `regime_feed`/`drift_feed`
  + `meta_layer` (ladder, eligibility, correlation, activation states
  DISABLED/SHADOW/DEMO/LIVE_SMALL/ACTIVE with explicit-only
  transitions); certification status model (`certify.py`, `status.py`);
  fast engine; stress runner; allocation digest seam (ML-8).
- **Strategy registry**: `strategies.py` — 5 strategies
  (ema_crossover, rsi_reversal, donchian_breakout, bollinger_reversal,
  macd_momentum), declared versions, `get_strategy`, params defaults.
  Signal contract: OHLC frame → desired position ∈ {−1,0,+1} from
  CLOSED bars only; engine acts next bar open (lookahead impossible
  by construction).
- **MQL5 EA framework** (`mql5/`): RiskManager, TradeManager, Sizer,
  MagicMap, StateStore, RetryQueue, SlGuard, Allocation.mqh (ML-8
  consumer), SignalEngine.mqh (inline signal logic). **No compiled
  Strategies/ modules, no DslStrategy.mqh, no bundle loader.**
- **No Factory components**: no `schemas/`, no `examples/strategies/`,
  no `spec_builder/`, no `importers/`, no `factory/` package, no DB,
  no FastAPI/Jinja2/HTMX deps, no Alembic.

## 1. Release B — DSL

| Capability | Status | Notes |
|---|---|---|
| Versioned JSON schema (`schemas/strategy.schema.json`) [B][M §7] | **MISSING** | SPEC names the path; create with schema_version, identity, specification, provenance, lifecycle, constraints |
| Canonical DSL → Python runtime interpreter [B][M §6/§8/§15] | **MISSING** | Preferred model: deterministic runtime interpreter over OHLC frames (no codegen) |
| Indicators: EMA/SMA/RSI/ATR/Bollinger/MACD/Donchian (+ Highest/Lowest) [B] | **EXISTS** (primitives) | `indicators.py` has all of them, numpy arrays, causal; DSL just references them |
| Operators: compare/AND/OR/NOT/cross above/below/threshold/range/arithmetic [B] | **MISSING** (as DSL) | primitives exist inside strategies; no generic expression tree |
| Exits: SL/TP models, trailing, breakeven, time exit, indicator exit [B] | **PARTIAL** | engine supports ATR SL/TP, trailing/breakeven (RunConfig `trail_atr`/`breakeven_atr`); DSL must express per-strategy exit spec → map onto engine semantics |
| Filters: spread/vol/session/regime/news/correlation/cooldown [M §6] | **PARTIAL** | costs.reject_mask + gap filters exist engine-side; session/regime/cooldown filters missing as strategy-level constructs |
| 10 example specs + 1 invalid spec [B] | **MISSING** | |
| Parity: compiled strategy ↔ DSL (bar-by-bar signals/trades) [B][M §16/§17] | **PARTIAL** | deterministic backtest + golden strategies exist; no DSL side to compare. Migrating the 5 reference strategies into DSL is the natural first parity set |
| MQL5 `DslStrategy.mqh` + bundle (`in/dsl_bundle.json`, tester_file) [B][M §61/§62] | **MISSING** | blocked BY DESIGN until Python DSL + parity stable (mission §61); EA loading rules pinned in SPEC §7/mission §62 |
| `requires_codegen` escape hatch [B] | **MISSING** | must exist in schema + lints |

## 2. Release C — Factory

| Capability | Status | Notes |
|---|---|---|
| Canonical strategy identity (immutable, versioned) [M §4/§19] | **PARTIAL** | registry has name+version strings; no identity model (spec_hash, parent linkage, provenance). Meta attribution uses strategy_id today |
| Provenance model (HUMAN/COMMUNITY/… + claims) [M §5/§13] | **MISSING** | |
| Intake workflow (paste/URL/file, safe providers) [C][M §12/§65/§66] | **MISSING** | `tools/fetch_real_data.py` is MARKET-data fetching, unrelated; importer must default to manual paste (HANDOFF §2) |
| Spec builder (LLM-assisted, human-in-loop) [C][M §9/§10] | **MISSING** | `ml_interfaces.py` proves the "interface without implementation" pattern to copy; provider abstraction required, keys from env, no key ⇒ manual editor still works |
| Ambiguity handling (two-stage interpretation) [M §10] | **MISSING** | |
| NL → spec, English + Persian [M §11] | **MISSING** | interpreter-level; canonical spec language-independent |
| Claim extraction (AUTHOR_CLAIM vs measured) [M §13/§27] | **MISSING** | |
| Semantic lints (missing SL, lookahead patterns, contradictions…) [C] | **MISSING** | meta_layer validates CONFIGS not specs; nothing validates strategy specs |
| Lifecycle state machine + evidence-required transitions [M §20/§32] | **PARTIAL** | Activation ladder (SHADOW→DEMO→LIVE_SMALL→ACTIVE, explicit-only, pinned) exists; pre-validation stages (DRAFT→…→OOS_SURVIVOR) + rejection/degraded/retired branches missing |
| Gate engine (Gates 0–12, configurable policy) [M §21] | **PARTIAL** | statistical machinery EXISTS (backtest, perturbation, WFA, CPCV/PBO, DSR/PSR, MC); no gate ENGINE that versions thresholds (`factory/gates.yaml`) and requires evidence per transition |
| Factory DB (FastAPI/SQLAlchemy/Alembic/SQLite/Pydantic) [C][M §18/§72] | **MISSING** | none of the deps in pyproject; local-first, 127.0.0.1 bind + password (DECISIONS §4.15) |
| Immutable versions + restart equivalence + idempotency [M §19/§39/§40] | **MISSING** (DB) | principles exist elsewhere (manifests, digests) to copy |
| Kanban UI (Jinja2+HTMX, Inbox→Retired) [C][M §26/§27] | **MISSING** | `dashboard.py` exists (research charts), not a Factory CRM |
| Strategy Monitor (drift/rolling expectancy/degradation) [M §30] | **PARTIAL** | `drift_feed.py` (causal per-strategy drift) + stress/SPC tooling exist; no Factory monitor loop over them |
| Hysteresis / anti-churn / challenger-incumbent [M §31/§32/§69] | **PARTIAL** | meta_layer has ≤±15%/day clamp + slow-moving ladder; challenger/incumbent comparison missing |
| Shadow mode (signals + hypothetical PnL, never orders) [M §33] | **PARTIAL** | Activation.SHADOW exists as a state; shadow OBSERVATION recording (hypothetical trades) missing |
| Multiple-testing control / research manifest / campaign accounting [M §22/§44/§48] | **PARTIAL** | `deflated_sharpe(n_trials)` + White/HSPA exist; campaign manifest + selection accounting missing |
| Dedup (normalized spec hash) [M §24] | **MISSING** | |
| Mutation engine (research-only, budgeted) [M §25] | **MISSING** | optimizer.grid_search is the deterministic primitive to reuse |
| Families/clustering + correlation-aware discovery [M §52/§53] | **PARTIAL** | corr groups exist engine-side (corr_group); family taxonomy + incremental-value report missing |
| Fitness report [M §54] | **PARTIAL** | report.py + certification reports exist for pipelines; per-candidate factory report missing |
| API + CLI [M §55/§56] | **PARTIAL** | `cli.py` exists (research commands); FastAPI app + factory verbs missing |
| Registry extension (available/validated/candidate/… /retired) [M §37] | **PARTIAL** | must MAP onto existing Activation + certification states — never collapse them (prior-mission invariant) |
| Allocation contract fields (strategy_id/version/weight/digest…) [M §38] | **EXISTS** | ML-8 `Allocation.mqh` + allocation digest tests pin the seam; Factory must EMIT that shape |
| Observability (structured lifecycle events) [M §57] | **PARTIAL** | meta_layer journals events; factory event taxonomy missing |

## 3. Release E — no-code conversational

| Capability | Status | Notes |
|---|---|---|
| Chat/Telegram channels, STT abstraction [E] | **MISSING** | SPEC §13 defines flow; provider-abstracted; EA and Factory use separate bot tokens |
| Restate → clarify (≤5 questions) → approve state machine [E] | **MISSING** | |
| Visual verification (last 10–20 hypothetical trades, candles + SL/TP) [E][M §76] | **PARTIAL** | backtest + trade list exist; rendering/approval loop missing; MT5 tester automation exists (`mt5tester.py`, `tools/run_mt5_backtest.py`) but is Windows/terminal-bound — headless Python render is the sandbox path |
| i18n fa/en + RTL [E] | **MISSING** | |
| Voice architecture (optional) [E] | **MISSING** | arch only, per SPEC |

## 4. Conflicts / cautions (do NOT silently reconcile)

1. **Lifecycle states**: SPEC's owner-facing promotion states
   (Draft/Specified/…/Live per File Contract + Activation) vs mission
   §20's research state machine (DRAFT…LIVE). Resolution (this
   delivery): mission §20 governs FACTORY lifecycle;
   `Activation` (DISABLED/SHADOW/DEMO/LIVE_SMALL/ACTIVE) remains the
   META/EA-side authority and is SET only by mapped factory
   transitions. Certification states are never collapsed.
2. **Gate thresholds**: SPEC Gate-1 numbers (≥200 trades/≥3y, PF≥1.3,
   DD≤20%, top-10%<50%, ≥60% positive quarters, Edge-to-Cost≥3, 2×
   cost stress) are the DEFAULTS for `factory/gates.yaml` — mission
   §21 forbids inventing thresholds; DECISIONS Gate-3 demo rule
   (≥4 weeks AND ≥30 trades, documented low-frequency exception)
   likewise.
3. **Weights**: DECISIONS §4.11 fixed ladder (gate_weight × regime_fit
   × performance × correlation × drift, clamp [0.25,1.5], ≤±15%/day)
   — Factory recommendations must pass THROUGH this, never replace it.
4. **Codegen path** (SPEC §10.3 generates `.mqh`): mission §15 prefers
   runtime interpreter; codegen is the ESCAPE HATCH only
   (`requires_codegen`), never the default, always `Needs Review` +
   human `reviewed_by`.
5. **Scraping**: SPEC §10.1 (robots/ToS-gated generic fetch) vs mission
   §66 (user-provided URL/text first). Delivery order: paste-first;
   URL fetch behind a safe provider abstraction, disabled by default.
6. **Deps**: adding fastapi/sqlalchemy/alembic/jinja2/htmx/pydantic —
   as OPTIONAL extras (`factory` extra), keeping core research engine
   dependency-light (existing repo convention).
7. **No ML** (mission §64): `ml_interfaces.py` pattern repeats —
   LLM adapter is an INTERFACE + optional provider; without keys the
   Factory is fully functional via manual/templated intake.

## 5. Build order (respects SPEC release gating + mission §61)

1. **Release B core**: schema + parser/normalizer + runtime interpreter
   + example specs + parity vs the 5 reference strategies (Python side).
2. **Factory core**: identity/provenance models, DB + lifecycle +
   gate engine (defaults = SPEC numbers), reports.
3. **Intake**: templates + lints + ambiguity model; LLM adapter as
   optional provider; claim extraction.
4. **Registry/Meta integration**: eligibility feed into
   `StrategyMetaInput.certification_state`; allocation via ML-8 shape.
5. **UI/API/CLI** (Jinja2+HTMX, FastAPI, `aegis` CLI), security
   hardening, observability.
6. **MQL5 DSL runtime** — only after 1–3 are stable and parity-proven
   (mission §61); EA loading rules per §62.

Each step lands as atomic commits with tests; nothing existing is
broken (mission §60: the 5 strategies and all 838 tests stay green).
