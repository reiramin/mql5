# gate_run40 (gate of record, gold2, with demo harness)

- HEAD SHA tested: `6894de2d4fefed25571af55503e5dedccda1d48a` (master, Merge PR #42: docs: gate_run43 + windows_pytest at 4b8cad0; gold1 owner step in BLOCKED.md)
- Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold2`
  (no `-DemoEvidence`: default `evidence\demo_safety`, as docs/SAFETY_DEMO_PLAN.md says)
- Evidence dir: `evidence\owner_gate\20261011-220002`
- MT5 (terminal64, metaeditor64, metatester64) was not running and git status was clean before every run below.

## Stage lines (verbatim)

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             PASS
  stage 3  broker_parity          FAIL
  first_blocking_stage: broker_parity
```

Stage 3 reason (stage_3.json, verbatim):

```
[scope: gold2; PARTIAL run -- certifies nothing] in-scope PENDING rows (not verified, not a pass): [('EURUSD', 'sizer.behaviour'), ('EURUSD', 'tick_value_denomination')]; EURUSD denomination_probe: reason="NOT_SYNCED_AFTER_60s" attempts=10 waited_seconds=69.219 last_error=0
```

## Result

```
GATE_RESULT=partial_broker_parity
```

Gate exit code: 1

Verdict (gate_summary.json; it has no `verdict` key, these are its verdict fields):
`certifiable=false`, `partial=true`, `unscoped_result=broker_parity`, `first_blocking=broker_parity`.

## reconciliation_verify.json "safety" block

Not produced. Stage 3 blocked the run, so stage 8 (which builds the safety
package) and the reconciliation verifier never ran in this gate run. There is
no `reconciliation_verify.json` in `evidence\owner_gate\20261011-220002`.
The demo evidence below was therefore NOT picked up or graded by this gate.

## Demo harness (step 3), before this gate run

Command per test (docs/SAFETY_DEMO_PLAN.md):
`python tools\demo_safety_harness.py run --test <test> --terminal "C:\Program Files\MetaTrader 5\terminal64.exe" --data-folder "<data folder>"`

All three files are in `demo_safety/<test>/` (run.json, ealog.txt,
restore_ealog.txt). All three runs report `ex5_sha256`
`ae25df6e41f3fca8034be2bc766c0c2c6fd6a4401f6c28470d4065b9e509e2f4`.

| test | run.json status | run.json error (verbatim) |
|---|---|---|
| restart | FAILED | timeout after 900s waiting for 'probe position opened' in the EA log; restore failed: restore account margin_mode 0 is not hedging (2) |
| netting | FAILED | timeout after 900s waiting for 'EA START' in the EA log; restore failed: restore account margin_mode 0 is not hedging (2) |
| hedging | FAILED | restore failed: restore account margin_mode 0 is not hedging (2) |

### restart — TEST demo lines

```
[2026.10.12 00:27:48] [INFO] TEST demo: START probe=1 magic=17514383 own_positions=0 registry=0 engine=0 margin_mode=0
(90 x) TEST demo: SNAPSHOT heartbeat margin_mode=0 own_positions=0 registry=0 positions=[]
```

The EA log shows `EXEC|open_rejected|EURUSD|INVALID_FILL|...` once per
second; the MT5 journal shows `failed market buy 0.01 EURUSD ... [Unsupported filling mode]`.

Final restore line: `[2026.10.12 00:43:00] [INFO] TEST demo: SNAPSHOT after_cleanup margin_mode=0 own_positions=0 registry=0 positions=[]`

### netting — TEST demo lines

None in ealog.txt (the EA START line never appeared within 900 s).

Final restore line: `[2026.10.12 00:58:48] [INFO] TEST demo: SNAPSHOT after_cleanup margin_mode=0 own_positions=0 registry=0 positions=[]`

### hedging — TEST demo lines

```
[2026.10.12 00:59:19] [INFO] TEST demo: START probe=2 magic=17514383 own_positions=0 registry=0 engine=0 margin_mode=0
[2026.10.12 00:59:23] [INFO] TEST demo: SNAPSHOT after_A buy 0.01 done=false margin_mode=0 own_positions=0 registry=0 positions=[]
[2026.10.12 00:59:29] [INFO] TEST demo: SNAPSHOT after_B sell 0.02 done=false margin_mode=0 own_positions=0 registry=0 positions=[]
[2026.10.12 00:59:34] [INFO] TEST demo: SNAPSHOT after_F foreign_buy 0.01 magic=17514384 done=false margin_mode=0 own_positions=0 registry=0 positions=[]
[2026.10.12 00:59:39] [INFO] TEST demo: CLEANUP closed 0
[2026.10.12 00:59:39] [INFO] TEST demo: SNAPSHOT after_cleanup margin_mode=0 own_positions=0 registry=0 positions=[]
```

Final restore line: `[2026.10.12 00:59:44] [INFO] TEST demo: SNAPSHOT after_cleanup margin_mode=0 own_positions=0 registry=0 positions=[]`

### Observed account mode (fact, no credentials)

The MT5 journal (logs\20261011.log) shows that the login configured under the
`hedging` role in the local accounts file was authorized with
`trading has been enabled, demo account - netting mode`, and the EA reports
`margin_mode=0` for it. The `netting` role login was also authorized as
`demo account - netting mode`. No logged-in account showed margin_mode=2.

## Compile gate (step 2), same HEAD, earlier

`tools\owner_gate.ps1 ... -Golds gold2`, evidence `evidence\owner_gate\20261011-211616`
(stage files in `compile_gate_step2/`):

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             FAIL
GATE_RESULT=partial_dsl_parity
```

Stage 2 reason (verbatim): `no compare_report.txt produced by run_dsl_parity.ps1`.
The MT5 journal shows the terminal starting from dsl_parity.ini and logging in;
no DslParityRunner line was logged for that start, and run_dsl_parity.ps1's
600 s timeout elapsed.

Leak check of every file in this report against the demo logins/passwords: 0 hits.
