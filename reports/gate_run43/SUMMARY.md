# gate_run43

- HEAD SHA tested: `4b8cad0` (master, Merge PR #41: IMPORT-CHART-1 importer ini names EURUSD H1)
- Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold1`
- Evidence dir: `evidence\owner_gate\20261011-142952`
- MT5 was not running before the gate started.
- Demo harness: not run (gold1 run; the demo runs are scheduled for after the EURUSD market opens)

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

Stage 4 reason (from stage_4.json), unchanged from gate_run41/42: importer
REFUSED at stage 'symbol_state' (last_error=4305) for EURUSD.G1:
SYMBOL_SPREAD_FLOAT and SYMBOL_SPREAD differ from the manifest spec and cannot
be re-applied on a selected symbol (5306); the release (SymbolSelect(false))
failed. Stages 5 and 8 did not run.

The importer ini of this run (import_EURUSD.G1.ini, included) does carry the
IMPORT-CHART-1 lines `Symbol=EURUSD` / `Period=H1`; with that chart named,
the refusal still occurred. What keeps EURUSD.G1 selected is not known.