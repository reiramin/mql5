# gate_run53

- HEAD SHA tested: `93d6e45a871fe7b3be2eee61ac3ef325946a5978` (master, S8-PATH-1: gold1 window run models the tester's intrabar order (#48))
- Trigger tag: `[runner: gold1]`
- Command: `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold1`
- Evidence dir: `evidence\owner_gate\20261012-121204`
- MT5 (terminal64, metaeditor64, metatester64) was not running and git status
  was clean before the gate started. The gate was not interrupted.
- Gate exit code: not captured (launched as a detached process; the console
  ends with the summary and GATE_RESULT).

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

Verdict fields: gate_summary.json `certifiable=false`, `partial=true`,
`unscoped_result=reconciliation`, `first_blocking=reconciliation`.
reconciliation_verify.json `verdict`: `NOT_VERIFIED_ARTIFACT_MISMATCH`.

## gold1 reconciliation (reconciliation_verify.json, gold.gold1)

`result`: `MATCH`, `state`: `VALID`, `reasons`: `[]`,
`first_divergence.gold1`: `null`, `first_trade_divergence.gold1`: `null`.

| model | paired | missing_in_mt5 | extra_in_mt5 | mt5_entry_deals | mt5_deals |
|---|---|---|---|---|---|
| m1_ohlc | 18 | 0 | 0 | 18 | 35 |
| every_tick | 18 | 0 | 0 | 18 | 35 |

real_ticks: NOT_APPLICABLE_BAR_ONLY_FIXTURE (leg not launched, not a pass).
Trade source for both legs: tester agent log (PASS_FROM_LOG log trade list; no report).

`tick_path_divergence.every_tick` (recorded as "observed and named, never a
python<->MT5 divergence by itself"): first exit differing from the m1_ohlc leg
at deal index 1, ticket #3: m1_ohlc `2024.02.05 02:00:40` sell 0.68 at 1.12842;
every_tick `2024.02.05 02:00:43` sell 0.68 at 1.12855.

## Stage 8 reason (verbatim start, stage_8.json)

```
[scope: gold1; PARTIAL run -- certifies nothing] verdict NOT_VERIFIED_ARTIFACT_MISMATCH: missing artifacts: ['hedging', 'netting', 'safety_restart']; archive manifest INVALID: ["archive manifest does not bind: ['safety/hedging.json', 'safety/netting.json', 'safety/restart.json']"]; safety evidence missing: ['restart', 'netting', 'hedging']; ...
```

Full text in stage_8.json and console.txt. This was not a `-DemoSafety` run.

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

## import symbol_state (import_EURUSD.G1.json, verbatim)

```
"symbol_state":"adopted_verified"
```

Same file: `"refused":false`, `"n_bars":720`.

## Journal lines for the failing stage

Stage 8 failed on missing demo safety artifacts (hedging / netting / restart),
not on a tester leg; no tester or terminal journal line belongs to that
reason. The gold1 log trade lists are included (`tester_gold1_*_log_trades.json`).
Tester journal / window files and symbol-spec exports of this run are NOT included.

Leak check of every file in this report against the demo logins/passwords: 0 hits.
