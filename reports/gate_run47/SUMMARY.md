# gate_run47 (gold2 gate of record, grading the gate_run46 demo evidence)

- HEAD SHA tested: `fdd7b58946d21e6b9d28635c8ae528126572fe74` (master, Merge PR #45: FILL-MODE-1 + STAGE3-SYNC-QUOTE-1)
- Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold2`
  (no `-DemoEvidence`: default `evidence\demo_safety`)
- Evidence dir: `evidence\owner_gate\20261012-090748`
- MT5 was not running and git status was clean before the gate started.
- Demo harness NOT re-run (owner instruction). `evidence\demo_safety` held the
  gate_run46 runs: restart / netting / hedging, all `COMPLETED`, all
  `ex5_sha256` `4f03256d54f2fd9318c42c0a45ab9fbea3c2f904e21cf2bfda9b619ab429b84f`.

## Stage lines (verbatim)

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             PASS
  stage 3  broker_parity          PASS
  stage 4  fixture_import         PASS
  stage 5  tester_legs            PASS_FROM_LOG
  stage 8  reconciliation         FAIL
  first_blocking_stage: reconciliation
```

## Result

```
GATE_RESULT=partial_reconciliation
```

Gate exit code: 1

Verdict (reconciliation_verify.json): `NOT_VERIFIED_ARTIFACT_MISMATCH`.
gate_summary.json: `certifiable=false`, `partial=true`, `unscoped_result=reconciliation`.

gold2 reconciliation: `result=MATCH`; every_tick and m1_ohlc each
`paired=37`, `mt5_entry_deals=37`, `mt5_deals=74`, `missing_in_mt5=0`, `extra_in_mt5=0`.

## Why the demo evidence was not graded (builder output, verbatim)

From `decide_77ea40a8087d45b39cb9280471c38434.json` (included):

```
"safety/restart.json": "... demo run EX5 sha256 '4f03256d54f2fd9318c42c0a45ab9fbea3c2f904e21cf2bfda9b619ab429b84f' != this gate's stage-1 compile hash 'd9a5609cdda9e5c38acc3d0312a4908e68e7c0692df3278e158942c8177de7a3': evidence of another binary"
"safety/netting.json": "... (same EX5 mismatch) ..."
"safety/hedging.json": "... (same EX5 mismatch) ..."
```

Observed (fact, no interpretation of cause): the compile gate at the SAME HEAD
`fdd7b58` (evidence `20261012-081942`, gate_run46 `compile_gate_gold2/`) recorded
`compile/Mql5Bot.ex5` = `4f03256d...`; this gate's compile recorded
`d9a5609c...`. Every gate run recompiles, so a demo run bound to one compile's
EX5 did not match the next gate's stage-1 hash.

## reconciliation_verify.json "safety" block (verbatim)

```json
{
    "hedging":  { "reasons": [ "hedging evidence missing" ], "state": "MISSING" },
    "kill_switch":  { "reasons": [], "result": "ZERO_NEW_ORDERS_WHILE_LATCHED", "state": "VALID" },
    "lost_response":  { "reasons": [], "result": "LOST_RESPONSE_ADOPTED_NO_DUPLICATE", "state": "VALID" },
    "meta_reduce":  { "reasons": [], "result": "ALL_SIZES_LE_RISK_APPROVED", "state": "VALID" },
    "netting":  { "reasons": [ "netting evidence missing" ], "state": "MISSING" },
    "restart":  { "reasons": [ "restart evidence missing" ], "state": "MISSING" },
    "risk_veto":  { "reasons": [], "result": "ENTRIES_VETOED_FOR_THE_DAY", "state": "VALID" },
    "sl_verify":  { "reasons": [], "result": "SL_STRIPPED_AND_RESTORED", "state": "VALID" }
}
```

Tester journal / window files and symbol-spec exports of this run are NOT
included (they contain demo-account values).

Leak check of every file in this report against the demo logins/passwords: 0 hits.
