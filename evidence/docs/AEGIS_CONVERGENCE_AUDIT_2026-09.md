# AEGIS convergence audit & gap closure — 2026-09 (Mac/code agent)

> **Lane.** CODE-side work on Mac. All MT5/MetaEditor/Strategy-Tester/
> broker/EX5 reality remains **OWNER-PENDING** and is never fabricated.
> Repo stays fail-closed and provenance-correct. Baseline HEAD at mission
> start: `aa7c3a3` (Wave 2.3). Frozen MQL5 anchor `227bf66` is **intact**
> (`git diff 227bf66 HEAD -- mql5/` empty).

This document is deliverables **A–D and F** of the mission. The Windows
owner handoff (E) is `docs/WINDOWS_OWNER_HANDOFF.md`.

---

## Method

Truth was established against the CURRENT code, not historical docs:
`git`/HEAD inspection, a green baseline (`pytest -q`), and direct reads of
the DSL, factory, indicator-universe, research-service, API and MQL5
sources. Claims below carry `file:line` anchors. The chosen strategy for
the two frozen-tree items (generic MQL5 runtime, RiskManager fix) is
**staged / anchor-preserving** (owner integrates + re-anchors) — selected
explicitly to keep the owner's compile-of-record and evidence valid.

---

## A. Current architecture — the real execution graph

```
NL / template text
  → factory/interpreter.py  TemplateInterpreter.interpret()   (deterministic; EN/FA)
      draft (v0): entry/exit trees + ambiguities; MARKET UNRESOLVED unless owner-supplied (§6 fix)
  → dsl/parse.py parse_spec()  → schema.validate_spec → normalize_spec → StrategySpec(frozen)
      identity: spec_hash / semantic_hash / dedup_hash (normalize.py)
      executable = version>0 AND no ambiguities (model.py:96)
  → dsl/runtime.py desired_positions()   GENERIC recursive interpreter
      operands: ind/price/const/add/sub/mul/div (eval_operand 184-212)
      conditions: and/or/not/cmp/cross/rising/falling/within (eval_condition 215-274)
      modes: instant | state; filters FLATTEN only; NaN→False; closed-bar
  → discovery/research_service.py run_idea()   research chain (market now REQUIRED, §6)
  → factory/gates.py + factory/store.py + factory/lifecycle.py
      lifecycle DRAFT→PARSED→…→LIVE; gates evidence-bound; OOS one-look
  → dsl/bundle.py build_bundle()   EXECUTABLE BUNDLE (identity+market+spec+contracts+hash)  [NEW]
  → Meta / allocation (score ≠ permission)  → Risk (final veto)  → MQL5 TradeManager (only order authority)
  → MT5   (OWNER-PENDING)
```

MQL5 side (frozen `mql5/`): `Mql5Bot.mq5` → `CSignalEngine.Evaluate(strategy)`
(`SignalEngine.mqh:291` fixed `switch` over 5 enums) → `SBotSignal` →
`RiskManager` → `TradeManager` → MT5. The **generic** peer runtime is
staged in `mql5_dsl_runtime/` (OWNER-PENDING/UNCOMPILED) and consumes the
same executable bundle — closing the §8 divergence without deleting the
five verified engines (§11).

Authority model (verified, unchanged): Strategy proposes → Meta allocates →
Risk vetoes → TradeManager executes. No LLM/ML/discovery/Meta/factory path
holds order authority.

---

## B. Gap report

Severity: P0 (unsafe/incorrect) · P1 (truthfulness/authority) · P2
(bounded correctness) · P3 (design/coverage).

| ID | Sev | Gap | Evidence | Root cause | Fixed? | Test | Owner-only? | Remaining risk |
|----|-----|-----|----------|-----------|--------|------|-------------|----------------|
| G1 | P1 | Interpreter GUESSED market EURUSD/H1 while claiming it never guesses | `interpreter.py:208` (old) vs assumptions at 176-177 | hard-coded default | ✅ market is explicit-or-UNRESOLVED ambiguity; schema forbids empty market for v>0 | `test_interpreter_market.py` (7) | no | none (fail-closed) |
| G1b | P1 | Same guess leaked into research pipeline / API | `research_service.run_idea` built v1 spec from guessed market; API `/campaigns` had no market | reliance on G1 | ✅ `run_idea(market=…)` fail-closed; CLI `--symbol/--timeframe`; API 422 when runner+no market | `test_api_ui.py` (+1), `test_master_convergence.py` | no | none |
| G2 | P1 | ALL 71 indicators claimed `mql5_status="parity-tested"` — no owner MT5 parity exists; 65+ have no MQL5 port | `registry.py:24` `BASE_PARITY`; REALITY_GATE_BLOCKED | blanket default over-claim | ✅ truthful default `canonical-defined`; no kind claims parity | `test_indicator_mql5_status_truthful.py` | no | none |
| G3 | P2 | Normalized document not schema-idempotent: `n`/`cooldown_bars` emitted as floats, rejected on re-parse (breaks bundle carry + DB reconstruct for those specs) | `normalize.py:279` floatifies; strict int checks `schema.py` (old 166-168, 431-434) | missed fields in idempotency restore | ✅ `_as_int` (tolerant of integral floats) for `n`/`cooldown_bars` | `test_dsl_bundle.py::…reparseable…` | no | none |
| G4 | P3 | **Central gap:** generic MQL5 execution absent — MQL5 fixed to 5 enums while Python DSL is generic | `SignalEngine.mqh:291-301` vs `runtime.py:215-274` | no MQL5 spec/bundle interpreter | ⏳ executable-bundle + Python parity DONE; MQL5 runtime STAGED (`mql5_dsl_runtime/`, owner-compiles) | `test_dsl_bundle.py`, `test_dsl_parity_golden.py` | compile+parity owner-only | MQL5 side unverified until owner compile |
| G5 | P2 | `RiskManager.mqh:296` inverted OrderCalcMargin direction (`price < slPrice`) | source review; PROGRESS.md 2026-09-16 | inverted ternary | ⏳ patch prepared `owner_patches/…`; not applied (frozen) | `test_riskmanager_direction_patch.py` (8) | apply+compile owner-only | bounded to asymmetric-margin sizing until applied |
| G6 | P0 | **ResearchService fabricated gate inputs** — `pbo=0.0`, `positive_in_expected_regime=True`, `max_correlation_with_book=0.0`, `marginal_heat_add=0.0`, score `cpcv_pbo_evidence=0.1` — forced gate-6/8/9 passes on a SEARCHED grid regardless of the strategy | `research_service.py:267-272,350` (old) | hard-coded constants papering over unmeasured gates | ✅ every input MEASURED: PBO via `robustness.combinatorial_purged_cv`, regime via `research_metrics.regime_pf`, DSR via `robustness.psr`, portfolio vs the actual book; unmeasurable ⇒ UNSET → gate SKIPs (blocks). Evidence bound to the SELECTED variant's spec_hash. `cpcv_pbo_evidence=1−PBO` | `test_research_service_truthful.py` (10) | no | none (fail-closed; weak-edge search now correctly REJECTED) |
| G7 | P0 | **Misleading WFE certification metric** — gate-5 (`gate5_walk_forward`, literally "walk-forward efficiency") was fed `cv_pf − train_pf`, a profit-factor DELTA between two in-sample sub-slices — no OOS, no return ratio, not WFE by the contract | `research_service.py:197` (old); `WFA_CONTRACT.md:119` defines WFE = OOS_return/IS_return; `optimizer.py:291-295` | inline shortcut using a PF difference under the WFE name | ✅ gate-5 input is now the CONTRACT WFE ratio (held-out return / IS return) over one rolling-origin window INSIDE the IS region (final one-look OOS untouched), via canonical `research_metrics.walk_forward_efficiency` (same formula as `optimizer.walk_forward`); undefined (non-positive IS leg) ⇒ UNSET → gate-5 SKIPs. Mislabeled `is_pf` selection key renamed `sel_pf`. Gate not weakened | `test_research_service_truthful.py` (+3) | no | none (fail-closed; name now truthful) |
| G8 | P1 | Bundle total-size limit (`validate_document_size`, 256 KiB) was enforced only on the FILE path (`parse.py:44`); an already-parsed dict reaching `load_bundle`/`parse_spec(dict)` skipped it | `bundle.py:load_bundle` (old) | size check tied to `load_document` only | ✅ `load_bundle` now validates `canon_json(envelope)` size first and fails closed (`BundleError`) before any structural work; MQL5 staged loader now also matches market **timeframe** (not only symbol) and its header truthfully enumerates MIRRORED vs OWNER-PENDING refusals | `test_dsl_bundle.py::…oversized…` | no | none |

No gate was weakened. No frozen artifact (gold/gold_2/owner_mt5_gate) was
regenerated. New evidence (`artifacts/dsl_parity/`) is additive.

---

## C. Generic DSL execution design (§8–§14)

**Executable bundle** (`python/mql5bot/dsl/bundle.py`) — the immutable,
hash-bound carrier BOTH runtimes read:

```
bundle_format_version   "1.0"          envelope schema
runtime_contract_version "1.0"         execution-semantics both runtimes speak
schema_version                          DSL document schema
identity{ strategy_id, strategy_version, spec_hash, semantic_hash }
market{ symbol, timeframe }             never guessed (§6)
indicator_contracts[ {kind,version,mql5_status} ]  drift-detectable
spec                                    the FULL normalized executable document
bundle_hash             = sha256(canon_json(envelope − bundle_hash))
```

`build_bundle(spec)` refuses non-executable specs (draft/ambiguous).
`load_bundle(env)` **fails closed** on: non-object envelope · unsupported
bundle/runtime version · missing identity · market missing · `bundle_hash`
mismatch · spec fails validation · non-executable spec · identity not
binding the content (re-derived spec_hash/semantic_hash mismatch) · market
mismatch · indicator-contract drift · unsupported indicator/condition/exit.
The MQL5 loader (`mql5_dsl_runtime/Include/DslBundle.mqh`) mirrors these
refusals (the canonical-JSON re-hash is the one owner-completion point,
documented inline; an unverified bundle is refused, not accepted).

Flow: `certified StrategySpec → build_bundle → bundle.json → {Python
load_bundle | MQL5 CDslBundleLoader} → generic runtime → SBotSignal
(direction + exit geometry) → Meta → Risk → TradeManager → MT5`. A new
strategy reaches execution as DATA — it never becomes one of
EMA_CROSSOVER/RSI_REVERSAL/DONCHIAN_BREAKOUT/BOLLINGER_REVERSAL/
MACD_MOMENTUM (proved by `test_dsl_parity_golden.py::…not_as_a_legacy_enum`).

Identity/hash rules: `spec_hash`/`semantic_hash` come from `normalize.py`;
the bundle re-derives and binds them; `bundle_hash` makes the envelope
tamper-evident; indicator-contract versions bind the registry definition so
a redefined indicator is refused, never silently run.

---

## D. Parity report (§12/§13)

**Contract** (`python/mql5bot/dsl/parity.py`): a *parity trace* records the
per-CLOSED-bar desired position (`{-1,0,+1}`), the state-transition events,
and the exit geometry, plus a `position_hash`. LOGICAL fields (positions,
events) are compared **EXACTLY — no tolerance**; spec-constant geometry
compared exactly. `compare_traces()` renders the verdict.

**Golden set** (`artifacts/dsl_parity/`, generated by
`tools/build_dsl_parity_golden.py`): 14 runnable fixtures covering the §13
surface — EMA position/cross, the canonical `EMA20×EMA50 ∧ RSI14>55, SL
2ATR/TP 3ATR`, OR/NOT, rising, within, arithmetic, point/percent stops,
trailing+breakeven+time, session, trading-days, cooldown — each with
`bundle.json` + `ohlc.csv` + `expected_trace.json`, bound by `manifest.json`
sha256s. Fail-closed cases (§13 25-28: ambiguous, unknown indicator,
malformed bundle, hash mismatch) are asserted in
`test_dsl_parity_golden.py`.

**Coverage matrix:**

| Leg | Status |
|-----|--------|
| Python DSL runtime ↔ executable bundle round-trip | ✅ proven (`test_dsl_bundle.py`) |
| Python parity traces deterministic / no-drift | ✅ proven (`test_dsl_parity_golden.py`) |
| Canonical example runs generically (not an enum) | ✅ proven |
| MQL5 generic runtime ↔ Python (positions EXACT) | ⏳ OWNER-PENDING — run `DslParityRunner.mq5`, compare to `expected_trace.json` |
| SL/TP price-level parity (execution layer) | execution-audit + owner Strategy-Tester leg (never claimed here) |

Tolerances: logical values EXACT; geometry EXACT; no broad tolerances that
could hide divergence. Extended indicator MTF/benchmark kinds are
registry-defined but owner-pending in MQL5 (refused by the staged loader
until implemented).

---

## F. Final test report

(Commands and measured results — filled from the definitive run.)

```
pytest -q -p no:cacheprovider          → PASS (100%, 1 skipped, 0 failed;
                                          PYTHONHASHSEED=12345, PYTEST_EXIT=0)
ruff check python/ tests/ tools/ factory/  → All checks passed
git diff --check                        → clean
git diff 227bf66 HEAD -- mql5/          → empty (frozen anchor intact)
```

The 2026-09-17 closure wave (G6, research-service truthfulness) added
`discovery/research_metrics.py` and `tests/test_research_service_truthful.py`
and rewrote `discovery/research_service.py` to measure every gate input.
The same-day continuation closed **G7** (gate-5 WFE is now the contract
walk-forward-efficiency ratio via `research_metrics.walk_forward_efficiency`,
not a profit-factor delta) and **G8** (bundle total-size limit now enforced on
the in-memory `load_bundle` path; MQL5 staged loader matches market timeframe
and carries an honest MIRRORED/OWNER-PENDING header) — `+3`
`test_research_service_truthful.py` WFE tests and `+1`
`test_dsl_bundle.py` oversized-bundle test. The suite above is the post-wave
green run.

Determinism: the DSL/bundle/parity suites are seed-independent (pure
functions + fixed fixtures); baseline verified under `PYTHONHASHSEED=12345`.

New/changed tests this pass: `test_interpreter_market.py` (7),
`test_indicator_mql5_status_truthful.py` (2), `test_dsl_bundle.py` (15),
`test_dsl_parity_golden.py` (parametrized, ~21), `test_riskmanager_direction_patch.py`
(8), plus updates to `test_factory_cli/intake/e2e`, `test_master_convergence`,
`test_api_ui` to make the market explicit at the executable boundary.

---

## Definition-of-Done status (§35)

Done (Mac-provable): current state audited · historical claims reconciled ·
interpreter contradiction fixed · canonical DSL verified · indicator
universe ↔ schema verified + truthful MQL5 status · executable bundle +
fail-closed loader · exact parity harness + representative golden set ·
generic runtime fail-closed · legacy five engines preserved · determinism ·
docs truthful · owner-only work separated · no fabricated MT5 evidence.

Owner-pending (cannot be Mac-proven): MQL5 generic-runtime **compile** and
the MQL5↔Python **position parity** legs; RiskManager patch **apply +
compile + re-anchor**; every MT5/tester/broker reality gate. See
`docs/WINDOWS_OWNER_HANDOFF.md`.
