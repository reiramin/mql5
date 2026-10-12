# gate_run46

- HEAD SHA tested: `fdd7b58946d21e6b9d28635c8ae528126572fe74` (master, Merge PR #45: FILL-MODE-1 + STAGE3-SYNC-QUOTE-1 [runner: demo] [runner: gold1])
- Trigger tags: `[runner: demo]` (market open: Monday 2026-10-12 08:19 UTC) and `[runner: gold1]`.
- Order of runs (MT5 closed and git status clean before each):
  1. compile gate `-Golds gold2` (so the demo EX5 is this HEAD's stage-1 compile, docs/SAFETY_DEMO_PLAN.md step 4) -> `compile_gate_gold2/`
  2. demo harness restart, netting, hedging -> `demo_safety/<test>/`
  3. `-Golds gold1` gate -> this directory (the result of record for this report)

## gold1 gate (result of record)

Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold1`
Evidence dir: `evidence\owner_gate\20261012-082928`

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             PASS
  stage 3  broker_parity          FAIL
  first_blocking_stage: broker_parity
GATE_RESULT=partial_broker_parity
```

Gate exit code: 1. Verdict fields (gate_summary.json): `certifiable=false`,
`partial=true`, `unscoped_result=broker_parity`.

Stage 3 reason (verbatim):

```
in-scope PENDING rows (not verified, not a pass): [('EURUSD', 'sizer.behaviour'), ('EURUSD', 'tick_value_denomination')]; EURUSD denomination_probe: reason="NOT_SYNCED_AFTER_60s" attempts=10 waited_seconds=69.406 last_error=0 synced=false sync_unmet="terminal not connected"
```

### symbol_state (import_EURUSD.G1.json)

Not available. Stage 3 blocked the run before stage 4; the importer did not
run and no `import_EURUSD.G1.json` was produced. Whether the owner's deletion
of EURUSD.G1 worked is still NOT measured. There is no importer error to quote.

## compile gate, -Golds gold2 (same HEAD, run first)

Evidence dir: `evidence\owner_gate\20261012-081942`

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             PASS
  stage 3  broker_parity          PASS
  stage 4  fixture_import         PASS
  stage 5  tester_legs            PASS_FROM_LOG
  stage 8  reconciliation         FAIL
GATE_RESULT=partial_reconciliation
```

reconciliation_verify.json `verdict`: `NOT_VERIFIED_ARTIFACT_MISMATCH`
(missing artifacts hedging, netting, safety_restart; this run started BEFORE
the demo re-run below, when `evidence\demo_safety` held only the FAILED runs
of gate_run40). gold2 reconciliation: `result=MATCH`; every_tick and m1_ohlc
each `paired=37`, `mt5_entry_deals=37`, `missing_in_mt5=0`, `extra_in_mt5=0`;
`first_divergence=null`, `first_trade_divergence=null` (same counts as the
previous gold2 reconciliation, evidence 20261011-095641).

"safety" block of that reconciliation_verify.json (verbatim):

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

Tester journal / window files and symbol-spec exports of that run are NOT
included: the leak check found demo-account values in them.

## demo harness (after the compile gate)

All three runs: `ex5_sha256` `4f03256d54f2fd9318c42c0a45ab9fbea3c2f904e21cf2bfda9b619ab429b84f`.
These runs were NOT graded by any gate yet: the gold1 gate stopped at stage 3,
and the gold2 compile gate ran before them. `COMPLETED` is the harness run
status, not a stage-8 grade.

| test | run.json status | restore |
|---|---|---|
| restart | COMPLETED | ok=true, margin_mode=2 |
| netting | COMPLETED | ok=true, margin_mode=2 |
| hedging | COMPLETED | ok=true, margin_mode=2 |

### restart — TEST demo lines (heartbeats omitted: 12)

```
[2026.10.12 11:24:26] [INFO] TEST demo: START probe=1 magic=17514383 own_positions=0 registry=0 engine=0 margin_mode=2
[2026.10.12 11:25:36] [INFO] TEST demo: PROBE position opened
[2026.10.12 11:24:26] [INFO] TEST demo: START probe=1 magic=17514383 own_positions=1 registry=1 engine=0 margin_mode=2
[2026.10.12 11:27:57] [INFO] TEST demo: START probe=3 magic=17514383 own_positions=1 registry=1 engine=0 margin_mode=2
[2026.10.12 11:27:58] [INFO] TEST demo: CLEANUP closed 1
[2026.10.12 11:27:58] [INFO] TEST demo: SNAPSHOT after_cleanup margin_mode=2 own_positions=0 registry=0 positions=[]
```

Final restore line: `[2026.10.12 11:28:04] [INFO] TEST demo: SNAPSHOT after_cleanup margin_mode=2 own_positions=0 registry=0 positions=[]`

### netting — TEST demo lines

```
[2026.10.12 11:28:12] [INFO] TEST demo: START probe=2 magic=17514383 own_positions=0 registry=1 engine=0 margin_mode=0
[2026.10.12 11:28:17] [INFO] TEST demo: SNAPSHOT after_A buy 0.01 done=true margin_mode=0 own_positions=1 registry=1 positions=[10905314559:buy:0.01:17514383]
[2026.10.12 11:28:22] [INFO] TEST demo: SNAPSHOT after_B sell 0.02 done=true margin_mode=0 own_positions=1 registry=1 positions=[10905315876:sell:0.01:17514383]
[2026.10.12 11:28:27] [INFO] TEST demo: SNAPSHOT after_F foreign_buy 0.01 magic=17514384 done=true margin_mode=0 own_positions=0 registry=0 positions=[]
[2026.10.12 11:28:32] [INFO] TEST demo: CLEANUP closed 0
[2026.10.12 11:28:32] [INFO] TEST demo: SNAPSHOT after_cleanup margin_mode=0 own_positions=0 registry=0 positions=[]
```

Final restore line: `[2026.10.12 11:28:38] [INFO] TEST demo: SNAPSHOT after_cleanup margin_mode=2 own_positions=0 registry=0 positions=[]`

### hedging — TEST demo lines

```
[2026.10.12 11:24:26] [INFO] TEST demo: START probe=2 magic=17514383 own_positions=0 registry=0 engine=0 margin_mode=2
[2026.10.12 11:28:49] [INFO] TEST demo: SNAPSHOT after_A buy 0.01 done=true margin_mode=2 own_positions=1 registry=1 positions=[58853429704:buy:0.01:17514383]
[2026.10.12 11:28:54] [INFO] TEST demo: SNAPSHOT after_B sell 0.02 done=true margin_mode=2 own_positions=2 registry=2 positions=[58853431041:sell:0.02:17514383,58853429704:buy:0.01:17514383]
[2026.10.12 11:28:59] [INFO] TEST demo: SNAPSHOT after_F foreign_buy 0.01 magic=17514384 done=true margin_mode=2 own_positions=2 registry=2 positions=[58853432531:buy:0.01:17514384,58853431041:sell:0.02:17514383,58853429704:buy:0.01:17514383]
[2026.10.12 11:29:04] [INFO] TEST demo: CLEANUP closed 3
[2026.10.12 11:29:04] [INFO] TEST demo: SNAPSHOT after_cleanup margin_mode=2 own_positions=0 registry=0 positions=[]
```

Final restore line: `[2026.10.12 11:29:11] [INFO] TEST demo: SNAPSHOT after_cleanup margin_mode=2 own_positions=0 registry=0 positions=[]`

Leak check of every file in this report against the demo logins/passwords: 0 hits.
