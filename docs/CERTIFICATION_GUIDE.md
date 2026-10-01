# Certification Guide — the validation ladder

This is the human-facing view. Binding definitions: `CERTIFICATION.md`
(scope surfaces, two lanes, evidence layers A–F), `MT5_ROUNDTRIP.md`
(TEN-step owner protocol), `AEGIS_REALITY_GATE_AUDIT.md` (attack
matrices), `AEGIS_EMPIRICAL_LANE_PACKAGE.md` (empirical package).

## The core rule

**One evidence class may never impersonate another.** Software pass ⇏
MT5 validation; gold pass ⇏ empirical qualification; empirical pass
without reconciliation ⇏ VERIFIED; parser success ⇏ anything runtime.

## The 11-stage owner gate — where it actually stands

The owner runs the whole ladder with one command
(`tools/owner_gate.ps1`); it self-protects, walks stages 0–10, and STOPS
at the first failure. The first full run (2026-09-20, MT5 build 6184) is
the account of record in [OWNER_DELIVERY.md](OWNER_DELIVERY.md); this
guide must not overstate it:

| Stage | Result on the 2026-09-20 run |
|---|---|
| 0 self-protection · 1 strict compile (0/0) · 2 DSL parity (14/14) · 3 broker parity (12 MATCH) · 4 fixture import | **PASS** (MT5-VALIDATED for that run; evidence is owner-side, gitignored) |
| 5 Strategy Tester legs | **FAIL** (`GATE_RESULT=tester_legs`) — 3 legs FAIL, 2 legs BLOCKED_OWNER_ENVIRONMENT (build 6184 wrote no `[Tester]` Report file; a BLOCKED leg is **not** a pass) |
| 6–10 reconciliation (incl. 8a–8d), archive, certify | **NEVER RUN** — the gate stopped at stage 5 |

**PASS_FROM_LOG — its own evidence class (built, unit-tested, never run
live).** Because build 6184 writes no Report file, stage 5 can now grade a
no-report leg from its OWN tester-log window
(`python/mql5bot/tester_log_grader.py`). A leg is `PASS_FROM_LOG` only when
that window shows ALL of: "successfully finished", bars > 0 for the leg's
symbol, a history-quality line, and a model statement equal to the
requested model. Anything less keeps the leg's existing verdict (FAIL,
FAIL_INSUFFICIENT_FIXTURE_HISTORY, FAIL_NO_TICK_HISTORY or
BLOCKED_OWNER_ENVIRONMENT). A window showing the EA refused the DSL bundle at
OnInit is a FAIL that says so; a window showing `no history data, stop
testing` is FAIL_NO_TICK_HISTORY (gate_run23; see docs/DECISIONS.md).

- It **proves**: MT5 ran this leg to completion, on this symbol, with
  bars > 0, at the stated history quality, in the requested model. The
  verdict quotes the exact lines and names the source ("tester agent log").
- It does **not** prove: anything a report states. There are no report
  metrics (profit factor, drawdown, trade statistics). The deal list is
  only what the EA printed (`DEAL #…` lines). Side and open/close come
  only from MT5's own deal lines and are otherwise left empty.
- It is **never** the report-based PASS. A stage with any log-graded leg
  records `PASS_FROM_LOG`, not `PASS`. Its summary counts legs passed from
  report versus from log. A gate that reaches the end on it reports
  `GATE_RESULT=certified_with_log_graded_legs`, not `certified`.
- It does **not** change the record above. On the lines captured from
  gate runs 16/17 the gold2 M1-OHLC window does grade PASS_FROM_LOG, but
  the gold1 legs still FAIL, so stage 5 is still FAIL.
- Stage 8 accepts a PASS_FROM_LOG log trade list as a leg's trade source
  when no report exists, and names the source as the tester agent log. A
  list with zero deals is compared, not rejected. Against gold2's frozen
  56-trade contract, zero deals is a **divergence**.

**Legs run the gold strategy (built, unit-tested, never run live).** The
measured gate_run17 root cause was that the EA ran its compiled-in default
strategy (`InpDslBundleFile` empty). Each leg now derives its strategy and
risk inputs from the gold manifest, loads the gold's DSL bundle, and fails
before launch if any input cannot be derived. Gold1's manifest pins no
`engine_config.allow_short`, so its legs now fail before launch on that
field. A leg only passes from log if the EA logged that it loaded the
expected strategy. See DECISIONS.md (STAGE 5 R9).

**Partial (scoped) runs certify nothing.** `owner_gate.ps1 -Golds gold2`
runs only gold2's import, legs and stage-8 comparison. This exists so a
first real Python↔MQL5 comparison can happen while gold1 awaits
regeneration. Such a run is evidence about gold2 only:
- It ends `GATE_RESULT=partial_<stage>` and never `certified`.
- Stage 8 can at best report `MT5_VALIDATED_PARTIAL_SCOPE`, which is not a
  positive verdict.
- Stages 9 and 10 are refused (recorded `REFUSED`, not run), and
  `gate_summary.json` says `"certifiable": false`.

A partial result says nothing about the excluded golds and is never
MT5-VALIDATED, VERIFIED or certified. (Built, unit-tested, never run live.)

**Nothing is VERIFIED.** Stage 8 (the binding Python↔MQL5 executed-trade
reconciliation) has never run, and only a run that ends
`GATE_RESULT=certified` can put VERIFIED on anything.

## Lane 1 — GOLD semantic lane

Question: *do the Python, DSL and MQL5 implementations agree on the
controlled fixture?*

- **Gold #1** — 16-trade fixture, frozen at `artifacts/gold/`
  (manifest, fixture, traces, expected execution, reconciliation).
- **Gold #2** — 56-trade fixture,
  `GOLD_2_RECONSTRUCTED_NEW_PROVENANCE`, frozen at `artifacts/gold_2/`.
- Deterministic, replayable, hash-chained. The golds are NEVER
  regenerated to match reality — a mismatch is evidence, investigated
  from the FIRST divergent event with the closed 14-class taxonomy
  (`SIGNAL/INDICATOR/WARMUP/SESSION/SIZING/ROUNDING/META/RISK/
  EXECUTION/DATA/TIMESTAMP/STATE/BROKER_SPEC/UNKNOWN` — no
  CLOSE_ENOUGH, no custom classes).
- **Gold semantic validation is NOT trading validation.** No
  trade-count minimum applies (56 trades is valid), and
  GOLD_SEMANTIC_PASS never implies MT5-VALIDATED or VERIFIED.

## Lane 2 — MT5 runtime lane

Question: *does the actual compiled EA behave as the deterministic
contract predicts?*

- Requires the owner's Windows/MetaEditor/terminal: strict compile,
  broker SymbolSpec export, gold legs on three tester models, model
  identity triad, real-tick coverage record, field-by-field
  reconciliation, safety exercises.
- The verifier (`tools/verify_owner_mt5_gate.py`) consumes the
  returned directory and assigns the verdict mechanically. Until owner
  artifacts exist this lane is **BLOCKED_OWNER_ENVIRONMENT**.

## Lane 3 — EMPIRICAL lane

Question: *does the strategy hold up across real regimes at sufficient
sample?*

- Separate dataset/symbols/windows, regime partition, full tester-model
  ladder, cost assumptions, degradation reporting, statistical gates —
  defined exactly in `AEGIS_EMPIRICAL_LANE_PACKAGE.md` (prepared, not
  executed).
- The **≥100-trade minimum lives ONLY here**. Applying it to golds (or
  letting golds satisfy it) is a contract violation.
- Empirical without reconciliation can never become VERIFIED.

## Lane 4 — DEMO lane

Adds live-like operation on a demo account: order routing, fills,
restart behavior, monitoring — after MT5 validation + clean
reconciliation + safety evidence + broker SymbolSpec confirmation +
human approval. Demo never auto-starts.

## Lane 5 — LIVE lane

Real money. A separate state with its own evidence; never implied by
any earlier lane; never started by tooling.

## Evidence layers A–F

A software → B gold semantics → C MT5 runtime → D empirical → E demo →
F live. Each layer has its own artifacts and its own gate; none
substitutes for another. Current states: A/B PROVEN locally; C/D/E
BLOCKED_OWNER_ENVIRONMENT / PENDING; F not begun.

## Statuses you will see

`GOLD_SEMANTIC_PASS` · `MT5_VALIDATED` · `EMPIRICAL_VALIDATED` ·
`DEMO_VALIDATED` · `VERIFIED` · `NOT_VERIFIED_*` (with exact reasons) ·
`BLOCKED_OWNER_ENVIRONMENT` · `MT5_VALIDATED_PARTIAL_SCOPE` (scoped stage-8
verification; not positive, certifies nothing) · `PASS_FROM_LOG` (stage-5 leg graded from
its own tester-log window, no report; never the report-based PASS) ·
`REALITY_GATE_BLOCKED` ·
`REALITY_GATE_INCOMPLETE` · `OWNER_EXECUTION_READY` ·
`PRODUCTION = NOT_READY`. These are distinct states, not synonyms.

## If MT5 disagrees with a gold

1. STOP. 2. Find the FIRST divergent event (index/bar/time/field,
both values, full state snapshot). 3. Classify with the closed
taxonomy. 4. Determine the authoritative contract (SPEC / MQL5
behavior / broker spec / deterministic test). 5. Change EXACTLY ONE
side. 6. Re-run affected regressions AND both golds. Never dual-patch;
never move the expected result to match reality.
