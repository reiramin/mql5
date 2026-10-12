# gate_run50

- HEAD SHA tested: `add80bf8905a1a1b01620dc4ec867632c15f6ffd` (master, Merge PR #46: DEMO-IN-GATE-1 + DEMO-LOGIN-PERSIST-1)
- Trigger tags: `[runner: demo-in-gate]` and `[runner: gold1]`. This report is the
  `gold1` run; the demo-in-gate run is gate_run49 (run first, same HEAD).
- Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold1`
- Evidence dir: `evidence\owner_gate\20261012-102222`
- MT5 (terminal64, metaeditor64, metatester64) was not running and git status
  was clean before the gate started.

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
reconciliation_verify.json for this run, so there is no "safety" block.

## symbol_state (import_EURUSD.G1.json, verbatim)

```
"symbol_state":"adopted_verified"
```

Same file: `"refused":false`, `"n_bars":720`, `roundtrip_sha256` ==
`manifest_dataset_hash` ==
`074530cd5b7424dc2138698e2ec72c176bf033c589474d3fde004d87e83728d3`.

## Stage 5 reason (verbatim, from console)

```
gold1_m1_ohlc: exit 1; FAIL — EA OnInit returned non-zero: the test never ran this leg's strategy. Tester log (this leg only): FG	2	03:24:11.450	Core 1	tester stopped because OnInit returns non-zero code 1 Not PASS_FROM_LOG: successfully_finished, bars_positive, strategy_loaded (expected DSL strategy 'ema_crossover_ref'; the EA logged None).
gold1_every_tick: exit 1; FAIL — EA OnInit returned non-zero: the test never ran this leg's strategy. Tester log (this leg only): QM	2	03:24:47.832	Core 1	tester stopped because OnInit returns non-zero code 1 Not PASS_FROM_LOG: successfully_finished, bars_positive, strategy_loaded (expected DSL strategy 'ema_crossover_ref'; the EA logged None).
gold1_real_ticks: NOT_APPLICABLE_BAR_ONLY_FIXTURE (leg not launched, not a pass)
```

Full text in stage_5.json.

## Journal lines for the failing legs

`gold1_m1_ohlc_oninit_lines.txt` and `gold1_every_tick_oninit_lines.txt`: tester
window lines from leg start up to the OnInit stop line (local time UTC-7).
Each contains, right before the stop line:

```
[mql5bot] DSL series build failed: 
```

Redacted: accounts-file logins/passwords -> `<REDACTED>`; any other standalone
6+ digit number -> `<ACCOUNT>`. Other tester journal / window files and
symbol-spec exports of this run are NOT included.

Leak check of every file in this report against the demo logins/passwords: 0 hits.
