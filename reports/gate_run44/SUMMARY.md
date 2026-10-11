# gate_run44

- HEAD SHA tested: `6894de2d4fefed25571af55503e5dedccda1d48a` (master, Merge PR #42: docs: gate_run43 + windows_pytest at 4b8cad0; gold1 owner step in BLOCKED.md)
- Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold1`
- Evidence dir: `evidence\owner_gate\20261011-220326`
- MT5 was not running and git status was clean before the gate started.
- Context: the owner deleted the stale custom symbol EURUSD.G1 by hand in MT5 before this session.

## Stage lines (verbatim)

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             PASS
  stage 3  broker_parity          FAIL
  first_blocking_stage: broker_parity
```

Stage 3 reason (verbatim):

```
in-scope PENDING rows (not verified, not a pass): [('EURUSD', 'sizer.behaviour'), ('EURUSD', 'tick_value_denomination')]; EURUSD denomination_probe: reason="NOT_SYNCED_AFTER_60s" attempts=10 waited_seconds=69.407 last_error=0
```

## Result

```
GATE_RESULT=partial_broker_parity
```

Gate exit code: 1

Verdict fields (gate_summary.json): `certifiable=false`, `partial=true`,
`unscoped_result=broker_parity`.

## symbol_state (import_EURUSD.G1.json)

Not available. Stage 3 blocked the run before stage 4 (fixture_import), so the
importer did not run and no `import_EURUSD.G1.json` was produced. Whether the
owner's deletion of EURUSD.G1 worked (`created_fresh`) is therefore NOT
measured by this run. There is no importer error to quote.

The same stage-3 FAIL (same PENDING rows, same `NOT_SYNCED_AFTER_60s`) occurred
in gate_run40 (gold2) at the same HEAD a few minutes earlier.

Leak check of every file in this report against the demo logins/passwords: 0 hits.
