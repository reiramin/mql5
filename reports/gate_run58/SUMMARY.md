# gate_run58 (FULL gate)

- HEAD SHA tested: `ab312d55eefd7458ddc2bc92b6fcd770acf2f955` (master, HARNESS-SUSPEND-1 + SPEC-WAIT-2 (#53))
- Trigger tag: `[runner: full]`
- Command (no `-Golds`: gold1 + gold2, stages 9-10 allowed):
  `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -DemoSafety`
  (launched through a runner wrapper that only blocks Windows idle sleep for the
  process lifetime and tees the console; it passes the arguments unchanged.)
- Started Tuesday 2026-10-13 09:03:01 UTC, inside the market window (next
  closure Tuesday 20:45 UTC). Gate ended 09:04:15 UTC (gate_summary.json
  `utc` 2026-10-13T09:04:15.9040245Z). Evidence dir:
  `evidence\owner_gate\20261013-090302`
- MT5 (terminal64, metaeditor64, metatester64) was not running and
  `git status --porcelain` was empty before the gate started. The gate was not
  interrupted; the run lasted 74 s, no sleep / no wall-clock gap.

## Previous run note

gate_run57 (47c4705) is INVALID per the runner rules: its restart test spans a
host suspend (run.json steps 2026-10-12 22:43:03 -> 2026-10-13 07:44:31 UTC).
47c4705 was not re-run; this run tests the new commit ab312d5.

## Leftover demo positions (checked before the run, no trading done)

- From the last demo EA logs (gate_run57, evidence `20261012-223713`): netting
  `SNAPSHOT after_cleanup ... positions=[]`; hedging `CLEANUP closed 3`, then
  `SNAPSHOT after_cleanup ... positions=[]`; restart opened none.
- Live, during this run: the terminal journal (hedging account, the account the
  terminal is restored to) reports `terminal synchronized ...: 0 positions, 0 orders`
  at 02:03:55, 02:04:04 and 02:04:12 local (UTC-7).
- The netting account was not queried live in this run (stage 7 never ran);
  its last known state is the gate_run57 `positions=[]` snapshot above.

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
GATE_RESULT=fixture_import
GATE_EXIT_CODE=1
```

`gate_exit_code.txt` = `1`.

Verdict fields (gate_summary.json): `certifiable=true`, `partial=false`,
`scope=['gold1','gold2']`, `unscoped_result=fixture_import`,
`first_blocking=fixture_import`, `exit_code=1`. (`certifiable=true` is the
run's scope flag, i.e. an unscoped run; it is NOT a certificate.)

## Stage 4 reason (verbatim, stage_4.json)

```
[json_refused] EURUSD.G2: importer REFUSED at stage 'symbol_state' (last_error=0): adopt-in-place: CustomRatesDelete left 5760 bar(s) on EURUSD.G2; a prior fixture's bars must never survive into this dataset
```

## Gold pairing / import counts and symbol_state

- EURUSD.G1 (gold1): `stage=complete`, `refused=false`, `n_bars=720`,
  `symbol_state=adopted_verified`, `adopt_properties_rewritten=0`, dataset hash
  `074530cd5b7424dc2138698e2ec72c176bf033c589474d3fde004d87e83728d3` matches manifest.
- EURUSD.G2 (gold2): `stage=symbol_state`, `refused=true`,
  `symbol_state=adopted_verified`, `adopt_properties_rewritten=0`, `last_error=0`,
  no `n_bars` / dataset hash (refused before the import).
- Observation (no conclusion drawn): 5760 is the same `n_bars` the EURUSD.G2
  import reported in gate_run56 and gate_run57 (`manifest_dataset_hash`
  `59cd339f...dd79` in both). `git diff 47c4705 ab312d5` does not touch the
  importer script (changed: Mql5Bot.mq5, SymbolSpec.mqh, demo_harness.py,
  mt5tester.py, owner_gate.ps1, tests, docs).
- Gold pairing counts (stage 5/8): none -- stage 5 did not run.

## Stages 5-10, safety block

Stages 5, 6, 7, 8, 9 and 10 did NOT run (no stage line, no stage_N.json).
- No tester legs, no demo harness run (no `demo_safety/*/run.json`), so
  HARNESS-SUSPEND-1 and SPEC-WAIT-2 were not exercised live by this run.
- Stage 8 did not run: no reconciliation_verify.json, so there is NO verifier
  verdict and NO safety block (the 8 safety tests have no VALID/MISSING/observed
  values for this run).
- **Stage 9 produced no archive manifest; stage 10 produced no certificate.**

## Journal lines for the failing stage

`stage4_journal_lines.txt` (local time UTC-7), redacted: accounts-file
logins/passwords -> `<REDACTED>` (18 occurrences); client IP -> `<IP>`.
- terminal journal `logs/20261013.log` lines 183-239: the G1 import launch
  (exit code 11), the G1 symbol-spec export (exit code 2) and the G2 import
  launch, which `closes terminal with code 8`.
- Experts log `MQL5/Logs/20261013.log` lines 33-43, including (verbatim):
  `[import] EURUSD.G2 REFUSED [symbol_state]: adopt-in-place: CustomRatesDelete left 5760 bar(s) on EURUSD.G2; a prior fixture's bars must never survive into this dataset (last_error=0)`

## Leak check

Every file in `reports/gate_run58/` was scanned for the demo logins and
passwords (raw and UTF-16) before commit: 16 files scanned, **0 hits**
(re-run after this file's final edit: 16 files, 0 hits).

## Files

console.txt, gate_summary.json, gate_exit_code.txt, stage_0..4.json,
import_EURUSD.G1/G2 .ini/.json, parity_report.json, dsl_compare_report.txt,
stage4_journal_lines.txt.
