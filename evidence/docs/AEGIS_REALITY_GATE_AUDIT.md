# AEGIS — REALITY GATE AUDIT

**Mission:** Python → DSL → MQL5 → MT5 gold-standard reconciliation
(execution-boundary proof). **Branch:** `arena/01a070b0-mql5bot`.
**Frozen Gold Standard:** `ema_crossover_ref` @
`artifacts/gold/manifest.json` (hash `4bb14203…89a7766b2cf0e278e`).

Nothing here fabricates terminal evidence. Every claim carries its
evidence pointer; every owner-only gate is `BLOCKED_OWNER_ENVIRONMENT`
with the exact owner action (§ owner-protocol below).

---

## §1 Reconciliation record

```text
commit         694550c (this audit's parent chain: ed21cb3 gold artifacts,
               c9247f4 reality-gate tests; mission-5 restored first:
               556858c caps/trail, abea0f4 docs §95)
branch         arena/01a070b0-mql5bot (remote synced; never force-pushed)
remote         origin = same tip; main is an ANCESTOR of this branch
               (verified: `git merge origin/main` → "Already up to
               date") — the branch already contains all owner work,
               including tools/run_mt5_backtest.py, docs/MT5_ROUNDTRIP.md,
               mql5/Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5
working_tree   clean at baseline
sandbox note   the workspace was wiped and re-cloned mid-session; the
               last two mission-5 commits (never pushed) were restored
               by content before this mission started
pytest         1190 collected / 1189 passed / 1 skipped (optuna-
               present guard, test_pipeline.py:403) / 0 failed (~330 s)
ruff           All checks passed (`ruff check python tests` — CI scope)
```

## §2 Cross-runtime contract map (every seam, its two sides, its proof)

| # | Contract | Python side | MQL5 side | Proof (test / artifact / source) | State |
|---|---|---|---|---|---|
| 1 | Strategy identity | `examples/strategies/ema_crossover.json` → `spec_hash` | EA inputs `InpFastEma=10, InpSlowEma=30, InpSlAtr=2.5, InpTpAtr=4.0` | `manifest.json`; `test_indicator_parity_python_vs_mql5_ema_transcription` (source pins) | MATCHED (source-level) |
| 2 | Signal semantics | `strategies.ema_crossover`: closed-bar state, fast>slow→+1, fast<slow→−1 | `SignalEngine.EvaluateEmaCrossover`: `EMA(h,1)` shift-1, same comparisons | `test_python_and_dsl_traces_agree_exactly`; SignalEngine.mqh:96–114 | MATCHED (Python↔DSL exact; MQL5 source-equivalent) |
| 3 | Indicator EMA | `indicators.ema` (α=2/(n+1), SMA seed) | MT5 `iMA MODE_EMA` (α=2/(n+1), price[0] seed) | transcription test: WARMUP-classified seed difference decays <1e-6 by bar 60 | MATCHED modulo classified WARMUP seed |
| 4 | Indicator ATR | `indicators.atr` Wilder period 14 | `iATR(symbol, tf, 14)` Wilder | trace equality (<1e-9) + source pin | MATCHED |
| 5 | Signal timing | signals from closed bars, act at NEXT bar open | `OnNewBar()` = first tick of new bar; market order | `test_signal_timing_contract_frozen`; backtest.py docstring contract | MATCHED (contract frozen in manifest) |
| 6 | SL/TP geometry | engine: `sl_atr×ATR[bar−1]`, min-stop enforced, TP no slip, both-touch → stop first | `FillPriceLevels`: fill ∓ slAtr×ATR(shift1), spread guard; SlGuard post-fill verify | `test_both_touch_bar_resolves_stop_first` + micro fixture | MATCHED (Python); MQL5 path owner-tested |
| 7 | Risk sizing | `sizer.size_position` (risk % equity, never round up, below-min REJECT, min-stop, margin calc injected) | `RiskManager.GetLots` (same budget/lossPerLot/normalize; margin via OrderCalcMargin + exact-rescale) | `test_sizing_parity_python_sizer_vs_mql5_formula` (scenario grid, identical lots + rejection semantics) | MATCHED (formula parity) |
| 8 | Broker spec | `SymbolSpec` injected snapshot | `SymbolSpec.mqh` runtime snapshot (`Spec*` primitives; owner export script) | `test_broker_symbol_parity.py` FIELD_MAP + fail-fast export | MATCHED (machinery); real broker export = owner step |
| 9 | Currency conversion | `profit_to_deposit` injected, never assumed 1.0; missing → refuse | `ProfitToDeposit` queried at runtime; unavailable → GetLots refuses | sizer/broker-parity tests; RiskManager.mqh:216–220 | MATCHED (refuse-both-sides) |
| 10 | Meta allocation | governor → Meta weight; entry chain `min(requested, Meta×budget)` | `g_alloc.ScaleLots` AFTER GetLots, ONLY reduce, Clamp01, unknown id under ACTIVE → 0, stale/missing → base gate | `test_meta_seam_only_reduces_and_drops` (weights 1/0.5/0.1/0.01/0.0, DROP ≤ volume_min); EA ordering source-pinned | MATCHED |
| 11 | Allocation file | `meta_layer.write_allocation_file` (atomic, self-digest) | `Allocation.mqh` strict scanner + SHA-256 digest + staleness | `test_gold_allocation_roundtrip` (write→read→tamper-refused→stale-flagged); `test_allocation_digest.py` byte-layout reconciliation | MATCHED |
| 12 | Kill Switch | entry chain: `kill-switch` veto owner; sticky states | `AllowsNewTrades()` is the FIRST gate of `OnNewBar`, before signal evaluation; state hot-persisted (S2); explicit reset input only | `test_kill_switch_is_the_first_entry_gate_in_the_ea`; `test_mql5_sources.py::test_s2_*`; MT5 REAL execution proof = owner step (§29) | MATCHED at seam (source); real-fill proof PENDING_OWNER |
| 13 | Circuit breaker | breaker freeze + keep-last-safe (Python) | allocation file is the only risk-relevant input the EA reads; a frozen Python layer simply stops writing new weights → EA keeps last valid file (base gate on staleness) | breaker tests (mission 4); Allocation.mqh staleness | MATCHED (architecture) |
| 14 | Retry / no-Sleep | — (EA-owned) | `RetryQueue` OnTimer exponential backoff, bounded `InpMaxRetries`; zero `Sleep(` in trading path | `test_mql5_sources.py::test_s3_*`, `test_retry_queue_*` | MATCHED (source-level) |
| 15 | Restart | — (EA-owned) | `StateStore` hot save/reload; ticket registry adoption; orphan pending cancel | `test_mql5_sources.py::test_s2/s6` | MATCHED (source-level); real restart = owner step |
| 16 | Netting/hedging | — (EA-owned) | margin-mode detection present; single managed position; magic = FNV-1a(strategy id) | `test_margin_mode_detection_*`, `test_s5_magicmap_*` | MATCHED (source-level); broker-real proof owner step |
| 17 | Observability IDs | journal + store reconstruction (`/strategies/{sid}/trail`) | EA journal lines: ENTRY/DEAL with ticket, lots, sl/tp; telemetry trade events | `discovery/journal.py` + Logger.mqh/Telemetry.mqh | MATCHED (design); correlation-ID deep-link = §39 gap below |
| 18 | MTF (§9) | gold standard uses NO MTF — not applicable on this ladder | — | registry MTF closed-bar property tests stand | NOT_APPLICABLE (gold); registry-level PASS |
| 19 | Pivot/confirmation (§10) | gold standard uses NO pivot indicator | — | registry pivot tests (signal_time ≥ confirmation_time) stand | NOT_APPLICABLE (gold); registry-level PASS |

**Verdict:** every sandbox-side contract is matched or explicitly
classified; NOTHING is silently tolerated. The unproven remainder is
exactly and only the owner-terminal ladder (compile → tester → golden
run → reconciliation), for which the deterministic protocol follows.

## § owner-protocol (§74 — deterministic MT5 steps, do not improvise)

> **SUPERSEDED numbering — labelled SHORTCUT.** The canonical owner
> protocol is the TEN-step sequence in `docs/MT5_ROUNDTRIP.md` ("The
> canonical owner sequence"). The nine-step list below is retained as a
> historical SHORTCUT view from this audit; the mapping to canonical
> numbers is given inline. Where the two ever disagree, MT5_ROUNDTRIP.md
> wins.

Precondition: Windows + MetaTrader 5 + MetaEditor; repo at this commit.

1. **Compile gate.** `powershell -File tools/compile.ps1 -Strict`.
   Record: compiler version, exit code, 0-error/0-warning count read
   from `logs/compile-<stamp>.log`, SHA-256 of each fresh `.ex5`.
   Any error/warning → STOP, record `SOFTWARE_FAIL`.
   *(canonical steps 1–2)*
2. **Symbol spec export.** Compile + run
   `mql5/Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5` on the demo
   broker for **EURUSD H1**. It writes the fail-fast broker export
   consumed by `tools/broker_symbol_parity.py`. Run
   `python tools/broker_symbol_parity.py` — the FIELD_MAP comparison
   must show every field PENDING→RESOLVED with the exported values.
   *(canonical step 3)*
3. **Fixture import.** Copy `artifacts/gold/gold_fixture.csv` into the
   terminal as H1 bars for a custom offline symbol (or request the
   broker's EURUSD H1 for the SAME window 2024-01-01T00:00→2024-01-06
   and use `Mql5BotDownloadData.mq5`; the fixture CSV is the
   controlling dataset — custom-symbol import is preferred so bars are
   identical to the hash in `manifest.json` → `dataset_hash`).
   *(canonical step 4)*
4. **Tester run.** `python tools/run_mt5_backtest.py run --config
   <gold job>` with: strategy=EMA_CROSSOVER, FastEma=10, SlowEma=30,
   SlAtr=2.5, TpAtr=4.0, sizing=RISK_PERCENT_EQ, RiskPercent=1.0,
   deposit=10000 USD, leverage as exported, spread fixed 1 point,
   model grade M1-OHLC **and** Every tick (both legs, per
   docs/MT5_ROUNDTRIP.md canonical steps 5–6; the real-ticks leg is
   canonical step 7). Archive the RAW HTML reports.
   *(canonical steps 5–7)*
5. **Parse.** `python tools/run_mt5_backtest.py parse <report.html>` —
   numbers only from the extractor, never hand-typed.
   *(sub-step of canonical steps 5–7)*
6. **Golden reconciliation.** Compare the parsed deal list against
   `artifacts/gold/expected_execution.json` +
   `artifacts/gold/reconciliation.json` field-by-field (§41 field
   list). For each field record MATCH / DIVERGENT + magnitude +
   classification (ROUNDING / WARMUP / SOURCE_SEMANTICS /
   TIMEFRAME_SEMANTICS / IMPLEMENTATION_BUG / UNRESOLVED). Fill
   `mt5_report.json` + `mt5_journal.txt` from the real artifacts only.
   *(canonical step 8, comparison part)*
7. **Kill-switch seam proof (§29).** With the EA on the demo symbol:
   latch the kill switch (StateStore file or drawdown trip), then feed
   the fixture — the journal must show ZERO new orders while
   `AllowsNewTrades()==false`, and the ENTRY line must be absent.
   *(canonical step 8a)*
8. **Restart proof (§27).** Restart the EA mid-fixture; verify no
   duplicate exposure, state reload line, unchanged magic.
   *(canonical step 8b)*
9. **Archive.** Commit `artifacts/gold/mt5_report.json`,
   `mt5_journal.txt`, the raw reports, and the compile log. Update
   `reconciliation.json` `python_vs_mt5_tester` from PENDING_OWNER to
   the observed verdict — as observed, never normalized.
   *(canonical steps 9–10; state assignment itself is canonical step 10)*

Any step that cannot run ⇒ that gate stays
`BLOCKED_OWNER_ENVIRONMENT`. Do not simulate, do not sample, do not
extrapolate.

## §55/§56 — watchdog verdict

Internal watchdog: implemented + component-tested (rate-limited alerts,
fail-safe both directions). EXTERNAL deployment: no watchdog
infrastructure exists in this sandbox ⇒ `WATCHDOG = PARTIAL`
(protocol + EA telemetry heartbeat implemented and source-pinned;
external harness `NOT_IMPLEMENTED` by design, deployment owner-side).
The external monitor needs only: heartbeat, equity, drawdown, open
positions, trade count, broker status, safety status — never
Factory/LLM/ML internals (`docs/EXTERNAL_WATCHDOG.md`).

## §62/§63 — real data

No real broker/market access in this environment. The repo contains the
owner-provided real-data tooling (`tools/fetch_real_data.py`) and one
real sample (`tests/data/real/vix_daily.csv` + `manifest.json`, hashed
provenance). The gold ladder runs on the deterministic fixture by
design; the realistic multi-asset basket (EURUSD/GBPUSD/USDJPY/XAUUSD…)
is `REAL_DATA = UNAVAILABLE` in this env and stays owner-side. No
symbol was pretended into existence.

## §64/§65 — demo plan & LIVE_SMALL readiness

Demo plan = docs/MT5_ROUNDTRIP.md canonical TEN-step owner sequence plus
the owner SHADOW table (11 steps), run ≥4 weeks on demo with telemetry
active; a short smoke test is explicitly NOT "demonstrated robustness".

`LIVE_SMALL_READY = NO`.

Gates not yet genuine: MT5 compile unproven, Strategy Tester unproven,
Python↔MT5 golden-run reconciliation unproven, demo evidence absent.
No automatic activation exists or will be added.

## §57/§58 — security & red team at the execution boundary

Standing suites: `test_dsl_security`, `test_factory_security`,
`test_factory_redteam`, `test_discovery_redteam`,
`test_convergence_static` (order-send AST ban, provider no-network,
no shell/dynamic exec in governance, UI cannot mark LIVE).
Reality-Gate additions: `test_python_never_sends_orders`,
`test_kill_switch_is_the_first_entry_gate_in_the_ea`,
`test_meta_seam_only_reduces_and_drops`,
`test_gold_allocation_roundtrip` (tamper/stale/digest),
`test_below_minimum_lots_never_become_orders`.
§58 matrix status: 1–14, 22, 26–29 covered by named tests (safe
expected results asserted); 15–21, 23–25, 30 are EA-behaviour items
proven at source level and owner-proven at runtime per protocol.
No HIGH/CRITICAL finding is open.

## §59 — property/metamorphic status on the gold ladder

| # | property | proof |
|---|---|---|
| 1 | same manifest → same Python trace | `test_gold_manifest_and_fixture_deterministic` |
| 2 | same manifest → same DSL trace | same test (byte-identical) |
| 3 | same manifest → same MQL5 expected semantics | manifest timing contract + EA source pins; runtime = owner leg |
| 4 | future data never changes past decisions | `test_future_mutation_never_changes_past_decisions` |
| 5 | display-name change ≠ identity change | identity = `strategy_id`+`spec_hash` (normalize); signals proven name-independent via DSL/runtime tests |
| 6 | dataset change invalidates evidence | §54 identity + `test_reproducibility.py` |
| 7 | policy change invalidates decisions | gate policy hash binding (store/gates tests) |
| 8 | degradation never raises allocation | decay monotonicity tests (mission 4 suite) |
| 9 | below-min lots never become orders | `test_below_minimum_lots_never_become_orders` |
| 10 | kill switch always blocks new entries | `test_kill_switch_is_the_first_entry_gate_in_the_ea` + entry-chain suite |
| 11 | breaker retains last safe allocation | breaker suite (mission 4) |
| 12 | restart does not duplicate trades | EA StateStore/adoption source tests; runtime = owner leg |
| 13 | allocation reload is atomic | writer temp+replace; scanner refuses partial (`test_allocation_digest`) |
| 14 | evidence cannot cross strategy/version | store evidence binding tests (mission 3/4) |
| 15 | Python↔DSL agree before MQL5 comparison | `test_python_and_dsl_traces_agree_exactly` (hard gate) |

## §72/§81 — final status model (independent, never collapsed)

```text
SOFTWARE                  PASS    full suite green; ruff clean
DSL                       PASS    canonical v1.0; gold spec frozen
INDICATOR UNIVERSE        PASS    71 kinds; gold EMA/ATR parity proven (RESEARCH surface only — binding scope model: docs/CERTIFICATION.md §Certification scope surfaces; MQL5 parity of new kinds BLOCKED_OWNER_ENVIRONMENT)
FACTORY                   PASS    research-only; no order path (AST)
RESEARCH                  PASS    IS-only selection, ONE OOS look
OOS                       PASS    structural firewall (standing suites)
PORTFOLIO                 PASS    concentration/heat/UNKNOWN-correlation
META                      PASS    allocation-only; never widens risk
SAFETY                    PASS    Meta≤Risk≤KillSwitch; breaker freeze
SECURITY                  PASS    boundary scans + red-team suites
PYTHON↔DSL PARITY         PASS    gold traces byte-equal (this mission)
PYTHON↔MQL5 PARITY        PARTIAL formula/source parity proven (sizing,
                                  signal, seams); runtime divergence
                                  unknown until the tester leg
MQL5 SOURCE AUDIT         PASS    4,933 lines; single OrderSend path
MT5 COMPILE               BLOCKED_OWNER_ENVIRONMENT  (§ owner-protocol 1)
MT5 STRATEGY TESTER       BLOCKED_OWNER_ENVIRONMENT  (§ owner-protocol 3–5)
PYTHON↔MT5 RECONCILIATION BLOCKED_OWNER_ENVIRONMENT  (§ owner-protocol 6)
DEMO                      NOT_IMPLEMENTED  (plan ready; owner-run)
WATCHDOG                  PARTIAL  internal done; external NOT_IMPLEMENTED
LIVE_SMALL_READINESS      NO       (§65 gates unmet — by design)
PRODUCTION                NOT_READY
```

## §83 — the fifteen questions, answered with evidence

* **Q1 Python intended signal?** YES — `python_trace.json` (16 trades,
  long/short/SL/TP/flip legs, deterministic).
* **Q2 DSL identical?** YES — `dsl_trace.json` byte-equal bars/trades;
  `reconciliation.json python_vs_dsl = MATCHED`.
* **Q3 MQL5 same signal?** SOURCE-EQUIVALENT — SignalEngine shift-1
  state logic + EA defaults pinned in tests; runtime proof = owner leg.
* **Q4 Risk same approved risk/lots?** YES at formula level —
  `test_sizing_parity_python_sizer_vs_mql5_formula` (identical lots and
  identical rejections on the grid); runtime = owner leg.
* **Q5 Meta only reduces?** YES — Clamp01 multiply, DROP at/below
  volume_min, ordering source-pinned after GetLots.
* **Q6 Broker normalization safe?** YES — floor-to-step never up; caps
  = min(volume_max, volume_limit, max_lots); below-min rejected.
* **Q7 MQL5 sends expected order?** PENDING_OWNER (tester leg).
* **Q8 MT5 shows expected fill?** PENDING_OWNER.
* **Q9 Position has expected SL?** Python: yes (engine + SlGuard design;
  both-touch stop-first proven). MQL5 runtime: PENDING_OWNER.
* **Q10 Attribution matches strategy/version?** YES at design level —
  FNV-1a magic per strategy id + allocation `strategy_versions`;
  runtime = owner leg.
* **Q11 Reconciliation agrees?** Python↔DSL: fully. Python↔MT5:
  PENDING_OWNER by explicit, non-fabricated state.
* **Q12 Kill Switch stops a real attempted entry?** Seam-proven both
  sides (first gate, before signal evaluation; sticky state; explicit
  reset). Real-fill proof = canonical owner step 8a
  (docs/MT5_ROUNDTRIP.md).
* **Q13 Breaker prevents unsafe allocation jumps?** YES (Python freeze +
  keep-last-safe, tested); EA consumes only the last valid file.
* **Q14 Restart preserves safe state?** Source-proven (StateStore hot
  save/reload, adoption, bounded retry); runtime = canonical owner step
  8b (docs/MT5_ROUNDTRIP.md).
* **Q15 Owner can reproduce everything?** YES — the canonical owner
  protocol is the deterministic TEN-step sequence in
  docs/MT5_ROUNDTRIP.md over committed artifacts with recorded hashes
  at every step (the nine-step list in §owner-protocol above is the
  superseded SHORTCUT view with the mapping annotated).

## §84 conclusion

`PRODUCTION = NOT_READY` — exactly these gates remain, in order:
(1) MT5 compile, (2) broker symbol-spec export round-trip,
(3) Strategy Tester gold legs (M1-OHLC + Every tick), (4) golden-run
reconciliation vs the frozen artifacts, (5) kill-switch/restart
runtime proofs, (6) ≥4-week demo per the SHADOW table. Python-validated
≠ MQL5-validated ≠ MT5-validated ≠ Demo-validated ≠ Live-validated:
the distinction is preserved everywhere in this report and in the
artifacts.

## §85 execution-authority source scan (FINAL REALITY-GATE §12, 2026-09-08)

Full-tree scan (`OrderSend`, `PositionModify`/`OrderModify`, `CTrade`,
`order_send`, `MetaTrader5` imports, execution subprocesses). Every
match classified:

| match | classification |
|---|---|
| `TradeManager.mqh` — 5× `OrderSend` | **THE** execution authority (entries, exits, SL/TP, retry path) |
| `Mql5Bot.mq5:355` — one `OrderSend(TRADE_ACTION_REMOVE)` | documented exception: restart-time orphan-pending CANCEL (recovery, never new exposure); failures hand to the RetryQueue |
| `SlGuard.mqh` / `PositionGuard.mqh` | modify/handling routes go THROUGH `CTradeManager` (Pump takes `CTradeManager&`) — no direct sends |
| `data.py` `import MetaTrader5` | read-only bar fetcher (`copy_rates_from_pos`) — data adapter, zero trade calls |
| `factory/security.py` `order_send` | a BAN-regex guard (red-team boundary), not execution |
| Factory / Research / ML / LLM / Meta layers | order-send-free (AST bans + red-team suites enforce) |

Conclusion: exactly ONE execution authority (TradeManager) plus its one
documented restart-cancel exception. Unchanged from the earlier audit;
re-verified against the current tree.

## §86 CI vs owner evidence — the two evidence classes (FINAL REALITY-GATE §24)

These classes are NEVER merged anywhere in the status model:

**LOCAL CI PROVES** — deterministic Python behavior; unit/golden
regression; Gold #1 (frozen, byte-identical regen) and Gold #2
(`GOLD_2_RECONSTRUCTED_NEW_PROVENANCE`, frozen) semantic integrity;
provenance hash chains and mutation batteries; source scans
(execution authority, UI can't mark LIVE, order-send bans);
certification-tool integrity (fail-closed state machine, report gate,
NOT_EXECUTABLE seam); documentation consistency pins.

**OWNER ENVIRONMENT PROVES** — actual compilation (fresh `.ex5`, 0/0);
actual broker SymbolSpec; actual Strategy Tester execution on the
three model grades; real-tick coverage evidence; Python↔MT5
reconciliation of both gold standards; runtime safety proofs
(kill-switch, restart matrix, retry/adoption, SL verify-modify-reverify,
netting/hedging legs); the ≥4-week demo phase.

Local green can raise the RESEARCH surface to PROVEN only; it can never
raise any MT5 dimension above NOT VERIFIED (`status.py`, pinned by
tests).

## §87 documentation consistency table (FINAL CERTIFICATION MODEL LOCK §8, 2026-09-08)

Full-doc scan for: Gold, 100 trades, VERIFIED, MT5-VALIDATED, research
validation, generated strategy, DSL, 71 indicators, five MQL5
strategies, real ticks, owner validation.

| Concept | Canonical definition | Docs using it | Status |
|---|---|---|---|
| Gold lane (semantic) | frozen fixtures, exact reconciliation, NO trade-count minimum; Gold #2 valid at 56 trades | CERTIFICATION.md §Two certification lanes, MT5_ROUNDTRIP.md §two lanes, README, HANDOFF, continuation §17 | CONSISTENT |
| Empirical lane | regime × model ladder, 100-trade minimum per required leg, spread floor, degradation observed | CERTIFICATION.md gates, MT5_ROUNDTRIP steps 5–7/state table, PHASE3_FINAL_REPORT:127, HANDOFF | CONSISTENT — threshold scoped to the empirical lane everywhere |
| VERIFIED | full ladder pass on a real terminal WITH recorded reconciliation; terminal owner only | CERTIFICATION.md, MT5_ROUNDTRIP state table, status.py, certify.py | CONSISTENT — reconciliation fail-closed in code |
| MT5-VALIDATED | MT5 dimension = every required leg ran ok (owner environment) | README vocabulary, MT5_ROUNDTRIP mapping, continuation §17 | CONSISTENT — never produced by Python-only evidence |
| GOLD_SEMANTIC_PASS | Layer-B dimension; never implies MT5_VALIDATED/VERIFIED | status.py, README, CERTIFICATION.md lanes | CONSISTENT (new this lock) |
| RESEARCH-VALIDATED | deterministic Python pipeline evidence | README, CERTIFICATION.md scope model, AUDIT §86 | CONSISTENT |
| Generated strategy → MQL5 | NOT possible directly; EA = five enum engines, no DSL interpreter; unsupported kinds NOT_EXECUTABLE fail-closed | README (pinned), CERTIFICATION.md scope surfaces, continuation §17 Q10, code pins | CONSISTENT — false "same EA pipeline" claim removed + pinned |
| 71 indicator kinds | research-universe contract surface, NOT 71 MQL5 executables | README, AUDIT §205 annotated, CERTIFICATION.md scope | CONSISTENT |
| Five MQL5 strategies | ENUM_MQL5BOT_STRATEGY exactly five members (source-pinned) | README, CERTIFICATION.md, test_docs_contract source pin | CONSISTENT |
| Real ticks | official MT5 semantics incl. generated-tick fallback; FULL/PARTIAL/UNKNOWN coverage | MT5_ROUNDTRIP step 7 rule, mt5tester vocabulary, HANDOFF | CONSISTENT |
| Owner validation | canonical TEN steps, one protocol, SHORTCUT rule for all others | MT5_ROUNDTRIP (single source), AUDIT §owner-protocol labelled SHORTCUT, HANDOFF OWNER ACTION REQUIRED | CONSISTENT |
| Demo / live | separate layers E/F, never automatic, PRODUCTION = NOT_READY | AUDIT §84/§86, MT5_ROUNDTRIP SHADOW table, demo checklist (new), HANDOFF | CONSISTENT |

Zero contradictions remain; every historical conflict (README DSL
claim, taxonomy variants, RSI dual classification, Gold-vs-100-trade
reading) is resolved and pinned.

## §88 stale-artifact attack matrix (OWNER MT5 EXECUTION GATE §29, 2026-09-08)

Every attack in the mission's list, its enforcement point, and its
evidence. Sandbox-enforced attacks are test-pinned; owner-side attacks
are enforced by the canonical protocol's pre-flight and binding rules
(`artifacts/owner_mt5_gate/README.md`).

| Attack | Enforcement point | Evidence |
|---|---|---|
| old EX5 + new source | `compile.ps1` freshness check + `-Strict` exit codes; EX5 newer than compile start | protocol step 1–2; compile_metadata.json |
| stale/cached EX5 reused | same + EX5 SHA-256 recorded per fresh binary | anti-fabrication rule 6; README compile provenance |
| new EX5 + old config | config hash bound in the gold manifests + tester ini echoed into every artifact | frozen_inputs.json pre-flight; `TesterConfig` snapshot |
| old report + new fixture | report deleted before each run; dataset hash re-checked before AND after legs | mt5tester.run_backtest; protocol step 4 |
| stale report | timestamp + config/symbol/commit/fixture-hash binding per attempt | anti-fabrication rule 6 |
| wrong broker SymbolSpec | actual export mandatory; synthetic spec never substitutes; per-field comparison classes | protocol step 3; `broker_symbol_parity.py` |
| wrong symbol / timeframe / model | `TesterConfig.validate` rejects unknown values; report Model line vs requested model | tests/test_certify_redteam.py; protocol §tester-model triad |
| wrong source commit | `frozen_inputs.json` pins the exact commit; mismatch = STOP | owner package pre-flight |
| missing report / missing sidecar | leg recorded as NOT run (never guessed) | mt5tester.run_backtest; protocol steps 5–7 |
| edited / empty / truncated / non-report file | `report_gate` refuses (no tables or no rows ⇒ not an ok leg; raw preserved) | tests/test_certify_redteam.py (battery) |
| malformed JSON config / unknown keys | `certify_strategy._load_config` rejects unknown keys | tools/certify_strategy.py |
| skipped real-tick leg | ladder verdict requires EVERY required leg; UNAVAILABLE recorded with reason, never FAILED, never silently omitted | certify.verdict_for; protocol step 7 |
| partial real ticks claimed FULL | coverage record mandatory; UNKNOWN is the default; FULL needs positive proof | real_tick_coverage.json; protocol §real-tick coverage rule |
| 100 trades without reconciliation | `run_certification(reconciliation_ok=…)` withholds the verdict fail-closed | tests/test_certify.py + test_status_model.py |
| gold pass claimed as MT5 validation | independent dimensions; GOLD_SEMANTIC_PASS never upgrades | tests/test_certify.py::test_gold_semantic_pass_never_produces_verified |
| unsupported strategy claimed executable | NOT_EXECUTABLE seam refuses tester legs before any runner | tests/test_certify_redteam.py |

All attacks fail closed; none depends on owner honesty — each has a
mechanical check or a pinned test.

## §89 FINAL PRE-OWNER ADVERSARIAL AUDIT — findings (2026-09-08)

Purpose: prove the boundary between DETERMINISTIC SOFTWARE EVIDENCE
and ACTUAL MT5 RUNTIME EVIDENCE is airtight before owner execution.
Status target unchanged: `REALITY_GATE_BLOCKED` / `PRODUCTION =
NOT_READY`. The verifier may be `PROVEN_READY` while MT5 stays
`BLOCKED_OWNER_ENVIRONMENT`.

README / source-truth audit (§2–§3): the remote README already states
the five built-in engines are the ONLY MQL5 execution surface, "no DSL
interpreter", and the 71-kind universe is research-surface only; both
claims are test-pinned (test_docs_contract). No contradiction found.
The three-surface canonical statement (research / execution /
owner-pending) lives in docs/CERTIFICATION.md §Certification scope
surfaces and matches source (ENUM_MQL5BOT_STRATEGY = 5 entries).

Real defects found and fixed this pass:

1. Reconciliation bindings declared EX5 / SymbolSpec / report hashes
   but never verified them against the actual bytes — a downstream
   record could conceal upstream tampering. Now `verify_reconciliation`
   recomputes the SHA-256 of the EX5, the SymbolSpec, and every parsed
   report and fails closed on any mismatch (§9 hash-chain).
2. Compile metadata accepted a future COMPILE_TIMESTAMP. Now a
   timestamp beyond the drift band is INVALID (impossible evidence)
   (§10). Timezone offsets at the same instant remain accepted.
3. Real-tick coverage was not cross-checked against the owner
   SymbolSpec or its own model triad. Now a wrong symbol/broker, an
   actual≠requested model (silent fallback), a FULL claim with a
   mismatched interval, or prose-only evidence all fail closed (§12).
4. Safety raw_evidence accepted prose ("passed", "seems fine"). Now it
   must bind a journal/log/report artifact; prose-only and
   screenshot-only both fail (§19).
5. The owner README's artifact table contradicted the verifier's
   LAYOUT (stale 16-slot draft filenames). Replaced with the exact
   29-file contract and pinned to LAYOUT by
   test_docs_contract::test_owner_readme_matches_verifier_layout_exactly
   so the contradiction cannot return (§6).

Confirmed-already-safe (no change needed): trade_gate(99) fails and
gold is untouched; empirical-only vs gold lane separation is
test-pinned; MT5 Python bridge is data-only (load_mt5, no order_send /
positions_modify / positions_close); Gold #1 regen byte-identity and
Gold #2 hash-chain detect one-byte tampering (proven by live tamper →
detect → git-restore); triage procedure forbids dual-patching and now
mandates re-running both golds after a single-sided fix.

Net effect: stricter verifier, accurate owner contract, no new trading
logic, no gold mutation, status unchanged. The next milestone remains
ACTUAL MT5 EVIDENCE from the owner environment.

## §90 VERIFIER EVIDENCE-BINDING HARDENING (FINAL PRE-OWNER §4–§11, 2026-09-08)

Principle enforced: A FILE PATH STRING IS NOT EVIDENCE. Only a
cryptographically bound, provenance-consistent, runtime-generated
artifact chain is evidence.

Hardened (verifier + contract + tests, no trading semantics touched):

1. Real-tick FULL coverage evidence is now a file binding
   {path, sha256}: file inside the evidence root, hash match, and the
   bound journal must name THIS symbol and THIS interval. Prose, bare
   paths, escapes, missing/unhashed/other-run journals all rejected
   (attack matrix A–L pinned).
2. Safety raw_evidence is file-bound the same way for all eight
   evidence classes (six runtime tests + netting + hedging); prose,
   "journal:..." claims, screenshots, altered/missing/escaped/wrong-
   hash files all fail closed; hedging keeps its BLOCKED_OWNER_
   ENVIRONMENT exception and nothing else may claim it.
3. environment.json binds the run (os/terminal/broker/server/account
   mode/symbol/timezone/run timestamp) and any contradiction with the
   owner SymbolSpec is MISMATCHED.
4. archive_manifest.json must bind EVERY file by SHA-256 plus the
   frozen source/fixture identities — filename lists rejected;
   one-byte mutation of any bound artifact is caught.
5. Raw tester reports join the binding chain
   (raw → parsed → reconciliation): reconciliation must bind
   raw_report_hashes per model, verified against actual bytes.

Owner ergonomics: `tools/owner_evidence_bind.py` computes every
binding (`bind <file>`, `manifest <dir>`) — the owner never hand-types
a hash. README gains the file-binding contract and the ten-step flow.

Gate: 1518 collected / 1517 passed / 0 failed / 0 errors / 1 skipped /
0 warnings; ruff clean; Gold #1 regen byte-identical; Gold #2 hash
chain green; five-engine enum intact; zero order authority outside the
documented layers; 100-trade minimum confined to the empirical lane.

Status unchanged: REALITY_GATE_BLOCKED / PRODUCTION = NOT_READY; the
verifier itself is OWNER_EXECUTION_READY while MT5 runtime evidence
remains BLOCKED_OWNER_ENVIRONMENT.
