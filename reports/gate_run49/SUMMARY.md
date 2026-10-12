# gate_run49

- HEAD SHA tested: `add80bf8905a1a1b01620dc4ec867632c15f6ffd` (master, Merge PR #46: DEMO-IN-GATE-1 + DEMO-LOGIN-PERSIST-1)
- Trigger tags: `[runner: demo-in-gate]` and `[runner: gold1]`. This report is the
  `demo-in-gate` run (market open: Monday 2026-10-12 10:18 UTC). The gold1 run
  is published separately.
- Command (switch name from docs/SAFETY_DEMO_PLAN.md at this HEAD, "Inside the gate"):
  `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold2 -DemoSafety`
- Evidence dir: `evidence\owner_gate\20261012-101846`
- MT5 (terminal64, metaeditor64, metatester64) was not running and git status
  was clean before the gate started.
- Earlier attempt at the same HEAD, same command, evidence dir
  `evidence\owner_gate\20261012-100135` (started 10:01 UTC): its console stops
  after the stage 4 PASS line and the gold2_m1_ohlc ini line; it has no gate
  summary. It was interrupted, is not a result, and is not published as a run.
  Its importer journal line (03:02:24 local) reads: `EURUSD.G2: 5760 bars,
  dataset hash MATCHES manifest ... symbol_state=adopted_verified`.

## Stage lines (verbatim)

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             PASS
  stage 3  broker_parity          PASS
  stage 4  fixture_import         FAIL
  first_blocking_stage: fixture_import
```

## Result

```
GATE_RESULT=partial_fixture_import
```

Gate exit code: 1

Verdict fields (gate_summary.json): `certifiable=false`, `partial=true`,
`unscoped_result=fixture_import`, `first_blocking=fixture_import`.

Stage 5 (tester legs), stage 7 (demo_safety) and stage 8 did not run: the demo
harness was NOT launched in this run. There is no reconciliation_verify.json for
this run, so there is no "safety" block and no reconciliation counts.

## Stage 4 reason (verbatim, stage_4.json)

```
[scope: gold2; PARTIAL run -- certifies nothing] [json_refused] EURUSD.G2: importer REFUSED at stage 'symbol_state' (last_error=0): adopt-in-place: CustomRatesDelete left 5760 bar(s) on EURUSD.G2; a prior fixture's bars must never survive into this dataset
```

import_EURUSD.G2.json: `"refused":true`, `"stage":"symbol_state"`,
`"symbol_state":"adopted_verified"`, `"last_error":0`.

## Journal lines for the failing stage

`stage4_import_journal_lines.txt`: terminal journal (`logs/20261012.log`) for
the import launch and the Experts log (`MQL5/Logs/20261012.log`) lines of the
importer, local time (UTC-7). Redacted: accounts-file logins/passwords ->
`<REDACTED>`; other 6+ digit account numbers -> `<ACCOUNT>`.

Symbol-spec exports and tester files of this run are NOT included.

Leak check of every file in this report against the demo logins/passwords: 0 hits.
