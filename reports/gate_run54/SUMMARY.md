# gate_run54

- HEAD SHA tested: `422c1749cec00d5406b023359cf00678e5d36e7d` (master, DEMO-CHECK-CRLF-1 + GATE-EXIT-1 (#49))
- Trigger tag: `[runner: demo-in-gate]` (market open: Monday 2026-10-12 13:04 UTC)
- Command (switch name from docs/SAFETY_DEMO_PLAN.md at this HEAD):
  `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold2 -DemoSafety`
- Evidence dir: `evidence\owner_gate\20261012-130454`
- MT5 (terminal64, metaeditor64, metatester64) was not running and git status
  was clean before the gate started. The gate was not interrupted.

## Stage lines (verbatim)

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             PASS
  stage 3  broker_parity          PASS
  stage 4  fixture_import         PASS
  stage 5  tester_legs            PASS_FROM_LOG
  stage 7  demo_safety            PASS
  stage 8  reconciliation         FAIL
  first_blocking_stage: reconciliation
```

## Result

```
GATE_RESULT=partial_reconciliation
GATE_EXIT_CODE=1
```

Verdict fields (gate_summary.json): `certifiable=false`, `partial=true`,
`unscoped_result=reconciliation`, `first_blocking=reconciliation`, `exit_code=1`.

## Stage 7 reason (verbatim, stage_7.json)

```
[scope: gold2; PARTIAL run -- certifies nothing] demo harness ran restart, netting, hedging with THIS run's stage-1 EX5 into C:\Users\ramin\Desktop\mql5\gate_run12\evidence\owner_gate\20261012-130454\demo_safety (harness: restart=exit 0, netting=exit 0, hedging=exit 0); every restore left the terminal on the hedging account, connected without credentials. NOT a safety grade: the runs are graded at stage 8
```

Demo runs (`demo_safety/<test>/run.json`): restart, netting, hedging all
`"status": "COMPLETED"`, `restore.ok=true`, `ex5_sha256`
`6be3d709d57c42097281bea5cb6ab86ad38542221683a15ea681cfa74f66e8d1`
(== `compile/Mql5Bot.ex5` in the stage-8 package build, source "sha256 == stage-1 log").

## Stage 8 reason (verbatim, stage_8.json)

```
[scope: gold2; PARTIAL run -- certifies nothing] UNHANDLED_ERROR: The property 'Name' cannot be found on this object. Verify that the property exists. (script line 1558)
```

`tools/owner_gate.ps1` lines 1556-1559 at this HEAD (verbatim; line 1558 is the third line):

```
if ($pkgBuild.data -and (Get-DataProp $pkgBuild.data "not_built")) {
    $nb = Get-DataProp $pkgBuild.data "not_built"
    [void]$placeNotes.Add(("package built by the gate; NOT built: {0}" -f ((@($nb.PSObject.Properties.Name) | Sort-Object) -join ", ")))
}
```

The package build call before it returned `"ok": true` and `"not_built": {}`
(stage8_package_build.json). The verifier (`verify_owner_mt5_gate.py`) did NOT
run: there is NO reconciliation_verify.json for this run. Therefore:
- there is no verifier "safety" block to quote (it does not exist for this run);
- there are no verifier reconciliation counts and no verifier verdict.

## Stage-8 package builder output (NOT the verifier; recorded for completeness)

These are the builder's graded files in `evidence\owner_mt5_package`, written
before the error. They are not a verdict.

Safety files (`expected_result` / `observed_result` / `passed`):

| test | expected | observed | passed |
|---|---|---|---|
| restart | RESTART_RECOVERED_NO_DUPLICATE | NO_RESTART | false |
| netting | NET_ONE_POSITION_PER_SYMBOL | NET_ONE_POSITION_PER_SYMBOL | true |
| hedging | INDEPENDENT_POSITIONS_ISOLATED_BY_MAGIC | INDEPENDENT_POSITIONS_ISOLATED_BY_MAGIC | true |
| kill_switch | ZERO_NEW_ORDERS_WHILE_LATCHED | ZERO_NEW_ORDERS_WHILE_LATCHED | true |
| risk_veto | ENTRIES_VETOED_FOR_THE_DAY | ENTRIES_VETOED_FOR_THE_DAY | true |
| meta_reduce | ALL_SIZES_LE_RISK_APPROVED | ALL_SIZES_LE_RISK_APPROVED | true |
| sl_verify | SL_STRIPPED_AND_RESTORED | SL_STRIPPED_AND_RESTORED | true |
| lost_response | LOST_RESPONSE_ADOPTED_NO_DUPLICATE | LOST_RESPONSE_ADOPTED_NO_DUPLICATE | true |

restart.json `quoted_lines` (verbatim):

```
[2026.10.12 16:06:55] [INFO] TEST demo: START probe=1 magic=17514383 own_positions=0 registry=0 engine=0 margin_mode=2
[2026.10.12 16:06:55] [INFO] TEST demo: START probe=1 magic=17514383 own_positions=1 registry=1 engine=0 margin_mode=2
[2026.10.12 16:06:55] [INFO] TEST demo: START probe=3 magic=17514383 own_positions=1 registry=1 engine=0 margin_mode=2
[2026.10.12 16:07:21] [INFO] TEST demo: PROBE position opened
```

gold2 pairing (reconciliation/gold2.json, builder side):

| model | paired | missing_in_mt5 | extra_in_mt5 | out_of_tested_window | window |
|---|---|---|---|---|---|
| m1_ohlc | 37 | 0 | 0 | 29 | 2024-01-02 -> 2024-01-04 |
| every_tick | 37 | 0 | 0 | 29 | 2024-01-02 -> 2024-01-04 |

Pairing notes: "37 entries from 74 deals (INFERRED: alternating open/close,
every entry pnl 0)" for both models; python side: 62 approved entries.

## symbol_state (import_EURUSD.G2.json, verbatim)

```
"symbol_state":"adopted_verified"
```

Same file: `"refused":false`, `"n_bars":5760`.

## Journal lines for the failing stage

Stage 8 failed on a gate-script error, not in a tester or terminal run; no
tester/terminal journal line belongs to that error. The console line is in
console.txt. Tester journal / window files, demo EA logs and symbol-spec
exports of this run are NOT included.

Leak check of every file in this report against the demo logins/passwords: 0 hits.
