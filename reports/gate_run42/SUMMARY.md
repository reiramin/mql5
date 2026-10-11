# gate_run42

- HEAD SHA tested: `3337bfa` (master, Merge pull request #38)
- Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold1`
- Evidence dir: `evidence\owner_gate\20261011-103909`
- Demo harness: not run (gold1 run; the demo runs are scheduled for after the EURUSD market opens)
- Context: re-run of gate_run41 after the owner hid EURUSD.G1 from Market Watch, closed its chart and closed MT5.

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

Stage 4 reason (from stage_4.json), the same as gate_run41: importer REFUSED at
stage 'symbol_state' (last_error=4305) for EURUSD.G1: SYMBOL_SPREAD_FLOAT and
SYMBOL_SPREAD differ from the manifest spec and cannot be re-applied on a
selected symbol (5306); the release (SymbolSelect(false)) failed.
Stages 5 and 8 did not run.

Observed by the runner (read-only): the terminal's config\ and MQL5\Profiles\
files contain no reference to EURUSD.G1, and import_EURUSD.G1.ini sets no
Symbol=. What keeps EURUSD.G1 selected at import time is not known.