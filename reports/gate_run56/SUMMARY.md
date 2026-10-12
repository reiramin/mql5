# gate_run56 (FULL gate)

- HEAD SHA tested: `32664ac4b4a24ff3ab6335363e6bf99349c064a6` (master, STAGE10-CERT-1: stage 10 certifies the stage-8 verifier verdict (#51))
- Trigger tag: `[runner: full]`
- Command (no `-Golds`: gold1 + gold2, stages 9-10 allowed):
  `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -DemoSafety`
- Started Monday 2026-10-12 17:44 UTC (market window open until 20:45 UTC);
  finished about 18:15 UTC. Evidence dir: `evidence\owner_gate\20261012-174443`
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
  stage 8  reconciliation         FAIL
  first_blocking_stage: reconciliation
```

## Result

```
GATE_RESULT=reconciliation
GATE_EXIT_CODE=1
```

Verdict fields (gate_summary.json): `certifiable=true`, `partial=false`,
`scope=['gold1','gold2']`, `unscoped_result=reconciliation`,
`first_blocking=reconciliation`, `exit_code=1`. (`certifiable=true` is the
run's scope flag, i.e. an unscoped run; it is NOT a certificate.)

reconciliation_verify.json `verdict`: `NOT_VERIFIED_ARTIFACT_MISMATCH`,
`missing`: `['safety_restart']`. Reasons (verbatim):

```
missing artifacts: ['safety_restart']
archive manifest INVALID: ["archive manifest does not bind: ['safety/restart.json']"]
safety evidence missing: ['restart']
['gold1:real_ticks', 'gold2:real_ticks']: NOT_APPLICABLE_BAR_ONLY_FIXTURE (bar-only fixture, leg not launched): no report exists and none is required; real-tick coverage NONE never yields MT5_VALIDATED
trade source for ['gold1:every_tick', 'gold1:m1_ohlc', 'gold2:every_tick', 'gold2:m1_ohlc']: tester agent log (PASS_FROM_LOG log trade list; no report exists)
```

## Stages 9 and 10

Stage 9 (archive_manifest) and stage 10 (certify) did NOT run: no stage line,
no stage_9.json / stage_10.json. **No archive manifest and no certificate were
produced.**

## Reconciliation counts (reconciliation_verify.json)

gold1: `result` `MATCH`, `state` `VALID`, `reasons` `[]`, first divergence `null`.
gold2: `result` `MATCH`, `state` `VALID`, `reasons` `[]`, first divergence `null`.

| gold | model | paired | missing_in_mt5 | extra_in_mt5 | mt5_entry_deals | mt5_deals |
|---|---|---|---|---|---|---|
| gold1 | m1_ohlc | 18 | 0 | 0 | 18 | 35 |
| gold1 | every_tick | 18 | 0 | 0 | 18 | 35 |
| gold2 | m1_ohlc | 37 | 0 | 0 | 37 | 74 |
| gold2 | every_tick | 37 | 0 | 0 | 37 | 74 |

real_ticks (both golds): NOT_APPLICABLE_BAR_ONLY_FIXTURE (not launched, not a pass).

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

## Stage 7 (stage_7.json, verbatim)

```
demo harness ran restart, netting, hedging with THIS run's stage-1 EX5 into C:\Users\ramin\Desktop\mql5\gate_run12\evidence\owner_gate\20261012-174443\demo_safety (harness: restart=exit 1, netting=exit 0, hedging=exit 0); every restore left the terminal on the hedging account, connected without credentials. NOT a safety grade: the runs are graded at stage 8
```

Demo runs (`demo_safety/<test>/run.json`), `ex5_sha256`
`72f6185b39aefbd84973d788c37c774aa06ff7053ca00d433316a5c77784ecd3` for all three:
- restart: `"status": "FAILED"`, `error`: `timeout after 900s waiting for 'EA START' in the EA log`, `restore.ok=true`
- netting: `"status": "COMPLETED"`, `restore.ok=true`
- hedging: `"status": "COMPLETED"`, `restore.ok=true`

restart steps (from run.json): EA START 17:49:10, probe position opened
17:49:12, terminal KILLED with the probe position open 17:49:42, relaunch
(probe 1) EA START 17:49:57, stopped after observation 17:51:28, launch probe 3
at 17:51:28, then `error` at 18:09:29 (900 s timeout), then restore, connection
check "credential-less launch connected" (margin_mode 2), `restore ok=true`.

## Journal lines for the failing stage

`stage8_restart_probe3_journal_lines.txt` (local time UTC-7), redacted:
accounts-file logins/passwords -> `<REDACTED>`; other 6+ digit account numbers -> `<ACCOUNT>`.
- terminal journal `logs/20261012.log` lines 2624-2651 (the probe-3 launch,
  10:51:29 - 11:07:57 local), containing:
  `Experts | initializing of Mql5Bot (EURUSD,M1) failed with code 1`
  (10:51:38.535), then authorized / synchronized ("1 positions"), and two
  `connection to MetaQuotes-Demo lost` lines (11:03:49, 11:07:24) each followed
  by a re-authorization.
- Experts log `MQL5/Logs/20261012.log` lines 360-361 (verbatim message text):
  `[2026.10.12 20:48:46] [ERROR] symbol spec build failed: tick_value_loss <= 0`
  `[2026.10.12 20:48:46] [INFO] shutting down (reason 8)`

## symbol_state (verbatim)

```
import_EURUSD.G1.json: "symbol_state":"adopted_verified"
import_EURUSD.G2.json: "symbol_state":"adopted_verified"
```

Tester journal / window files, demo EA logs and symbol-spec exports of this run
are NOT included.

Leak check of every file in this report against the demo logins/passwords: 0 hits.
