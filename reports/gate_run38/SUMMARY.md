# gate_run38

- HEAD SHA tested: `f7d1879d83e0de5acd27eff7648d2237f4052512` (master, Merge pull request #33)
- Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold2`
- Evidence dir: `evidence\owner_gate\20261007-131148`
- Demo harness: not run (docs/SAFETY_DEMO_PLAN.md does not exist at this SHA)

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
