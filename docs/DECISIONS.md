# Aegis — Decisions Log

Every meaningful architectural deviation from `docs/SPEC.md` and every
significant trade-off is recorded here with its rationale. When uncertain
about a financial rule, the more conservative option wins and is documented.

Format: newest on top. `[SPEC]` entries record SPEC-mandated decisions that
were already made and must not be silently reverted.

---

## 2026-09-16 — Wave 2.1 final audit + Mac freeze for owner certification

**Purpose.** Audit Wave 2, make the repository internally truthful and
reproducible, freeze the code side, and prepare the Windows Owner
Certification handoff. No new features, strategies, ML architecture or
unrelated refactor. Authority model unchanged.

**Wave-2 fix re-verification.** All seven Wave-2 fixes were re-checked
against code AND against the old-bug condition (not just "a test exists"):
CPCV block partition (old code makes `n_splits+1` overlapping blocks →
`n_combos=C(7,3)=35` for t=100, the pinned test asserts 6/20), two-sided
CPCV embargo, governor failed-gate no-resurrection (old symmetric delta cap
leaves 0.30 on a gate-failed book; test asserts 0.0), governor demote-only
`[0,1]` multiplier clamp, drift execution-window alignment (old window gives
~0.8 execution-drift on the 60-trade fixture; test asserts 0.0), meta-OOS
one-look-before-look ordering + deterministic `as_of`, cost-stress `None`
guard, and the ML risk-seam duplicate-`order_key` robustness. No accidental
semantic changes found. Fixes 1/2/3/6 were PROVEN to fail under the old-bug
condition (block overlap → C(7,3)=35; symmetric cap → 0.30 on a gate-failed
book; old drift window → ~0.8 execution-drift; old `.loc[key]` → TypeError on
dup keys). Three fixes were green-on-green (correct implementation, but the
existing tests passed even with the old bug): meta-OOS ordering, cost-stress
`None` guard, and the telemetry cap had no failing-under-old-bug test. Wave 2.1
CLOSED these gaps by adding four regression tests: a `run_backtest` spy proving
the refused second OOS look never touches the slice (old code re-ran it), a
degenerate-run test driving `max_drawdown_pct=None` through the cost-stress
gate (old code raised `TypeError`), and a real ephemeral-port telemetry server
asserting a small body → 200 and an oversized `Content-Length` → 413 before any
read.

**Provenance / status truthfulness (the substantive change).** The
broker-evidence model is now stated as THREE distinct facts so the repo
neither over- nor under-claims:
1. **CAPTURED (owner) ≠ NOT PERFORMED.** The owner has already run the
   exporter on Windows and obtained a successful `denomination_probe`
   (`ok=true`, `source=OrderCalcProfit`) for EURUSD / XAUEUR / US30 / BTC.
2. **NOT COMMITTED / NOT REPRODUCIBLE ≠ MISSING.** `data/` is gitignored, so
   those raw exports are not in Git and cannot be re-derived on Mac; the
   in-repo parity report is `n_exports:0`, all classes PENDING.
3. **probe.ok ≠ PARITY PASS.** The ACCOUNT vs PROFIT verdict is rendered only
   when the harness runs on a committed export. No verdict is claimed; the
   denomination decision stays owner-gated (Wave-1 entry unchanged).
   Documented in `docs/BROKER_SYMBOL_PARITY.md` (new "Owner-evidence
   provenance" section + status table) and `PROGRESS.md` CURRENT STATE. No
   raw owner export is committed to green a dashboard, and none is fabricated
   or modified. `data/broker_exports/parity_report.json` (gitignored, local)
   confirms the Mac view is genuinely `n_exports:0`.

**Denomination semantics — unchanged (PENDING).** Reviewed the implemented
parity logic: `denomination_probe.ok=true` is only a precondition; the
harness returns `ACCOUNT_CURRENCY` only when both exported tick values agree
with the independent `OrderCalcProfit` witness, else `PROFIT_CURRENCY` /
`UNVERIFIED` / PENDING. With no committed export the verdict cannot be
rendered here, so PENDING stands. No runtime sizer/RiskManager/SymbolSpec
semantics changed for the sake of completion; no FX rate invented; no
circular derivation from `tick_value`.

**TASKS.md migration.** `TASKS.md` is the archival Phase-2.5 checklist; its
unchecked boxes are NOT a current backlog (the Phase 0–14 research-foundation
modules are all implemented and tested). Added a STATUS BANNER marking it
archival, stating Phases 0–14 are CODE-COMPLETE, identifying the only open
items as the OWNER-PENDING Reality-Gate boxes, and pointing current status to
`PROGRESS.md` / this log / `docs/WINDOWS_OWNER_HANDOFF.md`. Checkbox states
left verbatim; history preserved.

**Freeze anchor.** `artifacts/owner_mt5_gate/frozen_inputs.json` still anchors
the compile to `227bf66`; `git diff 227bf66 HEAD -- mql5/` is empty (Waves 1–2
touched only Python/docs/owner-gate metadata), so the owner compiles the same
EA. The gold artifacts are unchanged since the anchor (freeze invariant
intact).

**ML boundary — unchanged.** ML remains estimation-only: `ml_interfaces.py`
labeler/meta-label/calibrator/feature-store are intentional interface-only
stubs (no training/inference anywhere); the risk seam only drops/shrinks and
re-checks; regime/drift feeds are causal, bounded `[0,1]`, missing→conservative
`0.5`. No generic AI trading system introduced. See `docs/ML_VS_LLM_BOUNDARY.md`.

**Security final pass.** Re-swept the tree with focus on Wave-2 files: NO
high/critical/medium reachable findings. The telemetry body cap is correct and
not bypassable (missing/negative/non-numeric Content-Length handled; chunked
transfer-encoding is not auto-decoded by `BaseHTTPRequestHandler`, so no
unbounded read). Wave 2 introduced no new file-write/subprocess/deserialization
/network sink. All prior controls (loopback binds, paste-first providers,
`yaml.safe_load`, UI→LIVE reject, evidence binding, human-approval actor
prefixes) intact.

**Windows handoff.** Added `docs/WINDOWS_OWNER_HANDOFF.md`: final source SHA /
frozen compile anchor, the `-Strict` compile command, required MQL5 targets,
required owner exports (EURUSD/XAUEUR/US30/BTC), and the 12 owner actions
mapped onto the canonical ten-step `docs/MT5_ROUNDTRIP.md` protocol (no shorter
protocol invented).

**Validation.** Full deterministic suite: **1585 passed, 1 skipped, 0 failed**
(Wave 2 was 1581/1; Wave 2.1 added four regression tests, no source-behaviour
change); `git diff --check` clean. "Ruff clean" here means the
canonical package `ruff check python/ tests/` (All checks passed) — the repo's
established scope; a bare `ruff check` also lints legacy `tools/`/`examples/`
and reports ~13 PRE-EXISTING findings there, untouched by any wave and out of
the canonical scope (Wave 2.1 changed only docs, no Python). This is the final
Mac engineering freeze — the next phase is Windows Owner Certification. Nothing
is runtime-certified.

## 2026-09-16 — Wave 2 research/ML/governance hardening: correctness fixes, no new authority

**Scope.** Wave 2 finished the code-side research/intelligence/governance
work reachable on Mac (no MT5 runtime). Full-repo audits of ML, meta,
discovery, robustness/WFA/OOS, portfolio and a source-level security
review. The authority model is UNCHANGED — no ML/LLM/meta/discovery path
gained order authority; every fix only tightens correctness or the
reduce-only/one-look/no-leakage guarantees. Wave-1 denomination decision
stands unchanged (still owner-gated; parity report still PENDING all
asset classes — see the Wave-1 entry below).

**Fixes applied (each with a pinned regression test).**

1. **CPCV block partition leakage** (`robustness.combinatorial_purged_cv`).
   The hand-rolled stride/remainder block construction produced
   `n_splits + 1` blocks with a duplicated boundary index whenever
   `n_periods % n_splits != 0` (e.g. 100/6 → 7 blocks, index 16 in two
   blocks), leaking a bar across the train/test split of the same fold and
   understating PBO — which feeds `gate6_cpcv_pbo` and the discovery score.
   Replaced with `np.array_split` (exactly `n_splits` disjoint blocks). The
   CPCV embargo was also made TWO-SIDED (it previously purged training only
   *before* each test block, leaving the trailing-edge adjacency of a
   following train block un-embargoed).

2. **Governor resurrected failed-gate strategies** (`discovery/governor.py`).
   The symmetric per-strategy delta cap smoothed an ineligible strategy's
   weight down to `prev − max_strategy_delta` instead of zero, so a strategy
   that just failed its gate could keep non-zero allocation (violating
   "no valid certification ⇒ exactly zero weight, every mode"). Ineligible
   records are now forced to a HARD zero and exempted from the delta cap,
   mirroring the `zero_reason` exemption in `meta_layer._apply_modes`.
   Additionally, caller-supplied decay/ramp multipliers are clamped to
   `[0, 1]` (demote-only by contract) and a single strategy is capped at the
   gross target band — a hostile/buggy multiplier `> 1` can no longer inflate
   exposure.

3. **Drift execution-window misalignment** (`drift_feed._median_bars`). The
   execution-drift baseline used a `recent_n + baseline_n` window (40 trades
   with defaults) instead of the `baseline_n` window (20) that the
   expectancy/PF/winrate components use, diluting a real holding-period shift
   and UNDER-reporting execution drift (non-conservative). The bars windows
   now slice identically to the pnl windows.

4. **Meta-OOS one-look ordering** (`meta_oos.run_meta_oos`). The registry
   `check_identity` ran only *after* the OOS backtests, so a repeat look
   re-executed the whole OOS evaluation before raising. The check now runs
   BEFORE the OOS slice is consumed. A dead wall-clock `datetime.now()` call
   in that path was removed, and `policy_weights` now defaults `as_of` to the
   data's own last timestamp (deterministic) instead of wall-clock.

5. **`float(None)` crash in the cost-stress gate** (`pipeline.cost_stress_gate`).
   `compute_metrics` reports `max_drawdown_pct=None` for degenerate runs;
   `float(None)` would raise mid-stage. Now coerced to `0.0` (the run fails
   the survival test on other conditions anyway).

6. **ML risk-seam robustness** (`ml_interfaces.check_ml_invariants`). The
   guard indexed by a non-unique `order_key` and crashed (`float(Series)`)
   on a realistic book with two orders on the same bar/side. It now compares
   summed per-key exposure (conservative, reduce-only), behaviour-identical
   for unique keys.

7. **Telemetry body cap** (`telemetry_bridge.do_POST`). The collector read
   an unbounded `Content-Length` body before parsing; now capped at 1 MiB
   (413 otherwise). Defense-in-depth on top of the Wave-1 loopback bind.

8. **Docstring honesty.** `optimizer.walk_forward` no longer implies it
   records a one-look (it does not — `OosRegistry` on the S5 path does), and
   `OosRegistry` now documents its single-writer / TOCTOU assumption.

**Validation.** Full deterministic suite: 1581 passed, 1 skipped, 0 failed
(was 1576 passed / 1 skipped before the five new Wave-2 regression tests);
ruff clean; `git diff --check` clean. No MT5 runtime, Strategy Tester, real
tick, Gold, demo/live or owner evidence was run or fabricated on Mac.

**Security review.** Source-level audit of `python/`, `factory/`, `tools/`,
`scripts/`, `mql5/` found NO high/critical reachable vulnerabilities:
subprocess is fixed-argv only, no `eval`/`exec`/`pickle`/`yaml.load`, no
network dereferencing in the intake path (community text is treated strictly
as sanitized DATA), no hardcoded secrets, servers loopback-bound, and the
factory→execution, ML→order and UI→live authority controls are enforced
server-side (evidence binding, human-approval actor prefixes, no order
endpoint). The telemetry body cap (#7) was the only hardening applied.

## 2026-09-16 — Wave 1 code-side pass: tick-value denomination stays owner-gated; loopback-default network servers

**Trigger.** Wave 1 asked whether the runtime double-converts stop-loss
risk: `SpecLossPerLot` (and the Python `loss_per_lot`) multiply
`tick_value_loss` — read at runtime from `SYMBOL_TRADE_TICK_VALUE_LOSS`
(`SymbolSpec.mqh:82`) — by a runtime `ProfitToDeposit` FX factor
(`RiskManager.mqh:213,374`). If MT5 already denominates that tick value in
the *account* currency, the second multiply is an unjustified conversion
for cross-currency symbols (e.g. EURUSD/US30/BTC on a EUR account).

**Decision — DEFER, do NOT patch runtime semantics.** The
ACCOUNT_CURRENCY vs PROFIT_CURRENCY denomination is exactly what
`tools/broker_symbol_parity.py` resolves, and only from a committed owner
export carrying an independent `OrderCalcProfit` witness
(`docs/BROKER_SYMBOL_PARITY.md`, Stage A). In this tree
`data/broker_exports/` contains **no owner export** (`parity_report.json`
→ `n_exports: 0`; every asset class PENDING). The witness numbers quoted
in the Wave-1 directive are not present as verifiable artifacts, and
deriving the fix from them would (a) contradict the repo's own fail-closed
deferral of this denomination and (b) act on evidence that cannot be
attested on this host — a provenance violation. Per the Wave-1 rule
"evidence does not conclusively prove a defect → do not patch runtime
semantics, preserve fail-closed behavior": no sizer / RiskManager /
SymbolSpec semantics changed. The suspected double-conversion is recorded
as an **owner-gated open item**: it is confirmed or refuted only when real
FX/METAL/INDEX/CRYPTO owner exports land and the parity harness renders an
accepted `ACCOUNT_CURRENCY` verdict on Windows. `NEVER derive FX from
tick_value` and `no global FX state` remain in force.

**Security hardening (Wave 1F, applied).** The two unauthenticated HTTP
servers — the telemetry collector (`telemetry_bridge.py`) and the status
dashboard (`dashboard.py`) — bound `0.0.0.0` unconditionally, exposing an
attacker-writable JSONL sink and a status endpoint to the whole LAN. Both
now default to `127.0.0.1` with an explicit `--host` opt-in for cross-host
use behind a firewall/tunnel. Fail-safe default; no capability removed.
Cross-host telemetry from the MT5 terminal now requires an explicit
`--host 0.0.0.0` (documented in the collector's `--help`).

**Trigger.** The repository is now published as a squashed single-commit
snapshot: `227bf66 Initial commit`
(`227bf665654b2d2491c89c226dcff735570b915a`, branch `master`). The prior
freeze anchor `52cbaa5e0077056d75ac7ed2afc423ef24d5cd23` recorded in
`artifacts/owner_mt5_gate/frozen_inputs.json` is unreachable from this
history, so
`tests/test_docs_contract.py::test_owner_mt5_gate_package_exists_and_is_pending_owner`
failed its `git merge-base --is-ancestor <anchor> HEAD` check.

**Diagnosis (this is NOT the shallow-clone case).** The 2026-09-08
environment note below documents a *shallow clone* reproduction where the
anchor object is merely absent locally and `git fetch --unshallow`
restores it with no source change. That is explicitly not the situation
here: `.git/shallow` is absent, `git rev-list --count HEAD` is exactly
`1`, and the historical commits (`58ce3ad`, `29dd770`, `781290b`, and the
old anchor itself) genuinely do not exist in the object store and cannot
be fetched. The history was rewritten by a squash; the anchor is gone for
good, not hidden.

**Decision — provenance-correctness-only re-anchor.**

1. `frozen_inputs.json` `source.commit` is migrated
   `781bea4 -> 54613aa -> 52cbaa5 -> 227bf665…` and `source.branch` set to
   `master`, under the same rule as the 2026-09-08 anchor migrations: a
   change to the source-of-record snapshot moves the anchor.
2. This re-anchor touches provenance only. Every frozen semantic hash in
   the file — gold #1/#2 fixture, config, dataset, manifest, spec, and the
   Gold #2 `artifact_hash_chain` — is byte-untouched, and
   `git_commit_recorded` for each gold (the historical commit that
   *produced* that gold) is deliberately left as-is; it records when the
   gold was made, not the current freeze anchor.
3. The freeze invariant still holds and is still enforced: with the anchor
   equal to HEAD the golds are present at the snapshot exactly as frozen,
   so `git diff <anchor> HEAD -- artifacts/gold artifacts/gold_2` is empty
   and `merge-base --is-ancestor` passes. The contract was re-pointed to
   the truth, not weakened; `certification_manifest.json` remains
   `REALITY_GATE_BLOCKED` / `PENDING_OWNER` and no owner evidence was
   fabricated.

**Owner flow unchanged.** Checkout `227bf665…`, run
`tools\compile.ps1 -Strict` (0/0 expected), re-run the exporter on the
live account, commit the real broker exports, then re-run
`tools/broker_symbol_parity.py`.

---

## 2026-09-15 — Stage A validation count discrepancy and exporter sign gate

1. The reported `1599 passed / 1 skipped` versus `1598 passed / 1 skipped`
   difference is not reproducible from this checkout. Under the exact requested
   Python 3.13/uv dependency command with collection-only mode, the base
   `58ce3ad` collected 1,569 tests; the current Stage-A tree collected 1,576
   before the new regression test and 1,577 after it. The same dependency
   environment was used for both collections.
2. A path-level collection diff found exactly two base tests intentionally
   replaced (`test_derived_tick_value_identity` and
   `test_derived_identity_cross_currency`) and the nine Stage-A denomination
   tests that replaced/expanded that coverage; no unrelated test path
   disappeared or changed collection status. Therefore the reported one-test
   delta cannot be attributed to accidental test loss or a dependency change
   in this repository. It is an unreproduced run-context/collection-count
   discrepancy, not a reason to remove or weaken a test.
3. The MQL5 exporter now sets `denomination_probe.ok` only after both
   `OrderCalcProfit` calls succeed, all probe numeric inputs/outputs are valid,
   BUY produces a strict negative loss, and SELL produces a strict positive
   gain. Each failure keeps its specific reason and the last error observed;
   evidence fields remain `null` unless the complete invariant is true.

---

## 2026-09-15 — Stage A: independent tick-value denomination measurement

1. The old PENDING-only derived FX identity was a harness defect: it could not
   independently attest whether MT5's tick value was denominated in account or
   profit currency. Deriving FX from `tick_value / (contract_size × tick_size)`
   is circular and is forbidden.
2. The exporter now optionally records one-symbol evidence from an independent
   `OrderCalcProfit` witness at 1.0 lot over `N` ticks (default 100). BUY uses
   `ask → ask - N*tick` and must be negative; SELL uses `bid → bid - N*tick`
   and must be positive. Tick values are re-read at that same moment. Failure
   remains explicit (`ok=false`, reason, last_error) and numeric fields are not
   fabricated.
3. The harness assesses each symbol independently. `ACCOUNT_CURRENCY` requires
   agreement with both witness sides; `PROFIT_CURRENCY` requires the structural
   tick hypothesis plus a meaningful separation from the account witness;
   otherwise the result is `UNVERIFIED / PENDING`. The controls are intentionally
   conservative: agreement tolerance `1e-3`, separation minimum `1e-2`.
4. The optional probe stays outside `FIELD_MAP`, preserving backward
   compatibility for old four exports. The parity-only sizer replay no longer
   forces `currency_deposit := currency_profit`; it uses the export's actual
   `account_currency` only for an independently supported account-currency
   verdict, and otherwise remains PENDING without manufacturing a conversion.
5. This is observability/measurement only. `RiskManager.mqh`, `SymbolSpec.mqh`,
   the Python runtime sizer/engines and owner-gate artifacts are untouched; no
   runtime risk semantics changed. Broker parity is STILL NOT VERIFIED, and BTC
   remains an owner-side open measurement.

---

## 2026-09-10 — Asset-class coverage: one rule could no longer consume a symbol (METAL export counted as FX)

1. **Proven defect, from the owner's own exports.** `asset_classes_covered()`
   walked the required classes in a single `if`/`elif` chain, so the first rule
   that matched a symbol consumed it outright. Its FX branch carried a bare
   shape test — `len(name) == 6 and name.isalpha()` — and the owner's `XAUEUR`
   export (`SYMBOL_PATH` = `Metals\XAUEUR`) satisfied that test, so the METAL
   branch was never reached: with four exports committed, coverage read
   `FX: exported: XAUEUR` and `METAL: PENDING (no owner export)`. The gate
   therefore believed a metal export satisfied the FX requirement while still
   demanding a METAL export that had in fact been delivered. Reproduced
   before/after against the same four documents.
2. **Two bugs in one shape.** The chain made the *class* order-dependent, and
   the unconditional `out["FX"] = ...` made the *representative* depend on
   enumeration order (last valid export won). Coverage is a per-class property,
   not a partition of the symbol universe: a symbol either evidences a class or
   it does not, independently of the other classes, and each class needs one
   deterministically chosen witness.
3. **Fix — semantics only, no new broker taxonomy.** The markers are exactly
   the ones the harness already used, now data: `CLASS_PATH_MARKERS`
   (`forex/fx/major/minor`, `metal/xau/xag`, `index/indices/cfd`,
   `crypto/btc/eth` on `SYMBOL_PATH`) and `CLASS_NAME_PREFIXES`
   (`XAU`/`XAG`, `BTC`/`ETH`). `_asset_classes_supported(path, name)` returns
   every class a symbol evidences (independent checks, a list, no `elif`), and
   `asset_classes_covered()` fills each class once from the first candidate in
   an explicit order (upper-cased name, then path). The 6-letter shape test was
   not deleted wholesale and was not swapped for another broad rule: it survives
   only as a **fallback**, consulted when the export carries no class evidence
   at all (some brokers leave `SYMBOL_PATH` empty or uninformative) and never
   for a name a specific class already claims — the exclusion list reuses the
   repo's own metal/coin prefixes, so `XAUEUR` cannot reach FX even path-less.
   A symbol that genuinely evidences two classes now counts toward both, which
   is honest coverage rather than a substitution.
4. **Determinism policy, stated and tested.** No filesystem or caller order is
   used as an implicit tie-breaker; alphabetical, reverse-alphabetical,
   metal-first and directory order all yield the identical mapping, and with
   duplicate candidates the representative is the sorted-first valid match
   (`EURUSD` over `GBPUSD`, `XAGUSD` over `XAUUSD`) whichever way round the
   inputs arrive.
5. **Tests (7 new, nothing removed or weakened).** In
   `tests/test_broker_symbol_parity.py`: the four-export coverage table, the
   `XAUEUR`-is-not-FX regression (with and without a path), the fallback
   constraint (path-less pair still FX; evidenced classes never re-routed; no
   evidence ⇒ everything PENDING, never invented), multi-class independence,
   order independence including `build_report()` over real files, the
   deterministic-representative rule, and an `ast` pin that fails any
   `if`/`elif` chain whose branches both assign coverage — structural, so
   reformatting cannot dodge it. Mutation-checked against the real classifier:
   full revert 7 failed; independent checks with the unconstrained shape test
   2 failed; fallback deleted 1 failed (recording that the path-less case is
   deliberate); last-write-wins restored 1 failed; format-only reformat green.
6. **What this does NOT mean.** In this owner-export-only path the rows carry
   `python_spec=None`, so no field-by-field owner-vs-Python comparison is being
   performed; `Verdict: 92 rows, 0 mismatches, 4 pending` counts rows, it does
   not certify parity. **Asset-class coverage corrected — BROKER PARITY REMAINS
   NOT VERIFIED**, and the four derived FX conversion rows stay `PENDING`
   (never fabricated away). `mql5/` was not touched: no exporter, encoding,
   schema, field-name, numeric-formatting, tolerance or fail-closed-rule change,
   no engine/risk/meta/gold/frozen-artifact change, and no owner export was
   edited, created or replaced — `data/broker_exports/` does not exist in this
   sandbox checkout, so the four-export run used the module's own synthetic
   fixture documents in a throwaway directory purely to exercise the classifier.

## 2026-09-10 — Broker export file encoding: the exporter pins `CP_UTF8` instead of the machine ANSI code page

1. **The mismatch, read from the repository rather than guessed.** The
   exporter opened the file with `FileOpen(fname, FILE_WRITE | FILE_TXT |
   FILE_ANSI)` — no code page given, so `CP_ACP`, the terminal host's Windows
   ANSI code page — while every Python side of the contract decodes it as
   strict UTF-8: `load_owner_export()` is
   `json.loads(path.read_text(encoding="utf-8"))` (`tools/broker_symbol_parity.py`),
   as are `tools/verify_owner_mt5_gate.py` and `tools/owner_evidence_bind.py`,
   and `main()` writes the parity report back out with `encoding="utf-8"`. No
   reader tolerates a BOM (`utf-8-sig` appears only in the CSV data lane,
   `python/mql5bot/data.py`). Since the escaping contract deliberately passes
   non-ASCII characters through untouched, "UTF-8" was an assumption of the
   reader, never a promise of the writer: on a Western-European Windows, U+00D8
   lands as the single byte `0xD8`, which is not valid UTF-8, so a correctly
   escaped export is still skipped as malformed. It stayed invisible because
   the observed broker text is pure ASCII — byte-identical in UTF-8 and CP1252.
2. **`FileOpen` verified before choosing the form.** The signature is
   `FileOpen(name, flags, delimiter='\t', codepage=CP_ACP)` (the repo's own
   `Mql5BotDownloadData.mq5` passes the delimiter as the third argument). The
   code page "only affects files opened in text mode (`FILE_TXT` or
   `FILE_CSV`), and only if `FILE_ANSI` mode is selected for strings"; a text
   file opened without `FILE_ANSI` is written as UTF-16 *with a BOM*, which
   `encoding="utf-8"` cannot decode at all. So the tempting
   `FILE_WRITE | FILE_TXT` + `CP_UTF8` spelling is the wrong fix: the flag that
   looks "ANSI-only" is exactly the one that makes a code page mean anything.
   The documented UTF-8 text mode (MQL5 Book, *Selecting an encoding for text
   mode*) is `FILE_WRITE | FILE_TXT | FILE_ANSI, 0, CP_UTF8` — conversion
   through the UTF-8 code page, therefore BOM-less — with `0` for the delimiter
   because `FILE_TXT` ignores it and the argument is positional.
3. **The change is one line plus its rationale comment:**
   `int fh = FileOpen(fname, FILE_WRITE | FILE_TXT | FILE_ANSI, 0, CP_UTF8);`.
   The exported bytes are now determined by the program, not by the host
   locale, and the `FILE_TXT` mode itself is untouched, so line-ending and
   `FileWriteString()` behaviour are exactly as before. `JsonEscape()`, the
   schema, field names, numeric formatting and the verifier's verdict
   semantics did not move; the encoding of the string values (raw non-ASCII,
   no `\uXXXX` over-escaping) is unchanged, only the code page that turns
   those characters into bytes.
4. **No evidence invalidated, and no other lane dragged along.** For
   pure-ASCII broker content the file bytes are identical, so no committed
   export and no recorded hash moves — and
   `artifacts/owner_mt5_gate/{frozen_inputs,certification_manifest}.json`
   record no hash of the export script. `Logger`/`Allocation`/`StateStore`/
   `MagicMap` text files are read back by MQL5 itself and the CSV download lane
   is read with `utf-8-sig`; none carries a byte-exact UTF-8 contract, so they
   were left alone rather than "consolidated".
5. **Regression design (layer 4 of `tests/test_broker_symbol_parity.py`).** The
   reader is *executed* on candidate bytes: only BOM-less UTF-8 loads, while
   CP1252, UTF-16 and BOM-prefixed UTF-8 are rejected, and a wrong-code-page
   export is reported as skipped and never transcoded. The exporter is then
   read structurally rather than by string match — the `FileOpen` call's flags
   are compared as a set and its code page as an argument — so flag order, line
   breaks and naming cannot break it, and the documented
   `FILE_BIN` + `StringToCharArray(..., CP_UTF8)` + `FileWriteArray()` route is
   accepted as an equivalent implementation. Finally the file-layer settings
   parsed from the source are *modelled into bytes and piped through
   `load_owner_export()`*, so the pins fail for the real reason rather than for
   a spelling. Mutation-checked: the pre-fix line, `FILE_TXT | CP_UTF8` without
   `FILE_ANSI`, `FILE_UNICODE`, and an explicit `CP_ACP` each fail two tests; a
   format-only reformat, the reordered flag set and the numeric code page
   `65001` stay green.
6. **No compile claim.** MetaEditor cannot run in this sandbox, so the
   exporter has not been recompiled here — source validation only. Owner flow
   unchanged: `tools\compile.ps1 -Strict` (expect 0 errors / 0 warnings),
   re-run the exporter per required asset class, `python tools\broker_symbol_parity.py`.
   Broker parity remains NOT VERIFIED: one FX export leaves METAL / INDEX_CFD /
   CRYPTO `PENDING`.

## 2026-09-09 — Broker export emitted invalid JSON: `JsonQuote()` wrote string values unescaped, so a backslash in `SYMBOL_PATH` made the owner export unparsable

**Trigger.** Owner run on MetaQuotes-Demo (MT5 terminal build 6184,
MetaEditor 5.0.0.6184), `Mql5BotExportSymbolSpec` on EURUSD,H1. The
script reported success (`[mql5bot] exported EURUSD ->
MQL5\Files\Mql5Bot\broker_exports\EURUSD.json`) and the generated file
contained `"path": "Forex\EURUSD"`. `tools/broker_symbol_parity.py`
then reported `WARNING: skipping malformed export: Invalid \escape: line
11 column 19 (char 259)` and treated the owner export as unavailable.
The script had compiled 0 errors / 0 warnings in the owner's MetaEditor,
so this is a runtime **serialization** defect, not a compile defect.

**Decisions:**

1. **Fix the exporter, never the validator.** A raw backslash inside a
   JSON string literal is not a legal escape (RFC 8259 permits only
   `\"`, `\\`, `\/`, `\b`, `\f`, `\n`, `\r`, `\t` and `\uXXXX`),
   so the document was malformed and every parser — not just ours — had
   to reject it. The harness keeps its fail-closed rule (a malformed
   export is skipped and reported, never silently repaired), the strict
   schema check is unchanged, and the owner's malformed file was NOT
   hand-edited or replaced by a fabricated corrected artifact: no
   `data/broker_exports/` content was written to the repository at all.
2. **Escaping is generic and happens at the string-value level.**
   `JsonQuote()` now delegates to a new `JsonEscape()` used for every
   string written into the document: backslash first (it introduces
   every sequence that follows), then `"`, `\n`, `\r`, `\t`, `\b`,
   `\f`, then `\u00xx` for the remaining U+0000..U+001F range.
   Ordinary characters — non-ASCII included — are copied through
   untouched, the finished document is never post-processed, and no
   encoding transformation was introduced (still `FILE_WRITE |
   FILE_TXT | FILE_ANSI`). It is not a `SYMBOL_PATH` special case and
   no broker value is hard-coded: the export stays actual MT5 runtime
   data. MQL5 documents no `"\b"`/`"\f"` string escapes, so those two
   controls are matched by hex value (`"\x08"`, `"\x0C"`).
3. **Regression evidence exists without a compiler, and pins behaviour rather
   than layout.** `tests/test_broker_symbol_parity.py` gained three layers:
   (1) the JSON contract itself — the exported representation must equal the
   canonical encoding `json.dumps(value, ensure_ascii=False)` (named escapes,
   `\u00xx` for the rest of the control range, ordinary and non-ASCII text
   copied through), parse through `json.loads` and decode back to the exact
   broker value; (2) a lightweight source contract that locates the escaping
   helper by brace matching and reads its rules from either implementation
   style (`StringReplace()` table or per-character `case` labels), so
   indentation, parameter naming and brace placement cannot break it, and
   that backslash escaping precedes the rest; (3) harness behaviour — an
   escaped export is parsed and counted, the *un*escaped pre-fix bytes are
   skipped and never repaired. Mutation-checked: a layout-only reformat and a
   per-character rewrite stay green, while dropping a single rule, dropping
   the control range, escaping the finished document instead of the values,
   or restoring the pre-fix helper all fail. Replaying the
   pre-fix source in the sandbox reproduced the owner's exact diagnostic
   (`Invalid \escape: line 11 column 19 (char 259)`); replaying the
   fixed source produced a document the harness accepts with coverage
   `FX: exported: EURUSD` and METAL / INDEX_CFD / CRYPTO still `PENDING`
   — one FX export does not close the parity gate.
4. **Adjacent issue recorded, not changed.** The exporter writes
   `FILE_ANSI` while `load_owner_export()` reads UTF-8. For the ASCII
   broker text actually observed here the bytes are identical, so this
   fix does not touch encoding; a broker with non-ASCII symbol paths or
   server names is a separate, documented concern.
   *Superseded 2026-09-10:* the concern is fixed at the source instead of
   documented — the exporter now pins `CP_UTF8`, see the entry above.
5. **No certification movement.** Schema `mql5bot.broker_export/1`,
   `FIELD_MAP`, tolerances, the parity verdict semantics, the five
   engines, Risk/Meta/Kill-Switch, retry semantics, gold #1/#2 and the
   frozen provenance are untouched. MetaEditor cannot run in this
   sandbox, so the exporter has NOT been recompiled here — source
   validation only. Owner flow: compile at the new commit
   (`tools\compile.ps1 -Strict`, expect 0 errors / 0 warnings), re-run
   the exporter on the live account for every required asset class,
   commit the real exports, then re-run `tools/broker_symbol_parity.py`.
   Whether this commit becomes the new freeze anchor is an owner
   decision under the same rule as 2026-09-08 (a source change that
   forces a fresh strict compile moves the anchor; `frozen_inputs.json`
   was deliberately left untouched here).

**Environment note for the next validation run.**
`tests/test_docs_contract.py::test_owner_mt5_gate_package_exists_and_is_pending_owner`
proves freeze reachability with `git merge-base --is-ancestor <anchor> HEAD`.
In a shallow or partially cloned workspace (`.git/shallow` present, history
grafted at the base commit) the frozen anchor object is not present locally
and the check fails with `fatal: Not a valid commit name 52cbaa5e…` while the
working tree is perfectly fine. `git fetch --unshallow origin` fetches the
real history and the test passes with no source change at all; the contract
was deliberately NOT weakened for the sandbox. Full-suite validation for this
fix was run after unshallowing (213 commits reachable, anchor an ancestor of
HEAD, `git diff <anchor> HEAD -- artifacts/gold artifacts/gold_2` empty).

---

## 2026-09-08 (2) — Strict-compile warnings closed: OrderCalcMargin fail-closed, script version metadata, PowerShell 5.1 ASCII determinism

**Trigger.** Owner re-compile at `54613aa`: 0 errors but 2 warnings
(strict exit 3): `RiskManager.mqh(334,16) warning 83` (unchecked
`OrderCalcMargin` return) and `Mql5BotDownloadData.mq5(15,11) warning
68` (version `1.0.0` not market format). Additionally the owner had to
hand-convert `tools\compile.ps1` to UTF-8 BOM for PowerShell 5.1 — a
portability defect in the repository.

**Decisions:**

1. **Unchecked `OrderCalcMargin` in the margin step-down loop — fixed
   fail-closed, not silenced.** Margin is risk-critical (SPEC §3.3
   "query, never assume"): a broker-calculation failure must never
   pass as a successful margin calculation. The loop now checks the
   boolean return and vetoes (`outReason = "OrderCalcMargin failed
   during step-down"`, 0 lots) the moment a call fails — never keeps
   stepping with a stale value, never guesses. The other two
   RiskManager call sites and the ExportSymbolSpec probes were already
   checked; behavior on success is unchanged. Pinned by
   `test_every_ordercalcmargin_call_is_checked`.
2. **Script version metadata moved to the market plane.**
   `Mql5BotDownloadData.mq5` now carries `#property version "1.00"`,
   same plane and rationale as the EA fix (MetaEditor requires
   xxx.yyy executable metadata on every program type that declares
   it). `Mql5BotExportSymbolSpec.mq5` declares no version property
   (hence zero warnings) and is left unchanged. Release/package
   version 1.0.0 (CHANGELOG/pyproject/`MQL5BOT_VERSION`/Python Meta)
   is untouched. Pinned by `test_all_mql5_version_properties_are_market_format`.
3. **PowerShell sources are pure ASCII from now on.** Windows
   PowerShell 5.1 parses BOM-less scripts with the system ANSI
   codepage, so non-ASCII bytes (em-dashes in `compile.ps1`, `§` in
   `run_mt5_backtest.ps1`) are nondeterministic across hosts — the
   owner should never need a manual encoding conversion. Both files
   were converted to ASCII equivalents (log/comment text only; zero
   behavioral change). Pinned by
   `test_powershell_sources_are_ascii_for_ps51`. New `.ps1` tooling
   must stay ASCII or carry an explicit UTF-8 BOM committed to the
   repository.
4. **Freeze anchor migrated `54613aa` → this warnings-closure
   commit.** `54613aa` compiles with warnings → strict gate exit 3 →
   the certification protocol (which requires 0/0) is unsatisfiable at
   that anchor. Migration is warnings-closure-only: no engine
   semantics, gold fixtures, manifests or protocol content changed;
   fixture/config/dataset hashes inside `frozen_inputs.json` are
   untouched. Owner flow: checkout the anchor commit, run
   `powershell -ExecutionPolicy Bypass -File tools\compile.ps1
   -Strict` directly from the clean clone (no BOM step), expect exit
   0 with three 0/0 targets; verify evidence from the latest checkout
   carrying the migrated `frozen_inputs.json`. The previous anchor
   note is superseded here, never silently.

---

## 2026-09-08 — First real MetaEditor compile: four fabricated identifiers removed; retry mapping fixed against real MQL5 retcodes; EA metadata version plane

**Trigger.** The owner's Windows environment (MT5 build 6148,
MetaEditor 5.0.0.6184, PowerShell 5.1) ran the first REAL strict
compile: `Mql5Bot.mq5` → 50 errors / 2 warnings; both helper scripts
compiled clean. This is a genuine integration-boundary defect class:
identifiers written without a real MQL5 compiler present.

**Decisions (all preserve canonical AEGIS semantics):**

1. **`TRADE_RETCODE_RETRY` and `TRADE_RETCODE_NO_QUOTES` do not exist
   in MQL5** (official reference: Trade Operation Result Codes —
   10006 is REJECT, 10018 is MARKET_CLOSED). They were removed, not
   renamed to look-alikes:
   - The intended "no quotes" transient is the real
     `TRADE_RETCODE_PRICE_OFF` (10021, "there are no quotes to process
     the request") — used at the three self-detected no-quote sites in
     `TradeManager.mqh` and already present in the retryable set.
   - The intended "server says retry" class has NO real equivalent;
     the transient classes are explicitly covered one-per-code by
     `REQUOTE` (10004), `PRICE_CHANGED` (10020), `PRICE_OFF` (10021),
     `TIMEOUT` (10012). The fake RETRY case was DELETED — mapping it
     onto REJECT would invert semantics (a refusal is fatal).
     Rejects/market-closed/invalid-* stay fatal: fail-safe = never
     retry what we do not understand (SPEC §8.D unchanged).
2. **`POSITION_TYPE_LONG/SHORT` do not exist in MQL5** (real
   `ENUM_POSITION_TYPE` = {POSITION_TYPE_BUY, POSITION_TYPE_SELL}).
   A single explicit mapping was added in `Config.mqh`:
   `#define POSITION_TYPE_LONG POSITION_TYPE_BUY`,
   `#define POSITION_TYPE_SHORT POSITION_TYPE_SELL` — the project
   vocabulary stays at all 27 call sites; values match the real enum
   so every comparison/adoption/netting computation is unchanged.
   The comment documents the four distinct direction concepts
   (signal/position/order/deal) that must never be conflated.
3. **`Ask()/Bid()` are `const`.** They are pure `SymbolInfoDouble`
   reads with no member mutation; `MinStopDist(...) const` may then
   call them under MQL5 const-correctness rules. No cast, no caller
   change, no semantic change.
4. **`Allocation.mqh ParseStrategies` gained an explicit terminal
   `return false`** after its `while(true)` loop. The path is
   unreachable (every iteration returns/continues), but MQL5 requires
   every syntactic control path to return; fail-closed matches the
   parser's defensive contract.
5. **`QueueCancelByTicket` moved to a labeled public block** in
   `CTradeManager`. Ownership analysis: the EA's restart orphan-scan
   owns the recovery POLICY; the TradeManager owns execution
   AUTHORITY. This method is the ONLY external entry into the cancel
   path and it never sends an order directly — it enqueues a bounded,
   magic-tagged, deduped retry item. Making it public is the correct
   boundary, not a visibility accident; nothing else in the private
   region changed.
6. **EA metadata version is a separate plane.** The strict gate
   requires zero warnings; MetaEditor rejects `#property version
   "1.0.0"` for Expert Advisors ("must be xxx.yyy"). The EA and
   `Config.mqh` now carry `#property version "1.00"`. This is
   MetaEditor MARKET-METADATA format only. It does NOT change:
   repository release version 1.0.0 (CHANGELOG/pyproject),
   `MQL5BOT_VERSION "1.0.0"` (telemetry identity), Python Meta layer
   1.0.0 (`docs/VERSION_CONSISTENCY.md`). Scripts keep their existing
   properties (they compiled clean). `#property strict` (MQL4 relic)
   was left in place: the scripts carry it and compiled with zero
   warnings on build 6184, proving it is silent.

**Regression pins.** `tests/test_mql5_sources.py` now enforces: every
`TRADE_RETCODE_*`/`POSITION_TYPE_*` used in MQL5 belongs to the
authoritative real-constant allow-list; the retryable set is exactly
{REQUOTE, PRICE_CHANGED, PRICE_OFF, TIMEOUT}; the LONG/SHORT→BUY/SELL
mapping exists; Ask/Bid are const; QueueCancelByTicket is public;
EA/Config version properties are xxx.yyy.

**Provenance.** No Gold artifact, expected execution, Python research
behavior, or certification rule was touched. The EA source at this
commit supersedes the pre-compile freeze for COMPILATION purposes
only: gold fixtures, manifests and certification protocol are pinned
unchanged (docs-only / MQL5-compile-correctness change under the
freeze policy; the verifier's SOURCE_COMMIT check must be re-anchored
by the owner runbook if and only if this commit is adopted as the new
frozen anchor — recorded here, never silently).

---

## 2026-09-07 — Gold #2 reconstructed with NEW provenance; three sizing-provenance bugs found and closed; forced risk-veto design REJECTED as overfitting

**Status.** Gold #2 exists again as
`GOLD_2_RECONSTRUCTED_NEW_PROVENANCE` (label pinned in
`artifacts/gold_2/manifest.json`). Sandbox-side deterministic evidence
is complete: **GOLD_2_PROVEN (LOCAL_DETERMINISTIC_GATE)**. The MT5 legs
against it (compile/tester/reconciliation) remain
**BLOCKED_OWNER_ENVIRONMENT** per the canonical TEN-step owner protocol.

**No continuity is claimed.** The historical Gold #2 artifacts (the
"seven trades") are absent from this environment; a tree-wide search
found nothing. This reconstruction is a NEW controlled experiment, not
a recovery; the manifest's `continuity_disclaimer` says so in the
artifact itself, and no test or doc may claim the historical trades
reproduce.

**What was built.**

* `examples/strategies/gold2_multifactor.json` — DSL spec: EMA8/21
  trend gate AND (RSI14 strict-zone escape OR Donchian-20 breakout),
  session [08:00, 16:00), state mode, SL 2.0 / TP 3.0 ATR14.
* `python/mql5bot/gold2_reference.py` — independent plain-numpy
  transcription of the spec (the Python↔DSL parity check is a real
  two-implementation comparison, plus `boundary_distances()`).
* `tools/build_gold2_standard.py` — engine-direct deterministic
  fixture builder (4 trading days × 1440 M1 bars, EURUSD parity spec):
  Day 1 meta 1.0 (SL/TP/signal exits, post-TP same-bar re-entry,
  session-boundary book entered 15:58 and flattened at 16:00), Day 2
  meta 0.5 (Risk→Meta ladder SEND 0.01), Day 3 meta 0.1 (escape-driven
  entries, SEND 0.08), Day 4 meta 0.0 (signal present, ALL entries
  dropped). 56 trades, 30L/26S, all three exit reasons, 10
  session-vetoed pre-open fires, RSI escape margins inside the
  ±0.5/±1/±2 bands (computed, persisted in
  `provenance.json::rsi_escape_edges`).
* `artifacts/gold_2/` — manifest, fixture CSV, Python trace, DSL
  trace, expected execution, reconciliation, provenance, all bound by
  the manifest hash chain.
* `tests/test_gold2_standard.py` — 18 tests; NO hand-typed expected
  values: every expectation is recomputed from fixture + engine; parity
  is exact (no tolerance on direction/reasons/vetoes).

**Provenance bugs found and closed (high-value findings).**

1. `META_SCHEDULE` was missing from the config hash. Fixed: the
   time-based allocation schedule is now a first-class member of
   `_config_hash()` (attack test: mutating ONLY the schedule changes
   the hash and the fills).
2. The builder's expected-execution sizing used `atr[signal_bar - 1]`
   — an off-by-one. The engine (`size_lots`) sizes on
   `atr[entry_bar - 1]` = `atr[signal_bar]`. Fixed, and proven two
   ways: a minimal ramp-tape experiment where only the signal-bar ATR
   reproduces the fill (±1 bars are distinguishable), and a full
   fixture reconciliation where all 56 engine fills equal the expected
   rows built from the signal-bar ATR.
3. The sizing BASIS is live equity, not day-start equity: the engine
   re-marks `basis = float(equity[i])` at the end of EVERY bar
   (engine.py). Expected execution now sizes on `equity[signal_bar]`
   and every fill reconciles exactly.

**REJECTED design (anti-overfitting).** An earlier draft added a
fifth day: a staircase of eight crash/spike impulse pairs meant to
force a 7% daily-loss halt inside the Gold fixture. It required
repeatedly escalating impulse magnitudes to overcome EMA-gap physics,
entries landed on momentum continuation bars (turning intended SLs into
TPs), and the resulting cascade was tuned until it produced the desired
ending — SCENARIO_MANIPULATION, not SCENARIO_DESIGN. It was deleted.
Rationale recorded, not hidden: the risk-veto/daily-loss mechanism does
not need Gold #2 to be dramatic; it is covered by dedicated
micro-fixtures (`tests/test_engine.py::test_daily_loss_limit_*`,
`tests/test_safety_micro_fixtures.py` which pins the `<=` halt
comparator by bracketing + literal source contract, and the Meta
reduce-only sweep). Gold #2 records the OBSERVED `risk_vetoes = 0`
honestly.

**Daily-loss halt semantics pinned.** Halt iff
`basis <= day_start_equity * (1 - lim/100)` evaluated at each bar open
on the previous-close basis — equality HALTS; the day lock lifts at the
next server-day boundary. Pinned by bracketing micro-fixture (halt
strictly below threshold, no halt strictly above) plus the literal
comparator check.

**Gold #1 regression.** Byte-identical under the frozen pin
(`--git-commit abea0f410c5a`) after every change in this entry.

---

## 2026-09-07 — RSI zone-escape: Python + DSL aligned to the EA rule — CONTRACT_GAP SUPERSEDED by PROVEN_EXACT (final closure)

**Supersedes.** The earlier same-day entry "RSI threshold tie rule —
CONTRACT_GAP (classified, pinned both ways)" is SUPERSEDED. A semantic
edge may not be simultaneously PROVEN and CONTRACT_GAP; this closure
resolves it to exactly ONE classification: **PROVEN_EXACT**.

**Decision.** The executing EA is the canonical authority for the tie
rule. `SignalEngine.mqh::EvaluateRsiReversal` was NOT modified. Instead,
the Python reference strategy (`mql5bot.strategies.rsi_reversal`) and the
DSL reference spec (`examples/strategies/rsi_reversal.json`, bumped to
version 2) were aligned to the EA zone-escape semantics:

* Zones are STRICT: oversold = `r < Oversold`, overbought = `r >
  Overbought`. Exact ties (r == 30.0/70.0) sit OUTSIDE the zone.
* Escape from oversold fires LONG: prev < oversold (strictly) and now >=
  oversold. Escape from overbought fires SHORT: prev > overbought
  (strictly) and now <= overbought.
* The escaped direction is CARRIED (EA `m_state`): the neutral band
  [oversold, overbought] (inclusive) holds the last direction; while the
  current sample is inside an extreme zone the OUTPUT direction is 0
  (stand aside) while the carried state persists.
* NaN on either sample produces no action (EA: invalid signal). For RSI
  this occurs only during warmup where no position exists, so observable
  behaviour is identical.

**Why this direction of alignment.** The EA is what would execute real
money; aligning the Python/DSL references to it avoids ever claiming the
EA diverges from its own reference. No MQL5 change was made, so no
compile-verified EA session was required to justify an EA edit; only the
runnable references moved.

**Proof.** `tests/test_indicator_semantics.py`:
`test_rsi_zone_escape_python_is_the_ea_rule_exactly` enumerates the full
tie-inclusive (prev, cur) truth table against a verbatim EA transcription
(every case including exact 30/70 ties must agree), and
`test_rsi_zone_escape_neutral_hold_and_extremes_pinned` pins hold-through-
neutral, stand-aside-at-extremes, and NaN warmup suppression. These
supersede the former
`test_contract_gap_python_cross_vs_ea_zone_at_exact_ties`.
`tests/test_dsl_parity.py` validates the DSL spec bar-by-bar against the
Python strategy, so the DSL inherits the same closure.

**Residual (honestly classified).** The sandbox cannot compile or run
MQL5. That the COMPILED EA behaves as transcribed remains the owner's
Strategy-Tester leg (BLOCKED_OWNER_ENVIRONMENT). The sandbox-side semantic
classification for this edge is final: PROVEN_EXACT.

---

## 2026-09-07 — Volume dust-guard unified at 1e-9 step units in BOTH runtimes (Reality Gate §4 semantic closure)

**Finding.** A cross-runtime divergence existed in the volume floor
dust-guard: `python/mql5bot/symbolspec.py::normalize_volume` used
`int(lots/step + 1e-12)` while the MQL5 side
(`SpecNormalizeVolume`, SymbolSpec.mqh:165, and the Meta re-normalisation
in Mql5Bot.mq5 OnNewBar) used `MathFloor(lots/step + 1e-9)`. In the input
zone `(k·step − 1e-9·step, k·step − 1e-12·step)` the two runtimes floored
to DIFFERENT grid points — one full volume step apart, i.e. a potentially
decision-changing split (lot size, and at the min boundary even
accept-vs-reject). The prior parity grid never landed in that zone, so the
split was latent. Reproduced and pinned by
`tests/test_volume_contract.py::test_the_pre_fix_split_zone_is_decision_changing`
(computed with the historical constants; kept as the permanent regression
per §36).

**Decision.** The canonical dust guard is `1e-9` step units in BOTH
runtimes. Python `normalize_volume` is aligned to the MQL5 constant (the
MQL5 source is untouched — it cannot be compile-verified in this sandbox,
and its value was the derivably-correct one). The guard is DERIVED, not
arbitrary:

* Purpose: absorb IEEE-754 double rounding when the TRUE mathematical
  volume sits exactly on the grid but the computed quotient `lots/step`
  lands a few ulp below the integer `k` (budget/loss-per-lot division,
  meta scaling, repeated arithmetic).
* Lower bound (guard must cover division dust): a correctly rounded double
  division errs by ≤ 0.5 ulp of the quotient; the full sizing chain
  (budget construction + loss-per-lot + division) contributes ≤ ~2 · 0.5
  ulp(k). For quotients k = volume_max/volume_step ≤ 1e6 — the DERIVED
  rescue envelope, which covers every realistic MT5 symbol spec (FX
  100/0.01 = 1e4; metals/index ≤ 5e4; crypto 500/0.001 = 5e5) — the worst
  case is ≤ 1.2e-10, an order of magnitude inside the 1e-9 guard. The old
  Python `1e-12` only covered quotients ≤ ~4.5e3, i.e. it silently lost
  one step on on-grid sizes computed from realistic equity/loss quotients
  (undersizing). Beyond the envelope (exotic specs only) the pinned worst
  case is a ONE-STEP UNDERSIZE with cross-runtime parity intact — risk
  only shrinks; the guard can never mint volume upward.
* Upper bound (guard must stay representation-only): the guard can promote
  a strictly-below-grid input by at most 1e-9 of one step (≤ 1e-11 lots
  for step 0.01 — relative risk error ≤ 1e-9 of a step, economically
  zero). Any relaxation beyond ~1e-6 of a step would start swallowing
  economically meaningful sub-step volume and is forbidden.

**Contract (pinned by `tests/test_volume_contract.py`).**
`normalize_volume` maps raw lots → execution volume as: non-positive →
0.0; else floor to the step grid with the 1e-9 dust guard; a positive
input whose floored grid point is below `volume_min` yields `volume_min`
(the SIZER separately rejects below-min risk budgets before ever calling
the normaliser — `BELOW_MIN`; the normaliser's min-bump is reachable only
off the sizing path and mirrors MQL5 exactly); caps
`min(volume_max, volume_limit)` are themselves floored onto the grid; a
cap below the minimum yields 0.0. Python and the MQL5 transcription are
bitwise-equal over the full adversarial matrix — exact equality, not
tolerance. This is `REPRESENTATION_TOLERANCE` (double dust), explicitly
NOT an `EXECUTION_TOLERANCE`: no economic magnitude is ever absorbed.

**Classification of the historical split:** `DECISION_CHANGING` in the
abstract (one-step lot difference; accept-vs-reject at the min boundary),
reachability limited to inputs tuned to ≤ 1e-12 of a step or to double
dust at quotient scales > ~4.5e3 — after unification the split no longer
exists in either direction. Evidence class: `LOCAL_DETERMINISTIC_GATE`
(Python) + `SOURCE_BEHAVIOR` (MQL5 transcription; runtime leg stays
`BLOCKED_OWNER_ENVIRONMENT`).

---

## 2026-09-07 — Cross-event contract, EMA seed parity, and the RSI tie-rule CONTRACT_GAP (Reality Gate §12/§13/§14/§15 closure)

**Cross contract (fixed under explicit contract, regression-locked).**
`indicators.crossover` previously fired an event at the NaN→value warmup
boundary (a NaN predecessor compared as "below" via `np.roll` padding),
while the EA — after the NaN value-feed fix above — suppresses evaluation
until two valid samples exist. That was a cross-runtime signal divergence
on every RSI-strategy warmup. Fix: an event now requires BOTH the current
and the previous sample valid. Polarity pinned: +1 = crossed above, −1 =
crossed below; `crossunder(a,b) == −crossover(a,b)` elementwise; the three
spellings `crossover(a,b) < 0`, `crossunder(a,b) > 0`, `crossover(b,a) > 0`
denote the SAME event — proven elementwise over the full NaN-inclusive
truth table (`tests/test_indicator_semantics.py`). The earlier
`crossunder` docstring described the sign backwards; corrected (docs-only,
the DSL runtime never consumed the sign). No threshold or polarity moved.

**EMA seed parity — classification: FORMAL_MODEL_PARITY +
WARMUP_EQUIVALENCE, quantified (mission §12).** Python canonical EMA
(manifest contract-v1) uses the SMA seed (first valid bar n−1); the
platform-model iMA computes from bar 0 seeded at price[0] (seeding detail
= COMMUNITY_EVIDENCE; official docs do not publish it — the owner's tester
leg is the final arbiter). Measured on the FROZEN gold fixture
(`tests/test_ema_seed_parity.py`):

* The seed residue decays EXACTLY geometrically at the forgetting factor
  (1 − 2/(n+1)) per bar — measured vs theory agree to 1e-6 relative. This
  DERIVES the decay ratios instead of pinning arbitrary ones: EMA(10)
  residue shrinks (11/9)^30 ≈ 411.6× per 30 bars; EMA(30) shrinks
  (31/29)^30 ≈ 7.39× per 30 bars. Residue < 1e-6 price units by bar 19
  (fast) / 53 (slow) on this fixture.
* Decision audit: ema_crossover_ref desired positions are IDENTICAL
  between seed models from bar 29 to the fixture end; before bar 29 the
  Python model is flat by contract. Measured near-miss margin: min
  |fast−slow| separation from bar 29 = 6.62e-6 vs max seed residue
  4.84e-6 → 1.37× ON THIS FIXTURE. HONEST LIMITATION: this does not
  prove decision-neutrality for arbitrary data — a seed flip inside the
  first ~slow-period bars remains possible on other datasets and stays
  classified WARMUP until the owner's MT5 reconciliation settles the
  platform side. Convergence alone is NOT accepted as parity; the window
  and margin are the contract.
* `indicators.ema` seeding was NOT changed (mission: never silently).

**RSI threshold tie rule — CONTRACT_GAP (classified, pinned both ways).**
**SUPERSEDED 2026-09-07** by the PROVEN_EXACT closure at the top of this
log (Python + DSL aligned to the EA zone-escape rule). Kept for history.
The Python cross-event spelling fires when the previous sample EQUALS the
line then moves off it (`≤`→`>`), while the EA zone-escape requires the
previous sample STRICTLY in the zone (`<` then `≥`), and symmetrically at
the current tie. The difference exists ONLY when RSI lands EXACTLY on
30.0/70.0 — constructible in fixtures, effectively measure-zero on tick-
quantized broker data, but NOT provably unreachable. Both behaviours are
pinned elementwise (`test_contract_gap_python_cross_vs_ea_zone_at_exact_ties`);
closing the gap belongs to the three-way reference-parity workstream and
requires a compile-verified EA session — it was NOT closed by intuition
here. Everything else in the (prev,cur) ∈ {NaN, below, equal, above}²
matrix is contractually identical.

**State memory (§14) & extreme transitions (§15).** `crossover`/
`crossunder` are pure and stateless: repeated evaluation, restart (fresh
copy) and replay are bitwise identical; a one-bar mutation never changes
decisions strictly before it. Extreme→extreme single-bar jumps produce
exactly ONE event in the observed direction — bar-close sampling observes
no intermediate values BY DESIGN; documented, not "fixed".

---

## 2026-09-07 — Warmup policy fixed as deterministic NaN propagation; EMPTY_VALUE never reaches a comparator (Reality Gate §8–§10 closure)

**Finding (source audit, MQL5 leg = BLOCKED_OWNER_ENVIRONMENT).** The EA's
`SignalEngine.GetValue` returned `0.0` on `INVALID_HANDLE`/CopyBuffer
failure and passed `EMPTY_VALUE` (DBL_MAX — the official MQL5 marker for
uninitialized indicator buffer slots, mql5.com "Other Constants"; RSI(14)
first valid value is index 14 per the official "Applying One Indicator to
Another" article) straight through to the strategy comparators. The
`IsNaN()` guards in the five strategies were therefore dead code on those
paths, and three warmup phantom-signal classes existed at source level:

* RSI_REVERSAL — on the FIRST valid RSI bar, `rPrev == EMPTY_VALUE`
  compares as overbought, the "escape overbought" transition fires, and a
  phantom SELL is produced (unless RSI happens to be below oversold).
* BOLLINGER_REVERSAL — `EMPTY_VALUE` lower band compares `close < lower`
  → phantom BUY in the first period−1 bars.
* MACD_MOMENTUM — `EMPTY_VALUE` signal line compares `line < signal`
  → phantom SELL before the signal line exists.
* DONCHIAN_BREAKOUT — independent class: out-of-range `iHigh`/`iLow`
  return 0, fabricating a zero-width channel → phantom breakout before
  N+2 bars exist.
* EMA_CROSSOVER — no EMPTY_VALUE region (built-in iMA computes from bar
  0); its only warmup difference is the seed (§ EMA seed contract below).

The Python canonical strategies are NaN-padded and NaN-guarded (no signal
before readiness), so the split was a genuine cross-runtime signal
divergence — a certification blocker until fixed.

**Decision (smallest justified contract — no new policy invented).** The
project's warmup model is (C) **deterministic NaN propagation**: an
unavailable/uninitialized indicator value is NaN in BOTH runtimes, every
strategy suppresses evaluation on NaN, and a suppressed bar emits an
INVALID signal (EA) / zero desired position (Python). `GetValue` now maps
INVALID_HANDLE, CopyBuffer≤0, and EMPTY_VALUE to an IEEE NaN (runtime
0/0), activating the already-present `IsNaN` guards; `EvaluateDonchian`
gates on `Bars(symbol, tf) >= period + 2` (the channel's shift range).
This is the minimal change that makes the MQL5 side honour the SAME
contract the Python side and the gold-standard traces already implement —
nothing about thresholds, signal polarity or Meta behaviour moved.

**INIT_FAILED audit (§10).** `INIT_FAILED` is used ONLY for fatal EA
states, each with a logged reason: symbol-spec build failure, trading not
enabled (terminal/EA/account), SignalEngine handle creation failure
(missing indicator IS fatal), PositionGuard init failure, magic
allocation failure, TradeManager/Allocation/StateStore init failures.
Input validation uses `INIT_PARAMETERS_INCORRECT` (distinct category).
Data insufficiency is explicitly NOT fatal — it suppresses signals via the
NaN contract above. `INIT_FAILED` is not a catch-all validation
mechanism, and no new path was added.

**Readiness matrix (first valid bar, closed-bar shift-1 evaluation).**

| Indicator | Lookback | First valid (0-based) | Stateful | NaN behaviour | Requires previous | Platform init (evidence class) | Python init | Contract |
|---|---|---|---|---|---|---|---|---|
| iMA MODE_EMA | 0 | bar 0 (seed = price[0]) | recursive | no EMPTY region | yes (recursive) | computed from first bar (COMMUNITY_EVIDENCE; runtime = owner leg) | SMA seed at bar period−1 | WARMUP-classified seed difference (§ EMA entry) |
| iRSI(14) | 15 | bar 14 | Wilder recursion | EMPTY_VALUE bars 0..13 (OFFICIAL_DOCUMENTATION) | yes | EMPTY prefix (OFFICIAL_DOCUMENTATION) | SMA seed, first valid bar 14 | NaN until first valid; suppressed |
| iATR(14) | 15 | bar 14 (Wilder) | Wilder recursion | EMPTY prefix | yes | EMPTY prefix (OFFICIAL_DOCUMENTATION, same mechanism) | Wilder, first valid bar 14 | NaN until first valid |
| iBands(20) | 20 | bar 19 | none | EMPTY bars 0..18 | no | EMPTY prefix (OFFICIAL_DOCUMENTATION) | SMA±k·σ, first valid bar 19 | NaN until first valid |
| iMACD(12,26,9) | main 0 (platform) / slow−1 (Py); signal +signal−1 | Py: main bar 25, signal bar 33 | recursive | EMPTY prefix where undefined | yes | main computed from bar 0 (seeded like iMA); signal EMPTY until defined (COMMUNITY_EVIDENCE; owner leg) | EMA-diff valid bar slow−1; signal valid bar slow+signal−2 | NaN until first valid; WARMUP-classified window difference vs platform (gold strategy unaffected) |
| Donchian(N) | N+1 bars | closed-bar index N (EA gate: `Bars >= N+2`) | state var | n/a (raw highs/lows) | state persists | Bars gate (this decision) | NaN-padded channel, valid from index N | invalid until window fully defined; both runtimes use the SAME prior-N window |

Evidence classes per §11: OFFICIAL_DOCUMENTATION (EMPTY_VALUE semantics,
RSI first-valid index), SOURCE_BEHAVIOR (the EA source as written),
COMMUNITY_EVIDENCE (iMA/iMACD seeding specifics — not settled until the
owner's tester leg), TESTED_RUNTIME = none in this sandbox (no MetaEditor)
→ those legs stay `BLOCKED_OWNER_ENVIRONMENT`.

**Regression lock.** `tests/test_indicator_readiness.py` (matrix +
phantom-signal reproduction of the OLD behaviour + proof the fixed
semantics suppresses), `tests/test_mql5_sources.py::
test_signal_engine_nan_warmup_contract` (source pins).

---

## 2026-09-04 — 0–20 execution plan: Phase 9 environmental blocker, parallel-research protocol (documented decision)

**Decision.** The canonical 0–20 execution plan (owner-pasted, governs from
this date) requires each phase's EXIT GATE before the next begins, and any
gate that cannot pass must STOP with a report.  Phase 9 (MT5 Truth Engine)
cannot pass in this Linux sandbox: its gate is "PASS only if on Windows:
EA compiles, tester executes, raw report preserved, parser reads a real
report".  Python-only research phases 10–13 therefore proceed **in
parallel** while Phase 9 stays **OPEN** — this mirrors the repo's standing
pattern (MetaEditor verification is an owner round-trip; the Compile line
of PROGRESS.md has reported NOT VERIFIED every phase and is never guessed).
Nothing claiming MT5 execution truth is produced: phase-10 benchmarks and
phase-11+ statistics remain FAST-engine research results, explicitly not
final certification until the Phase-9 owner round-trip passes and the
Truth-Engine reconciliation exists.  Phase order otherwise unchanged;
re-opening this waiver requires a new DECISIONS entry.

---

## 2026-09-04 — Headless tester: deterministic contract + locale-tolerant report parsing (AEGIS Phase 2)

**Decision.** The headless Strategy Tester stack (`python/mql5bot/mt5tester.py`,
`tools/run_mt5_backtest.{py,ps1}`) fixes symbol/timeframe/model/dates/
deposit/currency/leverage explicitly per run and derives a deterministic
report stem, but does NOT pretend to control spread: MT5 tester applies the
broker symbol conditions (spread source, tick history). Cost scenarios
(BASE/STRESSED/SEVERE) are applied in the Python execution model and
compared against MT5 runs with documented tolerances (Phases 4/6) — never
presented as identity. MT5 tester HTML reports are locale-labelled; the
parser therefore (a) preserves every raw label/value pair, (b) matches
metrics through English synonym labels case-insensitively, and (c) treats
the report file as the source of truth when any ambiguity remains. The
.5f engine enumeration per MetaTrader 5 docs is 0 = every tick, 1 = 1-minute
OHLC (default), 2 = open prices, 3 = every tick on real ticks, 4 = real
ticks. Raw `.htm` reports are always preserved before parsing; exit code 3
guards `run`/`batch` on non-Windows hosts instead of silently skipping.
Owner round-trip remains mandatory before any backtest claim (HANDOFF §10).

## 2026-09-04 — Compile round-trip gates on real compiler output (AEGIS Phase 1)

**Decision.** `tools/compile.ps1` verifies success only when the produced
`.ex5` exists AND is newer than the compile start time, with the MetaEditor
log captured verbatim (per-file logs in `%TEMP%`, one combined reproducible
log with SHA-256s in `logs/`). English `error`/`warning` tokens are counted
when present; non-English MetaEditor builds produce no tokens, so the
`.ex5` freshness check is authoritative and the raw log is always kept for
human review — a stale `.ex5` from an earlier build is never accepted as
proof. `-Strict` fails the run on any warning token.

---

## 2026-09-04 — Keep the committed Mql5Bot tree in place while Aegis releases land (DEV)

**Decision.** The canonical layout in SPEC §6 (`ea/MQL5/...`, `factory/...`,
`schemas/`, `research/`, docs set) is the destination architecture, but this
repository already contains a working, tested, two-language stack under
`mql5/`, `python/`, `tests/`. We will NOT rename/move/restructure that tree as
a first step: restructuring without a compile-capable environment would
destroy working functionality for zero behavioural gain (audit §1, §7).

**Rationale.** Release work is incremental and evidence-based. The Mql5Bot EA
becomes the Release-A seed: its files grow into SPEC §8 behaviour, and new
canonical models are first implemented in Python where they can be unit-tested
in this sandbox, then ported to MQL5 in compile-verified sessions (audit §17).
SPEC §8 class/file names (e.g. `SymbolSpec.mqh`) will be used for new MQL5
files when they are added, inside the existing `mql5/Include/Mql5Bot/` tree.

**Cost.** The layout differs from SPEC §6 until a later consolidation release;
`docs/IMPLEMENTATION_AUDIT.md` §1 maps current paths. The SPEC §6 layout
remains the target for a dedicated, separately planned refactor that keeps
`git history` intact and is verified by the MQL5 unit-test harness.

## 2026-09-04 — Python-first canonical risk/identity models (DEV)

**Decision.** Release-A's "injected `SSymbolSpec` risk math", "volume/price
normalisation", and "FNV-1a magic derivation" are implemented first as pure,
dependency-light Python modules in `python/mql5bot/` (canonical model +
synthetic-spec tests), and the MQL5 port must match them. The existing
`CRiskManager`/`CTradeManager` code is left running untouched until the port
lands in a compile-verified session.

**Rationale.** SPEC §14 requires PositionSizer tests on synthetic broker specs
(EURUSD 5-digit, USDJPY, XAUUSD, US30-like, BTCUSD-like; clamping; insufficient
margin). MetaEditor is unavailable in this environment, so MQL5 changes cannot
be compile-verified here; the Python twin is the verifiable specification of
the arithmetic. This mirrors the existing, working strategy-parity approach
(README "Strategy ↔ backtest parity") and extends it to risk code. Keeping the
old EA untouched avoids regressions (task rule: never destroy working
functionality).

**Cost.** A short window where the live EA's internal math and the canonical
Python model are not yet byte-identical; the EA remains demo-only per its own
documentation, and the port task is tracked in the audit's order list (§17.2).

## 2026-09-04 — SPEC.md §19 (external references) reconciliation (DOC)

**Decision.** The committed `docs/SPEC.md` ends at §18 "OUTPUT STYLE".
HANDOFF.md §4.17 refers to "SPEC §19" for the external-repository policy
(paper_trading_view, BTC multi-horizon builder, MT5 docker/data-bridge,
AutoTradeSignal/core, highcharts). Policy is applied as written in HANDOFF §4
and in the work-session brief: reference-only, no third-party trading code
imported, no Highcharts, no Selenium in the core. When SPEC.md is next
edited, fold this section in as its final numbered section.

## 2026-09-04 — Version naming (DOC)

**Decision.** The committed code labels itself Mql5Bot "1.0.0"
(`Config.mqh`, `Mql5Bot.mq5`, `CHANGELOG.md`). Aegis `v1.0.0` per SPEC §5.6 is
the end of Release E. The code's own version string keeps tracking the
committed EA codebase; Aegis release tags (`A-ea-core` … `v1.0.0`) are
separate and follow SPEC.

---

## 2026-09-04 — Engine state hardening (never soften a halt or pause)

**Decision.** `ENGINE_NO_NEW_TRADES` (daily-loss breach) is the *soft* pause
and `ENGINE_HALT` (drawdown kill switch, SL-guard escalation, manual trip)
is the *hard* stop. Only a day rollover clears the daily-loss pause; the
kill switch is cleared ONLY by an explicit one-shot reset (input
`InpResetKillSwitch` + GlobalVariable `reset_ack` edge — see state-store
commit) — never by equity recovery and never by a rollover. A daily-loss
breach while a guard pause or the halt is active must NOT soften that state
(the EA only applies the daily pause from `ENGINE_NORMAL`). Mirrored in
`python/mql5bot/failsafe.py`.

## 2026-09-04 — Cold-state persistence: strict text, delete-then-write

**Decision.** Internal EA state files (`AEGIS_STATE v1` ticket registry,
`MAGICMAP v1`) stay strict line-based text until the EA↔Factory JSON
contract ships (a reviewed JSON writer lands with that contract). Saves are
delete-then-write because `FileOpen(FILE_WRITE|FILE_READ)` does not
truncate — stale tail rows would resurrect removed tickets/ids on load.
Reads are strict: a corrupt header quarantines the file aside (never
applied partially); malformed rows are skipped. Hot state (kill switch,
reason, day key, day-start equity, equity peak) rides GlobalVariables so a
restart always restores it; management flags (`partialDone`, `beDone`) are
persisted per `POSITION_IDENTIFIER` in the cold registry — never in the
position comment (brokers overwrite comments).

---

## Earlier decisions carried from HANDOFF.md §4 (kept; [SPEC]-consistent)

1. **[SPEC §3.1]** Signal/Risk separation: strategies emit signals only;
   meta-layer and Risk Engine veto; Factory never trades (files only).
2. **[SPEC §3.2]** Every position always has an SL; failure to set SL → close +
   CRITICAL + alert.
3. **[SPEC §3.3, §3.10]** Query broker specs at runtime; all risk math on an
   injected `SSymbolSpec` struct (unit-testable with synthetic specs).
4. **[SPEC §3.9]** Stable identity: Magic = FNV-1a hash of `strategy_id` into a
   reserved range, persisted in a registry; never index-based.
5. **[SPEC §3.8]** Attribution/management state persisted by
   `POSITION_IDENTIFIER` in files, NOT in the position comment (brokers
   overwrite comments).
6. **[SPEC §3.4]** No `Sleep()`; retries via a `RetryQueue` processed in
   OnTimer with backoff.
7. **[SPEC §9]** Strategy Tester: DSL specs delivered as one bundle via
   `#property tester_file`; WebRequest/Calendar skipped in tester.
8. **[SPEC §2]** Releases A→E gated by DoD; release N+1 starts only after N is
   tagged. Compiled AND DSL copies of the 4 reference strategies with a
   bar-by-bar parity test (golden test of the DSL engine).
9. **[SPEC §12.2]** Combination default = `weighted_netting` (one book position
   per symbol; opposite signals netted; pro-rata attribution).
10. **[SPEC §12.2]** Weights = gate × regime_fit × performance × correlation ×
    drift factors; adaptive part clamped [0.25, 1.5], ≤ ±15 %/day; hard zeros
    allowed; daily cadence; ≤10 meta parameters.
11. **[SPEC §10.4]** Gate 3 demo = ≥ 4 weeks AND ≥ 30 trades (low-frequency
    exception: ≥ 8 weeks AND ≥ 15 trades, flagged). OOS budget: one look per
    strategy version.
12. **[SPEC §8.C]** Kelly sizing capped ≤ 0.25 Kelly, off by default;
    martingale forbidden; grid/averaging off by default and hard-capped.
13. **[SPEC §8.H]** Two separate Telegram bot tokens (EA vs Factory).
14. **[SPEC §4]** Factory: Python 3.11+, FastAPI, SQLAlchemy+Alembic, SQLite,
    Jinja2+HTMX (no JS framework), binds 127.0.0.1, password from env; MQL5
    compile is local-only (PowerShell), GitHub CI is Python-only.
15. **[SPEC §8.A]** Server GMT offset estimated from
    `TimeCurrent() − TimeGMT()` when connected, persisted.
16. External repos: read-only inspiration; no third-party trading code; no
    Highcharts (licensing) — if interactive charting is ever needed,
    TradingView lightweight-charts only, recorded here first.

## Open questions

- None blocking. (Owner-side compile logs for MQL5 batches are required before
  those batches are considered done — see audit §17.)

## ML-1..ML-7 — Meta Layer contract 1.0.0 → 1.1.0 (2026-09-05)

Pre-implementation contract hardening (mandate Phase 1).  All seven
corrections resolve ambiguity or non-determinism that would have made
the implementation contradictory or order-dependent; none weakens a
safeguard.  Full rationale in `docs/META_LAYER_IMPLEMENTATION_SPEC.md`.

- **ML-1 (correlation simultaneity).**  The 1.0.0 wording
  ("overlapping exposure with already-weighted strategies") is
  sequential and order-dependent: A→B→C ≠ C→A→B.  Corrected to a
  SIMULTANEOUS snapshot: one pairwise correlation matrix over all
  eligible candidates × the PREVIOUS decision's persisted weights
  (equal prior when absent) → one raw penalty vector.  Permutation
  invariance is a pinned test property, not an implementation
  accident.
- **ML-2 (missing data classified, not neutralized).**  1.0.0 said
  missing source → NEUTRAL 1.0.  That is a free pass: an uncertified
  or unmonitored strategy would quietly earn full weight.  Corrected
  to: REQUIRED source missing ⇒ INELIGIBLE (UNCERTIFIED); OPTIONAL
  source missing for one strategy ⇒ bounded conservative fallback
  (the zero-observation value) + journal flag; missing for ALL ⇒
  global equal-weight fallback.  Neutral 1.0 is never granted.
- **ML-3 (all-zero vs global failure).**  The 1.0.0 pair (hard zero /
  equal-weight fallback) left the "all raw scores == 0" state
  undefined.  Corrected: zero WITH source present is a HARD ZERO
  (ineligible, never resurrected); all candidates hard-zero ⇒ SAFE
  HOLD, not equal weight.  Equal weight exists ONLY for global
  source failure.
- **ML-4 (normalization pipeline made explicit).**  "Normalization
  may only REDUCE weights" was imprecise (a proportional share of a
  budget can exceed a small raw product).  Replaced by the normative
  pipeline: mask → proportional share → cap (reduce) → bounded
  redistribution into uncapped ELIGIBLE only → budget scale →
  constraints (reduce) → change limit.  Zeros never receive mass.
- **ML-5 (determinism clauses).**  strategy_id-ascending ordering,
  lexical tie-breaks, canonical JSON serialization, fixed float
  policy — byte-identical journals for identical inputs.
- **ML-6 (eligibility taxonomy + activation states).**  Named
  INELIGIBLE reasons (UNCERTIFIED, CERT_FAILED, REGIME_FORBIDDEN,
  REGIME_UNKNOWN, DRIFT_BLOCK, STALE_DATA, DISABLED, COOLDOWN,
  KILL_SWITCH, CONFIG_INVALID) and the DISABLED→SHADOW→DEMO→
  LIVE_SMALL→ACTIVE ladder with explicit, audited, never-automatic
  transitions (default DISABLED).
- **ML-7 (daily weight-change limit).**  New clause controlling
  weight oscillation between decisions (config `max_weight_change`,
  default off).  Hard zeros always take effect immediately;
  re-entry restarts from zero.  Risk Engine remains the final
  authority for every order (unchanged, restated).

## ML-8 — EA allocation consumer & sizing seam (2026-09-05)

Implementation decision under the UNCHANGED SPEC contract
(`in/allocation.json`, line 107).  (a) `mql5/Include/Mql5Bot/Allocation.mqh`
is a strict consumer of exactly the documented schema: schema_version
"1", digest, computed_at (UTC ISO), per-strategy id/weight; stale
(>7 days) decays to the caller's base gate weight; missing/malformed
falls back to the base gate weight — never "last known good" and
never silently applied.  (b) The single EA seam scales risk-approved
lots AFTER `RiskManager.GetLots` and BEFORE any order path —
reduce-only by construction; SL/TP, risk %, limits and the kill
switch are untouched.  (c) No Meta Layer math is duplicated in MQL5
(weights are computed only in `meta_layer.py` and consumed in the EA;
parity is by construction, pinned structurally).  No contract revision
was required.

## ML-9 — Exposure clamp vs Risk-Engine authorities (contract 1.1.0 → 1.1.1)

Empirical-gate mission Phase 1 found that §5.2 ("Daily clamp … clamped
to the portfolio daily-loss budget enforced by the Risk Engine") could
be read as if the Meta Layer computes or targets the daily-loss budget.
It does not and must not: the four controls are DISTINCT and remain
owned as follows — (A) meta weight-change limit = Δweight between
decisions (Meta); (B) daily-loss limit = maximum permitted account
loss (Risk Engine ONLY); (C) drawdown kill-switch = maximum equity
drawdown (Risk Engine ONLY); (D) portfolio exposure cap = maximum
allocation/exposure (Meta owns its ALLOCATION budgets; the Risk
Engine owns the hard account exposure limits).  §5.2 is reworded
accordingly: the layer's clamps are its own allocation budgets; no
daily-loss or drawdown quantity is an input, parameter, or branch of
the Meta Layer.  The implementation already matched the corrected
semantics (no such input exists in code); this was a WORDING fix, and
a regression test now pins that the layer's surface cannot express a
daily-loss or drawdown authority.

## ML-10 — Version consistency: declared contract version corrected to 1.1.1 (2026-09-05)

Audit (meta-production mission, Phase 1) found the Python producer
(`meta_layer._versions()`) and the MQL5 consumer header declaring contract
**1.1.0** while the implemented semantics have been contract **1.1.1**
(ML-9, authority split) since `0a722f1`. Resolution: contract **1.1.1** is
the single authoritative version; the producer now emits
`CONTRACT_VERSION = "1.1.1"` from one code constant; `Allocation.mqh` and
`Mql5Bot.mq5` references updated. No contract clause changed; the
allocation wire format is unchanged (`body.schema_version = "1"`);
readers gate on `decision_version`/`schema_version`, never on
`contract_version`, so journals/files remain compatible both directions.
The contract document's stale lifecycle note (claiming no implementation
exists) is replaced by the real status: IMPLEMENTED — SOFTWARE PASS;
EMPIRICAL VALIDATION: SHADOW-READY; MT5/demo evidence PENDING (owner).
Enforced by `tests/test_docs_consistency.py`.

---

## D-CONV-1..6 — Final convergence decisions (2026-09-06)

1. **Entry chain is ONE function** (`discovery/entry_chain.py`) implementing the §57 event order; non-strategy origins are refused BEFORE any gate. Rationale: veto order must be inspectable in a single place; per-layer checks scattered across call sites allowed "who blocks whom" to drift.
2. **Approval records bind evidence hash + policy version; machine actors can never carry human_approval=True.** Rationale: §32 structured approvals are the last human checkpoint — a forgeable flag is worse than none.
3. **Governor applies decay×ramp AFTER gross-target normalization.** Rationale: safety multipliers that get renormalized away are decorative; degradation must reduce REAL allocation.
4. **Campaign progress is bound to policy hash AND dataset hash; either mismatch refuses continuation.** Rationale: §15 data-boundary — continuing research across a data change silently invalidates every stored comparison.
5. **Correlation classification distinguishes UNKNOWN instead of defaulting to 0 or 1.** Rationale: §26 — missing evidence must not impersonate an answer; portfolio admission already treats UNKNOWN conservatively.
6. **Research runner is injected into the console; without it campaigns are registered PAUSED with a visible warning.** Rationale: a fake "research done" is a §0 violation (no silent approximation).
