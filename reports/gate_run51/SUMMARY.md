# gate_run51

- HEAD SHA tested: `c8bc02205d5f1b73f5f13c61bf70b0796a21adf0` (master, WARMUP-FROMDATE-1: gold1 legs start where the EA has its InpDslBars of history (#47))
- Trigger tag: `[runner: gold1]`
- Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold1`
- Evidence dir: `evidence\owner_gate\20261012-103123`
- MT5 (terminal64, metaeditor64, metatester64) was not running and git status
  was clean before the gate started.

## Stage lines (verbatim)

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             PASS
  stage 3  broker_parity          PASS
  stage 4  fixture_import         PASS
  stage 5  tester_legs            PASS_FROM_LOG
  stage 8  reconciliation         DIVERGENCE_EXPECTED
  first_blocking_stage: reconciliation
```

## Result

```
GATE_RESULT=partial_reconciliation
```

Gate exit code: 1

Verdict fields: gate_summary.json `certifiable=false`, `partial=true`,
`unscoped_result=reconciliation`, `first_blocking=reconciliation`.
reconciliation_verify.json `verdict`: `NOT_VERIFIED_ARTIFACT_MISMATCH`.

## Reconciliation counts (reconciliation_verify.json, gold1.entry_counts)

| model | paired | missing_in_mt5 | extra_in_mt5 | mt5_entry_deals | mt5_deals |
|---|---|---|---|---|---|
| m1_ohlc | 18 | 0 | 0 | 18 | 35 |
| every_tick | 18 | 0 | 0 | 18 | 35 |

real_ticks: NOT_APPLICABLE_BAR_ONLY_FIXTURE (leg not launched, not a pass).
Trade source for both legs: tester agent log (PASS_FROM_LOG log trade list; no report).

## First divergence (reconciliation_verify.json, verbatim fields)

gold1, model `m1_ohlc`, trade_index 16, timestamp `2024-02-07T09:00:00`,
field `volume`: python `0.13`, mt5 `0.14` -> `SIZING_MISMATCH`.

Stage 8 reason (stage_8.json, start):

```
[scope: gold1; PARTIAL run -- certifies nothing] EXPECTED for the 4257f1e sizing fix: first divergence on 'volume' -> SIZING_MISMATCH. Regenerate the affected expected_execution with NEW provenance (owner/build side); NEVER revert the fix, NEVER patch the gold artifacts here.
```

Full text in stage_8.json and console.txt.

## reconciliation_verify.json "safety" block (verbatim)

```json
{
  "hedging": {
    "reasons": [
      "hedging evidence missing"
    ],
    "state": "MISSING"
  },
  "kill_switch": {
    "reasons": [],
    "result": "ZERO_NEW_ORDERS_WHILE_LATCHED",
    "state": "VALID"
  },
  "lost_response": {
    "reasons": [],
    "result": "LOST_RESPONSE_ADOPTED_NO_DUPLICATE",
    "state": "VALID"
  },
  "meta_reduce": {
    "reasons": [],
    "result": "ALL_SIZES_LE_RISK_APPROVED",
    "state": "VALID"
  },
  "netting": {
    "reasons": [
      "netting evidence missing"
    ],
    "state": "MISSING"
  },
  "restart": {
    "reasons": [
      "restart evidence missing"
    ],
    "state": "MISSING"
  },
  "risk_veto": {
    "reasons": [],
    "result": "ENTRIES_VETOED_FOR_THE_DAY",
    "state": "VALID"
  },
  "sl_verify": {
    "reasons": [],
    "result": "SL_STRIPPED_AND_RESTORED",
    "state": "VALID"
  }
}
```

`missing`: `['hedging', 'netting', 'safety_restart']` (no demo evidence in this
run; this was not a `-DemoSafety` run).

## import symbol_state (import_EURUSD.G1.json, verbatim)

```
"symbol_state":"adopted_verified"
```

## Journal lines for the failing stage

`gold1_m1_ohlc_trade16_lines.txt`: tester window lines 318-331 of the m1_ohlc
leg around the first divergent trade (2024.02.07 09:00), local time UTC-7.
Redacted: accounts-file logins/passwords -> `<REDACTED>`; other 6+ digit
account numbers -> `<ACCOUNT>`. Full log trade lists: `tester_gold1_*_log_trades.json`.

Other tester journal / window files and symbol-spec exports of this run are NOT included.

Leak check of every file in this report against the demo logins/passwords: 0 hits.
