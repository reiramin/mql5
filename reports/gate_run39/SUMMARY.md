# gate_run39

- HEAD SHA tested: `f29b7fa55bb9a4cbe49652318d4a9e4fc1ea69ef` (master, Merge pull request #34)
- Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold2`
- Evidence dir: `evidence\owner_gate\20261007-145454`
- Demo harness: not run (%USERPROFILE%\.mql5bot\demo_accounts.json does not exist; MQL5BOT_DEMO_ACCOUNTS not set)

## Stage lines (verbatim)

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             PASS
  stage 3  broker_parity          PASS
  stage 4  fixture_import         PASS
  stage 5  tester_legs            PASS_FROM_LOG
  stage 8  reconciliation         FAIL
```

## Result

```
GATE_RESULT=partial_reconciliation
```

Gate exit code: 1

reconciliation_verify.json verdict: `"NOT_VERIFIED_ARTIFACT_MISMATCH"`
