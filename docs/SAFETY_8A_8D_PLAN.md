# Safety sub-checks 8a-8d — plan and status

Owner authorization (2026-10-06): `mql5/Experts/Mql5Bot/` may get
test-only inputs, default OFF. At their defaults the existing gold legs
must behave byte-identically. Nothing here is MT5 evidence until a gate run
produces it. Status: **built, unit-tested, never run live**.

## a. What the verifier requires

`owner_gate.verify_safety`, for each of the six `SAFETY_TESTS` plus netting
and hedging:

- **Path.** `safety/<name>.json` (`kill_switch`, `risk_veto`,
  `meta_reduce`, `sl_verify`, `lost_response`, `restart`, `netting`,
  `hedging`).
- **Fields.** All non-empty and never `PENDING_OWNER`:
  - `action`
  - `initial_state`
  - `resulting_state`
  - `observed_result`
  - `expected_result` (new, SAFETY-RESULT-1)
  - `raw_evidence`
- **`raw_evidence` binding.** `{path, sha256}` inside the package, with
  bytes equal to the hash. It must not be a screenshot, a bare path or
  prose.
- **Archive manifest.** Every `safety/*.json` is a required, hash-bound
  artifact.
- **Pass rule (new).** A file is VALID only when
  `observed_result == expected_result`. Before this change any
  `observed_result`, even a failure, was VALID.
- **Hedging exception.** Only `hedging` may state
  `blocked_owner_environment` (an account that cannot exercise it). That
  is recorded as `BLOCKED_OWNER_ENVIRONMENT`, never a pass.
- **Verdict effect.** Any MISSING file keeps the verdict
  NOT_VERIFIED_*; any INVALID file gives NOT_VERIFIED_ARTIFACT_MISMATCH.

## b. The eight tests

Every tester leg runs in stage 8, before the package build. It uses the
first scoped gold's m1_ohlc configuration: the gold leg's own inputs plus
the test inputs. Its window is kept as `tester_safety_<test>_window.txt`.
`stage8_package` copies it to `safety/raw/<test>_window.txt`, together with
this run's gold m1_ohlc window as the baseline. `mql5bot.safety_legs` then
grades it into `safety/<test>.json`.

A trigger that never fired, or a baseline with nothing to block, is
recorded as `INCONCLUSIVE_*` / `NOT_*`. That never passes.

| test | MT5 scenario | where | inputs / fault injection | evidence | stage |
|---|---|---|---|---|---|
| kill_switch (8a) | latch the kill switch after the first entry, keep feeding the fixture | **Strategy Tester** | `InpTestKillSwitchAfterEntries=1` (test-only): `TripKillSwitch(REASON_MANUAL)` + a `TEST 8a kill switch: LATCHED …` line | `ZERO_NEW_ORDERS_WHILE_LATCHED`: no `instant … sl:` request after the latch, while the baseline has entries after that time | 8 |
| risk_veto (8a) | daily-loss halt on the fixture | **Strategy Tester** | `InpDailyLossPct=0.5` (production input; no test hook) | `ENTRIES_VETOED_FOR_THE_DAY`: after `DAILY LOSS LIMIT HIT`, no entry request that server day, while the baseline has one | 8 |
| meta_reduce (8a) | Meta scale 0.5 with no allocation file | **Strategy Tester** | `InpBaseGateWeight=0.5` (production) + `InpTestSafetyLog=true` (test-only: logs risk-approved vs final lots) | `ALL_SIZES_LE_RISK_APPROVED`: every final ≤ approved, at least one reduced, and the sent volume = final | 8 |
| sl_verify (8c) | a secured position loses its SL | **Strategy Tester** | `InpTestStripSlEntries=3` (test-only): `PositionModify(sl=0)` on the first 3 secured positions; reports from `POSITION_SL` when the EA's protection (ProtectManagedPositions → SlGuard) restores it | `SL_STRIPPED_AND_RESTORED`: every applied strip is restored (closed-first is not counted) | 8 |
| lost_response (8c) | ambiguous order result (TIMEOUT / lost response) → adoption before retry | **demo** (or tester with a TradeManager.mqh injection, outside today's authorization) | needs a fault in `Include/Mql5Bot/TradeManager.mqh`; the tester always answers | journal: adoption/retry, attempt cap, backoff, no duplicate exposure | owner, on demo |
| restart (8b) | restart the EA during a pending execution, an active retry, an open position, and an allocation poll | **demo** | none: a real EA/terminal restart; the tester cannot restart an EA | state reload line, unchanged magic, no duplicate exposure, orphan pendings cancelled/adopted | owner, on demo |
| netting (8d) | gold leg on a NETTING account with opposite signals | **demo account** (netting) | none; the tester takes the account's margin mode, and gate_run35's account is hedging | journal: net flips, one position per symbol | owner, netting account |
| hedging (8d) | independent positions, own magic/tickets | **demo** (hedging) | two EA instances with different magics; the tester runs one EA, and this EA holds one position at a time | independent tickets, no cross-contamination; or `blocked_owner_environment` | owner, on demo |

**Tester-only (implemented):** kill_switch, risk_veto, meta_reduce,
sl_verify.

**Demo-only (not implemented; stay MISSING):** lost_response, restart,
netting, hedging. Stage 8 therefore keeps FAILING until those four exist,
even if all four tester legs pass.

## c. Default-OFF guarantee

- **Hook guards.** Each hook runs only behind its input:
  - `if(InpTestStripSlEntries > 0) TestSlStripPump();`
  - `if(InpTestKillSwitchAfterEntries > 0) { … }`
  - `if(InpTestSafetyLog) g_log.Info(…)`

  At the defaults (0 / 0 / false) none of them runs or touches state.
  `tests/test_safety_legs.py` pins these guards in the source.
- **Tester .ini.** `EA_INPUT_DEFAULTS` mirrors the three inputs at their
  defaults. A gold leg's .ini therefore lists them as `0/0/false`.
- **Compile.** MQL5 cannot be compiled on the Mac. The strict 0/0 compile
  of the edited EA is the owner's stage 1.

## Known risks (unmeasured until a gate run)

- **OnTimer in the tester.** The risk_veto halt and the sl_verify pump run
  in `OnTimer`, which the tester simulates. If it does not fire, these
  legs grade `NOT_TRIGGERED` / `NOT_STRIPPED`, which is a recorded
  failure, never a pass.
- **0.5% may not trip.** A daily loss of 0.5% may not occur on the fixture.
  The leg then grades `NOT_TRIGGERED`, and the value is the owner's to
  change.
- **Leaked HALT.** The kill switch is persisted via GlobalVariables. In the
  tester those are per run, but if the HALT leaked into a later leg that
  leg would show it: `engine NOT in NORMAL state at startup`.
