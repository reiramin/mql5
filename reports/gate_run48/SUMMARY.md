# gate_run48

- HEAD SHA tested: `fdd7b58946d21e6b9d28635c8ae528126572fe74` (master, Merge PR #45: FILL-MODE-1 + STAGE3-SYNC-QUOTE-1)
- Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold1`
- Evidence dir: `evidence\owner_gate\20261012-091345`
- MT5 was not running and git status was clean before the gate started.
- Run right after gate_run47 (gold2 gate of record), same HEAD.

## Stage lines (verbatim)

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             PASS
  stage 3  broker_parity          PASS
  stage 4  fixture_import         PASS
  stage 5  tester_legs            FAIL
  first_blocking_stage: tester_legs
```

## Result

```
GATE_RESULT=partial_tester_legs
```

Gate exit code: 1

Verdict fields (gate_summary.json): `certifiable=false`, `partial=true`,
`unscoped_result=tester_legs`. Stage 8 did not run; there is no
reconciliation_verify.json for this run.

## symbol_state (import_EURUSD.G1.json, verbatim)

```
"symbol_state":"created_fresh"
```

Same file: `"refused":false`, `"stage":"complete"`, `"last_error":0`,
`"n_bars":720`, `roundtrip_sha256` == `manifest_dataset_hash` ==
`074530cd5b7424dc2138698e2ec72c176bf033c589474d3fde004d87e83728d3`.
`created_fresh` means the owner's manual deletion of EURUSD.G1 worked.

## Stage 5 reason (verbatim, from console)

```
gold1_m1_ohlc: exit 1; FAIL — EA OnInit returned non-zero: the test never ran this leg's strategy. Tester log (this leg only): KK	2	02:14:44.336	Core 1	tester stopped because OnInit returns non-zero code 1 Not PASS_FROM_LOG: successfully_finished, bars_positive, strategy_loaded (expected DSL strategy 'ema_crossover_ref'; the EA logged None).
gold1_every_tick: exit 1; FAIL — EA OnInit returned non-zero: the test never ran this leg's strategy. Tester log (this leg only): KQ	2	02:15:09.334	Core 1	tester stopped because OnInit returns non-zero code 1 Not PASS_FROM_LOG: successfully_finished, bars_positive, strategy_loaded (expected DSL strategy 'ema_crossover_ref'; the EA logged None).
gold1_real_ticks: NOT_APPLICABLE_BAR_ONLY_FIXTURE (leg not launched, not a pass)
```

Full text in stage_5.json. Tester journal / window files and symbol-spec
exports of this run are NOT included (they may contain demo-account values).

Leak check of every file in this report against the demo logins/passwords: 0 hits.
