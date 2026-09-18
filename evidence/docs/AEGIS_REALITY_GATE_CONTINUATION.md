# AEGIS — REALITY GATE CONTINUATION AUDIT (session 2026-09-07)

**Branch:** `arena/01a07c73-mql5bot` (session-pinned).
**Parent work:** `arena/01a070b0-mql5bot` tip `b8004f81` (166 commits),
merged into this branch by fast-forward at session start — no history
rewritten, no work reset.
**Mission:** continue the Reality Gate to `PROVEN` or
`BLOCKED_OWNER_ENVIRONMENT`. No fabricated evidence.

---

## §0 Reconciliation record (what was actually true at session start)

```text
checked-out branch   arena/01a07c73-mql5bot @ 817d20d (== origin/main,
                     1 commit). The mission-referenced branch
                     arena/01a07b97-mql5bot DOES NOT EXIST on the remote.
prior gate work      recovered from origin arena/01a070b0-mql5bot
                     (b8004f81): reality-gate audit, gold standard,
                     166 commits — merged fast-forward, verified clean.
UNRECOVERABLE        the session the mission describes (H-01 tripwire
                     test, "§4 sweep 24/24", "9/9 proof suite",
                     ratios 4.78e9×/9.33e6×, pins 1e9/1e6, "39 doc
                     anchors", "§6 17/17") left NO artifacts on any
                     remote branch. Those claims are treated as
                     UNVERIFIED — none of them is inherited below;
                     everything is re-derived from files and git state.
working tree         clean before and after the merge
python               3.11.2 (fresh venv; deps installed from
                     requirements.txt + ruff 0.16.6 + optuna 5.0.0)
baseline suite       1190 collected / 0 failed / 1 skipped
                     (optuna-present guard) — matches the prior audit's
                     claim EXACTLY; reproduced from scratch
ruff                 All checks passed (re-run, not assumed)
MQL5 toolchain       ABSENT (no MetaEditor/wine) → every MQL5 runtime
                     leg is BLOCKED_OWNER_ENVIRONMENT, as before
gold artifacts       artifacts/gold/* present; manifest hash
                     4bb14203…89a7766b2cf0e278e
```


### Status-vocabulary drift audit (mission §3) — no synonym collapse

Audited every evidence/status term across `docs/*.md`
(PROVEN_EXACT, PROVEN_DECISION_EQUIVALENT, PROVEN with scope qualifiers
`(source)/(contract)/(Python leg)/(classified)/(re-derived)`,
CONTRACT_GAP, BLOCKED_OWNER_ENVIRONMENT, SOURCE_BEHAVIOR,
OFFICIAL_DOCUMENTATION, COMMUNITY_EVIDENCE, IMPLEMENTATION_BUG, and the
feature-completion states IMPLEMENTED/PARTIAL/NOT_IMPLEMENTED):

* No evidence status is collapsed into a weaker/stronger synonym:
  `PARTIAL` appears ONLY as feature-completion state or in the fixed
  phrase "PYTHON↔MQL5 PARTIAL"; it is never used where PROVEN is owed.
* No MT5-runtime status (`MT5-VALIDATED`, tester evidence, reconciliation)
  is claimed anywhere from sandbox-only evidence; every such leg is
  BLOCKED_OWNER_ENVIRONMENT.
* COMMUNITY_EVIDENCE (MT5 built-in indicator seeding) and
  SOURCE_BEHAVIOR labels are kept distinct from PROVEN throughout.
* The ONE classification contradiction found — the RSI exact-tie edge
  recorded as PROVEN (matrix row 9) in one place and CONTRACT_GAP in
  another — violates "the same edge may not be simultaneously PROVEN and
  CONTRACT_GAP". Per the mission rule it is assigned exactly ONE
  classification: PROVEN_EXACT, by taking the executing EA as canonical
  for the tie and aligning the Python/DSL references to it. The
  assignment is recorded in DECISIONS.md (2026-09-07 top entry) and the
  code/spec/test alignment ships in the RSI-closure commit of this same
  series; the former CONTRACT_GAP entry is marked SUPERSEDED.

## §1 Category map (kept separate, never collapsed)

* **CANONICAL** — SPEC.md v4; DECISIONS.md entries; the gold manifest
  contracts (signal timing, both-touch stop-first, EMA contract-v1 SMA
  seed, ATR Wilder 14, risk_percent_equity sizing, meta reduce-only).
* **IMPLEMENTATION DETAIL** — Python normaliser/sizer/engine internals,
  MQL5 module internals, the exact dust-guard constant (now a CONTRACT
  constant, `VOLUME_FLOOR_DUST_EPS`), GetValue plumbing.
* **OBSERVED (this session)** — the 1e-12/1e-9 volume-epsilon split; the
  EMPTY_VALUE/0.0 warmup value feed; the crossover NaN-boundary event;
  the RSI tie-rule difference; gold #1 byte-identity under the pin;
  all test outcomes cited below.
* **INFERRED (labelled)** — MT5 built-in indicator seeding (iMA price[0],
  iMACD main-from-bar-0) = COMMUNITY_EVIDENCE, not settled without the
  owner terminal leg.
* **CERTIFIED (sandbox-side)** — everything marked PROVEN in §14 with a
  named test/artifact.
* **BLOCKED** — MT5 compile, Strategy Tester, Python↔MT5 reconciliation,
  broker symbol-spec export, demo, live: all `BLOCKED_OWNER_ENVIRONMENT`
  (no MetaEditor/terminal/broker in this Linux sandbox).

## §2 Findings fixed under explicit contract (this session)

### F-1 Volume floor dust-guard split — was DECISION_CHANGING (§3.2/§4)

* Raw input class: any lots whose quotient `lots/step` falls in
  `(k − 1e-9, k − 1e-12)` step units below a grid point `k·step`
  (reachable via double dust at quotient scales above ~4.5e3, or via
  constructed inputs).
* Python (pre-fix) floored to `(k−1)·step`; MQL5 floored to `k·step`.
  One full volume step apart; at the min boundary the same class flips
  accept-vs-reject. Classification: `DECISION_CHANGING`.
* It did not affect the gold ladder (EURUSD step 0.01, quotients ≤ 1e4,
  no zone hits) — but that is luck of the fixture, not a proof.
* Fix: unified at `1e-9` step units in both runtimes (Python moved; MQL5
  untouched — it held the derivably-correct value). Threshold DERIVED:
  covers ≤ 0.5-ulp division dust for quotients ≤ 1e7 and ≤ ~2-op chains
  for quotients ≤ 1e6 (every realistic `SYMBOL_VOLUME_STEP` spec); can
  promote strictly-below-grid inputs by ≤ 1e-9 of one step
  (representation-only; never execution tolerance). Beyond the envelope
  the pinned worst case is a one-step UNDERSIZE with parity intact.
* Contract now: `docs/DECISIONS.md` 2026-09-07 (volume entry) +
  `tests/test_volume_contract.py` (60 tests incl. the legacy-split
  reproducer and bitwise Python↔MQL5-transcription sweep).

### F-2 Warmup value feed — EMPTY_VALUE/0.0 reached comparators (§8/§10)

* MQL5 `GetValue` returned 0.0 on failures and passed EMPTY_VALUE
  (DBL_MAX, official MQL5 marker for uncomputed buffer slots) through to
  strategy comparators; the `IsNaN` guards were dead code. Source-level
  phantom classes: RSI first-valid-bar SELL, Bollinger warmup BUY, MACD
  warmup SELL, Donchian out-of-range-zero breakout. Python strategies are
  NaN-suppressed → genuine cross-runtime signal divergence.
* Fix (MQL5, source-level evidence only — compile leg owner-gated):
  deterministic NaN propagation; `Bars >= period + 2` gate for Donchian.
  INIT_FAILED untouched (audit below). Warmup model = mission §9 option
  (C), the smallest contract consistent with the existing Python
  semantics — no new policy invented.

### F-3 Cross events fired at the NaN warmup boundary (§13)

* `crossover` rolled NaN predecessors into "below", minting an event on
  the first valid sample of every warmed-up series. Fixed: events require
  BOTH samples valid. Full truth table + tie asymmetry pinned (below).

### F-4 RSI threshold tie rule — CLOSED as PROVEN_EXACT (final, 2026-09-07)

* The former exact-tie difference is now CLOSED by aligning Python and
  the DSL reference spec to the executing EA rule (DECISIONS.md final
  entry). The EA is canonical for the tie; its source was NOT modified.
* `strategies.rsi_reversal` and the DSL `rsi_reversal_ref` spec now both
  implement the EA zone-escape: zones are STRICT (r < oversold / r >
  overbought; exact ties sit OUTSIDE the zone), escape requires prev
  strictly in the zone then now escaped (prev < os, now ≥ os for long;
  prev > ob, now ≤ ob for short), the escaped direction is carried and
  the output is gated by the current zone (neutral band holds, extreme
  zone stands aside), and NaN stays flat.
* Proof: `tests/test_indicator_semantics.py`
  `test_rsi_zone_escape_python_is_the_ea_rule_exactly` (full tie-
  inclusive truth table vs an EA transcription) and
  `test_rsi_zone_escape_neutral_hold_and_extremes_pinned`. This supersedes
  the earlier `test_contract_gap_python_cross_vs_ea_zone_at_exact_ties`.
* Runtime confirmation that the compiled EA behaves as transcribed
  remains the owner's Strategy-Tester leg — the sandbox cannot run MQL5.

## §3 Canonical numeric semantics policy (mission §16)

Four layers, distinguished everywhere below:
1. REPRESENTATION difference (double encoding/rounding),
2. MATHEMATICAL difference (the real-valued model),
3. DECISION difference (a signal/size/exit choice changes),
4. EXECUTION difference (what the broker actually does).

| Comparison | Quantity/precision source | Type allowed | Proof method |
|---|---|---|---|
| Volume floor dust guard | lots, step units; IEEE-754 double | REPRESENTATION only (≤ 1e-9 of one step) | `tests/test_volume_contract.py` (derivation + sweep) |
| Sizer cap/min comparisons | lots; 1e-12 abs on config values | REPRESENTATION only | sizer tests + transcription parity |
| Margin comparison | deposit ccy; NO epsilon (MQL5 parity) | none | `tests/test_sizer.py` grid |
| EMA seed residue | price units; decays (1−α)^b | MATHEMATICAL, bounded, WARMUP-classified | `tests/test_ema_seed_parity.py` |
| RSI all-gains clamp | 1e-12 denominator floor | REPRESENTATION (<1e-6 from 100.0; ≥ 29.99… from any threshold) | `tests/test_indicator_readiness.py` |
| Barrier touches | price; INCLUSIVE ≤/≥, no epsilon | none — exact touch fills | `tests/test_barrier_exits.py` |
| Stop fill slippage | points; adverse on stops only | EXECUTION model (costs contract) | costs tests |
| Gold trace equality | all fields | EXACT (byte-identical artifacts) | `tests/test_reality_gate.py` |

Rule enforced this session: NO new epsilon was added; one was REMOVED
from the margin comparison's neighbourhood of influence (unified to the
MQL5 value), and every surviving constant now has a derived bound and a
regression lock. "Close enough" is not a category anywhere above.

## §4 Volume normalization contract (mission §4/§5) — CLOSED

Mapping, stated canonically: **raw lots → 0.0 if non-positive; else
floor onto the step grid with the 1e-9 step-unit dust guard; a positive
value whose grid point is below `volume_min` maps to `volume_min`
(normaliser layer); caps `min(volume_max, volume_limit)` are grid-floored;
cap below min → 0.0.** The SIZER additionally rejects below-minimum RISK
BUDGETS (`BELOW_MIN`) before normalisation on the trading path — the
min-bump is unreachable there (mirrors MQL5 exactly).

Proven for: exact grid points, one step below/above, fractional floors,
1-ULP-below-grid, 1e-14/1e-13/1e-12/1e-11/1e-10 step-relative dust,
0.4/0.999 fractional perturbations, exact min, just-below-min (ULP and
full step), exact max, beyond max, cap-below-min, zero/negative/NaN/Inf,
derived volumes from budget÷loss-per-lot, repeated arithmetic
(idempotence + grid closure), JSON/repr serialization round-trip, and 8
broker configurations (FX, JPY-cross, metals, index CFD tick 0.1/0.25,
crypto step 0.001, micro-lot, volume-limited, step 0.05) — Python vs the
MQL5 transcription BITWISE over a seeded sweep. `REPRESENTATION_TOLERANCE`
and `EXECUTION_TOLERANCE` are explicitly separated in the module doc:
the guard is the former only; the latter does not exist.

## §5 Barrier exits (mission §6) — CLOSED (Python leg)

24-case matrix re-derived from the actual code and pinned
(`tests/test_barrier_exits.py`; the lost session's "20 exits" list is not
recoverable and is NOT claimed): per direction (long/short) — exact SL
touch, one point inside, one point beyond (with adverse slippage), exact
TP touch, one point inside, one point beyond (no slippage), open
gap-through SL (fill at open, worse), open gap-through TP, both-touched
intrabar → STOP FIRST, both gapped at open → STOP FIRST; plus
tick-normalized levels (identical semantics) and tick-size-relative cases
on an index-CFD spec (tick 0.25, point 0.01). Both-touch ordering is
deterministic by construction: per-book SL-before-TP in `manage()` and
if/elif order in `open_gap_exits()` (source-pinned), never a sort. The
gold micro-fixture both-touch bar resolves `stop_loss` at trace level.
Near-miss margins: barrier comparisons are inclusive with ZERO tolerance
— the only "near miss" is one point/tick inside = no fill (proven).
MQL5 runtime leg (broker-matched SL/TP) = `BLOCKED_OWNER_ENVIRONMENT`.

## §6 Indicator semantic closure (mission §7–§15)

* **Readiness matrix** — DECISIONS.md 2026-09-07 (warmup entry): per
  indicator lookback, first-valid bar, statefulness, NaN behaviour,
  platform-init evidence class, Python init, contract. Pinned by
  `tests/test_indicator_readiness.py` (Python TESTED_RUNTIME; EA legs
  SOURCE_BEHAVIOR; EMPTY_VALUE/RSI-first-valid OFFICIAL_DOCUMENTATION
  [mql5.com Other Constants; Applying One Indicator to Another]; iMA/iMACD
  seeding COMMUNITY_EVIDENCE pending the owner leg).
* **Warmup policy** — model (C) deterministic NaN propagation; a not-ready
  indicator suppresses the signal (invalid signal / zero desired
  position), identical in both runtimes. No general IsReady gate was
  added to OnNewBar (mission: don't) — the value feed itself became
  NaN-correct, which activates the guards already present.
* **INIT_FAILED audit** — 5 fatal sites, all environment/identity
  failures with logged reasons (spec build, trading disabled, indicator
  handles, guard init, magic allocation); 8 input-validation sites use
  the distinct `INIT_PARAMETERS_INCORRECT`; data insufficiency is
  explicitly NOT fatal (NaN suppression). Not a catch-all. Pinned.
* **EMA seed parity** — `FORMAL_MODEL_PARITY` + `WARMUP_EQUIVALENCE`,
  quantified: residue decays EXACTLY geometrically at (1−α) (measured =
  theory to 1e-6 rel; derived ratios (11/9)^30 ≈ 411.6× fast /
  (31/29)^30 ≈ 7.39× slow per 30 bars — these replace the unrecoverable
  session ratios with proven quantities); residue < 1e-6 by bar 19/53;
  decisions on the frozen gold fixture IDENTICAL from bar 29; near-miss
  margin 1.37× recorded WITH its honest limitation (fixture-specific;
  arbitrary-data neutrality NOT claimed). EMA seeding NOT changed.
* **RSI / crossover / crossunder** — canonical truth table over
  {NaN, below, equal, above}² pinned; events are strict-above-state
  transitions (+1 entering incl. EQUAL→ABOVE; −1 leaving incl.
  ABOVE→EQUAL); tie asymmetry and the sign-flip domain (holds tie-free,
  breaks at exact ties) pinned explicitly; `crossover(a,b)<0` ⇔
  `crossunder(a,b)>0` ⇔ `crossover(b,a)>0` proven elementwise on tie-free
  inputs; crossunder docstring sign error corrected. RSI first-valid =
  bar 14; all-gains clamp pinned as representation-only.
* **State memory** — crossover/crossunder pure & stateless (repeated
  evaluation, restart, replay bitwise identical); strategies are pure
  functions of the frame; one-bar mutation never affects strictly-earlier
  decisions. The EA's `SPrevSignalState` is zero-init and restart-clear
  (state re-derives from indicators after restart — documented).
* **Extreme transitions** — one-bar extreme→extreme yields exactly ONE
  event (bar-close sampling observes no intermediate values — BY DESIGN,
  documented); multi-threshold gap-overs, direction reversals, exact
  touches and touch-then-retreat all pinned.

## §7 Gold standards

* **Gold #1 (AEGIS-GOLD-1)** — re-run after ALL session changes:
  regenerated under the frozen `--git-commit abea0f410c5a` pin →
  **all six artifacts byte-identical** (manifest hash unchanged:
  4bb14203…89a7766b2cf0e278e). Trace/entry/exit/SL/TP/position-state
  equivalence holds by byte identity; both-touch stop-first holds in the
  trace. A naive unpinned regen differs ONLY in the auto-stamped
  `git_commit` field — investigated, root-caused, no semantic change
  (§35 rule observed; nothing was re-pinned to make anything pass).
  Status: PROVEN (LOCAL_DETERMINISTIC_GATE).
* **Gold #2** — the historical artifacts (the mission's "7 trades,
  MATCHED" description) have **NO trace anywhere in this environment**
  (verified by tree-wide search); continuity can NOT be re-established
  and is NOT simulated. The artifact is RECONSTRUCTED with new
  provenance: `GOLD_2_RECONSTRUCTED_NEW_PROVENANCE`
  (`artifacts/gold_2/`, builder `tools/build_gold2_standard.py`,
  reference `python/mql5bot/gold2_reference.py`, spec
  `examples/strategies/gold2_multifactor.json`, suite
  `tests/test_gold2_standard.py`). Sandbox-side evidence is complete:
  deterministic fixture, Python↔DSL exact parity, all 56 fills
  reconciled against recomputed sizing (signal-bar ATR + live equity
  basis + Meta floor), hash chain + replay determinism, honest
  `risk_vetoes = 0` (risk-veto coverage lives in dedicated
  micro-fixtures — see DECISIONS.md 2026-09-07). Status:
  **GOLD_2_PROVEN (LOCAL_DETERMINISTIC_GATE)**; the MT5 legs against it
  (compile / tester / reconciliation) remain BLOCKED_OWNER_ENVIRONMENT
  via the canonical TEN-step protocol.
  * **OnNewBar `desired == 0` divergence (classified, not fixed).**
    The EA's `OnNewBar` executes `if(desired == 0) return;` BEFORE its
    exposure-management path, so a flat proposal leaves an existing EA
    position untouched (stand-aside), while the Python engine with
    `allow_signal_exit=True` closes strategy books when desired goes to
    0 (flatten). This is the pre-existing flat-vs-standaside gap: it is
    DOCUMENTED here and excluded from Gold #2's parity claims (Gold #2
    compares Python reference ↔ DSL runtime, both flatten-semantics;
    the EA runtime leg belongs to the owner protocol). The mission
    forbids altering OnNewBar, so the divergence stays classified, not
    closed.

## §8 Actual EA execution order (traced from source, mission §21)

```text
OnTick → new-bar detection (iTime change; first tick of EA skipped)
  → OnNewBar:
      1  pending-order housekeeping (fills/expiry)
      2  SyncRecords / ManageOpenPositions / ProtectManagedPositions
      3  KILL SWITCH: g_risk.AllowsNewTrades()        ← first entry gate
      4  daily-loss / drawdown hit flags
      5  spread gate
      6  pending/retry-in-flight gate
      7  SYMBOL_TRADE_MODE gate (full/long-only/short-only)
      8  session filter (server time — TimeCurrent)
      9  signal evaluation (g_signal.Evaluate; NaN-suppressed warmup)
     10  direction gates (allow-short, long/short-only)
     11  exposure compare → flip = close opposite, enter next bar
     12  RISK: g_risk.GetLots (spec-injected; below-min REJECT; margin)
     13  META: g_alloc.ScaleLots — AFTER risk, BEFORE order, reduce-only
     14  meta re-normalisation: floor to step (1e-9 guard), DROP < min
     15  SL/TP geometry from signal + fill side
     16  EXECUTION: TradeManager OpenMarket/OpenPending (single OrderSend
         path; RetryQueue on transient retcodes, no Sleep)
     17  SL VERIFICATION: g_slguard.Enqueue (verify → modify → reverify
         → close → CRITICAL, timer-driven)
OnTimer: retry pump, guard pump, recovery, limits, allocation poll,
         heartbeat; OnTradeTransaction: book reconciliation
```

Compared to the canonical safety order (SPEC §3/§8): MATCHED — kill
switch precedes signal evaluation; Risk precedes Meta; Meta only reduces;
execution only through TradeManager; SL verification enqueued on every
accepted entry. Source-order pins: `tests/test_reality_gate.py::
test_kill_switch_is_the_first_entry_gate_in_the_ea`, `test_meta_seam_
only_reduces_and_drops`, `tests/test_mql5_sources.py` (single OrderSend
path, zero Sleep, retry backoff, SlGuard chain).

## §9 Safety sections (mission §22–§28) — sandbox-side evidence

* **Kill Switch (§22)** — first gate before signal evaluation (order
  pin above); sticky hot-persisted state (S2) survives restart; explicit
  reset input only; Python entry chain veto proven
  (`govern_entry … kill_switch_state="EMERGENCY_HALT"` → refused,
  veto_owner "kill-switch"). Real-fill proof = canonical owner step 8a
  (`BLOCKED_OWNER_ENVIRONMENT`).
* **Circuit breaker (§23)** — Python freeze + keep-last-safe allocation
  (breaker suite); EA consumes only the last valid allocation file;
  staleness decays to base gate — no strategy can deactivate it
  (architecture-level proof; `docs/ALLOCATION_CIRCUIT_BREAKER.md`).
* **SL invariant (§24)** — SlGuard.mqh verify→modify→reverify→close→
  CRITICAL chain source-pinned (S1); Python `slguard.py` behavioural
  twin; missing-stop sizing REJECTED both sides ("missing stop" /
  `MISSING_STOP`); no synchronous sleeping (S3 zero-Sleep scan).
  Broker-reject runtime leg = owner.
* **Uncertain execution (§25)** — RetryQueue bounded exponential backoff
  on OnTimer; idempotent one-signal-per-(strategy,symbol,bar) state;
  ticket registry adoption; orphan-pending cancel on restart (S2/S3/S6
  source tests). Lost-response dedup at runtime = owner leg.
* **Netting/hedging (§26)** — margin-mode detection source-pinned;
  Python netting/weighted-netting/hedged-legs engine tests; magic =
  FNV-1a(strategy_id) persisted registry, stable across add/remove
  (S5 pins) → attribution restart-safe and registry-order-independent.
  Broker-real leg = owner.
* **Multi-asset (§27)** — engine lines are per-(symbol, strategy) with
  aligned-index enforcement; per-symbol spec/costs; portfolio exposure
  controls evaluated post-action with recorded rejections
  (`test_meta_multi_asset`, `test_meta_metamorphic_multi_asset`,
  portfolio governance suites). One symbol cannot corrupt another's
  state (line isolation + reject-don't-crash policy, tested).
* **Boundary scan (§28)** — AST/static scans forbid order-sending calls
  outside the single EA path and outside sanctioned Python seams
  (`test_convergence_static`, `test_python_never_sends_orders`,
  factory security suites): Factory → signals/config only; Research →
  evidence only; ML → secondary-filter interfaces only; LLM → no
  execution authority; Meta → allocation only; Risk → final capital
  veto; Kill Switch → independent emergency veto. All hold at scan +
  unit level; runtime = owner.

## §10 Gate architecture (mission §29) — what CI proves and does not

* `LOCAL_DETERMINISTIC_GATE` — GitHub CI (3.10/3.11/3.12): ruff,
  alembic up/down, the full 1190-test pytest suite, CLI smoke. Proves:
  Python semantics, Python↔DSL parity, gold-ladder determinism, source
  pins of the MQL5 tree, safety scans. Does NOT compile MQL5, does NOT
  touch MT5, does NOT touch a broker.
* `MT5_RUNTIME_GATE` — owner Windows terminal: `tools/compile.ps1
  -Strict`, SymbolSpec export script, Strategy Tester gold legs,
  kill-switch and restart runtime proofs. Protocol canonicalized in
  `docs/MT5_ROUNDTRIP.md` — the canonical TEN-step owner sequence
  (single source of truth; the audit's nine-step list is the labelled
  SHORTCUT view). Currently `BLOCKED_OWNER_ENVIRONMENT`.
* `BROKER_ENVIRONMENT_GATE` — real broker symbol-spec export round-trip,
  demo ≥ 4 weeks per the SHADOW table, live-small decision. Owner-only.

## §11 MT5 actual validation (mission §30/§31)

No MetaEditor, no terminal, no broker in this Linux sandbox (verified:
no `metaeditor64`, no `wine`). Therefore:

* MQL5 compilation: **BLOCKED_OWNER_ENVIRONMENT** (the SignalEngine.mqh
  change in this session is source-review-only; the owner's compile leg
  must confirm 0 errors/0 warnings before it is considered verified).
* Strategy Tester: **BLOCKED_OWNER_ENVIRONMENT**.
* Python↔MT5 reconciliation artifact: `reconciliation.json` fields
  `python_vs_mql5` and `python_vs_mt5_tester` remain `PENDING_OWNER` —
  unchanged, not simulated. Field list for the future comparison is
  frozen in the artifact (16 fields incl. Meta digest, risk result).
* Mismatch taxonomy ready and now CANONICAL (closed 14-class set incl.
  BROKER_SPEC_MISMATCH, bound with the triage procedure in
  docs/MT5_ROUNDTRIP.md step 8). No "close enough".

## §12 Evidence classes of this session's results (mission §32)

| Result | Class |
|---|---|
| Volume contract & split fix | LOCAL_DETERMINISTIC (Python) + SOURCE_BEHAVIOR (MQL5 transcription) |
| Warmup NaN contract | SOURCE_BEHAVIOR (MQL5 edit, compile unverified) + TESTED_RUNTIME (Python model + phantom repro) |
| EMA seed quantification | TESTED_RUNTIME (models) — platform seed COMMUNITY_EVIDENCE |
| Barrier exits | LOCAL_DETERMINISTIC (engine); broker-matching BLOCKED_OWNER_ENVIRONMENT |
| Gold #1 identity | LOCAL_DETERMINISTIC (byte-exact regen under pin) |
| Kill switch / SL / retry / breaker | SOURCE_BEHAVIOR + LOCAL_DETERMINISTIC twins; runtime BLOCKED_OWNER_ENVIRONMENT |
| Everything MT5/broker | BLOCKED_OWNER_ENVIRONMENT |

No deterministic fixture ever impersonates tester evidence; no source
pin impersonates a compile; no transcription impersonates the platform.

## §13 Artifact integrity (mission §34)

* Gold artifacts: generated by `tools/build_gold_standard.py` from
  explicit piecewise segments (no RNG); carry SHA-256 digests of inputs;
  frozen to commit `abea0f410c5a` via the `--git-commit` pin; re-running
  pinned reproduces them BYTE-FOR-BYTE at this session's tip (verified);
  `test_gold_manifest_and_fixture_deterministic` enforces this on every
  future run. Not manually edited; no doc sentence claims green without
  the test/artifact behind it.
* New session artifacts: this document + DECISIONS entries + named test
  files, all commit-bound (see git log; atomic commits per mission §40).

## §14 Final certification matrix (mission §38)

| # | Section | Status | Evidence | Remaining risk |
|---|---|---|---|---|
| 1 | Volume normalization contract | PROVEN | test_volume_contract.py (60), DECISIONS entry, source pins | runtime MQL5 confirm = owner compile |
| 2 | Volume epsilon safety | PROVEN | derivation tests; promotion bound; bitwise sweep | none sandbox-side |
| 3 | Tripwire/split classification | PROVEN | legacy-split reproducer test; DECISIONS classification | historical H-01 artifacts UNRECOVERABLE (noted, not faked) |
| 4 | Numeric ratio pins | PROVEN (re-derived) | geometric-decay derivation tests (411.6×/7.39× measured = theory) | lost session's 4.78e9×/9.33e6× unverifiable |
| 5 | Barrier exits | PROVEN (Python leg) | test_barrier_exits.py (17), gold micro fixture | broker matching = owner |
| 6 | Indicator readiness/warmup | PROVEN (contract) | readiness matrix, NaN feed fix, phantom repros | iMA/iMACD seeding = COMMUNITY_EVIDENCE until owner leg |
| 7 | INIT_FAILED usage | PROVEN | audit test (5 fatal + 8 param sites) | compile confirm = owner |
| 8 | EMA seed parity | PROVEN (classified) | test_ema_seed_parity.py (decay, decisions, margins) | arbitrary-data neutrality NOT proven; WARMUP-classified |
| 9 | RSI/cross semantics | PROVEN_EXACT (EA-canonical tie rule) | zone-escape truth table; Python+DSL aligned to EA (F-4 closed) | runtime confirm = owner leg |
| 10 | State memory | PROVEN | statelessness/replay/mutation tests | — |
| 11 | Extreme transitions | PROVEN | pinned one-event-per-jump semantics | — |
| 12 | Gold #1 | PROVEN | byte-identical pinned regen after all changes | — |
| 13 | Gold #2 | GOLD_2_PROVEN (LOCAL_DETERMINISTIC_GATE) | GOLD_2_RECONSTRUCTED_NEW_PROVENANCE: 56 fills reconciled, exact Python↔DSL parity, replay-deterministic artifacts, honest risk_vetoes=0 | MT5 legs against it = BLOCKED_OWNER_ENVIRONMENT; no continuity claimed with the lost historical artifact |
| 14 | Session/time semantics | PROVEN (basis) | server-time basis both sides (TimeCurrent; dayclock rules) | broker-server↔UTC mapping = owner env |
| 15 | Meta parity | PROVEN (sandbox) | reduce-only, digest roundtrip, tamper/stale refused, DROP≤min | runtime reload = owner |
| 16 | EA execution order | PROVEN (source) | traced order + source-order pins | runtime = owner |
| 17 | Kill Switch | PROVEN (seam) | first-gate pin + entry-chain veto + sticky state | real-fill proof = canonical owner step 8a |
| 18 | Circuit breaker | PROVEN (architecture) | freeze/keep-last-safe + staleness decay | — |
| 19 | SL invariant | PROVEN (source+twin) | SlGuard chain pins + slguard.py tests | broker-reject runtime = owner |
| 20 | Uncertain execution | PROVEN (source) | RetryQueue/adoption/orphan pins | lost-response runtime = owner |
| 21 | Netting/hedging | PROVEN (sandbox) | margin-mode pins + engine netting tests | broker-real = owner |
| 22 | Attribution restart-safety | PROVEN (source) | FNV-1a persisted MagicMap pins | — |
| 23 | Multi-asset isolation | PROVEN (sandbox) | multi-asset suites + reject-don't-crash | — |
| 24 | Factory/Research/ML/LLM boundary | PROVEN (scan+unit) | AST bans + red-team suites | — |
| 25 | MQL5 compilation | BLOCKED_OWNER_ENVIRONMENT | no MetaEditor in sandbox | canonical owner steps 1–2 |
| 26 | Strategy Tester | BLOCKED_OWNER_ENVIRONMENT | no terminal | canonical owner steps 4–7 |
| 27 | Python↔MT5 reconciliation | BLOCKED_OWNER_ENVIRONMENT | PENDING_OWNER fields preserved | canonical owner step 8 |
| 28 | Demo / live readiness | NOT_IMPLEMENTED / NO | SHADOW plan ready | owner ≥ 4 weeks demo |

## §15 The 39 answers (mission §39)

1. **Exact tripwire split found:** volume floor dust-guard — Python
   1e-12 vs MQL5 1e-9; inputs in `(k−1e-9, k−1e-12)` step units below a
   grid point floor to different steps (0.01 vs 0.02 witness pinned).
   (The lost session's H-01-specific tripwire is unrecoverable; this is
   the real split found in the restored tree.)
2. **Why:** two independently chosen dust-guard constants; the parity
   grid never sampled the divergence zone.
3. **Execution impact:** none observed in gold/CI (no zone hits); the
   class is decision-changing in principle (lot step; accept/reject at
   the min boundary) — fixed anyway.
4. **Contract defining it now:** DECISIONS.md 2026-09-07 volume entry +
   `VOLUME_FLOOR_DUST_EPS` (1e-9, both runtimes) + test suite.
5. **What H-01 proves:** the mission's H-01 test is unrecoverable; its
   functional successor is `test_the_pre_fix_split_zone_is_decision_changing`,
   which proves the invalid (legacy) state changes a decision and the
   production path rejects/promotes per the unified contract — label:
   EXPECTED_NEGATIVE_TEST (the legacy constant is the invalid state).
6. **Why the numeric thresholds are defensible:** the 1e-9 guard is
   bounded below by 0.5-ulp division dust at legal quotients and above by
   the 1e-9-step promotion ceiling; decay "ratios" are the EMA forgetting
   factor raised to bar-count (measured = theory). Nothing is "large
   enough to pass".
7. **Volume-grid decisions identical Python vs MQL5:** YES, bitwise over
   the full adversarial sweep (transcription parity) — runtime confirm
   remains owner-gated.
8. **Epsilon representation-safe:** YES — every surviving constant is
   representation-only with a proven bound; no execution tolerance exists.
9. **Can epsilon alter an execution decision:** NO after unification —
   the only reachable effect is ≤ 1e-9 of one step (risk error < 1 nano-
   dollar on the reference spec); beyond the derived envelope the worst
   case is a conservative one-step undersize, parity intact.
10. **All barrier exits deterministic:** YES — 24-case matrix, inclusive
    touches, gap-throughs, per-book stop-first ordering (no sort).
11. **Exact near-miss margins:** barrier comparisons carry ZERO
    tolerance (one point/tick inside = no fill); EMA decision margin on
    the gold fixture = 1.37× seed residue (recorded with its limitation).
12. **Indicator readiness explicit:** YES — readiness matrix + NaN
    propagation contract; no undocumented warmup path remains.
13. **INIT_FAILED used correctly:** YES — 5 fatal env/identity sites
    with reasons; input errors use INIT_PARAMETERS_INCORRECT; data
    insufficiency is non-fatal (NaN suppression).
14. **NaN/EMPTY_VALUE pinned:** YES — EMPTY_VALUE == DBL_MAX
    (OFFICIAL_DOCUMENTATION) maps to NaN at the value feed; NaN never
    satisfies a comparator; pinned in tests.
15. **EMA seed formally resolved:** YES as FORMAL_MODEL_PARITY +
    WARMUP_EQUIVALENCE with quantified decay, gold-fixture decision
    identity from bar 29, and an honest 1.37× margin note. Not
    EXACT_PLATFORM_PARITY (seed differs), not a CONTRACT_GAP (window is
    bounded and classified).
16. **RSI crossover/crossunder resolved:** YES — full truth table,
    tie-asymmetry pinned, notation equivalences proven; the residual
    exact-tie difference is CLOSED as PROVEN_EXACT (Python + DSL aligned
    to the EA zone-escape rule; EA source canonical, unchanged — F-4).
17. **State-memory characterized:** YES — pure/stateless indicators,
    frame-pure strategies, zero-init restart-clear EA state.
18. **Extreme single-bar transitions characterized:** YES — exactly one
    event per jump by design; matrix pinned.
19. **Gold #1 unchanged:** YES — six artifacts byte-identical under the
    frozen pin after every session change.
20. **Gold #2 fully matched:** The HISTORICAL Gold #2 cannot be
    matched — its artifacts do not exist in this environment and no
    continuity is claimed or simulated. The RECONSTRUCTED Gold #2
    (GOLD_2_RECONSTRUCTED_NEW_PROVENANCE) is fully matched
    sandbox-side: Python reference ↔ DSL runtime exact parity, every
    fill reconciled against recomputed sizing, replay-deterministic
    artifacts. MT5-runtime match = BLOCKED_OWNER_ENVIRONMENT.
21. **Session semantics exact:** YES at basis level — server time both
    sides; broker-server↔UTC mapping is an owner-env reconciliation item
    (manifest note).
22. **Meta allocation parity exact:** YES sandbox-side (reduce-only,
    clamp, DROP≤min, digest/tamper/stale, ordering pins).
23. **Kill Switch independently verified:** YES at seam (first-gate pin
    + entry-chain veto + sticky state); real-fill = canonical owner step 8a.
24. **Circuit Breaker independently verified:** YES (freeze +
    keep-last-safe; EA consumes only last valid file).
25. **Missing-SL behaviour verified:** YES (source chain + behavioural
    twin; missing stop → sizing rejection both sides).
26. **Uncertain-order handling verified:** YES at source (bounded
    backoff, adoption, orphan cancel); runtime dedup = owner.
27. **Netting verified:** sandbox YES (engine semantics); broker-real =
    owner.
28. **Hedging verified:** sandbox YES (independent-mode legs, magic
    mapping); broker-real = owner.
29. **Attribution restart-safe:** YES (persisted FNV-1a MagicMap pins;
    registry-order-independent).
30. **Multi-asset shared-account verified:** sandbox YES (isolation +
    exposure controls); live interaction = owner.
31. **Factory/Research/ML/LLM boundaries enforced:** YES (AST/static
    scans + red-team suites; no execution authority outside TradeManager).
32. **What CI really proves:** LOCAL_DETERMINISTIC_GATE — Python
    semantics, Python↔DSL byte parity, gold determinism, MQL5 source
    pins, safety scans, across py3.10/3.11/3.12.
33. **What CI does NOT prove:** MQL5 compilation, Strategy Tester,
    Python↔MT5 reconciliation, broker behaviour, demo/live robustness.
34. **Actual MQL5 compilation verified:** NO — BLOCKED_OWNER_ENVIRONMENT
    (incl. this session's SignalEngine edit).
35. **Strategy Tester verified:** NO — BLOCKED_OWNER_ENVIRONMENT.
36. **Python↔MT5 reconciliation verified:** NO — PENDING_OWNER fields
    preserved for the owner leg.
37. **What remains blocked:** everything in rows 25–28 of §14. Gold
    #2 itself is reconstructed (row 13); what remains blocked for it is
    the MT5 compile/tester/reconciliation legs.
38. **Exact owner action next:** run the canonical TEN-step owner
    sequence (docs/MT5_ROUNDTRIP.md — single source of truth; the audit's
    nine-step list is its labelled SHORTCUT view) — including the MT5
    legs against the reconstructed Gold #2 fixture
    (`artifacts/gold_2/manifest.json` pins the dataset/config hashes to
    verify against).
39. **Highest single certification risk:** the UNCOMPILED MQL5 tree —
    every MQL5 change (incl. this session's warmup fix) is source-
    reviewed only until the owner's `-Strict` compile passes; a compile
    failure there is the only thing that could invalidate sandbox-side
    closures. Second: the EMA seed COMMUNITY_EVIDENCE seeding detail
    (settled by the same owner leg).

## §16 Final status (mission §42)

**`REALITY_GATE_BLOCKED`** — correctness is established to the limit of
this environment: every non-environment-dependent requirement above is
PROVEN with named tests/artifacts/commits, and every environment-
dependent requirement carries its exact owner action. It is NOT
`REALITY_GATE_COMPLETE` because MQL5 compile / Strategy Tester /
Python↔MT5 reconciliation evidence cannot be produced here. The former
RSI exact-tie CONTRACT_GAP is CLOSED as PROVEN_EXACT (Python + DSL
aligned to the EA zone-escape rule — F-4). Gold #2
(`GOLD_2_RECONSTRUCTED_NEW_PROVENANCE`) is CLOSED as
`GOLD_2_PROVEN` on the LOCAL_DETERMINISTIC_GATE (see the freeze record
below); its owner-side tester legs remain the same BLOCKED-OWNER items.
The only residual sandbox-side item is the EMA WARMUP window with
quantified margin (pinned and documented — COMMUNITY_EVIDENCE until the
owner leg). `PRODUCTION = NOT_READY`, `LIVE_SMALL_READY = NO` —
unchanged and unchangeable from this environment.

### Gold #2 FREEZE RECORD (closure mission §1–§3)

Gold #2 is FROZEN as an immutable integration artifact. Any future
change requires a documented semantic reason and re-provenance; it is
never regenerated to chase counts or to absorb risk vetoes (those live
in the dedicated safety micro-fixtures). Integrity re-verified on the
final gate:

| item | value |
|------|-------|
| dataset `gold2_fixture.csv` SHA-256 | `59cd339f…` |
| config hash | `69e54b83…` (includes the Meta allocation schedule) |
| manifest hash | `251deec8…` |
| recorded builder commit | `6b172da` |
| provenance label | `GOLD_2_RECONSTRUCTED_NEW_PROVENANCE` |
| trades | 56 (30 LONG / 26 SHORT); all 56 fills reconciled exactly |
| replay | Python vs DSL runtime byte-identical replay of the exact frozen inputs (fresh process) |
| regression | Gold #1 regeneration byte-identical (13/13 artifact diffs) |
| suite | 29 gold2 + safety micro-fixture tests green; full suite green |
| hash chain | all six artifact hashes match `provenance.json`; dataset hash matches `manifest.json` |


## §17 Closure supplement (FINAL PRE-MT5 CLOSURE MISSION, 2026-09-08)

This section is the single closure artifact for the final pre-MT5
mission. It does NOT redefine anything: the §14 matrix and the §15
39 answers above remain in force; this supplement adds the closure-
mission surface matrix (§33 of that mission) and the closure answers
(§34), keyed to the mission's own numbering.

### §33 matrix — Surface | Status | Evidence | Environment

Status vocabulary (exactly): `PROVEN`, `PROVEN_DECISION_EQUIVALENT`,
`BLOCKED_OWNER_ENVIRONMENT`, `INCOMPLETE`, `UNKNOWN`.

| Surface | Status | Evidence | Environment |
|---|---|---|---|
| Python backtest/portfolio engine semantics | PROVEN | full unit+golden suite; Gold #1 byte-identical regen | sandbox |
| DSL runtime ↔ Python reference parity | PROVEN | parity suites incl. Gold #2 byte-identical replay | sandbox |
| Indicator semantics (five-engine set: EMA/RSI/ATR/Donchian/Bollinger/MACD) | PROVEN | indicator semantics suite; F-1..F-4 closures; RSI tie = PROVEN_EXACT single answer | sandbox |
| EMA seed | PROVEN_DECISION_EQUIVALENT | WARMUP-classified; decay quantified; decisions identical from bar 29; margin 1.37x | sandbox (exact seeding = owner leg) |
| Gold #1 | PROVEN | frozen; regen byte-identical at every gate | sandbox |
| Gold #2 (`GOLD_2_RECONSTRUCTED_NEW_PROVENANCE`) | PROVEN (local deterministic) | FROZEN; 56 fills reconciled exactly; hash chain verified; replay deterministic; risk_vetoes=0 valid | sandbox |
| Safety micro-fixtures (daily-loss halt, exact equality, reduce-only monotonicity, weight-1 identity, weight-0 drop, below-min drop, stale/torn Meta, drawdown, KS, retry, missing SL, state recovery) | PROVEN | tests/test_safety_micro_fixtures.py (12) + dedicated suites | sandbox |
| Meta allocation parity (reduce-only, digest, tamper/stale refusal) | PROVEN | gold allocation roundtrip + digest/tamper tests | sandbox |
| Session/time semantics | PROVEN_DECISION_EQUIVALENT | server-time basis pinned both sides | sandbox (broker↔UTC mapping = owner) |
| Certification state machine (fail-closed) | PROVEN | tests/test_status_model.py, tests/test_certify.py: VERIFIED unreachable without a real terminal ladder; SOFTWARE_PASS never upgrades | sandbox |
| Provenance chain (SOURCE→SPEC→FIXTURE→CONFIG→DATASET→EXPECTED→RUN→RECONCILIATION→VERDICT) | PROVEN | gold manifest hash-chains; config-hash includes Meta schedule; mutation battery breaks identity | sandbox |
| Execution authority separation (TradeManager only) | PROVEN | OrderSend source scan (TradeManager + restart-cancel only); Python layers order-send-free (red-team tested) | sandbox |
| Scope boundary (Execution / Research / Owner-Pending surfaces) | PROVEN | docs/CERTIFICATION.md §Certification scope surfaces; EA has no DSL interpreter | sandbox |
| MQL5 compilation | BLOCKED_OWNER_ENVIRONMENT | no MetaEditor here | canonical steps 1–2 |
| SymbolSpec export + FIELD_MAP resolution | BLOCKED_OWNER_ENVIRONMENT | export script + parity tool ready | canonical step 3 |
| Strategy Tester legs (M1-OHLC / Every Tick / real ticks) | BLOCKED_OWNER_ENVIRONMENT | no terminal | canonical steps 4–7 |
| Python↔MT5 reconciliation (Gold #1 + Gold #2) | BLOCKED_OWNER_ENVIRONMENT | PENDING_OWNER fields preserved, never fabricated | canonical step 8 |
| Runtime proofs (kill-switch, retry, lost-response adoption, SL verify-modify-reverify, restart) | BLOCKED_OWNER_ENVIRONMENT | seam-level sandbox proofs only | canonical steps 8a–8c |
| Netting/hedging account legs | BLOCKED_OWNER_ENVIRONMENT | sandbox margin-mode pins only | canonical step 8d |
| Demo phase (≥ 4 weeks) / live readiness | BLOCKED_OWNER_ENVIRONMENT | SHADOW plan ready; PRODUCTION = NOT_READY | owner |

No surface is marked PROVEN that depends on the terminal; no terminal
surface is marked anything but BLOCKED_OWNER_ENVIRONMENT. Nothing is
INCOMPLETE or UNKNOWN on the sandbox side after this closure.

### §34 answers (closure mission, keyed to its sections)

1. **§1 recovery** — the environment re-clone lost the arena commit
   objects; all work survived as the working tree and was re-committed
   (snapshot) onto the branch; this turn re-based it onto the remote
   tip, recovering the remote-only VIX dataset. Nothing was rebuilt.
2. **§2 freeze** — Gold #2 is frozen; it is an integration artifact
   (56 trades, 30L/26S, 4 days, session-filtered, all exit types,
   Meta schedule exercised, risk_vetoes=0 VALID).
3. **§3 integrity** — PASS at the final gate: six-artifact hash chain
   OK; dataset hash = manifest; config hash includes the Meta
   schedule; fresh-process replay byte-identical; Gold #1 regen
   byte-identical. Any future diff = STOP + root-cause.
4. **§4 separation** — Gold #2 = integration behavior; safety
   fixtures = invariant behavior; vetoes are never forced into
   Gold #2; the Day-5 staircase stays abandoned as overfitting
   evidence.
5. **§5 safety coverage** — the dedicated list (daily-loss halt,
   exact equality, reduce-only monotonicity, weight-1 identity,
   weight-0 drop, below-min drop, stale Meta, torn allocation,
   drawdown/KS, retry, missing SL, state recovery) is confirmed in
   test_safety_micro_fixtures.py + named suites, each with
   invariant/trigger/expected/observed; no duplicates.
6. **§6 single classification** — audited: every item carries exactly
   one status; the old RSI CONTRACT_GAP wording survives only inside
   SUPERSEDED history entries of DECISIONS.md.
7. **§7 RSI exact tie** — ONE answer: PROVEN_EXACT under the
   EA-canonical strict zone-escape rule (F-4), Python + DSL aligned.
8. **§8 EMA seed** — WARMUP_CLASSIFIED / COMMUNITY_EVIDENCE; Gold #1
   proves decisions are identical from bar 29 with 1.37x margin; it
   does not prove exact MT5 seeding; the owner leg settles it. No
   wording-driven upgrade.
9. **§9 scope model** — Execution-Certified (five built-in EA engines
   + seams) / Research-Certified (71 kinds, DSL, Gold #1/#2) /
   Owner-Pending (new-kind MQL5 parity) — canonical in
   docs/CERTIFICATION.md; README/AUDIT annotated.
10. **§10 generated strategies** — cannot execute on the EA directly
    (no DSL interpreter in the MQL5 tree); unknown indicators fail
    closed at DSL schema, EA enum surface, and evidence-gated
    promotion — now ALSO enforced in the certification code itself:
    `certify.mql5_execution_status` returns NOT_EXECUTABLE for any id
    outside the five built-in engines and refuses its tester legs
    before any runner is invoked (pinned by
    `tests/test_certify_redteam.py`).
11. **§11 execution authority** — full-tree scan: OrderSend only in
    TradeManager.mqh plus one documented restart-cancel in the EA
    main; Factory/Research/ML/LLM/Meta/Risk/KS are spec/evidence/
    veto layers, order-send-free (red-team tested).
12. **§12 state machine** — fail-closed by construction: SOFTWARE_PASS
    and EMPIRICAL_VALIDATION_PENDING never imply VERIFIED; VERIFIED
    only from run_certification with every required leg ran+ok.
13. **§13 stale-artifact attacks** — protocol rule 6 rejects stale
    .ex5/reports, wrong commit/fixture/config/symbol/timeframe/model,
    missing raw/sidecar/compile log, malformed/incomplete parses,
    skipped legs, mismatched manifests; sandbox-side enforcement is
    pinned by the status-model and certify suites plus the gold
    hash-chain tests.
14. **§14 provenance mutation** — mutating config fields, data,
    strategy params, Meta schedule values, SymbolSpec fields, source
    commit, or tester model breaks the certification identity
    (hash-chain + mutation battery; Gold #2 manifest binds all).
15. **§15 canonical protocol** — docs/MT5_ROUNDTRIP.md is the single
    source of truth; every other list is a SHORTCUT mapping onto it
    (enforced by tests/test_docs_contract.py).
16. **§16 mechanical commands** — the protocol names exact tools:
    compile.ps1 -Strict, run_mt5_backtest.py run/parse/matrix,
    broker_symbol_parity.py, certify_strategy.py — all present; no
    "inspect results" hand-waving.
17. **§17 compile evidence** — fresh .ex5 with SHA-256, 0 errors /
    0 warnings counted from the log, .ex5 newer than source, commit
    hash next to the log (compile.ps1 exit codes 0/2/3/4).
18. **§18 SymbolSpec** — FIELD_MAP binds digits, point, tick size/
    value, contract size, volume min/max/step/limit, stops/freeze,
    currencies, trade_mode, filling, order_mode, expiration, margin —
    every field PENDING→RESOLVED or the leg stays BLOCKED.
19. **§19 owner Gold #1 legs** — M1/OHLC + Every Tick + real ticks on
    the frozen fixture; semantic agreement where the contract says
    exact; no forced PnL equality across models; the real-tick leg
    must record its coverage (FULL/PARTIAL/UNKNOWN) on official MT5
    fallback semantics — PARTIAL/UNKNOWN keeps certification
    constrained.
20. **§20 owner Gold #2 legs** — frozen fixture/config/manifest;
    divergences classified BEFORE any Python edit (protocol step 4/8
    updated accordingly).
21. **§21 reconciliation** — field-by-field with the CLOSED 14-class
    taxonomy now canonical in `docs/MT5_ROUNDTRIP.md` step 8
    (SIGNAL/INDICATOR/WARMUP/SESSION/SIZING/ROUNDING/META/RISK/
    EXECUTION/DATA/TIMESTAMP/STATE/BROKER_SPEC mismatch + UNKNOWN),
    plus the triage rule: one class per divergence, first divergent
    bar/state located, decision-change assessed, causal source
    attributed BEFORE any patch; no close-enough.
22. **§22 model ladder** — strict: M1 OHLC < Every Tick < real ticks
    < demo < live (certify.py tester_plan).
23. **§23 runtime proofs** — kill-switch (8a), restart (8b), retry +
    lost-response adoption + SL verify-modify-reverify + kill-switch-
    before-entry (8c) are owner runtime proofs, not locally verified.
24. **§24 netting/hedging** — explicit owner legs (8d), both journals
    recorded.
25. **§25 PENDING_OWNER** — reconciliation uses PENDING_OWNER for
    unavailable MT5 fields; tickets/fills/PnL are never fabricated or
    copied from Python output.
26. **§26 demo gate** — no auto MT5-VALIDATED→LIVE-VALIDATED; demo
    phase is separate; PRODUCTION = NOT_READY.
27. **§27 self-contained runbook** — MT5_ROUNDTRIP.md carries install
    → compile → preset → fixture → symbol → timeframe → model →
    report location → parse → hash → reconcile → pass/fail → what to
    send back.
28. **§28 no redesign** — this closure changed docs only (+rebase);
    no engine/factory/Meta replacement, no new framework, no
    wholesale rewrites.
29. **§29 local gate** — 1347 passed / 0 failed / 1 skipped; ruff
    clean on all changed paths; Gold #1 regen byte-identical; Gold #2
    hash chain OK.
30. **§30 file audit** — artifact audit performed; the rebase
    RECOVERED two remote-only files (tests/data/real/vix_daily.csv +
    manifest.json); nothing clearly disposable was deleted because
    none was found.
31. **§31 commits** — atomic, in order: status/docs consistency
    (9f82e9c), scope boundary (67ec2a0), owner protocol sync
    (d9ea3e4); certification hardening/red-team required no code
    change (audited, already fail-closed and test-pinned) and were
    recorded in this supplement instead of empty commits.
32. **§32 owner handoff** — see HANDOFF.md "Reality-Gate Closure
    (2026-09-08)": status REALITY_GATE_BLOCKED; proven locally list;
    blocked-owner list; next action = canonical ten steps; required
    return artifacts.
33. **§33 final matrix** — the five-status surface matrix above;
    terminal surfaces BLOCKED_OWNER_ENVIRONMENT, sandbox surfaces
    PROVEN / PROVEN_DECISION_EQUIVALENT, none INCOMPLETE/UNKNOWN.
34. **§34–§35 final status** — REALITY_GATE_BLOCKED (unchanged,
    unchangeable from this environment); PRODUCTION = NOT_READY;
    Gold #2 is GOLD_2_RECONSTRUCTED_NEW_PROVENANCE, never "the
    recovered historical artifact"; no profitability claim anywhere.


### §17a FINAL REALITY-GATE addendum (second pass, 2026-09-08)

This closure pass hardened the sandbox side further WITHOUT touching
the frozen gold artifacts:

* **fail-closed report gate** — `mt5tester.report_gate`: a parsed
  tester report without tables or label/value rows (empty, truncated,
  non-report, edited) can never become an ok leg; wired into
  `run_backtest`, raw artifact always preserved;
* **real-tick coverage contract** — official MetaTrader semantics
  quoted in `docs/MT5_ROUNDTRIP.md` step 7: missing tick data makes
  the tester generate ticks in Every-tick mode, so selecting the
  real-tick model never implies every tick was real; closed vocabulary
  `REAL_TICK_COVERAGE_FULL/PARTIAL/UNKNOWN` in `mql5bot.mt5tester`;
  the report's actual Model line is now captured as evidence;
* **NOT_EXECUTABLE seam** — `certify.MQL5_EXECUTABLE_STRATEGIES`
  (exactly the five built-in engine ids) + `mql5_execution_status`;
  unsupported/generated strategies are refused at the certification
  boundary before any runner call (no approximation onto a built-in);
* **red-team battery** — `tests/test_certify_redteam.py` (17 tests):
  report-level, config-level, execution-surface and no-false-VERIFIED
  attacks, all failing closed;
* **canonical protocol corrections** — real-tick coverage rule,
  Every-Tick≠real-ticks binding note, closed 14-class mismatch
  taxonomy + triage procedure, SymbolSpec divergence classification,
  mission-vocabulary state mapping, complete step-9 archive inventory,
  owner execution package (machine/inputs/outputs/failure rule), and
  the step 8a–8d runtime safety procedures table;
* **scope-boundary contract pins** — `tests/test_docs_contract.py`
  pins the truthful README wording, the three-surface scope model, and
  the five-member MQL5 enum surface against silent regression;
* **execution-authority re-scan** — AUDIT §85: one authority
  (TradeManager) + one documented restart-cancel; AUDIT §86 states the
  CI-vs-owner evidence-class split that is never merged.

Gold #1 and Gold #2 were NOT modified this pass — integrity-checked
only (hash chains, frozen-pin regression). Overall status unchanged:
`REALITY_GATE_BLOCKED`, `PRODUCTION = NOT_READY`.


### §17b FINAL LOCAL GATE evidence (mission §25, 2026-09-08)

Exact counts at this commit (no "green" hand-waving):

| gate item | result |
|---|---|
| full suite collected | 1366 |
| passed | 1365 |
| failed | 0 |
| errors | 0 |
| skipped | 1 |
| warnings | 0 (collection warning fixed) |
| lint (ruff, python/ + tests/) | All checks passed (remaining debt only in untouched tools/meta_real_basket.py + tools/meta_regime_matrix.py, pre-existing) |
| Gold #1 integrity | frozen; regeneration byte-identical (13/13 artifact diffs) with --git-commit abea0f410c5a |
| Gold #2 integrity | frozen; six-artifact SHA-256 chain OK; dataset hash = manifest; replay deterministic |
| provenance attacks | mutation battery green (config field, dataset, strategy param, Meta schedule, source commit — all break identity) |
| unsupported generated strategy | NOT_EXECUTABLE fail-closed battery green (tests/test_certify_redteam.py, 17 tests) |
| certification parser red-team | empty/truncated/non-report/malformed/config attacks all fail closed |
| source authority scan | AUDIT §85 — one authority (TradeManager) + one documented restart-cancel |
| docs consistency | scope pins + protocol pins + status pins green (tests/test_docs_contract.py, test_status_model.py) |
| artifact audit | no scratch files, no stale reports, no duplicate gold artifacts, no untracked files, no fake MT5/.ex5 files, no contradictory manifest |

Status unchanged: `REALITY_GATE_BLOCKED`, `PRODUCTION = NOT_READY`.
The remaining blocker is empirical owner-side MT5 evidence, exactly as
specified by the canonical ten-step protocol.

### §17c FINAL CERTIFICATION MODEL LOCK record (third pass, 2026-09-08)

This pass made the certification boundary unambiguous — code, docs and
pins, WITHOUT touching the frozen gold artifacts or any strategy/risk/
meta/execution logic:

* **two independent lanes** — GOLD/semantic (exact reconciliation of
  frozen fixtures; NO trade-count minimum; Gold #2 valid at 56 trades)
  vs EMPIRICAL (regime × model ladder; the untouched 100-trade
  minimum lives here only); canonical definitions in
  `docs/CERTIFICATION.md` §Two certification lanes, mirrored in
  MT5_ROUNDTRIP.md, README, HANDOFF;
* **GOLD_SEMANTIC_PASS dimension** — `status.gold_semantic_status`:
  Layer-B evidence only; never implies MT5_VALIDATED/VERIFIED; the
  mirror rule (100 empirical trades never imply gold parity) is pinned
  too;
* **reconciliation fail-closed gate** —
  `certify.run_certification(reconciliation_ok=...)`: a would-be
  VERIFIED verdict is WITHHELD with the recorded reason unless the
  step-8 reconciliation evidence is present and complete;
  `tools/certify_strategy.py --reconciliation PATH` requires the
  owner's artifact; mission §18 attack "100 trades without
  reconciliation → VERIFIED" is now structurally impossible (pinned);
* **withheld-status accuracy** — `certify_status_model` reports the
  exact withholding reason instead of a misleading "did not run";
* **evidence layers A–F** — canonical table in CERTIFICATION.md; no
  layer substitutes another;
* **§20 minimal boundary test** — a strategy built on a real 71-kind
  universe kind (T3) that has no five-engine representation: promotion
  stops (IllegalTransition without evidence), execution status
  NOT_EXECUTABLE, runner never invoked, verdict never VERIFIED;
* **demo layer checklist** — 11 required observations; demo never
  starts automatically; live needs demo + human approval;
* **documentation consistency table** — AUDIT §87; every scanned
  concept CONSISTENT, zero contradictions.

Final local gate at this pass: 1372 collected / 1371 passed / 0 failed
/ 0 errors / 1 skipped / 0 warnings; ruff clean on python/ + tests/;
Gold #1 regen byte-identical; Gold #2 six-artifact hash chain OK;
execution-authority scan unchanged (AUDIT §85). Status unchanged:
`REALITY_GATE_BLOCKED`, `PRODUCTION = NOT_READY`.

### §27 Final certification matrix (model-lock pass)

| Evidence Layer | Requirement | Status | Evidence | Remaining Risk |
|---|---|---|---|---|
| A — SOFTWARE | deterministic correctness, provenance, tooling integrity | PROVEN | 1372-test gate; provenance mutation batteries; source scans; fail-closed cert tooling | none sandbox-side |
| B — GOLD SEMANTICS | Gold #1 + #2 parity, Python↔DSL, Python↔MQL5 source parity | PROVEN | frozen artifacts; byte-identical regen; replay; hash chains (GOLD_SEMANTIC_PASS locally) | MT5-side reproduction = owner legs (steps 5–8) |
| C — MT5 RUNTIME | actual compile, .ex5, SymbolSpec, tester runs, real ticks | BLOCKED_OWNER_ENVIRONMENT | canonical steps 1–7; coverage vocabulary ready | owner terminal required |
| D — EMPIRICAL | regime × model ladder, 100-trade minimum, spread floor, degradation | BLOCKED_OWNER_ENVIRONMENT | certify ladder + gates implemented + tested; owner data required | broker data availability; real-tick coverage may be PARTIAL (recorded, never hidden) |
| E — DEMO | ≥4-week demo, 11 observations | BLOCKED_OWNER_ENVIRONMENT | checklist defined; never automatic | — |
| F — LIVE | real capital | NOT begun; PRODUCTION = NOT_READY | human-approval gates only | — |
| Gold-vs-empirical separation | lanes never substitute | PROVEN | code gates + pins (both directions) | — |
| Reconciliation gate | VERIFIED requires step-8 evidence | PROVEN | fail-closed withholding + tests | — |
| Unsupported-kind boundary | NOT_EXECUTABLE, no order path | PROVEN | §20 end-to-end test | — |

### §28 Final answers (model-lock mission)

1. Remote == local? YES — branch HEAD identical to origin at every
   verification point.
2. Gold #1 frozen? YES — integrity-only this pass, byte-identical.
3. Gold #2 frozen? YES — not modified; hash chain re-verified.
4. Gold #2 independent from the 100-trade threshold? YES — gold lane
   is a semantic correctness lane; no trade-count minimum applies;
   pinned in code docs + protocol.
5. Separate empirical lane? YES — regime × model ladder with its own
   gates, canonical in CERTIFICATION.md.
6. 100-trade threshold applied only where it belongs? YES — empirical
   required legs only; unchanged; scoping stated in every doc that
   mentions it.
7. README DSL/MQL5 statement truthful? YES — five engines only, no
   interpreter; pinned in both directions.
8. DSL interpreter in MQL5? NO — source-verified and source-pinned.
9. What strategy surface reaches MQL5? Exactly the five built-in
   engines (enum surface); everything else stops at the research
   surface.
10. Unsupported generated strategies? NOT_EXECUTABLE: schema reject,
    certification refusal before any runner, promotion evidence-gate
    stop — no order path, never VERIFIED.
11. State machine fail-closed? YES — SOFTWARE_PASS/GOLD pass/pending
    evidence never upgrade; VERIFIED needs terminal legs + recorded
    reconciliation.
12. Gold pass → MT5_VALIDATED? NO — structurally impossible
    (independent dimensions, pinned).
13. Empirical pass → VERIFIED without reconciliation? NO — verdict
    withheld fail-closed with the reason.
14. Real-tick coverage measured? YES — FULL/PARTIAL/UNKNOWN record
    mandatory on official fallback semantics; PARTIAL constrains.
15. Stale artifacts pass? NO — report gate, hash bindings, freshness
    rules, red-team battery.
16. One ten-step protocol? YES — pinned; all others SHORTCUT-labelled.
17. Gold execution separated from empirical certification? YES — two
    lanes in protocol steps 5–9, state table, checklist, README,
    HANDOFF return package.
18. Owner package complete? YES — machine/inputs/outputs/failure rule
    + 16-item return package + per-step commands/artifacts.
19. Proven locally? Layer A fully, Layer B as GOLD_SEMANTIC_PASS
    (local deterministic), certification-tool integrity.
20. Owner-blocked? Layers C–F: compile, SymbolSpec, tester legs,
    reconciliation, empirical ladder, runtime proofs, demo, live.
21. Exact first owner command?
    `powershell -ExecutionPolicy Bypass -File tools\compile.ps1 -Strict`
22. First artifact to return? The step 1–2 pair: verbatim compile log
    + fresh `.ex5` SHA-256 hashes at the pinned commit.
23. Highest remaining risk? Real-tick coverage assumption (mitigated:
    mandatory coverage record; residual = broker data availability),
    then owner-environment execution fidelity generally — all
    BLOCKED_OWNER_ENVIRONMENT by definition.

### §17d OWNER MT5 EXECUTION GATE preparation record (fourth pass, 2026-09-08)

This pass moved the project from deterministic evidence to EXECUTION
READINESS for the owner's terminal run. Nothing about strategy/risk/
Meta/execution architecture changed; both gold artifacts untouched
(integrity-only).

* **owner execution package** — `artifacts/owner_mt5_gate/`: README
  (manual), `frozen_inputs.json` (mechanically generated freeze
  record: all fixture/manifest/expected-execution hashes + the frozen
  source-commit anchor), `certification_manifest.json` (the §28
  identity chain, every owner-side value PENDING_OWNER),
  `real_tick_coverage.json` (defaults to UNKNOWN), `checklist.md`
  (§31 YES/NO), `report_template.md` (§32 format);
* **freeze invariant pinned mechanically** — the freeze anchor is an
  ancestor of HEAD and the gold artifacts are byte-unchanged since it
  (tests/test_docs_contract.py);
* **state vocabulary completed** — GOLD_SEMANTIC_PASS, empirical
  qualification, DEMO_VALIDATED mapped onto the canonical machine with
  the no-shortcut progression; SymbolSpec per-field outcome classes
  (EXACT_MATCH / SEMANTICALLY_COMPATIBLE / DECISION_CHANGING_MISMATCH
  = STOP / UNSUPPORTED_BROKER_DIFFERENCE);
* **stale-artifact attack matrix** — AUDIT §88: every attack mapped to
  its enforcement point + evidence; all fail closed;
* **§20 boundary test committed** (it had missed staging in the lock
  pass): T3-universe-kind strategy fails closed end-to-end.

Final gate at this pass: 1373 collected / 1372 passed / 0 failed /
0 errors / 1 skipped / 0 warnings; ruff clean (python/ + tests/);
Gold #1 regen byte-identical; Gold #2 hash chain OK.

**Current §31 YES/NO state (sandbox side):** every pre-flight, compile,
SymbolSpec, gold-run, reconciliation, safety-runtime, netting/hedging
and no-live-capital question is UNANSWERED — they require the owner's
terminal. The package defines exactly how each gets answered with raw
artifacts. Status: `REALITY_GATE_BLOCKED`, `PRODUCTION = NOT_READY`.
The next milestone is actual terminal evidence, executed from
`artifacts/owner_mt5_gate/README.md`.

## §17e — Evidence-intake verifier lock record (2026-09-08)

Mission: build the FINAL EVIDENCE CONSUMER so owner-returned artifacts
are verified mechanically, with no human interpretation for basic
validity, and no path from missing/stale/wrong/partial/simulated
evidence to a positive verdict.

Delivered:

* `python/mql5bot/owner_gate.py` — the verifier: 29-artifact directory
  contract; seven validity states (MISSING/PRESENT_UNVERIFIED/VALID/
  INVALID/STALE/MISMATCHED/PENDING_OWNER); compile evidence (six
  provenance fields, EX5/log hash binding, timestamp freshness with a
  clock-skew band only, zero-error/zero-warning token scan); SymbolSpec
  required fields + four per-field classes with STOP on
  DECISION_CHANGING_MISMATCH; tester-model triad (requested vs
  report-reported vs journal) per leg; real-tick coverage (FULL needs
  positive proof; UNKNOWN never promotes); reconciliation binding chain
  SOURCE→FIXTURE→CONFIG→DATASET→SYMBOLSPEC→EX5→MODEL→REPORT with any
  broken edge invalidating the leg; first-divergence engine over the
  event list with a deterministic field→taxonomy map (14 classes,
  owner-declared classes never trusted); safety/netting/hedging raw
  evidence (screenshot-only rejected; hedging may be
  BLOCKED_OWNER_ENVIRONMENT, nothing else may); freeze-anchor change
  classification (EXECUTION_RELEVANT vs NON_EXECUTION_RELEVANT).
* `tools/verify_owner_mt5_gate.py` — one command consumes the owner
  directory, prints the machine-readable JSON report (verdict, reasons,
  per-artifact states, gold reconciliation, first divergence, safety)
  and exits nonzero on every negative verdict.
* `tests/test_owner_gate.py` — 29 consumer tests: complete-package
  happy path; stale EX5 / stale log / wrong source commit / model
  identity mismatch / broken binding / SymbolSpec attacks; partial
  packages (compile-only, per-slot missing) never verify with exact
  reasons; UNKNOWN/PARTIAL coverage constrains the verdict; FULL
  without evidence rejected; first divergence found at the earliest
  event with deterministic class; classification table closed at 14;
  screenshot-only safety invalid; hedging-block exception applies to
  hedging alone; no-evidence package can never be positive.
* `docs/AEGIS_EMPIRICAL_LANE_PACKAGE.md` — §28 empirical lane package
  DEFINED, not executed: symbols/dates/timeframe/regime partition/model
  ladder/100-trade-per-regime minimum/costs/degradation/statistical
  gates + fail-closed execution preconditions.
* Owner README gained the evidence directory contract + the consume
  command.

Gate results at this pass: full suite 1402 collected / 1401 passed /
0 failed / 0 errors / 1 skipped / 0 warnings; ruff clean on
`python/mql5bot/owner_gate.py`, `tests/test_owner_gate.py`,
`tools/verify_owner_mt5_gate.py`; Gold #1 regen byte-identical
(all 7 artifacts); Gold #2 hash chain OK; docs-contract pins green.

Verifier verdict ceiling is MT5_VALIDATED; empirical/demo/VERIFIED
remain unreachable by this gate by design. No owner evidence exists
yet: the runtime stays `BLOCKED_OWNER_ENVIRONMENT`, the certification
status stays `REALITY_GATE_BLOCKED`, and `PRODUCTION = NOT_READY`.
The verifier itself is PROVEN_READY while the MT5 runtime is
BLOCKED_OWNER_ENVIRONMENT — those two statements coexist without
contradiction (§35).

## §17g — FINAL RUNTIME EXECUTION GATE: environment capability discovery (2026-09-08)

Mission directive: do NOT assume MT5 is unavailable — discover the
actual agent runtime FIRST, then decide `MT5_EXECUTION_AVAILABLE` vs
`MT5_EXECUTION_UNAVAILABLE`.

### Discovery findings (probed, not assumed)

| Capability | Probe | Result |
|---|---|---|
| OS | `uname -a`, `/etc/os-release` | Linux (Debian 12 bookworm), x86_64, host `e2b.local` — sandbox container |
| Windows / VM / RDP | filesystem scan + client check | NO Windows, NO VM, NO configured remote (`ssh` binary exists, zero hosts/credentials) |
| PowerShell | `command -v powershell pwsh` | NOT INSTALLED |
| MetaEditor | `find / -iname "*metaeditor*"` | NOT FOUND anywhere on the filesystem |
| MetaTrader 5 terminal | `find / -iname "*terminal64*" -o -iname "*metatrader*" -o -iname "*.ex5"` | NOT FOUND (zero `.ex5` files system-wide) |
| Wine / compat layer | `command -v wine wine64` | NOT INSTALLED |
| GUI / display | `$DISPLAY`, `$WAYLAND_DISPLAY`, `xdotool` | no display server, no GUI automation |
| Python `MetaTrader5` package | `import MetaTrader5` | ModuleNotFoundError (package is Windows-only; even installed it cannot reach a terminal here) |
| Repository access | git state | `/home/user/mql5bot`, branch `arena/01a07c73-mql5bot`, HEAD == origin == `ca6cd47`, tree clean |

### Capability decision

**`MT5_EXECUTION_UNAVAILABLE`** — and therefore
`OWNER_ENVIRONMENT_UNAVAILABLE` for this agent. Per §31: STOP runtime
execution work; no fake evidence; no simulated compile/tester output;
no new code added to appear productive.

### Source freeze re-verification (handoff prerequisite)

* Frozen anchor: `781bea4a3751c349442231bb11262c2842787e67` (ancestor
  of HEAD — verified).
* Drift check (§4): `git diff anchor..HEAD` over `mql5/`,
  `artifacts/gold/`, `artifacts/gold_2/`, `examples/strategies/` is
  EMPTY — the executable MQL5 surface and both golds are byte-
  identical to the frozen anchor. The only `python/` change is
  `owner_gate.py` (the evidence verifier, which consumes evidence and
  cannot alter execution semantics). All post-anchor commits are
  therefore NON_EXECUTION_RELEVANT to the MQL5 build; the frozen
  anchor remains the valid compile identity.
* `frozen_inputs.json`, manifests, configs and fixture hashes intact
  (docs-contract freeze pin green at last full gate: 1518 collected /
  1517 passed / 0 failed / 0 errors / 1 skipped / 0 warnings).

### Status (unchanged, as required)

`REALITY_GATE_BLOCKED` · `OWNER_EXECUTION_READY` (tooling prepared) ·
`PRODUCTION = NOT_READY`. MT5 runtime evidence remains
`BLOCKED_OWNER_ENVIRONMENT`.

### Exact handoff to the owner (single source of truth: artifacts/owner_mt5_gate/README.md)

1. On the Windows MT5 machine, in the repository folder at the pinned
   commit: `powershell -ExecutionPolicy Bypass -File tools\compile.ps1 -Strict`
   → produces `compile/compile.log`, `compile/compile_metadata.json`,
   fresh `compile/Mql5Bot.ex5`; expected: 0 errors, 0 warnings.
2. Continue steps 2–10 exactly as the README ten-step table defines
   (SymbolSpec export → gold M1/Every-Tick/Real-Ticks legs → safety →
   reconciliation → `tools/owner_evidence_bind.py manifest` →
   `python tools/verify_owner_mt5_gate.py <evidence-dir> --repo .`).
3. Return the directory AS-IS whatever the verdict; a difference is
   evidence, never a reason to edit fixtures.
