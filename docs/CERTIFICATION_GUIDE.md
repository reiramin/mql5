# Certification Guide — the validation ladder

This is the how-to. The contract — what a certificate is and what it does
and does not claim — is [CERTIFICATION.md](CERTIFICATION.md); the gate, its
stages, runner tags and commands are [OWNER_GATE.md](OWNER_GATE.md); the
empirical package is `AEGIS_EMPIRICAL_LANE_PACKAGE.md`.

## The core rule

**One evidence class may never impersonate another.** Software pass ⇏
MT5 validation; gold pass ⇏ empirical qualification; empirical pass
without reconciliation ⇏ VERIFIED; parser success ⇏ anything runtime.

## Getting a certificate, step by step

1. **Merge with a runner tag.** `[runner: full]` makes the Windows MT5
   runner run `owner_gate.ps1 -DemoSafety` (gold1 + gold2 + demo, stages
   0–10). Scoped tags (`[runner: gold1]`, `[runner: gold2]`,
   `[runner: demo-in-gate]`) run part of it and certify nothing.
2. **The gate runs itself** and stops at the first failure: self-protection,
   strict compile, DSL parity, broker parity, fixture import, tester legs,
   demo safety, reconciliation (with the five tester safety legs), archive
   manifest, certificate. There is no stage 6.
3. **Read the result** in the run's report on branch `gate-reports`
   (`reports/gate_run<N>/SUMMARY.md`): `GATE_RESULT=`, `GATE_EXIT_CODE=`,
   each `stage_<n>.json`, `reconciliation_verify.json` (the verdict, the
   gold pairing counts, the safety block) and, when issued,
   `certificate/certificate.md`.
4. **On a failure,** the first failing stage names the reason. Root-cause it
   from the raw lines in the report, fix it in a PR (never by loosening a
   rule or editing evidence), and merge with the tag that re-runs it.

**Where it stands (gate_run59, 2026-10-13).**
`GATE_RESULT=certified_with_log_graded_legs`; stages 0–10 PASS (stage 5
PASS_FROM_LOG); verdict `MT5_VALIDATED_BAR_MODELS`; gold1 18/18 and gold2
37/37 MATCH in `m1_ohlc` and `every_tick`; 8/8 safety VALID; certificate
issued. MT5 execution-parity and safety certificate, bar models, no
real-tick claim, no profitability claim. The first full run (2026-09-20,
stopped at stage 5) is kept as history in
[OWNER_DELIVERY.md](OWNER_DELIVERY.md).

**PASS_FROM_LOG — its own evidence class.** MT5 build 6184 writes no
`[Tester]` Report file, so stage 5 grades a no-report leg from its OWN
tester-log window (`python/mql5bot/tester_log_grader.py`). A leg is
`PASS_FROM_LOG` only when that window shows ALL of: "successfully
finished", bars > 0 for the leg's symbol, a history-quality line, and a
model statement equal to the requested model. Anything less keeps the
leg's verdict (FAIL, FAIL_INSUFFICIENT_FIXTURE_HISTORY,
FAIL_NO_TICK_HISTORY or BLOCKED_OWNER_ENVIRONMENT). Every gold leg of
gate_run59 was graded this way.

- It **proves**: MT5 ran this leg to completion, on this symbol, with
  bars > 0, at the stated history quality, in the requested model. The
  verdict quotes the exact lines and names the source ("tester agent log").
- It does **not** prove: anything a report states. There are no report
  metrics (profit factor, drawdown, trade statistics). The deal list is
  only what the EA printed (`DEAL #…` lines).
- It is **never** the report-based PASS. A stage with any log-graded leg
  records `PASS_FROM_LOG`, and a gate that reaches the end on it reports
  `GATE_RESULT=certified_with_log_graded_legs`, not `certified` (exit 1).

**Real ticks are not applicable.** A bar-only gold's real_ticks leg is not
launched; it is recorded `NOT_APPLICABLE_BAR_ONLY_FIXTURE`, real-tick
coverage `NONE (bar-only fixture)`, and is never a pass (owner decision
2026-10-03).

**Legs run the gold strategy.** Each leg derives its strategy and risk
inputs from the gold manifest and loads the gold's DSL bundle into the EA's
DSL bundle runtime; it fails before launch if any input cannot be derived,
and passes from log only if the EA logged that it loaded the expected
strategy (STAGE 5 R9).

**Partial (scoped) runs certify nothing.** `-Golds gold2` runs only gold2's
import, legs and stage-8 comparison. It ends `GATE_RESULT=partial_<stage>`;
stage 8 can at best report `MT5_VALIDATED_PARTIAL_SCOPE` (not positive);
stages 9 and 10 are refused; `gate_summary.json` says
`"certifiable": false`.

## Lane 1 — GOLD semantic lane

Question: *do the Python, DSL and MQL5 implementations agree on the
controlled fixture?*

- **Gold #1** — 18-trade fixture, frozen at `artifacts/gold/`
  (manifest, fixture, traces, expected execution, reconciliation;
  regenerated once under S8-REANCHOR-2).
- **Gold #2** — 56-trade fixture (37 entries fall inside the tested
  window and are paired),
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
  returned directory and assigns the verdict mechanically. State:
  `MT5_VALIDATED_BAR_MODELS` (gate_run59): no real-tick leg.

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
substitutes for another. Current states: A/B PROVEN locally; C
certified for the bar models (gate_run59); D not run; E limited to the
three stage-7 demo safety probes; F not begun.

## Statuses you will see

`GOLD_SEMANTIC_PASS` · `MT5_VALIDATED` · `MT5_VALIDATED_BAR_MODELS`
(bar models only, no real-tick claim; the certified verdict) ·
`certified` / `certified_with_log_graded_legs` (gate results) ·
`EMPIRICAL_VALIDATED` ·
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
