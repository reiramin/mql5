# gate_run57 (FULL gate)

- HEAD SHA tested: `47c4705186804377cbcb2c655e65b6b09b643f27` (master, SPEC-WAIT-1 + HARNESS-INIT-FAIL-1 (#52))
- Trigger tag: `[runner: full]`
- Command (no `-Golds`: gold1 + gold2, stages 9-10 allowed):
  `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -DemoSafety`
- Started Monday 2026-10-12 22:37 UTC (after the 20:45-22:15 rollover; next
  closure Tuesday 20:45 UTC). gate_summary.json written 2026-10-13 07:47 UTC.
  Evidence dir: `evidence\owner_gate\20261012-223713`
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
  stage 7  demo_safety            FAIL
  first_blocking_stage: demo_safety
```

## Result

```
GATE_RESULT=demo_safety
GATE_EXIT_CODE=1
```

Verdict fields (gate_summary.json): `certifiable=true`, `partial=false`,
`scope=['gold1','gold2']`, `unscoped_result=demo_safety`,
`first_blocking=demo_safety`, `exit_code=1`. (`certifiable=true` is the
run's scope flag, i.e. an unscoped run; it is NOT a certificate.)

Stage 8 did NOT run: there is no reconciliation_verify.json, so there is no
verifier verdict, no "safety" block and no reconciliation counts for this run.

## Stages 9 and 10

Did NOT run (no stage line, no stage_9.json / stage_10.json). **No archive
manifest and no certificate were produced.**

## Stage 7 reason (verbatim, stage_7.json)

```
[demo_terminal_not_restored] the terminal is NOT left logged in to the hedging account and connected without credentials -- every later gate launch would fail stage 3: [demo_restore_not_connected] restart: restore failed: [ea_init_failed] [2026.10.13 01:42:36] [ERROR] symbol spec build failed: tick_value_loss <= 0 (gave up after 60 s WAITING_SYMBOL) (harness: restart=exit 1, netting=exit 0, hedging=exit 0)
```

Demo runs (`demo_safety/<test>/run.json`), `ex5_sha256`
`d08593986c6a98bf956c0ebbd225d8cd5f5d7be107f535a4c696a8eb64946d35` for all three:
- restart: `"status": "FAILED"`, `restore.ok=false`, `restore.margin_mode=null`,
  error `[ea_init_failed] [2026.10.13 01:42:36] [ERROR] symbol spec build failed: tick_value_loss <= 0 (gave up after 60 s WAITING_SYMBOL)`
- netting: `"status": "COMPLETED"`, `restore.ok=true`, `connect_check` `{"sync_unmet": "", "synced": true, "margin_mode": 2}`
- hedging: `"status": "COMPLETED"`, `restore.ok=true`, `connect_check` `{"sync_unmet": "", "synced": true, "margin_mode": 2}`

restart steps (run.json, UTC): start + terminal_started probe 1 at
2026-10-12 22:43:03; next step "seen: EA init failed" at 2026-10-13 07:44:31;
restore launch probe 3 at 07:44:31; "seen: EA init failed" (same detail line)
at 07:45:50; `restore ok=false`.

The netting and hedging runs ran after the restart run; the hedging run was the
last one, and its restore connection check reports synced with `sync_unmet` empty.

## Journal lines for the failing stage

`stage7_restart_journal_lines.txt` (local time UTC-7), redacted: accounts-file
logins/passwords -> `<REDACTED>`; other 6+ digit account numbers -> `<ACCOUNT>`.
- terminal journal `logs/20261012.log` lines 3077-3082: the probe-1 launch at
  15:43:05 local; these are the last lines of that file (no Network /
  authorization line after the launch in that file).
- terminal journal `logs/20261013.log` lines 1-27: first line 00:43:18 local
  `authorized on MetaQuotes-Demo`, the probe-3 restore launch at 00:44:34, one
  `connection to MetaQuotes-Demo lost` (00:45:38) followed by re-authorization,
  and the start of the netting run at 00:45:55.
- Experts log `MQL5/Logs/20261013.log` lines 1-5, including (verbatim text):
  `[2026.10.13 01:42:36] [WARN] WAITING_SYMBOL: symbol spec not ready (tick_value_loss <= 0); retrying for up to 60 s, no new positions`
  (00:43:25 and 00:44:45 local).

## Stage 5 (summary of stage_5.json)

4 legs PASS_FROM_LOG (gold1 + gold2, m1_ohlc + every_tick; source: tester agent
log, no report); 2 legs NOT_APPLICABLE_BAR_ONLY_FIXTURE (real_ticks, not
launched, not a pass). Real-tick coverage NONE.

## symbol_state (verbatim)

```
import_EURUSD.G1.json: "symbol_state":"adopted_verified"
import_EURUSD.G2.json: "symbol_state":"adopted_verified"
```

Tester journal / window files, demo EA logs and symbol-spec exports of this run
are NOT included.

Leak check of every file in this report against the demo logins/passwords: 0 hits.
