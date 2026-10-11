# gate_run41

- HEAD SHA tested: `3337bfa` (master, Merge pull request #38)
- Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold1`
- Evidence dir: `evidence\owner_gate\20261011-100947`
- Demo harness: not run (gold1 run; the demo harness runs are scheduled for after the EURUSD market opens)
- Numbering: gate_run40 is reserved for the gold2 demo gate of record (owner instruction), so this run is gate_run41.

## Stage lines (verbatim)

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             PASS
  stage 3  broker_parity          PASS
  stage 4  fixture_import         FAIL
```

## Result

```
GATE_RESULT=partial_fixture_import
```

Gate exit code: 1

Stage 4 reason (from stage_4.json): importer REFUSED at stage 'symbol_state'
(last_error=4305) for EURUSD.G1: SYMBOL_SPREAD_FLOAT and SYMBOL_SPREAD differ
from the manifest spec and cannot be re-applied on a selected symbol; the
release (SymbolSelect(false)) failed. The gate's stated remediation: close any
chart on EURUSD.G1 in the terminal, then re-run the gate.
Stages 5 and 8 did not run.
