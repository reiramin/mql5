# gate_run45

- HEAD SHA tested: `5fd43686adee7505133f77c4ee702a3205fe5c83` (master, Merge PR #43: DEMO-HARNESS-RELAUNCH-1; gate_run40/44 read)
- Trigger: new merge on origin/master, no `[runner: ...]` tag -> default `-Golds gold2`
- Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold2`
- Evidence dir: `evidence\owner_gate\20261012-065619`
- MT5 was not running and git status was clean before the gate started.
- Demo harness: not re-run (no `[runner: demo]` tag).

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
in-scope PENDING rows (not verified, not a pass): [('EURUSD', 'sizer.behaviour'), ('EURUSD', 'tick_value_denomination')]; EURUSD denomination_probe: reason="NOT_SYNCED_AFTER_60s" attempts=10 waited_seconds=69.25 last_error=0
```

## Result

```
GATE_RESULT=partial_broker_parity
```

Gate exit code: 1

Verdict fields (gate_summary.json): `certifiable=false`, `partial=true`,
`unscoped_result=broker_parity`.

Leak check of every file in this report against the demo logins/passwords: 0 hits.
