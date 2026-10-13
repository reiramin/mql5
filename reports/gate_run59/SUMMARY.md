# gate_run59 (FULL gate, owner-requested re-run of ab312d5)

- HEAD SHA tested: `ab312d55eefd7458ddc2bc92b6fcd770acf2f955` (master, HARNESS-SUSPEND-1 + SPEC-WAIT-2 (#53))
- **Owner-requested re-run of ab312d5** (same commit as gate_run58). Before it,
  the owner deleted the custom symbol EURUSD.G2 in MT5 (same remedy as the
  earlier created_fresh case) and closed MT5. gate_run58 had stopped at stage 4:
  `CustomRatesDelete left 5760 bar(s) on EURUSD.G2`.
- Trigger: owner instruction (commit tag `[runner: full]`)
- Command (no `-Golds`: gold1 + gold2, stages 9-10 allowed):
  `tools\owner_gate.ps1 -DataFolder "C:\Users\ramin\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" -DemoSafety`
  (launched through the runner wrapper, which only blocks Windows idle sleep for
  the process lifetime and tees the console; arguments passed unchanged.)
- Started Tuesday 2026-10-13 09:24:13 UTC, inside the market window (next
  closure Tuesday 20:45 UTC). Gate ended 09:37:01 UTC (gate_summary.json `utc`
  2026-10-13T09:37:01.0310353Z). Evidence dir: `evidence\owner_gate\20261013-092414`
- MT5 (terminal64, metaeditor64, metatester64) was not running and
  `git status --porcelain` was empty before the gate started. The gate was not
  interrupted.
- Wall-clock gap check (consecutive `steps[].utc` in every run.json): max gap
  restart 90 s, netting 36 s, hedging 25 s -- all under 5 minutes. `suspended`
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
- EURUSD.G2: **`created_fresh`** (as the owner expected after deleting the
  symbol), `stage=complete`, `n_bars=5760`, dataset hash
  `59cd339f6ebd2070ffa726c9b4dbaf6074ef232fd2a391afcacb8c3e8bf3dd79` == manifest.

## Stages 9 and 10

- Stage 9 **produced the archive manifest**: `archive_manifest.json`
  sha256 `1db44f20b2edf73471b9dc95d662e8aa7374579a4dd99a6d1530827b0c699583`
  ("evidence bound by owner_evidence_bind.py (no hand-typed hash); scope: bar models").
- Stage 10 **produced the certificate**: `certificate/certificate.json`
  sha256 `0d6f87d284630061e87522e7727717457770648143f9e97d26d0d73422e32ce6`,
  `certificate/certificate.md` sha256
  `093c9f07fe07200bd6db9fd54d7d13f1942221bfccd0665af590f8f64c19aebd`.
  Verdict MT5_VALIDATED_BAR_MODELS, scope bar models, source commit ab312d5.
  The certificate states it makes no profitability claim.

## Demo harness (stage 7)

All three runs `status=COMPLETED`, `restore.ok=true`, ex5_sha256
`26fd36a90a62ddaa3ab2fa47c686a2ba85432389b1a8ba4c5b54a8596cec276b` for all three
(this run's stage-1 EX5). Harness: restart=exit 0, netting=exit 0, hedging=exit 0.
- restart 09:28:18 - 09:31:08 UTC, netting 09:31:09 - 09:32:13 UTC,
  hedging 09:32:15 - 09:33:07 UTC.
- No `WAITING_SYMBOL` line appears in any demo EA log of this run, and no run
  was suspended: the SPEC-WAIT-2 wait path and the HARNESS-SUSPEND-1 abort path
  were not exercised by this run (they were not needed, not proven).

## Leftover demo positions

Checked before the run, no trading done by the runner:
- hedging: gate_run58's terminal journal (09:04 UTC) reported
  `terminal synchronized ...: 0 positions, 0 orders`.
- netting: last known state gate_run57 `SNAPSHOT after_cleanup ... positions=[]`
  (not queried live before this run).
- After this run: every demo EA log ends with `SNAPSHOT after_cleanup ...
  own_positions=0 registry=0 positions=[]` (restart, netting, hedging).

## Failing-stage journal lines

None: no stage failed.

## Leak check

Every file in `reports/gate_run59/` scanned for the demo logins and passwords
(raw and UTF-16) after this file's final edit: see "Leak check result" below.

Leak check result: 34 files scanned, **0 hits**.
