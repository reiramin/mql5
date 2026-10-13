# gate_run60 (FULL gate)

- HEAD SHA tested: `50cdb71c149c24689a89dba2dfac97b1afd9dd1c` (master, IMPORT-SELFHEAL-1 (#55))
- Trigger tag: `[runner: full]`
- Command (no `-Golds`: gold1 + gold2, stages 9-10 allowed):
  `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -DemoSafety`
  (launched through the runner wrapper, which only blocks Windows idle sleep for
  the process lifetime and tees the console; arguments passed unchanged.)
- Started Tuesday 2026-10-13 11:05:33 UTC, inside the market window (next
  closure Tuesday 20:45 UTC). Gate ended 11:18:14 UTC (gate_summary.json `utc`
  2026-10-13T11:18:14.5354956Z). Evidence dir: `evidence\owner_gate\20261013-110534`
- MT5 (terminal64, metaeditor64, metatester64) was not running and
  `git status --porcelain` was empty before the gate started. The gate was not
  interrupted.
- Wall-clock gap check (consecutive `steps[].utc` in every run.json): max gap
  restart 91 s, netting 19 s, hedging 21 s -- all under 5 minutes. `suspended`
  is null in all three. The run is VALID.

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
  stage 9  archive_manifest       PASS
  stage 10 certify                PASS
  first_blocking_stage: 
```

## Result

```
GATE_RESULT=certified_with_log_graded_legs
GATE_EXIT_CODE=1
```

`gate_exit_code.txt` = `1`. Per docs/OWNER_GATE.md, a passing run with every
gold leg graded from the tester log ends `certified_with_log_graded_legs`, kept
distinct from `certified` by design; only `certified` exits 0.

Verdict fields (gate_summary.json): `certifiable=true`, `partial=false`,
`scope=['gold1','gold2']`, `unscoped_result=certified_with_log_graded_legs`,
`first_blocking=null`, `exit_code=1`, `real_tick_coverage`:
gold1=`NONE (bar-only fixture)`, gold2=`NONE (bar-only fixture)`.

Stage 8 verifier verdict (reconciliation_verify.json): **`MT5_VALIDATED_BAR_MODELS`**
-- bar models only (m1_ohlc + every_tick); no real-tick claim; real_ticks legs
NOT_APPLICABLE_BAR_ONLY_FIXTURE (not launched, not a pass). All four gold legs
are graded from the tester agent log (PASS_FROM_LOG), no report exists.

## Safety block (verbatim, reconciliation_verify.json `safety`)

| test | state | observed (result) | reasons |
|---|---|---|---|
| hedging | VALID | INDEPENDENT_POSITIONS_ISOLATED_BY_MAGIC | [] |
| kill_switch | VALID | ZERO_NEW_ORDERS_WHILE_LATCHED | [] |
| lost_response | VALID | LOST_RESPONSE_ADOPTED_NO_DUPLICATE | [] |
| meta_reduce | VALID | ALL_SIZES_LE_RISK_APPROVED | [] |
| netting | VALID | NET_ONE_POSITION_PER_SYMBOL | [] |
| restart | VALID | RESTART_RECOVERED_NO_DUPLICATE | [] |
| risk_veto | VALID | ENTRIES_VETOED_FOR_THE_DAY | [] |
| sl_verify | VALID | SL_STRIPPED_AND_RESTORED | [] |

8 of 8 VALID, 0 MISSING.

## Gold pairing counts (reconciliation_verify.json `gold`)

| gold | model | mt5_deals | mt5_entry_deals | paired | missing_in_mt5 | extra_in_mt5 | result |
|---|---|---|---|---|---|---|---|
| gold1 | m1_ohlc | 35 | 18 | 18 | 0 | 0 | MATCH |
| gold1 | every_tick | 35 | 18 | 18 | 0 | 0 | MATCH |
| gold2 | m1_ohlc | 74 | 37 | 37 | 0 | 0 | MATCH |
| gold2 | every_tick | 74 | 37 | 37 | 0 | 0 | MATCH |

`python_trade_count`: gold1 18, gold2 56 (verbatim field values).
`first_divergence` and `first_trade_divergence`: null for both golds.
`missing`: []. `archive_manifest.state`: VALID.

## symbol_state

- EURUSD.G1: `adopted_verified`, `stage=complete`, `n_bars=720`, dataset hash
  `074530cd5b7424dc2138698e2ec72c176bf033c589474d3fde004d87e83728d3` == manifest.
- EURUSD.G2: `adopted_verified`, `stage=complete`, `n_bars=5760`, dataset hash
  `59cd339f6ebd2070ffa726c9b4dbaf6074ef232fd2a391afcacb8c3e8bf3dd79` == manifest.
  (G2 was the symbol created fresh in gate_run59, adopted here.)
- IMPORT-SELFHEAL-1 (drop + recreate when the adopt wipe leaves bars) was
  **not exercised** by this run: the adopt wipe left no bars on either symbol,
  the Experts log shows only the normal `SYMBOL_STATE adopted_verified` and
  `dataset hash MATCHES manifest` lines (04:06 local, UTC-7), and no symbol was
  dropped or recreated. The self-heal path remains built, unit-tested, never run live.

## Stages 9 and 10

- Stage 9 **produced the archive manifest**: `archive_manifest.json`
  sha256 `bd624aa1285fe2c202c9df1bc2a5b12ad49e6c601c420f942e18cef7d121e11e`
  ("evidence bound by owner_evidence_bind.py (no hand-typed hash); scope: bar models").
- Stage 10 **produced the certificate**: `certificate/certificate.json`
  sha256 `5f86787041bac23fbc882672406877421594996016e2fffe8378c7ce48e8e326`,
  `certificate/certificate.md` sha256
  `21158f1250e201a53532f7a9bd43aad41eb3487cea77688f3c51116bee35c996`.
  Verdict MT5_VALIDATED_BAR_MODELS, scope bar models, source commit 50cdb71.
  The certificate states it makes no profitability claim.

## Demo harness (stage 7)

All three runs `status=COMPLETED`, `restore.ok=true`, ex5_sha256
`444ca16efb0b15c25d45191a546a5d460bc273634c8c81d7c9eba9890c0af2a5` for all three
(this run's stage-1 EX5).
- restart 11:09:39 - 11:12:33 UTC, netting 11:12:35 - 11:13:24 UTC,
  hedging 11:13:25 - 11:14:15 UTC.
- No `WAITING_SYMBOL` line in any demo EA log of this run, and no run was
  suspended: the SPEC-WAIT-2 wait path and the HARNESS-SUSPEND-1 abort path were
  not exercised (not needed, not proven).

## Leftover demo positions

Checked before the run, no trading done by the runner: gate_run59's demo EA
logs all end with `SNAPSHOT after_cleanup ... positions=[]` (restart, netting,
hedging). After this run every demo EA log again ends with
`SNAPSHOT after_cleanup ... own_positions=0 registry=0 positions=[]`.

## Failing-stage journal lines

None: no stage failed.

## Leak check

Every file in `reports/gate_run60/` scanned for the demo logins and passwords
(raw and UTF-16) after this file's final edit.

Leak check result: 34 files scanned, **0 hits**.
