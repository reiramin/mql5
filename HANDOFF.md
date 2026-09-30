# AEGIS — PROJECT HANDOFF (mental roadmap, decisions, state, todo)
Read this together with `docs/SPEC.md` (v4). SPEC is canonical for WHAT to build; this file is canonical for WHERE we are, WHY decisions were made, and WHAT to do next. If they conflict, SPEC wins for engineering, this file wins for process/state.

> **CURRENT STATE POINTER (2026-09-20 — first full owner gate run + the
> operator-experience wave).** The authoritative *current* status is
> [docs/OWNER_DELIVERY.md](docs/OWNER_DELIVERY.md) (the account that goes to
> the owner), then `PROGRESS.md` → CURRENT STATE and `docs/DECISIONS.md`
> (newest on top). The design narrative in §0–§14 below is retained as
> roadmap/rationale; where a §-item predates the current state, this pointer
> wins.
>
> **Where the gate stands.** The owner ran the 11-stage certification gate on
> 2026-09-20 (MT5 build 6184, Windows 10). Result: `GATE_RESULT=tester_legs`
> — **stages 0–4 PASS, stage 5 (Strategy Tester legs) FAIL, stages 6–10
> never ran.** Nothing is VERIFIED; no strategy has ever been certified.
> Stages 0–4 PASS is owner-side evidence (`evidence\owner_gate\20260920-092713`,
> gitignored); the hashes are in the delivery note.
>
> **Done (proven on the 2026-09-20 run):** stage 0 self-protection, stage 1
> strict compile 0/0, stage 2 DSL parity 14/14, stage 3 broker parity 12
> MATCH, stage 4 fixture import.
>
> **Built, unit-tested, NEVER run against a live system** (the
> operator-experience wave, Python/docs/tests only — `mql5/` untouched):
> - Telegram: the alert channel (`notify/telegram.py`) plus the operator
>   surface (`notify/telegram_ops.py`) — daily digest, per-trade
>   notifications, and the `status`/`positions`/`report`/`stop` commands.
>   Asymmetric friction: `stop` trips the kill switch immediately; there is
>   NO resume from Telegram (`KillSwitch.manual_stop` escalate-only). Runs as
>   `python -m mql5bot.notify.telegram_ops` (env-only config).
> - The FastAPI operator console (`api/`), `python -m mql5bot.api`, and its
>   opt-in Persian RTL status page (`?lang=fa`); English default is
>   byte-identical. Presentation layer `i18n.py`; needs `uvicorn` (not a
>   bundled dep) to serve.
> - The guided strategy conversation (`factory/conversation.py`, routes
>   `/guided/start` + `/guided/validate`) and `LlmInterpreter`
>   (`factory/interpreter.py`). The conversation REQUIRES the owner to accept
>   the restatement (content-bound `acceptance_token`) and ENDS at
>   **SCHEMA-VALIDATED — structure only; the strategy has NOT been tested.**
> - Entry points: `python -m mql5bot`, `python -m mql5bot.api`,
>   `python -m mql5bot.notify.telegram_ops` (commit `3061ca6`).
> - Docs: `docs/ROADMAP_UX.md`, `docs/TELEGRAM.md`, `docs/DEPLOYMENT.md`,
>   `docs/PERSIAN_CONSOLE.md`.
>
>
> **CONSOLE v2 (commits `920c139`..`fb5cdc1`) — built, unit-tested, never run
> live.** Token authentication (`MQL5BOT_CONSOLE_TOKEN`, signed session
> cookie, the runner refuses a non-loopback bind without it), a shared
> offline shell with the not-yet-proven banner, live updates via a
> same-origin telemetry proxy, and the pages `/strategies`, `/strategy/{sid}`,
> `/new`, `/trades`, `/certification` (read-only gate rail) and `/settings`
> (health checklist, env var names only). See `docs/CONSOLE.md`.
> **CDN fix `b06c7b3`** — the two legacy templates no longer load htmx from
> unpkg.com; every template is offline, guarded by
> `tests/test_templates_offline.py`.
>
> **Known cosmetic item (frozen, deliberately not fixed):**
> `mql5/Experts/Mql5Bot/Mql5Bot.mq5` line 24 still carries
> `#property link "https://github.com/raminhdev/mql5bot"`. The repository is
> `reiramin/mql5`. Editing it would invalidate the compile-of-record, so it
> waits for the next owner recompile.
>
> **Untouched / not built:** the DSL bundle path in MT5 (the tester ran the
> compiled-in default, `InpDslBundleFile` empty); the split deployment in `docs/DEPLOYMENT.md`
> has **never been deployed or drilled**; no telemetry provider is wired into
> the Telegram/console state (they report "not connected").
>
> **Open blockers:**
> - stage 5 FAIL: MT5 build 6184 writes no `[Tester]` Report file (the two
>   gold #2 legs ran clean but are BLOCKED_OWNER_ENVIRONMENT — not a pass,
>   nothing to parse); the gold #1 H1 fixture (120 bars) is too short for
>   MT5's warm-up reservation (start moved past the end of the data).
> - stages 6–10 never run — including stage 8, the binding Python↔MQL5
>   executed-trade reconciliation.
> - BTC denomination still PENDING (excluded from stage 3).
> - no demo, no live, no VPS, no recovery drill.
>
> **Do not touch `mql5/`.** The 2026-09-20 compile-of-record is valid for
> HEAD `81520e6`; any change under `mql5/` invalidates it and forces the
> whole 0–10 chain to be re-run on the owner's Windows machine.

---
## 0. One-paragraph summary
Owner (Persian-speaking, non-programmer, trades via MetaTrader 5) wants an automated trading system where he can describe strategies in plain language (sourced weekly from a public strategy-sharing website), have them turned into executable logic, validated statistically, selected/combined intelligently by market regime, and traded with strict risk controls. We designed **Aegis**: (1) **Aegis-EA** — an MQL5 execution/risk framework with a JSON strategy DSL interpreter; (2) **Aegis-Factory** — a Python "strategy CRM" that converts descriptions → DSL specs → statistical gates → allocation → monitoring/retirement. Core philosophy: **strategies are data; the framework makes losing money due to bugs, mis-sizing, missing stops, broker quirks, overfitting or human error as close to impossible as engineering allows. No profit claims, ever.**

---
## 1. Owner profile & goals (do not lose these)
- Not a programmer. Must add/edit strategies by describing them (Persian or English, text or voice, web or Telegram). Never touches code or JSON.
- Wants: multiple strategies checked simultaneously; automatic selection of the one(s) fitting current market conditions, or a combination.
- Wants: SL/TP and "everything needed for profitability" — we translated that into: risk engine, cost model, execution quality, regime engine, meta-layer, drift detection, statistical gates.
- Wants: zero tolerance for bugs incl. UI, because it is real money.
- Environment: the repository is `reiramin/mql5` on GitHub. The working process (a Mac agent, a Windows agent, a human reviewer) is described in §7.

---
## 2. Honest assumptions we told the owner (keep repeating them)
- No bot/prompt gives guaranteed profit. 90%+ of public strategies have no edge or are curve-fit; weekly rotation without statistical gates = random trading minus costs.
- The value is the **factory + filter**: intake 20–50 strategies/week, validate brutally, discard ~95%, demo the rest, promote only survivors with small risk, retire losers automatically. Expect 1–2 strategies/month reaching live-small.
- Any "intelligent" selector must be validated like a strategy and must beat equal-weight out-of-sample, otherwise default to equal-weight.
- Realistic outcome of a correct system: controlled drawdown and moderate, steady returns — not monthly doubling.
- Check the source website's Terms of Service before scraping; importer defaults to manual paste.

---
## 3. Evolution of the spec (why v4 looks like it does)
- **v1** (EA framework): modular EA, IStrategy interface, Risk Engine veto, Execution with retry, filters, dashboard UI, tests, docs, DoD 1–30.
- **v2** additions: crash-resilient git protocol (one file = one commit = one push; TASKS.md/PROGRESS.md), **Strategy DSL** (strategies as JSON, no recompile), **Factory/CRM** (intake → spec → gates → allocation → Kanban), DoD 31–40.
- **v3** additions: **Regime Engine** (rule-based, EA+Python parity), **Meta-Layer** (eligibility, slow-moving explainable weights, combination modes independent/weighted_netting/vote/best_of_regime), **Profitability Essentials** (cost model, portfolio heat, currency exposure, DD scaler, vol targeting, execution quality, data audit, drift/SPC), **No-code conversational intake** (restatement → clarification → visual verification with charts of last 10–20 hypothetical trades → approve), DoD 41–55.
- **v4 (current, canonical)**: consolidation after two line-by-line review passes. Fixed contradictions and money-losing bugs (see §5). Introduced **5 independently usable releases A–E**, a single repo layout, a **File Contract** between EA and Factory, and unified DoD (55 items).

---
## 4. Key architectural decisions (already made; change only via docs/DECISIONS.md)
1. Signal/Risk separation: strategies emit signals; Meta-layer and Risk Engine veto; Factory never trades (files only).
2. Every position always has SL; failure to set SL → close + CRITICAL.
3. Query broker specs at runtime; all risk math on injected `SSymbolSpec` struct (unit-testable with synthetic specs).
4. Stable identity: Magic = FNV-1a hash of `strategy_id` into reserved range, persisted in MagicMap; never index-based.
5. Attribution/management state persisted by `POSITION_IDENTIFIER` in files, NOT in position comment (brokers overwrite comments; ~31 char limit).
6. No `Sleep()`; retries via `RetryQueue` processed in OnTimer with backoff.
7. Strategy Tester: DSL specs delivered as a single bundle via `#property tester_file`; WebRequest/Calendar skipped in tester.
8. Releases A→E gated by DoD; do not start N+1 before N is tagged.
9. Reference strategies exist both compiled and as DSL; bar-by-bar parity test is the golden test of the DSL engine.
10. Combination default = `weighted_netting` (one book position per symbol; net opposite signals; pro-rata attribution).
11. Weights: gate_weight × regime_fit × performance_factor × correlation_penalty × drift_factor; adaptive part clamped [0.25,1.5], ≤ ±15%/day; hard zeros allowed; daily cadence only; ≤10 meta params.
12. Gates: Gate3 demo = ≥4 weeks AND ≥30 trades (low-frequency exception documented). OOS budget: one look per strategy version.
13. Kelly sizing capped ≤0.25 Kelly, off by default. Martingale forbidden; grid off by default and hard-capped.
14. Two separate Telegram bot tokens (EA vs Factory).
15. Factory: Python 3.11+, FastAPI, SQLite, Jinja2+HTMX (no JS framework), binds 127.0.0.1 with password from env. MQL5 compile is local-only (PowerShell); GitHub CI only for Python.
16. Server GMT offset estimated from `TimeCurrent()−TimeGMT()` when connected, persisted.
17. External repos: read-only inspiration; no third-party trading code imported; no Highcharts (license); if interactive charts ever needed → TradingView lightweight-charts only, decided in DECISIONS.md first (SPEC §19).

---
## 5. Review findings already folded into SPEC v4 (so the next AI doesn't re-introduce them)
Contradictions removed: two repo layouts → one; three workflows → one; three DoD lists → one; "Python only" vs React/PowerShell → explicit language list; impossible MQL5 CI → local script; compiled vs DSL strategies → both + parity; missing final-report requirement → restored.
Money-losing bugs fixed: index-based Magic; attribution in comment; weight clamp vs zero weights; Gate3 "OR"; Sleep vs retry; DSL files unavailable in tester sandbox; duplicate bot token; WebRequest/Calendar in tester; lot tests tied to broker symbol names; Python/TA-Lib indicator init mismatch (own Wilder implementation + tolerance); undefined data source for visual verification (headless tester exports CSV, Python renders); no EA⇄Factory contract (added File Contract with atomic writes + schemas); Factory offline/no LLM key behavior; recovery via comment; uncapped Kelly; missing GMT offset API; Factory web security.

---
## 6. How the project got here (short history)
The first sessions ran on a hosted agent ("Arena") with an ephemeral sandbox
that lost unpushed work and dropped long pastes; that is why every rule below
insists on small commits and on everything living in the repository. That
process is retired. Its branch names (`arena/<id>-mql5bot`) and the old
repository name (`raminhdev/mql5bot`) still appear in historical logs and in
one frozen file (see the known cosmetic item in the CURRENT STATE pointer);
they are provenance, not the current setup.

---
## 7. Operating model (process rules — mandatory)
Three roles, each with one job. No role does another's.
- **Mac agent (edits and pushes).** Writes Python, tools, docs and tests;
  runs ruff and the full pytest suite; commits on a branch and pushes. It
  cannot run MetaTrader 5 and never claims a compile, a tester result or a
  reconciliation. It never touches `mql5/`, `artifacts/`, `evidence/`,
  `logs_owner/` or any frozen manifest (see `CLAUDE.md`).
- **Windows agent (runs the gate, returns raw evidence).** On the owner's
  Windows machine with the MT5 terminal, it runs `tools/owner_gate.ps1`
  against a pushed commit and returns the raw evidence directory
  (`evidence\owner_gate\<UTC>\` — one `stage_<n>.json` per stage plus
  `gate_summary.json` and the `GATE_RESULT=` line) unedited. It does not
  interpret, summarise away, or repair evidence.
- **Human reviewer (audits every commit).** Reads every commit the agents
  push, checks each claim against a file, a test or a hash, and decides
  what merges to `master`. The gate result is truth; the reviewer never
  accepts a BLOCKED leg as a pass or one unit's result as evidence for
  another.
- Work happens on branches; `master` changes only after review. No amend,
  no force-push. Every "done" names the file, test or hash that proves it;
  anything built but never run against a live system is written "built,
  unit-tested, never run live".
- Each session ends with a dated entry in `AUTONOMOUS_LOG.md`.

---
## 8. Session prompt templates (HISTORICAL — Arena era)
> Retained for provenance. The current process is §7 and `CLAUDE.md`; where these templates mention Arena or `main`, they are superseded (the default branch is `master`).

### 8.1 Planning session (run once, after SPEC.md is in main)
PLANNING SESSION — the only outputs are TASKS.md and PROGRESS.md. No project code.
1. git fetch; git checkout main; git pull. Paste `git log --oneline -5` (must include "docs: add master spec v4").
2. Read docs/SPEC.md COMPLETELY (all 19 sections). If missing or truncated, STOP and tell me.
3. Create TASKS.md from SPEC §6 (layout), §16 (workflow), §17 (DoD): Release A–E → Phase → one checkbox line per FILE, in dependency/build order; each phase ends with its test file(s) and a "docs updated" line; final "DoD verification" section listing items 1–55; mark PING.md done, nothing else.
4. Create PROGRESS.md: current_release A, current_phase 1, current_file none, next_3_steps (first 3 unchecked files), unpushed false, open_questions [].
5. Commit and push each file SEPARATELY. Paste both hashes.
6. End with `git log origin/<branch> --oneline -10` and the exact branch name. Do not start Phase 1.

### 8.2 Work session (repeat until done)
WORK SESSION.
1. git fetch; git checkout main; git pull. If Arena forces its own branch, branch it FROM latest main. Paste `git log --oneline -5`.
2. Read docs/SPEC.md, TASKS.md, PROGRESS.md. Paste PROGRESS.md. Do not re-plan.
3. Take the FIRST 10 unchecked files from TASKS.md in order. Paste the list before starting.
4. ONE FILE → git add <file> TASKS.md PROGRESS.md → commit → push → paste hash. Only then the next file.
5. If a push fails 3 times, STOP and report.
6. After the 10 files (or when a phase ends): update PROGRESS.md (next 3 steps), push, end with `git log origin/<branch> --oneline -15` and the branch name for me to merge.
7. Touch nothing outside these files except TASKS.md / PROGRESS.md.

### 8.3 Red Team session (after each release tag)
RED TEAM REVIEW — no new features. Read docs/SPEC.md and the code of Release <X>. Produce docs/REDTEAM_<X>.md listing every way this release could lose money or violate SPEC §3 principles (execution, sizing, stops, recovery, netting/hedging, tester vs live, file contract, UI), each with severity, evidence (file:line), and a concrete fix. Then fix CRITICAL/HIGH items one file per commit, re-run tests, update CHANGELOG.

---
## 9. TODO — intended but NOT yet applied (HISTORICAL, Arena era — the current backlog is `TASKS.md`)
**Immediate (owner + agent)**
- [ ] Owner: create `docs/SPEC.md` on `main` via GitHub web UI (full v4 text + §19). Verify not truncated (ends with §19).
- [ ] Owner: create `HANDOFF.md` on `main` (this file).
- [ ] Owner: merge `arena/01a06c21-mql5bot` → `main` (PING.md) so the branch and main converge.
- [ ] Agent: Planning session (§8.1) → TASKS.md + PROGRESS.md. Owner merges. Owner sends TASKS.md text to a reviewing AI to check dependency order/completeness before coding.
- [ ] Agent: Work sessions for Release A (§8.2), ~10 files each. Owner merges after each.

**Golden reference files I intended to write (high leverage: they prevent agent drift) — not yet written**
- [ ] `schemas/strategy.schema.json` — complete DSL v1 JSON schema (meta, indicators, conditions, entry, exit, filters, risk overrides, regimes, vol_targeting, params, requires_codegen).
- [ ] `factory/regime.yaml` — feature lookbacks, thresholds, hysteresis N, dimensions.
- [ ] `factory/gates.yaml` — the numeric thresholds from SPEC §10.4 as config.
- [ ] `examples/strategies/*.json` — the 4 reference strategies in DSL (MACrossTrend, RSIMeanReversion, RangeBreakout, DonchianTrend) + 6 more + 1 invalid.
- [ ] `docs/FILE_CONTRACT.md` with all 6 JSON schemas (allocation, command, heartbeat, trades, bundle, correlation).
- [ ] A sample Persian intake conversation (description → restatement → questions → approval) as a golden example for Release E.
- [ ] `docs/DECISIONS.md` seeded with §4 of this handoff.

**Process**
- [ ] Red Team session after Release A, B, C, D, E.
- [ ] Owner: ≥4 weeks demo on the target broker for Release A before enabling anything from C/D/E on live money; verify restart recovery, kill switch, netting/hedging manually.
- [x] Move from Arena to local agents — superseded by the Mac agent / Windows agent / human reviewer process in §7.

---
## 10. Risks & warnings for the next AI
- MetaEditor compile cannot run in the agent sandbox; agent must write code carefully and the owner (or a Windows agent) runs `tools/compile.ps1` and feeds back errors. Never claim "compiles" without a log.
- Keep everything in the repo; chat is not a record.
- Wine/Docker MT5 results may differ from Windows; only Windows portable MT5 is the reference for gates.
- Do not add ML before the rule-based system is stable (meta-labeling is v1.1, flagged, ≥300 live trades).
- Do not "simplify" the risk engine, magic map, attribution persistence or file contract — each fix in §5 corresponds to a real-money failure mode.
- Any deviation from SPEC must be recorded in docs/DECISIONS.md with rationale; conservative option wins when uncertain.
- Never write marketing language or profitability claims in code, docs, UI or Telegram messages.

---
## 11. Definition of "we are on track" (owner's weekly self-check)
- `main` has SPEC.md, HANDOFF.md, TASKS.md, PROGRESS.md and code; `git log` shows one commit per file.
- Current release's phase in PROGRESS.md matches ticked items in TASKS.md.
- A strict 0/0 compile log SHOULD exist for the latest EA state (this is an owner-pending target, not a current fact — see the CURRENT STATE pointer above); MQL5 unit tests and pytest pass.
- No unreviewed agent branch older than one session.
- Release tags exist for finished releases; Red Team doc exists per finished release.

---
## (Convergence mission, 2026-09-06) Where the system stands NOW

- Branch `arena/01a070b0-mql5bot`. The AEGIS autonomous layer
  (factory + indicator universe + discovery governance + operator
  console) is IMPLEMENTED and RESEARCH-VALIDATED on synthetic data;
  see `docs/AEGIS_FINAL_CONVERGENCE_AUDIT.md` for the per-subsystem
  truth table and `docs/AUTONOMOUS_STRATEGY_DISCOVERY.md` for the map.
- Production activation remains **NOT_READY**: MT5 compile, Strategy
  Tester acceptance, Python↔MT5 reconciliation and real-data research
  are owner actions (`BLOCKED_OWNER_ENVIRONMENT`). Nothing faked.
- Owner-only next actions: (1) compile EA in MetaEditor, (2) run the
  Strategy Tester acceptance scenario, (3) provide real H1 data for
  the 5+ symbol basket, (4) demo-phase operation, (5) first human
  approvals through the console.
- Production promotion policy: SHADOW→DEMO→LIVE_SMALL→LIVE, every
  human-gated step recorded with actor+reason+evidence hash+policy
  version; auto-live promotion stays OFF (RESEARCH_AUTOMATION default).

---
## Appendix — Mission 5 state (master production convergence)

- Research integration closed: the deterministic research service is
  production code (`discovery/research_service.py`), driven identically
  by the console one-click intake and `factory-cli research`.
- Observability: structured journal (closed vocabulary) + full audit
  reconstruction (`FactoryStore.reconstruct`, `/strategies/{sid}/trail`).
- Data/cache hardening: §52 firewall, §54 cache identity, §82 global
  caps (grid, concurrency, time budget).
- §7 indicator coverage complete: 71 kinds (T3, ICHIMOKU, BETA added;
  DMI = ADX outputs).
- Boundary states (§90) kept SEPARATE in
  `docs/MASTER_PRODUCTION_CONVERGENCE_AUDIT.md` §95: Python-side PASS,
  MT5 gates BLOCKED_OWNER_ENVIRONMENT, overall NOT_READY.

---
## Reality-Gate Closure (2026-09-08) — owner handoff for the MT5 round-trip

**Overall status: `REALITY_GATE_BLOCKED` — `PRODUCTION = NOT_READY`.**
The sandbox has proven everything that can be proven without a MetaTrader 5
terminal. Nothing about compilation, tester runs, reconciliation, demo, or
live trading has been proven anywhere, and nothing is faked.

**Proven locally (sandbox, deterministic, replay-verified):**
- Python ↔ DSL parity, indicator semantics (RSI exact-tie = PROVEN_EXACT;
  EMA seed = WARMUP-classified, decision-equivalent), Gold #1 (frozen,
  byte-identical regen) and Gold #2 (`GOLD_2_RECONSTRUCTED_NEW_PROVENANCE`,
  FROZEN: 56 fills reconciled exactly, hash-chain verified — it is NOT the
  lost historical Gold #2 and never claimed to be).
- Safety invariants in dedicated micro-fixtures (daily-loss halt, kill
  switch seam, retry, missing-SL, Meta reduce-only/stale/tamper refusal,
  state recovery).
- Certification state machine is fail-closed: nothing here can become
  VERIFIED; only owner MT5 evidence can.
- Execution authority: only TradeManager sends orders (plus one documented
  restart-cancel); Factory/Research/ML/LLM/Meta cannot.
- Scope boundary: the EA executes exactly its five built-in engines; the
  71-kind indicator universe is research-certified, not MT5-certified
  (`docs/CERTIFICATION.md` §Certification scope surfaces).

**Blocked on the owner's Windows MT5 environment (BLOCKED_OWNER_ENVIRONMENT):**
strict compile + log, SymbolSpec export, Strategy Tester legs (M1-OHLC /
Every Tick / real ticks), Python↔MT5 reconciliation of Gold #1 AND Gold #2,
runtime proofs (kill-switch, restart, retry, lost-response adoption, SL
verify-modify-reverify), netting + hedging account legs, then ≥4-week demo.

**Next action (the ONLY path forward):** run the canonical TEN-step
protocol in `docs/MT5_ROUNDTRIP.md` — it is the single source of truth;
every other checklist is a shortcut of it. It contains the exact commands,
configs, artifact paths, hashes, parsers, and pass/fail criteria for a
non-programmer.

**Send back to the agent, per attempt:** the compile log, fresh `.ex5`
SHA-256 hashes, the SymbolSpec export, every leg's RAW tester report +
JSON sidecar, the parsed deal lists, the kill-switch/restart/retry proof
journals, and the `certify_strategy.py` report. Any Gold #2 divergence is
reported AS OBSERVED and classified BEFORE any code change.

---
# OWNER ACTION REQUIRED — the ten canonical steps (mechanical view)

This is a SHORTCUT view of the canonical TEN-step protocol in
`docs/MT5_ROUNDTRIP.md` (the single source of truth — every step below
maps 1:1 onto its canonical step number). Machine: **Windows + MetaTrader 5
+ MetaEditor 5**. Failure rule for EVERY step: any missing/mismatched
artifact ⇒ `NOT_VERIFIED`; never repaired after the fact, a rerun is a
new record.

### Step 1 — strict compile
Command: `powershell -ExecutionPolicy Bypass -File tools\compile.ps1 -Strict`
Input: this exact repository commit. Output: fresh `.ex5` per target.
Artifacts: compiler exit code 0, source identity, compile timestamp,
`.ex5` SHA-256 per target. Fail: exit 1/2/3/4 ⇒ STOP (`SOFTWARE_FAIL`).

### Step 2 — verify compiler log
Input: `logs\compile-<stamp>.log` from step 1. Output: verbatim log,
0 errors / 0 warnings counted from the LOG, `.ex5` SHA-256, repo commit
hash next to the log. Fail: any error/warning token, missing/stale log
⇒ `SOFTWARE_FAIL`.

### Step 3 — export the ACTUAL broker SymbolSpec
Compile + run `mql5\Scripts\Mql5Bot\Mql5BotExportSymbolSpec.mq5` on the
demo account for the certification symbol; then
`python tools\broker_symbol_parity.py`. Output: timestamped, SHA-256'd
export under `data\broker_exports\`. Never substitute the synthetic
parity spec; any difference is classified (SIZING / STOP_CONSTRAINT /
VOLUME_GRID / MARGIN / EXECUTION), never silently rewritten.

### Step 4 — load the FROZEN Gold #1 and Gold #2
Inputs: `artifacts\gold\gold_fixture.csv` + `artifacts\gold_2\gold2_fixture.csv`
(Gold #2 = `GOLD_2_RECONSTRUCTED_NEW_PROVENANCE`, never regenerated) +
each `manifest.json` (config hash, dataset hash), the source commit hash,
the step-3 SymbolSpec binding, timeframe M1, each documented window.
Import the fixtures as custom offline symbols. Fail: dataset hash ≠
manifest ⇒ STOP; hash re-checked AFTER the legs (no mutation mid-test).

### Step 5 — M1-OHLC baseline
Command per leg: `python tools\run_mt5_backtest.py run --config <job>.json`
(model grade 1-minute OHLC, both golds). Output: RAW `.htm` report +
`.json` sidecar archived verbatim; parsed by `run_mt5_backtest.py parse`
(never hand-typed). Fail: missing raw report or parse failure ⇒ the leg
did NOT run.

### Step 6 — Every Tick
Same EA/config/window, model grade Every tick. Artifacts: raw report +
sidecar + model identifier + report hash + parsed result. Never
substituted by M1-OHLC.

### Step 7 — Every Tick based on real ticks
Same configuration on `Every tick based on real ticks`. VERIFY the
terminal actually used real ticks: record requested vs ACTUAL model
(the report's Model line + journal), real-tick coverage
(`REAL_TICK_COVERAGE_FULL` / `_PARTIAL` / `_UNKNOWN`), fallback
intervals, broker data availability, test interval. Official MT5
semantics: missing tick data ⇒ the tester silently generates ticks —
selecting the mode does NOT mean every tick was real. PARTIAL/UNKNOWN
keeps certification constrained.

### Step 8 — Python↔MT5 reconciliation
Compare BOTH gold fixtures, field-by-field: source commit, fixture hash,
config hash, symbol, timeframe, timestamp, bar, signal, direction,
entry, volume, SL, TP, exit, exit reason, Meta, Risk, Kill Switch,
position id, ticket/deal ids, realized PnL where available. Every field
MATCH / DIVERGENT (+ one class from the closed 14-class taxonomy) /
NOT_APPLICABLE — never "close enough". Gold #2 `PENDING_OWNER` fields
are filled ONLY with real MT5 evidence. Run the step 8a–8d runtime
proofs (kill switch, restart matrix, retry/adoption/SL proofs, netting
AND hedging legs — see the procedures table in docs/MT5_ROUNDTRIP.md).

### Step 9 — archive everything
ONE immutable certification manifest binding: compile log, `.ex5`
hashes, SymbolSpec export, ALL raw + parsed reports, both gold
manifests + expected executions + reconciliation, the real-tick coverage
record, owner environment metadata (terminal build, broker, account
type), tester model, source/config/data hashes — every item with
SHA-256 + timestamp, append-only.

### Step 10 — assign certification state
`python tools\certify_strategy.py --config <config.json>` — it can only
ASSIGN a state from evidence steps 1–9 produced. States: SOFTWARE_PASS /
EMPIRICAL_VALIDATION_PENDING (≙ RESEARCH_VALIDATED) / VERIFIED (≙
MT5_VALIDATED + full ladder, owner only) / FAILED / NOT_ELIGIBLE, with
the MT5 dimension VERIFIED / NOT VERIFIED. Python-only evidence can
NEVER produce MT5_VALIDATED or VERIFIED. Exit code 0 = VERIFIED,
anything else = NOT VERIFIED with the reason.

**Send back per attempt — the complete return package (16 items, raw
files only, never screenshots):**

1. compile log (verbatim)
2. fresh `.ex5` SHA-256 hashes
3. terminal/build information (terminal build, tester build, broker,
   account type)
4. the ACTUAL broker SymbolSpec export
5. Gold #1 M1-OHLC report (raw)
6. Gold #1 Every-Tick report (raw)
7. Gold #1 real-tick report (raw)
8. Gold #2 M1-OHLC report (raw)
9. Gold #2 Every-Tick report (raw)
10. Gold #2 real-tick report (raw)
11. parsed report JSONs (extractor output, one per leg)
12. the Python↔MT5 reconciliation record(s)
13. the real-tick coverage record (FULL/PARTIAL/UNKNOWN + fallback
    intervals)
14. empirical certification reports (regime × model ladder,
    100-trade-gated — separate from the gold runs)
15. the immutable archive manifest (step 9, all hashes + timestamps)
16. the final status output of `tools/certify_strategy.py` (with
    `--reconciliation` pointing at item 12)

Note the two lanes: items 5–13 answer "does actual MQL5 execution
reproduce the frozen fixtures?" (no trade-count gate — Gold #2's 56
trades are valid); item 14 answers the empirical regime question (that
is where the 100-trade minimum lives). Until these exist, the honest
status stays `NOT VERIFIED — OWNER MT5 EVIDENCE MISSING`, which is the
correct answer, not a failure.
