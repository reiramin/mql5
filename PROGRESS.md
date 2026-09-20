# PROGRESS

> **HOW TO READ THIS FILE.** The single authoritative statement of where
> the repository is *right now* is the **CURRENT STATE** block immediately
> below. Everything under **HISTORICAL SESSION LOGS** is an append-only
> archive of past sessions — it names old branches (`arena/…`), superseded
> phase numbers and historical test counts that are **NOT** the current
> state and must not be read as such. History is preserved, never rewritten.
> Canonical status also lives in `docs/DECISIONS.md` (newest on top) and
> `HANDOFF.md`.

---

## CURRENT STATE (authoritative) — 2026-09-20, branch `master`

**Lane.** CODE-COMPLETE / RESEARCH-COMPLETE on Mac; the first full owner
gate run is DONE and stopped at stage 5. RUNTIME-PENDING and OWNER-PENDING
items remain Windows/owner responsibilities (see below). The plain-language
account of record is [docs/OWNER_DELIVERY.md](docs/OWNER_DELIVERY.md).

**First full owner certification gate run — 2026-09-20 (MT5 build 6184,
Windows 10, evidence `evidence\owner_gate\20260920-092713`, gitignored).**
HEAD `81520e6`, frozen anchor `a85cba3`. Result: `GATE_RESULT=tester_legs`.
Stage-by-stage:

- **stage 0 self_protection — PASS.** Anchor ok, tree clean, autocrlf ok,
  frozen hashes + 42 DSL-bound files verified, toolchain located, `mql5bot`
  resolved IN-REPO (v1.0.0).
- **stage 1 strict_compile — PASS.** 0 errors, 0 warnings; 5 targets
  (`DslParityRunner`, `Mql5Bot`, `Mql5BotDownloadData`,
  `Mql5BotExportSymbolSpec`, `Mql5BotImportFixture`).
- **stage 2 dsl_parity — PASS.** 14/14 fixtures EXACT + tampered bundle
  refused.
- **stage 3 broker_parity — PASS.** 12 MATCH rows; crypto PENDING excluded
  (`BTC:sizer.behaviour`, `BTC:tick_value_denomination`).
- **stage 4 fixture_import — PASS.** Both gold fixtures imported; round-trip
  dataset hash == manifest; both intact after the tester legs.
- **stage 5 tester_legs — FAIL.** Six legs, four distinct verdicts:
  `gold1_m1_ohlc`/`gold1_every_tick` FAIL (INSUFFICIENT_FIXTURE_HISTORY —
  the 120-bar H1 fixture is too short; MT5 moved the start past the data),
  `gold1_real_ticks` FAIL (no proving line in its window),
  `gold2_m1_ohlc`/`gold2_every_tick` BLOCKED_OWNER_ENVIRONMENT (ran to
  completion, 2880 bars, but build 6184 wrote no Report file — **not** a
  pass), `gold2_real_ticks` FAIL. Zero trades on the legs that ran.
- **stages 6–10 (reconciliation incl. 8a–8d, archive, certify) — NEVER
  RUN.** Stage 8 is the binding Python↔MQL5 executed-trade parity claim;
  it has never run, so cross-engine parity on real trades is unproven.

**Nothing is VERIFIED.** No strategy has ever been certified; the Python
funnel produces `SOFTWARE_PASS` / `EMPIRICAL_VALIDATION_PENDING` only. The
DSL bundle path was never exercised in MT5 (`InpDslBundleFile` empty → the
EA ran its compiled-in default). No demo, no live, no VPS, no recovery
drill.

**Feature Wave 3 (2026-09-20, Python/tools/docs/tests only — `mql5/`
frozen anchor untouched):** operator-experience layer, each built and
unit-tested, **never run against a live system**:
- Telegram alert channel (`notify/telegram.py`) — env-only creds,
  token-scrubbed, bounded timeout, min send interval (commit `d22a783`);
  extended in Wave 3 with trade open/close notifications, a daily digest,
  and read-only status/positions/report/stop commands under asymmetric
  friction (stop is easy; there is no Telegram path that can resume).
- LlmInterpreter (`factory/interpreter.py`, commit `73df61a`) plus the
  restatement-from-scrubbed-draft fix (commit `5a946b3`).
- Persian/RTL console presentation layer (`i18n.py` + console templates,
  commit `4752140`) — opt-in; English default byte-identical.
- Owner delivery note refreshed from the gate run (commit `b3f9d3c`),
  plus the roadmap, split-deployment guide, and the guided Persian
  strategy-conversation flow (this wave).

**Do not touch `mql5/`.** The 2026-09-20 compile-of-record is valid for
HEAD `81520e6`; any `mql5/` change forces the whole 0–10 chain re-run.

---

## PRIOR STATE — 2026-09-17, branch `master`

**Lane.** CODE-COMPLETE / RESEARCH-COMPLETE on Mac; RUNTIME-PENDING and
OWNER-PENDING items remain Windows/owner responsibilities (see below).

- **Final closure wave (2026-09-17) — research-service truthfulness + generic
  DSL convergence.** Two Mac-side product-path closures, frozen `mql5/` anchor
  `227bf66` untouched:
  1. **No fabricated PASS.** `discovery/research_service.py` no longer injects
     `pbo=0.0` / `positive_in_expected_regime=True` / portfolio zeros / score
     `cpcv_pbo_evidence=0.1`. Every gate input is now MEASURED (PBO via
     `robustness.combinatorial_purged_cv`, regime via
     `discovery/research_metrics.regime_pf`, DSR via `robustness.psr`,
     portfolio vs the actual book); an unmeasurable input stays UNSET so the
     gate SKIPs (blocks). Evidence is bound to the SELECTED variant's own
     `spec_hash`; a FAIL record can never promote. A marginal-edge grid search
     now measures PBO≈1.0 and is correctly REJECTED (the discard is the design).
     New module `discovery/research_metrics.py`; regression
     `tests/test_research_service_truthful.py`. Details: `docs/DECISIONS.md`
     2026-09-17.
  2. **Generic DSL→MQL5 bridge** (executable bundle + fail-closed loader +
     Python parity golden + staged generic MQL5 runtime), see the 2026-09-17
     convergence entry below and `docs/AEGIS_CONVERGENCE_AUDIT_2026-09.md`.
  3. **Truthful WFE + bundle-size hardening (continuation).** Gate-5
     (`gate5_walk_forward`) no longer accepts `cv_pf − train_pf` (a
     profit-factor delta): its input is now the CONTRACT walk-forward-
     efficiency ratio (held-out return / IS return) computed by
     `discovery/research_metrics.walk_forward_efficiency` over one rolling
     window inside the IS region (the one-look OOS slice is untouched), the
     same formula as `optimizer.walk_forward`; undefined ⇒ UNSET → gate-5
     SKIPs. The mislabeled `is_pf` selection key is renamed `sel_pf`. The
     bundle total-size limit (256 KiB) is now enforced on the in-memory
     `load_bundle` path, and the staged MQL5 loader matches market timeframe
     (not only symbol) with an honest MIRRORED/OWNER-PENDING header.
     Gaps G7/G8 in `docs/AEGIS_CONVERGENCE_AUDIT_2026-09.md`.

- **Waves 1 & 2 (code-side) complete.** Wave 1 established fresh owner-broker
  evidence scaffolding, independent `OrderCalcProfit` denomination probes,
  the Stage-A exporter, and loopback-default network servers. (Owner-compile
  status, precisely: the **exporter script** compiled 0 errors / 0 warnings
  in the owner's MetaEditor; the **EA**'s last real owner compile was 0
  errors / **2 warnings**, after which those warnings were closed by
  source-only edits that have NOT been recompiled — so a **strict 0/0 EA
  compile-of-record remains OWNER-PENDING**, not achieved. See
  `docs/DECISIONS.md`/`CHANGELOG.md` 2026-09-08.) Wave 2
  finished the research/ML/governance hardening: CPCV block-leakage fix +
  two-sided embargo, governor no-resurrection + demote-only clamps, drift
  execution-window alignment, meta-OOS one-look-before-look ordering +
  deterministic `as_of`, cost-stress `None` guard, ML risk-seam
  duplicate-key robustness, telemetry body cap, and docstring honesty.
  Full detail: `docs/DECISIONS.md` 2026-09-16 Wave-2 entry.
- **Tests.** Full deterministic Python suite green: **1667 passed, 1
  skipped, 0 failed** (post-closure-wave; adds the research-service
  truthfulness, generic DSL bundle/parity, interpreter market no-guess,
  indicator-status truthfulness, RiskManager-patch, and the G7 WFE / G8
  bundle-size continuation tests on top of the 1602 Wave-2.3 baseline).
  Verified under `PYTHONHASHSEED=12345` and cross-checked identical under
  seeds 1/777 on the determinism-sensitive suites. `ruff check python/ tests/ tools/ factory/`
  clean (broadened from `python/ tests/`; the previously-documented `tools/`
  ruff debt is cleared); `git diff --check` clean. Prior waves: +17 regression
  tests across Waves 2–2.2 (five Wave 2, four Wave 2.1, eight Wave 2.2 pinning
  the owner-gate verifier hardening).
- **Broker parity — parity machinery CODE-COMPLETE; in-repo verdict
  PENDING; owner witness CAPTURED-OUTSIDE-REPO.** Three distinct facts,
  kept apart:
  1. *Not performed vs not committed.* The owner environment (Windows) has
     ALREADY captured symbol-spec exports with a successful
     `denomination_probe` (`ok=true`, `source=OrderCalcProfit`) for
     EURUSD / XAUEUR / US30 / BTC. `data/` is `.gitignore`d, so those raw
     owner exports are **NOT committed** and are **NOT
     repository-reproducible** on Mac — but the measurement WAS performed.
     "Not in the repo" ≠ "not done".
  2. *Probe ok ≠ parity PASS.* `denomination_probe.ok=true` is a
     *precondition* (both `OrderCalcProfit` calls valid, signs correct,
     tick values re-read), NOT a verdict. The ACCOUNT_CURRENCY vs
     PROFIT_CURRENCY verdict is rendered only when
     `tools/broker_symbol_parity.py` runs on the committed export. With no
     export committed here, the in-repo report is `n_exports:0`, every
     class PENDING. Broker parity is therefore **NOT VERIFIED in this
     repository** — no PASS is claimed.
  3. *Denomination decision stays PENDING.* The tick-value ACCOUNT vs
     PROFIT denomination remains owner-gated (see DECISIONS.md 2026-09-16
     Wave-1 entry); it is confirmed/refuted only when the owner commits the
     exports and the harness renders an accepted verdict on Windows.
  The parity machinery (harness, field map, tolerances, exporter, tests)
  is code-complete. Binding contract for the committed evidence:
  `docs/BROKER_SYMBOL_PARITY.md` + `artifacts/owner_mt5_gate/` (the owner
  evidence package with frozen input hashes).
- **Authority model unchanged.** `STRATEGY → META/PORTFOLIO → RISK +
  EXECUTION veto`; no ML/LLM/meta/discovery path has order authority. The
  only order authority is the MQL5 `TradeManager`.

**Remaining Windows / owner work (RUNTIME-PENDING — never faked on Mac):**
strict MetaEditor compile of record, Strategy Tester legs (M1-OHLC / Every
Tick / Every-Tick-real-ticks), Python↔MT5 reconciliation, kill-switch seam
+ restart proofs, Gold #2 rebuild with new provenance, real owner broker
exports (FX/METAL/INDEX/CRYPTO) → denomination verdict, and the final owner
certification manifest. Status stays **REALITY_GATE_BLOCKED** until the
owner round-trip runs. No profit claims; no runtime-certified claim.

**Owner-coordinated source fix pending (one line, MT5-verify-only).** Wave 2.3
confirmed an inverted `OrderCalcMargin` direction in `RiskManager.mqh:296`
(`price < slPrice` should be `price > slPrice`; bounded impact — nil on
symmetric-margin FX, wrong required-margin only on asymmetric long/short margin
instruments). It was NOT changed on Mac to preserve the frozen source anchor
`227bf66` ("compile exactly this commit"). The owner applies it at the next
strict compile + `source.commit` re-anchor. Wave 2.3 also hardened the Python/
tooling side (determinism, fail-closed reconciliation/parity/sizer, frozen
symbol identity) — see `docs/DECISIONS.md` 2026-09-16 Wave 2.3 entry.

---

# HISTORICAL SESSION LOGS (archive — NOT current state)

# PROGRESS — AEGIS Reality Gate continuation (historical)

- Branch: `arena/01a07c73-mql5bot` (session-pinned; prior gate work from
  `arena/01a070b0-mql5bot` @ b8004f81 merged in by fast-forward)
- Session 2026-09-07: semantic-closure mission. Recovered and verified the
  baseline (1190 tests green, ruff clean), then closed: volume
  normalization contract (fixed a DECISION_CHANGING 1e-12/1e-9 dust-guard
  split), warmup NaN-propagation contract (EMPTY_VALUE no longer reaches
  comparators; INIT_FAILED audited), cross-event NaN-boundary fix, EMA
  seed parity quantified, RSI/crossover truth tables pinned (tie-rule
  CONTRACT_GAP classified), barrier-exit 24-case matrix, Gold #1
  re-verified byte-identical under the frozen pin. Final: 1317 tests,
  0 failed, 1 skipped; ruff clean. Full record:
  `docs/AEGIS_REALITY_GATE_CONTINUATION.md`. Final status:
  **REALITY_GATE_BLOCKED** — MT5 compile / Strategy Tester /
  Python↔MT5 reconciliation remain BLOCKED_OWNER_ENVIRONMENT
  (9-step protocol in docs/AEGIS_REALITY_GATE_AUDIT.md §owner-protocol).
  Gold #2 artifacts are unrecoverable in this environment: INCOMPLETE,
  rebuild-with-new-provenance required (never simulated).
- Compile: **NOT VERIFIED** (no MetaEditor here; the SignalEngine.mqh
  warmup fix is source-review-only until the owner's -Strict compile)

## Next 3 steps
1. OWNER: run §owner-protocol steps 1–9 (compile → SymbolSpec export →
   fixture → tester gold legs → parse → golden reconciliation → kill-
   switch seam → restart proof → archive).
2. Rebuild the multi-factor Gold #2 ladder with new provenance (session-
   filtered spec), or recover the lost session's artifacts.
3. After a green compile: re-run the full gate and promote
   PYTHON↔MQL5 PARITY from PARTIAL per observed reconciliation.

---
# PROGRESS — AEGIS Phase 2.5 / Research Foundation Correction (historical)

- Branch: `arena/01a06cdc-mql5bot`
- Plan: owner pasted the canonical **0–20 AEGIS execution plan** (new
  numbering supersedes the older TASKS/PROGRESS phase lists); phases are
  gated and executed in order, each with an evidence report.  Plan 0–8
  gate-audited against the committed research stack; the remaining plan
  gaps were closed in this session (see session log) — plan 0 baseline
  re-verified, gates 1–8 now PASS with evidence below.
- Tests: **265 passed** (pytest tests/ exit 0, /tmp/venv-mql5; ruff clean
  on changed files; 265 = 258 prior + 7 portfolio)
- Phase 9 (MT5 Truth Engine): **OPEN** — Windows/MetaEditor owner
  round-trip required (DECISIONS.md 2026-09-04 documents the parallel
  research protocol; python phases 10+ proceed, nothing claims MT5 truth)
- Phase 10 (fast research engine benchmark): measured evidence recorded in
  CHANGELOG (22.6 ms/run, ~21.3k bars/s, 100/1k/10k ladder, 1.18-1.20x
  parallel speedup at 2 cores, numerical equivalence PASS, ~90 MB parent
  retention at 10k sets); optimisation backlog (caching/pruning) deferred
  to Phase 18 with the same measurement harness
- Compile: **NOT VERIFIED** (no MetaEditor here; owner round-trip via
  tools/compile.ps1 — reported honestly, never guessed)

## Next 3 steps
1. MQL5-side metrics mirror (heartbeat JSON v2 with `total_return_pct`,
   `max_drawdown_pct`, `profit_factor`, `recovery_factor`, `ulcer_index`,
   `rolling_sharpe` etc.) + Aegis dashboard alignment — requires the
   owner round-trip (no MetaEditor here); python `metrics.py` is the
   canonical reference for the field list.
2. Optional: expose Phase-8 statistics in WFA/`optimizer.py` selection
   surface (cross-section ranking, robustness filters) now that
   `_selection_metrics` and walk-forward returns already carry full
   metric reports.
3. Sweep remaining phase backlog items listed in this file's phase
   checklists (verify against this file below).

## Phase A audit — exit_reason / max_drawdown_pct consumers (2026-09-04)
- Engine semantics (current): a DD-kill / daily-loss halt closes still-open
  books at the next open with `REASON_MAX_DRAWDOWN` / `REASON_DAILY_LOSS_LIMIT`;
  a position whose stop fills intrabar on the crossing bar exits as
  `stop_loss`.  The Phase-4 wrapper re-pin (tests/test_backtest.py
  test_max_drawdown_kill_switch) pins exactly that: final trade reason
  `stop_loss`, realised DD band loosened to -9.0..-4.9, halt acts at the
  open after the crossing close, no entry after the halt open.
- Consumer audit: `python/mql5bot/cli.py` (prints `max_drawdown_pct`,
  never reads `exit_reason`); `dashboard.py` (:120 renders the reason text
  in the trades table; :107 displays maxDD card); `report.py` (:99 renders
  `exit_reason` in the trade table; :131/:189 maxDD).  NO consumer branches
  on the reason vocabulary or on DD semantics — all display-only.  Impact
  of the re-pin on consumers: none (no code change needed); the reason
  vocabulary remains the engine's documented set
  (`EXIT_REASONS` in engine.py / costs.py).

## Benchmark harness — BEFORE table (2026-09-04, tests/test_benchmark.py, marked `bench`)
Row | value
--- | ---
run_backtest wall | 63.8 ms/run (3120 hourly bars)
bars/sec | 48,888
trades/sec | 1,457
peak memory (single run) | ~0.7 MB
walk_forward (2 windows, 2880 bars) | 0.32 s total = 0.16 s/window
grid 100 sets (seq / par-2) | 2.21 s / 1.85 s
grid 1,000 sets | 22.23 s / 18.64 s
grid 10,000 sets | 296.08 s / 250.02 s (~40 runs/s par)
equivalence parallel == sequential | PASS (all sizes)
Optimisation AFTER tables will be added here when phases C/D land.

- 2026-09-04: Phase-C milestone (FAST/TRUTH split): `fast_engine.py`
  NumPy-array single-line screening engine, wrapper-identical signature
  and result shape, reusing canonical sizer/costs/leg_cash math; scope
  gates raise NotImplementedError; equivalence pinned on 38 tests across
  5 strategies x cost/exit/halt/trail/partial knob sets + engine-style
  signal exits (random fixtures, exact trade rows, equity within 1e-8).
  Bench (3120 hourly bars, this sandbox, min-of-5):
  | engine | ms/run | bars/s | speedup |
  | --- | --- | --- | --- |
  | TRUTH run_backtest (BEFORE) | ~61-73 | 43k-51k | 1.0 |
  | FAST run_fast (AFTER) | ~38-42 | 75k-82k | ~1.6x |
  FAST results are screening-only, never final; certification remains
  TRUTH engine + MT5 tester.  Suite 312 tests green; ruff clean.
- 2026-09-04: Phase-B milestone (robust fitness): RobustFitnessConfig +
  composite_score pinned on hand fixtures; metric="composite" OPT-IN in
  grid_search/walk_forward with explicit config; OOS one-look policy
  documented; 273 tests green, ruff clean.
- 2026-09-04: Phase-A milestone (repair verifiability): root pytest via
  pythonpath, ruff clean python+tests, bench harness + BEFORE table,
  exit_reason/max_drawdown consumer audit; 268 tests green.
- 2026-09-04: Phase-D milestone (staged pipeline): mql5bot/pipeline.py —
  RunManifest (deterministic content id), S1 screen (FAST default),
  S2 x2-cost stress with documented survival gate, S3 OWN trade-level
  purge+embargo CPCV (entry-bar attribution, per-fold selection log,
  verified both ways on crafted folds), S4 mt5_stage (skipped manifest
  when no terminal — never faked), S5 OOS one-look registry enforced in
  code (OosOneLookViolation, check-before-run); deterministic cache by
  content digest; optuna_optimize optional extra only (guarded ImportError
  otherwise); docs/STAGED_PIPELINE.md.  Suite 328 tests green; ruff clean.
- 2026-09-04: Phase-E milestone (ML interfaces only): ml_interfaces.py —
  TripleBarrierLabeler/MetaLabeler/ProbabilityCalibrator/FeatureStore
  stubs raising NotImplementedError (no training, no ML stack anywhere),
  frozen RiskContext + MLAdvice seam whose schema cannot carry SL/risk/
  limit fields, apply_ml_advice (veto/direction/cap only, post-checked)
  and check_ml_invariants catching all four violations; package scan
  asserts no banned ML imports.  Suite 346 tests green; ruff clean.
- 2026-09-04: Phase-F milestone (real-tick certification protocol):
  mql5bot/certify.py + tools/certify_strategy.py + docs/CERTIFICATION.md.
  Data-grade ladder per regime (M1 OHLC -> every tick -> every tick on
  real ticks -> real ticks, 4 regimes incl. 2022 bear + 2020 crash);
  100-trade min; spread floor (never assumed); 0.5-3.0 pip slippage
  surcharge tiers on the canonical leg; OHLC-vs-tick degradation vs the
  expected 30-50% band reported per leg with inside_band flags, None
  (never guessed) on undefined baselines; verdict VERIFIED only when
  every required leg ran and passed — CLI exits 1 with explicit reasons
  without a terminal host.  README gains the "Research evidence, not
  promises" section.  Suite 357 tests green; ruff clean.
- 2026-09-04: Phase-G milestone (acceptance): all gates re-run for the
  final ten-section report (docs/PHASE3_FINAL_REPORT.md) — 357 tests
  green from the repo root, ruff clean on python+tests+tools, bench
  BEFORE/AFTER re-measured (FAST 74-82k bars/s ~1.6x vs TRUTH), banned
  tokens removed from chain-authored content, zero MQL5 files touched,
  MetaEditor line honestly NOT VERIFIED.  Pushed at 5734a85.
## Session log
## Session log
## Session log
- 2026-09-04: Phase-10 milestone: perf module + benchmark tool + tests
  committed; corrected benchmark measurement (untimed loops, scaled
  tracemalloc retention probe) and captured the phase evidence run
  (single run 22.6 ms ~21.3k bars/s; grid 100/1k/10k sets seq 2.2/22.2/
  296 s, par 1.9/18.6/250 s at 2 cores, equivalence PASS).  Phase-9
  blocker decision recorded in DECISIONS.md; 245 tests green.
## Session log
## Session log
## Session log
- 2026-09-04: Phase-B milestone (robust fitness): RobustFitnessConfig +
  composite_score pinned on hand fixtures; metric="composite" OPT-IN in
  grid_search/walk_forward with explicit config; OOS one-look policy
  documented; 273 tests green, ruff clean.
- 2026-09-04: Phase-A milestone (repair verifiability): root pytest via
  pythonpath, ruff clean python+tests, bench harness + BEFORE table,
  exit_reason/max_drawdown consumer audit; 268 tests green.
- 2026-09-04: Phase-12 milestone: portfolio research module (returns/
  correlation/covariance/vol, equal weight, HHI, currency exposure, heat,
  strategy overlap, allocation veto with zero-impact rejections) pushed;
  265 tests green.  Next: Phase 13 meta-layer.
- 2026-09-04: Phase-11 milestone: robustness gates module committed and
  pushed (PSR/DSR, trade MC, perturbation/SPP, CPCV+PBO, White RC/Hansen
  SPA, report stamping) with synthetic known-good/known-bad tests; 258
  tests green.
- 2026-09-04: Phase-10 benchmark milestone: perf module + tool committed
  (see log above); measured evidence recorded in CHANGELOG.
- 2026-09-04: Phase-9 blocker decision recorded (DECISIONS.md).
  Environment had been reset (local git truncated to base `817d20d`, 44
  dirty/untracked files, /tmp/venv gone): fetched origin, byte-verified
  all 75 files against `c0a49f6`, restored with `git reset --hard`, rebuilt
  /tmp/venv-mql5, re-verified 216 passed.  Phase-0 audit read
  HANDOFF/TASKS/PROGRESS/SPEC/IMPLEMENTATION_AUDIT/DECISIONS and traced
  engine/costs/dayclock/sizer/specs/optimizer/mt5tester.
- 2026-09-04: Plan-gap closures (6 commits, pushed): deterministic cost
  profiles ZERO/BASE/STRESSED/SEVERE with monotone-ledger engine test
  (plan 2 exit); WFA per-window param_hash/strategy_version/dataset_version
  + declared strategy versions (plan 7 outputs); adversarial future-mutation
  leakage pins across indicators/strategies/regime (plan 8 exit);
  docs/STATE_MODEL.md (plan 4) and docs/WFA_CONTRACT.md (plan 6).
  Suite: 239 green.
- 2026-09-04: Phase-8 metrics upgrade milestone committed/pushed: compute_metrics
  extended with recovery_factor, ulcer index, downside deviation, VaR/CVaR
  (95/99), rolling Sharpe median/worst, monthly win-rate/avg/std, trade
  median/avg pnl + duration, exposure/turnover approximations, max
  consecutive losses, HHI concentration, top-5 share, trailing-20
  expectancy/win rate — all legacy keys untouched (empty schema extended);
  9 new pinned tests in tests/test_metrics.py; 216 tests green.
- 2026-09-04: Phase-7 milestone `5306c47`: walk_forward leakage controls

  (embargo_bars keeps selection off OOS-adjacent bars; purge_bars drops
  boundary-censored selection trades with is_trades_purged reporting);
  automated leakage tests incl. a signal-level causality test for every
  registered strategy; 207 tests green.- 2026-09-05: PHASE 3 FINAL HARDENING (research-integrity blockers).
  NOTE (2026-09-05, integrity gate session): the original session
  commits (50b8f02..caa0bd3) were lost when the sandbox reset before a
  successful push (GitHub auth had expired); the preserved working tree
  was verified (436 passed, 1 skipped, ruff clean) and re-committed in
  full.  The hashes below refer to the LOST originals and are kept for
  the audit trail of what each fix contains:
  CPCV fold-isolated state model (BLOCKER 1): purged_cv_stage
  no longer scores folds from one full-sample stateful backtest — every
  span is evaluated on its own cold-start isolated simulation with a
  price-only warmup that never reaches a test-block interior; engine
  `warmup_bars` primitive added (TRUTH+FAST); adversarial state-leak
  suite (5 triggers: drawdown halt, equity sizing, daily-loss halt,
  open-position carry, position cap) each proving the old masked
  full-sample design contaminates training scores while the new stage
  stays bit-identical.
  `a02687a` docs/CV_STATE_CONTRACT.md (BLOCKER 2): data-vs-state
  leakage, per-span state table, what may/may never cross, WFA
  contrast, three never-reuse rules.
  `c3f7edf` Optuna matches its claims (BLOCKER 3): TPE+seed,
  HyperbandPruner wired in STEP units, trial.report/should_prune/
  TrialPruned on TRAINING-side dev-frame prefixes only, oos_guard_df
  refuses certifying-slice optimization, content-addressed per-step
  cache, deterministic study_name (Hyperband brackets), n_jobs option,
  7 acceptance tests; optuna 4.9.0 API confirmed.
  `f35b9a3` status model + zero-survivor blocking (BLOCKERS 5+7):
  mql5bot.status (SOFTWARE_PASS / EMPIRICAL_VALIDATION_PENDING /
  VERIFIED / FAILED / NOT_ELIGIBLE, MT5 NOT VERIFIED separate);
  run_stages S2-zero-survivors now BLOCKS S5 with NO_VALID_SURVIVOR
  (previously the screen leader silently became an OOS certification
  candidate); registry entries and certify reports carry explicit
  statuses.
  `484496e` OOS registry identity (BLOCKER 6): schema-2 content-digest
  identity (dataset content anchor, strategy/engine/cost-model/feature/
  protocol versions + cost-config digest); version bumps cannot mint a
  second look; tag changes refused; v1 migration; refused before any
  run.
  `9793035` FAST scope honesty + benchmark (BLOCKER 4): scope states
  array-based vs remaining Python loops, no Numba; profiler-driven
  micro-optimizations kept only where measured (strftime 4.7x, np.full
  cost series 78x); engine-level A/B measured at 1.001x — NO speedup
  claimed; docs/BENCHMARK_FAST.md with the full measured matrix
  (3k/30k/300k bars x 1/100/1000 sets) and the harness-defect log.
  `a54df4f` docs/MT5_ROUNDTRIP.md (BLOCKER 8): 8-step owner workflow,
  checklist, anti-fabrication rules.
  `060f9b0` scenario matrix: trend, mean-reversion (OU), slippage
  spike, commission x2 monotonicity, WFA state carry, restart
  equivalence, cache miss.
  Session totals: 437 tests collected (436 passed, 1 skipped — the optuna-optional guard skips when optuna is installed), ruff clean. MT5 compile: NOT RUN
  (no metaeditor64.exe in this sandbox). MT5 status: NOT VERIFIED.

- 2026-09-04: Phase-6 milestone `3c46d08`: `optimizer.walk_forward`
  rewritten on one scheduled engine run (no per-window capital resets);
  rolling-origin IS windows; per-window IS/OOS metrics, WFE, trade count,
  drawdown, cost, regime; engine rows carry `fees`/`costs` ledger columns
  (exact 7-tick x 2-leg decomposition pinned); `run_backtest` gained the
  engine `schedule` passthrough; 203 tests green.
- 2026-09-04: Phase-4 legacy wrapper milestone `345fb0e`: `backtest.py`
  rewritten as a thin canonical single-symbol wrapper over the portfolio
  engine (sizer + costs + DayClock; direct risk formula and calendar
  normalize() gone); `Instrument.params` channel on the engine (registry
  defaults < run-wide params < schedule segments); all 11 legacy tests
  green, two deliberately updated where they pinned removed legacy
  behaviour (below-min clamp-up to 0.01 lots; close-marked max-drawdown
  detection) — both documented in the commit message.  CHANGELOG suite
  count corrected to the authoritative 198 (previously asserted 172/143
  were stale); stale Notes line removed.
- 2026-09-04: Mission received. Phase 0 verified: tree clean at `1fc0289`,
  pytest 143, docs read; direct `risk/(stop*contract)` sizing confirmed in
  `backtest.open_trade`; single-`pos` engine; calendar-date resets;
  concatenating WFA confirmed in optimizer.walk_forward.
- 2026-09-04: Phases 1–3 committed (specs/sizer/dayclock/costs, 143 green).
- 2026-09-04: Canonical portfolio engine (`python/mql5bot/engine.py`) +
  profit-side tick value in `symbolspec.py` + 29 engine tests committed at
  `a77a5bf` and pushed (Phases 1/4/5 python): netting/hedging semantics,
  tick-valued PnL, exposure caps, server-day daily-loss/drawdown checks,
  swap/commission/reject/gap/margin costs, walk-forward param freeze.
  Engine validation fixes along the way: realized-PnL cash accounting,
  sub-tick PnL zeroing, tick-rounded fills, FIFO offset attribution,
  halt checks at bar open on prior-close equity.

## 2026-09-05 — PHASE 3 FINAL INTEGRITY GATE: SOFTWARE_PASS (16/16)

- Phases completed this session: (6) zero-survivor regression test
  verified present; (7) OOS failure/recovery policy documented+tested
  (failed run consumes no look; first success locks forever);
  (8) FAST benchmark fully re-run (A/B geomean 1.184x, prior 1.001
  superseded with explanation); (9) standing perf policy; (11) OOS-
  suffix leak regression for Optuna; (12) MT5 doc extended to the
  exact 10 steps + 5 states (all four tools verified present); (13)
  reproducibility manifests + run-twice equivalence; (14) full suite
  green; (15) 16-criteria gate record; post-PASS Meta Layer CONTRACT.
- Gate record: docs/PHASE3_GATE.md.  Meta contract:
  docs/META_LAYER_CONTRACT.md (contract only, no implementation).
- Final suite at gate: 482 passed, 1 skipped, ruff clean.
- NOTE (carried): the prior session's 10 commits (50b8f02..caa0bd3)
  were lost to a sandbox reset and reconstructed as 2714bbf; old
  hashes in earlier notes refer to originals that no longer exist.

## 2026-09-05 — META LAYER IMPLEMENTED (contract v1.1.0), SOFTWARE_PASS 30/30

- Contract hardened BEFORE code (ML-1..ML-7): simultaneous correlation
  snapshot, classified missing-data policy, all-zero vs global-failure
  semantics, normative normalization pipeline, determinism clauses,
  eligibility taxonomy, activation ladder, weight-change limit.
- python/mql5bot/meta_layer.py: typed domain model, eligibility engine
  (10 hard-block reasons), five factors (shrunk+winsorized OOS
  performance, pairwise corr min-30-obs, drift map), product score,
  deterministic normalization, four modes, attribution book, six
  tunables, canonical journals, activation ladder, SAFE HOLD.
- python/mql5bot/meta_oos.py: equal-weight baseline, purge/embargo
  fold diagnostics, ONE-LOOK OOS via OosRegistry (META_POLICY),
  frozen config hash.  tools/meta_validation.py: measured META vs
  EQUAL_WEIGHT + profile; docs/META_LAYER_VALIDATION.md (red team
  16 fixed + 1 waived; activation = SHADOW_ONLY max; 30/30 gate).
- mql5: Allocation.mqh strict consumer + single reduce-only sizing
  seam in Mql5Bot.mq5 (after RiskManager.GetLots); parity by
  construction; compile remains NOT RUN IN SANDBOX.

---
## Final Convergence (2026-09-06)

- Restored sandbox state fast-forward from origin after rollback;
  preserved a parallel workstream in stash + patch (not merged).
- Campaign manifests (§16) + lineage (§13) + trial accounting (§17);
  resume refuses foreign policy AND foreign dataset.
- Concentration report (per-axis HHI) + UNKNOWN-honest correlation
  classification; post-scale realized caps enforced.
- Entry chain with §57 order + origin authority; approval records bind
  evidence hash + policy version; machine self-approval refused.
- Full-chain acceptance (§75) + negative (§76) + safety (§77) +
  capital (§78) + scale (§79/§80) + retirement (§81) on the REAL
  engines (synthetic data, honestly labeled).
- Static architecture scans (§68); CI gains ruff + Alembic smoke.
- Final suite: see docs/AEGIS_FINAL_CONVERGENCE_AUDIT.md §84 report.

## Mission 6 — Reality Gate (execution boundary)

- Mission-5 final commits restored after the sandbox wipe (556858c,
  abea0f4) and pushed.
- Gold Standard frozen: ema_crossover_ref @ artifacts/gold/manifest.json
  (fixture, python/dsl traces, expected execution, reconciliation;
  MT5 fields PENDING_OWNER — never fabricated).
- Python↔DSL parity proven byte-exact; sizing parity vs MQL5 GetLots
  transcription; Meta seam only-reduces; kill-switch first-gate seam;
  allocation round-trip; both-touch stop-first; causality properties.
- docs/AEGIS_REALITY_GATE_AUDIT.md: full contract map + deterministic
  owner MT5 protocol + §72 status model (PRODUCTION = NOT_READY).
