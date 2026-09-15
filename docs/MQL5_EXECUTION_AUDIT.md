# MQL5 EXECUTION AUDIT — Mission 3 / AEGIS Phase 2

Source-level audit of every trade path in `mql5/` against the five-stage
contract **REQUEST → RESULT → VERIFICATION → RECOVERY → FAILURE**. This is a
code audit, not a live-behaviour certification: MT5 compile and Strategy
Tester evidence remain owner-gated (Phase 4). Source-structure claims below
are pinned by `tests/test_mql5_sources.py`; compile status is **NOT RUN** in
this sandbox.

Sources audited (commit `0bf5724` + this phase's fix):
`Mql5Bot.mq5` (939→952 lines), `TradeManager.mqh` (796→810), `RetryQueue.mqh`,
`SlGuard.mqh`, `RiskManager.mqh`, `SymbolSpec.mqh`, `StateStore.mqh`,
`Allocation.mqh`, `PositionGuard.mqh`, `Config.mqh`, `MagicMap.mqh`,
`Session.mqh`, `Telemetry.mqh`, `Logger.mqh`.

---

## 0. Global execution rules (verified by audit + tests)

| Rule | Evidence | Pin |
|---|---|---|
| **No `Sleep()` anywhere in EA sources** | grep over `*.mq5`/`*.mqh`: zero occurrences; all waiting is event-driven (`OnTimer` 1 s pump, `OnNewBar`) | `test_s3_no_sleep_calls_anywhere_in_ea_sources` |
| **No unbounded retry loop** | every send is single-attempt; retryables go to `CRetryQueue` (hard attempt cap `maxAttempts`, exponential backoff 0.5 s→10 s cap, dedupe keeps the counter, `maxItems=8` per timer tick, queue-full ⇒ drop + log) | `test_retry_queue_uses_exponential_backoff_and_timer_pump`; `Config` `IsRetryableRetcode` = {REQUOTE, PRICE_CHANGED, PRICE_OFF, TIMEOUT} — real MQL5 codes only (2026-09-08 correction, `DECISIONS.md`: the earlier RETRY/NO_QUOTES entries were identifiers that do not exist in MQL5) |
| **Every entry passes the Risk Engine** | `OnNewBar` sizes ONLY via `g_risk.GetLots(...)`; `slPrice<=0` ⇒ `"missing stop"` ⇒ 0 lots ⇒ no order. Meta seam runs AFTER sizing and can only shrink (floor-and-drop) | `test_ea_wires_allocation_as_reduce_only_sizing_seam`; INV-STOP-1, INV-RISK-3 |
| **Validated SL on every position** | orders carry SL computed from the risk distance (`MarketChain`/`PlacePendingOnce` clamp to `MinStopDist`, tick-grid rounded, correct side); post-fill `CSlGuard` verify→modify→close→escalate; escalation trips the kill switch | `test_s1_*`; INV-STOP-2 |
| **Restart-auditable** | hot state (engine state/reason/day-key/day-start/peak) via GlobalVariables + `HotStateLoad`; ticket registry journal (`delete-then-write`, no ghost resurrection); unknown positions adopted (`SyncRecords`), orphan pendings cancelled once per init (with bounded retry — finding F-1), SlGuard re-verifies adopted positions | `test_s2_*`; StateStore delete-then-write comment |
| **Broker facts queried, never assumed** | `BuildSymbolSpec` snapshots `SymbolInfo*`/stops/freeze at runtime; margin via `OrderCalcMargin`; trading-enabled checks gate `OnInit` (tester exempt) | `test_s4_*` |

Retcode classification (`Config.mqh`): success = {DONE, DONE_PARTIAL, PLACED};
retryable = {REQUOTE (10004), PRICE_CHANGED (10020), PRICE_OFF (10021),
TIMEOUT (10012)} — corrected 2026-09-08 against the real MQL5 retcode
table (`DECISIONS.md`); everything else is a **final rejection**
(logged, never retried).

---

## 1. Path A — Market entry (`OnNewBar` → `OpenMarket` → `MarketChain`)

| Stage | Behaviour (source) |
|---|---|
| REQUEST | `OnNewBar` gates: `AllowsNewTrades` ∧ ¬daily/kill ∧ spread OK ∧ no pending/queued work ∧ trade-mode allows ∧ session OK ∧ signal valid ∧ exposure flat. Size = `GetLots` (risk budget / loss-per-lot, floored to grid, capped by maxLots/volumeMax/volumeLimit, margin-checked via `OrderCalcMargin` with one exact linear down-scale + bounded 500-step walk, else refuse). Meta scale AFTER risk, reduce-only; below broker min ⇒ **no trade** (never min-bump). |
| RESULT | `SendDealOnce` measures latency (`GetTickCount64`), returns `res.retcode` even when `OrderSend` returns false. |
| VERIFICATION | success ⇒ slippage measured vs request (`SlippageOf`), structured `EXEC|open` audit line. `TIMEOUT`/`RETRY` ⇒ **`FindRecentDeal(magic, comment, 30 s)` before any re-send** — if the fill already landed, no duplicate is sent (duplicate-prevention). |
| RECOVERY | REQUOTE ⇒ exactly ONE immediate re-send with refreshed price/SL/TP; INVALID_FILL ⇒ bounded FOK→IOC→RETURN chain (≤ 3 sends total per call); other retryables ⇒ `QueueOpen` (backoff, fresh prices, attempt cap), entry logged `open_queued`. |
| FAILURE | final rejection ⇒ `open_rejected` audit line, no trade. Queue give-up ⇒ `open_retry_giveup` audit line. Post-fill SL: `SlGuard.Enqueue` (desired SL/TP) — unprotectable positions are closed, then engine pauses. |

## 2. Path B — Pending entry (`OpenPending` / `PlacePendingOnce` / `OnBar` expiry)

REQUEST: stop order offset = max(input offset, broker stops level) so it can
never be placed inside INVALID_STOPS; SL/TP attached at placement (clamped,
tick-rounded). RESULT: `DONE`/`PLACED` ⇒ `pending_placed` audit. VERIFICATION:
`OnBar` per bar: ticket gone ⇒ filled (position adopted by `SyncRecords` +
SlGuard) or cancelled. RECOVERY: retryable ⇒ `RETRY_ACTION_PENDING` queue.
FAILURE: attempt-cap give-up (`pending_retry_giveup`); expiry after
`InpPendingExpireBars` ⇒ `CancelPending` (queued retry on retryable failure).
One pending at a time (`m_pendingTicket` guard).

## 3. Path C — Close (`ClosePosition` → `CloseOnce`)

REQUEST: opposite deal on the position ticket, comment `mql5bot-close-N`.
RESULT: retcode + latency. VERIFICATION: `PositionSelectByTicket` first —
**already gone ⇒ success** (idempotent); TIMEOUT/RETRY ⇒ re-check: gone ⇒ done
(closed meanwhile). RECOVERY: retryable ⇒ `QueueClose`; queued closes re-check
existence per attempt (no double-close). FAILURE: fatal retcode ⇒ log + return
false (caller logs; kill-switch path re-attempts on its bounded cadence:
`g_tickCounter % 10`). Partial closes use the same path with explicit volume.

## 4. Path D — SL/TP modify (`ModifySLTP` → `ModifyOnce`)

REQUEST: `TRADE_ACTION_SLTP` on the ticket. RESULT: retcode. VERIFICATION:
position-gone ⇒ success (nothing to modify). RECOVERY: retryable ⇒
`QueueModify`. FAILURE: `NO_CHANGES` and `INVALID_STOPS` are accepted as
terminal without spamming; others logged. SlGuard supervises the outcome: a
modify that never lands ends in the close path (phase 1 → phase 2 ladder,
8/15/20-pump bounds).

## 5. Path E — Pending cancel (`CancelPending`, orphan scan `CancelOrphanPendings`)

REQUEST: `TRADE_ACTION_REMOVE`. RESULT: retcode. VERIFICATION: DONE ⇒ cleared.
RECOVERY: own pending ⇒ queued `RETRY_ACTION_CANCEL`; **orphan scan (F-1,
fixed this phase): retryable failure now calls `g_trade.QueueCancelByTicket(t)`
instead of only logging** — attempt-capped, deduped, backoff. FAILURE:
give-up logged; residual risk documented in F-1 (fill still yields a stopped
or guard-protected position).

## 6. Path F — SlGuard supervision (`SlGuard.mqh`, pumped from `OnTimer`)

Verify (`SlVerdict`: MISSING / WRONG_SIDE / TOO_CLOSE / NOT_FOUND / OK) →
one modify (phase 0→1) → close (phase 1→2, ≥8 pumps) → escalate (>20 pumps ⇒
`TripKillSwitch(REASON_SL_GUARD)`). Desired SL = strategy signal SL, else
structural 2×ATR fallback; neither available ⇒ close is the only remediation.
All bounded; no Sleep; ≤3 items pumped per tick.

## 7. Path G — Restart / recovery

`OnInit`: input validation (`INIT_PARAMETERS_INCORRECT`) → spec build →
trade-enabled checks → hot-state restore (explicit one-shot kill-switch reset
via `GlobalVariable` ack edge) → magic registry (FNV-1a, persisted) → ticket
registry load → retry queue clean → allocation poll. First `OnTimer`:
orphan-pending cancel scan (once, now with retry enqueue), `SyncRecords`
adopt/prune, `ProtectManagedPositions` re-enqueue SlGuard for every
unprotected managed position. Engine state that is not NORMAL is logged at
startup and enforced by `AllowsNewTrades`.

## 8. Non-trading paths

`OnTradeTransaction` (logging/telemetry only — never trades),
`Telemetry` (WebRequest, 2 s timeout, default OFF, non-trading thread
context on the timer — a hung webhook delays at most `m_timeoutMs`),
`Logger` (file, flushed on deinit).

---

## 9. Findings

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| F-1 | MEDIUM (fixed this phase) | `CancelOrphanPendings` was single-shot: a retryable cancel failure only logged, and the scan never re-ran — an orphan pending could stay live with no expiry tracking (the `OnBar` expiry loop is lost after restart because `m_pendingTicket==0`). Mitigations existed (pending carries SL/TP from placement; fill ⇒ adoption + SlGuard), but abandonment was silent. | **FIXED**: retryable failures enqueue `RETRY_ACTION_CANCEL` via new `CTradeManager::QueueCancelByTicket` (attempt cap, dedupe, backoff). Pinned by `test_orphan_pending_cancel_retries_via_bounded_queue`. Residual: if the queue gives up (≥ attempt cap of persistent retryables), the pending may fill; the fill still produces a stopped position (SL attached at placement) or — if SL was stripped server-side — a guard-protected/close-enforced one. Compile verification owner-gated. |
| F-2 | LOW (accepted) | `OnNewBar` flip handling closes the opposite position and waits for the NEXT bar to enter — intentional one-bar latency, prevents same-bar flip races. | Documented; no action. |
| F-3 | LOW (accepted) | Kill-switch close-all retries on a `tickCounter % 10` cadence, not per tick — bounded by design to keep the timer tick bounded; RetryQueue already backs off per attempt. | Documented; no action. |
| F-4 | INFO | Static source tests pin structure, not compiled behaviour. MQL5 compile + Strategy Tester remain owner-gated (Phase 4: MT5 TRUTH = OWNER ONLY). | Phase 4. |

## 10. Exit gate — Phase 2

- [x] Every path mapped REQUEST→RESULT→VERIFICATION→RECOVERY→FAILURE (§1–§7).
- [x] Zero unsafe unbounded retries (§0; RetryQueue caps everywhere; F-1 fixed).
- [x] No `Sleep` in the trading path (grep + pinned test).
- [x] Every entry passes the Risk Engine (sizing-only seam; reduce-only; pinned).
- [x] Validated SL: placement clamp + SlGuard verify→modify→close→escalate.
- [x] Restart-auditable: hot state + ticket registry + adoption + re-verify.
- [x] Findings listed with severity and disposition (§9); F-1 fixed with test.
- [ ] Owner-gated (NOT VERIFIED here): MT5 compile 0 errors, Strategy Tester run.
