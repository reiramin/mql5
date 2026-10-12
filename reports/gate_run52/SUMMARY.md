# gate_run52

- HEAD SHA tested: `c8bc02205d5f1b73f5f13c61bf70b0796a21adf0` (master, WARMUP-FROMDATE-1: gold1 legs start where the EA has its InpDslBars of history (#47))
- Trigger: owner one-off instruction (not a commit tag): "run it now: -Golds gold2
  -DemoSafety on c8bc022, published as gate_run52". The commit's own tag is
  `[runner: gold1]` (run as gate_run51).
- Owner-stated preconditions: EURUSD.G2 deleted by the owner, terminal on the
  hedging account, market open.
- Command (switch name from docs/SAFETY_DEMO_PLAN.md at this HEAD):
  `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold2 -DemoSafety`
- Started 2026-10-12 11:31 UTC (Monday, market open). Evidence dir:
  `evidence\owner_gate\20261012-113115`
- MT5 (terminal64, metaeditor64, metatester64) was not running and git status
  was clean before the gate started. The gate was not interrupted. It
  finished in about 8 minutes; the console ends with the summary and
  GATE_RESULT.
- Gate exit code: NOT captured (the runner's exit-code marker file was not
  written by the wrapper process). The result of record is GATE_RESULT and
  gate_summary.json.

## Stage lines (verbatim)

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             PASS
  stage 3  broker_parity          PASS
  stage 4  fixture_import         PASS
  stage 5  tester_legs            PASS_FROM_LOG
  stage 7  demo_safety            FAIL
  first_blocking_stage: demo_safety
```

## Result

```
GATE_RESULT=partial_demo_safety
```

Verdict fields (gate_summary.json): `certifiable=false`, `partial=true`,
`unscoped_result=demo_safety`, `first_blocking=demo_safety`.

Stage 8 did NOT run. There is no reconciliation_verify.json for this run, so:
- the "safety" block does not exist for this run (nothing to quote);
- there are NO gold2 reconciliation counts (paired / missing / extra) for this run.

## symbol_state (import_EURUSD.G2.json, verbatim)

```
"symbol_state":"created_fresh"
```

Same file: `"refused":false`, `"n_bars":5760`.

## Stage 5 (summary of stage_5.json)

gold2_m1_ohlc and gold2_every_tick: PASS_FROM_LOG (source: tester agent log, no
report). gold2_real_ticks: NOT_APPLICABLE_BAR_ONLY_FIXTURE (not launched, not a
pass). Real-tick coverage NONE. Full text in stage_5.json.

## Stage 7 reason (verbatim, stage_7.json)

```
[scope: gold2; PARTIAL run -- certifies nothing] [demo_terminal_not_restored] the terminal is NOT left logged in to the hedging account and connected without credentials -- every later gate launch would fail stage 3: [demo_restore_not_connected] restart: restore failed: connection check: the credential-less launch wrote no export (MQL5/Files/Mql5Bot/demo_connect_check/EURUSD.json); [demo_restore_not_connected] netting: restore failed: connection check: the credential-less launch wrote no export (MQL5/Files/Mql5Bot/demo_connect_check/EURUSD.json); [demo_restore_not_connected] hedging: restore failed: connection check: the credential-less launch wrote no export (MQL5/Files/Mql5Bot/demo_connect_check/EURUSD.json) (harness: restart=exit 1, netting=exit 1, hedging=exit 1)
```

Demo runs (`demo_safety/<test>/run.json`): all three `"status": "FAILED"`,
`ex5_sha256` `353b05032d453e9be358462ad3ddd299701213294ba3809ffc7ca825985336bf`,
`restore.ok=false`, `restore.margin_mode=2`. Each run's step list ends with
"credential-less connection check" -> "terminal exited by itself" -> `restore ok=false`.
The restart run's steps include "terminal KILLED with the probe position open"
and a relaunch; netting and hedging include "seen: account probe + cleanup".

## Journal lines for the failing stage

`stage7_journal_lines.txt` (local time UTC-7), redacted: accounts-file
logins/passwords -> `<REDACTED>`; other 6+ digit account numbers -> `<ACCOUNT>`.
- terminal journal `logs/20261012.log` lines 1312-1330, 1370-1388, 1428-1446:
  the three credential-less connection-check launches (restart, netting,
  hedging). Each shows `authorized on MetaQuotes-Demo`, `terminal synchronized`,
  `trading has been enabled, demo account - hedging mode`, then
  `script Mql5BotExportSymbolSpec (EURUSD,H1) closes terminal with code 2`.
- Experts log `MQL5/Logs/20261012.log` lines 215-220, verbatim message on all
  six export launches in 04:37-04:39 local:
  `[mql5bot] export FAILED: cannot open Mql5Bot\demo_connect_check\ EURUSD.json err=5004`
  (the path in the log line contains a space before `EURUSD.json`).
- After the run, `MQL5\Files\Mql5Bot\demo_connect_check\` exists and is empty.

NOT included: tester journal/window files, symbol-spec exports and EA logs of
this run (the tester journal/window files and symbol-spec exports contain
demo-account values).

Leak check of every file in this report against the demo logins/passwords: 0 hits.
