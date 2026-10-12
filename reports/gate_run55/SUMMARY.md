# gate_run55

- HEAD SHA tested: `90041fe6018fea180242e12bf72645f4c46b2536` (master, STAGE8-EMPTY-NOTBUILT-1 + RESTART-GRADE-1 (#50))
- Trigger tag: `[runner: demo-in-gate]` (market open: Monday 2026-10-12 16:32 UTC)
- Command (switch name from docs/SAFETY_DEMO_PLAN.md at this HEAD):
  `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -Golds gold2 -DemoSafety`
- Evidence dir: `evidence\owner_gate\20261012-163255`
- MT5 (terminal64, metaeditor64, metatester64) was not running and git status
  was clean before the gate started. The gate was not interrupted.

## Stage lines (verbatim)

```
  stage 0  self_protection        PASS
  stage 1  strict_compile         PASS
  stage 2  dsl_parity             PASS
  stage 3  broker_parity          PASS
  stage 4  fixture_import         PASS
  stage 5  tester_legs            PASS_FROM_LOG
  stage 7  demo_safety            PASS
  stage 8  reconciliation         PASS
  stage 9  archive_manifest       REFUSED
  stage 10 certify                REFUSED
  first_blocking_stage: 
```

## Result

```
GATE_RESULT=partial_reconciliation
GATE_EXIT_CODE=1
```

Verdict fields (gate_summary.json): `certifiable=false`, `partial=true`,
`scope=['gold2']`, `unscoped_result=reconciliation`, `first_blocking=null`, `exit_code=1`.

reconciliation_verify.json `verdict`: `MT5_VALIDATED_BAR_MODELS_PARTIAL_SCOPE`
(`missing`: `[]`). Its reasons (verbatim):

```
scoped verification of ['gold2'] only: its evidence verified against the frozen record on the bar models — no real-tick claim; m1_ohlc + every_tick only
PARTIAL: excluded ['gold1'] were not examined — this verifies nothing about them and certifies nothing
['gold2:real_ticks']: NOT_APPLICABLE_BAR_ONLY_FIXTURE (bar-only fixture, leg not launched): no report exists and none is required; real-tick coverage NONE never yields MT5_VALIDATED
trade source for ['gold2:every_tick', 'gold2:m1_ohlc']: tester agent log (PASS_FROM_LOG log trade list; no report exists)
```

This is a scoped (gold2-only), bar-model-only result. It certifies nothing:
gold1 was excluded, real ticks were not run, stages 9 and 10 were refused.

## Stages 9 and 10 (verbatim, stage_9.json / stage_10.json)

```
stage 9  REFUSED: [scope: gold2; PARTIAL run -- certifies nothing] [refused_scoped_run] archive manifest not built: scoped run over gold2; excluded: gold1
stage 10 REFUSED: [scope: gold2; PARTIAL run -- certifies nothing] [refused_scoped_run] certify_strategy.py not run: a scoped run is never certifiable; excluded: gold1 [real-tick coverage: gold2=NONE (bar-only fixture)]
```

## gold2 reconciliation counts (reconciliation_verify.json, gold.gold2)

`result`: `MATCH`, `state`: `VALID`, `reasons`: `[]`,
`first_divergence.gold2`: `null`, `first_trade_divergence.gold2`: `null`.

| model | paired | missing_in_mt5 | extra_in_mt5 | mt5_entry_deals | mt5_deals |
|---|---|---|---|---|---|
| m1_ohlc | 37 | 0 | 0 | 37 | 74 |
| every_tick | 37 | 0 | 0 | 37 | 74 |

real_ticks: NOT_APPLICABLE_BAR_ONLY_FIXTURE (leg not launched, not a pass).

## reconciliation_verify.json "safety" block (verbatim)

```json
{
  "hedging": {
    "reasons": [],
    "result": "INDEPENDENT_POSITIONS_ISOLATED_BY_MAGIC",
    "state": "VALID"
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
    "reasons": [],
    "result": "NET_ONE_POSITION_PER_SYMBOL",
    "state": "VALID"
  },
  "restart": {
    "reasons": [],
    "result": "RESTART_RECOVERED_NO_DUPLICATE",
    "state": "VALID"
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

## Stage 7 (stage_7.json, verbatim)

```
[scope: gold2; PARTIAL run -- certifies nothing] demo harness ran restart, netting, hedging with THIS run's stage-1 EX5 into C:\Users\ramin\Desktop\mql5\gate_run12\evidence\owner_gate\20261012-163255\demo_safety (harness: restart=exit 0, netting=exit 0, hedging=exit 0); every restore left the terminal on the hedging account, connected without credentials. NOT a safety grade: the runs are graded at stage 8
```

Demo runs (`demo_safety/<test>/run.json`): restart, netting, hedging all
`"status": "COMPLETED"`, `restore.ok=true`, `ex5_sha256`
`c8099a05e0e230f99d94bd01671574524988db4a6b9015893ec9c3e84b4be866`.

## symbol_state (import_EURUSD.G2.json, verbatim)

```
"symbol_state":"adopted_verified"
```

Same file: `"refused":false`, `"n_bars":5760`.

## Journal lines

No stage FAILed. Stages 9 and 10 were REFUSED by the gate's scope rule
(`[refused_scoped_run]`), not by a tester or terminal run; no journal line
belongs to them. Tester journal / window files, demo EA logs and symbol-spec
exports of this run are NOT included.

Leak check of every file in this report against the demo logins/passwords: 0 hits.
