# gate_run25: three MT5 ↔ Python divergences (gold2, read-only analysis)

Date: 2026-10-03. Branch `feat/real-ticks-not-applicable` (base `144bff7`).
No code was changed for this analysis, and nothing under `mql5/` was
touched. Every fix below is a proposal.

## What this rests on

**MT5 side.** This is only the gate_run25 lines the owner quoted in chat
(HEAD 144bff7, `-Golds gold2`). I did not have the run's evidence folder:
no window captures, no `tester_gold2_*_log_trades.json`, no per-trade MT5
timestamps. The quoted lines are:

- `start time changed to 2024.01.02 00:00 to provide data at beginning`
- m1_ohlc and every_tick: `DSL bundle loaded from common`,
  `generic DSL execution enabled: gold2_multifactor`,
  `successfully finished`, 2880 bars, quality 100%, 74 deals each, final
  balance 8069.20 / 8017.51 USD.
- First MT5 entry lots: 0.01, 0.28, 0.98, 1.48.
- Every MT5 entry logs `[WARN] adopted unknown position #N (restart recovery)`.

**Repo side.** I read these committed files directly:
`artifacts/gold_2/python_trace.json`,
`artifacts/gold_2/expected_execution.json`,
`artifacts/gold_2/gold2_fixture.csv` and the code cited below.

Labels used below:
- **MEASURED**: read from a committed file or a quoted log line.
- **CODE**: what the source says. It has not been observed running.
- **INFERRED**: my reasoning from the first two. It has not been verified.

---

## (a) MT5 starts on 2024.01.02; the Python trace trades from 2024-01-01 08:01

### Facts

- **MEASURED.** `gold2_fixture.csv` has 5760 M1 bars, from
  `2024-01-01 00:00` to `2024-01-04 23:59`. That is 4 days × 1440 bars.
  `python_trace.json` has 5760 bars and 56 trades. Counted by
  `signal_time` day: 2024-01-01 has 19, 2024-01-02 has 16, 2024-01-03 has
  21 and 2024-01-04 has 0.
- **MEASURED.** 16 + 21 = **37**. MT5 logged 74 deals, which is
  **37 round trips**.
- **MEASURED.** MT5 logged 2880 bars, which is 2 × 1440.
- **CODE.** The gate takes the tester period from the fixture's first and
  last timestamps and does not guess it:
  - `python/mql5bot/mt5tester.py:800-820` (`fixture_date_range`) returns
    `min(stamps), max(stamps)`, so the period is `2024.01.01` to
    `2024.01.04`.
  - `python/mql5bot/gate_selfcheck.py` `derive_tester_inputs` calls it.
  - `tools/owner_gate.ps1` stage 5 (`Invoke-Decide @("tester-inputs", ...)`)
    passes the period to the leg.
  - `mt5tester.py:349-350` writes it as `FromDate=` / `ToDate=`.
- **CODE.** The gate already recognises the MT5 line that moves the start
  date: `gate_selfcheck.py:959` (`_WARMUP_RESERVE_RE`). The comment at
  `gate_selfcheck.py:920-924` says MT5 reserves history before the test
  window for warm-up.

### Explanation (INFERRED)

The custom symbol's history starts exactly at FromDate (2024.01.01 00:00).
MT5 needs some history before the test window, so it moved the start
forward one day: `start time changed to 2024.01.02 ... to provide data at
beginning`. All of 2024-01-01 became pre-history and the EA never traded
on it.

The 2880 bars match 2024-01-02 plus 2024-01-03. So MT5 also appears to
treat `ToDate=2024.01.04` as the end of the 3rd, not the end of the 4th.
The Python trace has no trades on the 4th, so that end-date difference
costs no trades on this fixture.

Python trades from bar 0, after NaN warm-up. Its 19 trades on 2024-01-01
are exactly the trades MT5 did not run: 56 − 19 = 37. The day count
matches exactly. Whether each trade matches one-for-one is **not
established**, because I had no MT5 trade times.

### Consequence

Comparing the trades by position in the list (MT5 trade *k* against Python
trade *k*) compares 2024-01-02 MT5 trades with 2024-01-01 Python trades.
That comparison is invalid. Point (b) shows the effect on lot sizes.

### Proposed fixes (not implemented)

1. **Reconciliation side, preferred, no `mql5/` change.** Stage 8 should
   align on the window MT5 actually ran. That means:
   - parse the `start time changed to <date>` line and the
     `<N> bars generated` line from the leg's own window;
   - clip the Python trace and expected_execution to
     `[effective_start, effective_end)`;
   - compare by `signal_time`, never by list position.

   The clipped equity start still differs: Python enters 2024-01-02 with
   its 2024-01-01 losses, so sizing differs (see (b)). The reconciliation
   must either re-run the Python reference from the effective start with
   `equity_start` reset, or classify those fields as an expected
   equity-basis divergence. That choice belongs to the owner.
2. **Fixture side.** Give the fixture pre-history (for example, one
   leading day that is never traded) and keep FromDate at the first traded
   day. This changes the fixture, its hash, the manifest and the frozen
   inputs, so it needs a re-anchor and an owner decision.
3. **ToDate.** Pass `ToDate = last fixture day + 1` so the last day is
   included. Today it costs no trades, but it is a latent difference.

---

## (b) First lots: MT5 0.01, 0.28, 0.98, 1.48 vs expected 1.4, 1.07, 1.15, 1.5

### Facts

- **MEASURED.** In `expected_execution.json`, the first four entries
  (2024-01-01, 08:00 to 09:09) have `risk.approved_lots` 1.4, 1.07, 1.15
  and 1.5, with `sizing_basis` 10000.0 down to 9795.93.
  `python_trace.json` has the same lots for its 2024-01-01 trades.
- **MEASURED.** The 2024-01-02 entries in `expected_execution.json` are:

  | time | kind | approved lots | sizing basis |
  |---|---|---|---|
  | 08:00 | signal_transition | 0.01 | 9403.70 |
  | 08:06 | persistence_reentry | 0.02 | 9403.70 |
  | 08:45 | signal_transition | 0.26 | 9402.53 |
  | 09:11 | signal_transition | 0.89 | 9396.16 |
  | 09:40 | signal_transition | 1.36 | 9385.34 |
  | 10:11 | signal_transition | 1.48 | 9369.26 |

  The 08:00 entry has `atr_signal_bar` 0.035, so its stop distance is
  0.070. That is why the lot size is the minimum.
- **MEASURED.** The 2024-01-02 trades in `python_trace.json` have lots
  0.01 (08:07), 0.13, 0.44, 0.68, 0.74 and 0.73. From the second trade on,
  these are about **half** of the expected_execution lots for the same
  signals. There is also no trace trade for the 08:00 signal. This
  disagreement *inside the committed gold2 artifacts* is a separate open
  item. I have not explained it here.
- **CODE.** EA sizing
  (`mql5/Include/Mql5Bot/RiskManager.mqh:198-388`, `GetLots`):
  - budget = `AccountInfoDouble(ACCOUNT_EQUITY)` (`:257`) ×
    risk% / 100 (`:268`);
  - divided by loss per lot at the stop distance (tick-value loss,
    cross-checked with `OrderCalcProfit`);
  - floored to the volume step;
  - then scaled by the Meta allocation (`Mql5Bot.mq5:1022`) and floored
    again.
- **CODE.** Python sizing uses the same basis. `basis = equity[i]`, the
  signal bar's closing equity
  (`tools/build_gold2_standard.py:583-606`).

### Explanation (INFERRED)

The list-position comparison is invalid because of (a). MT5's first trade
is on 2024-01-02, so its lots belong next to the 2024-01-02 rows, not the
2024-01-01 rows.

Next to those rows, the MT5 lots follow the same pattern. They start at
the minimum (0.01) because of the 08:00 ATR spike, then ramp up as ATR
falls back: 0.28 vs 0.26, 0.98 vs 0.89, 1.48 vs 1.36 or 1.48.

One cause that fits the direction of the gap: MT5 enters 2024-01-02 with
about 10000 USD of equity because it never traded 2024-01-01. Python has
9403.70. That is a ratio of about 1.063. The MT5/expected ratios are about
1.08 to 1.10. The remaining 2–4% is not explained.

Possible extra sources I could not check without the MT5 window:
- fill-price differences (spread and slippage) change the stop distance;
- the Meta allocation weight the leg actually used;
- whether MT5's first trade is the 08:00 signal or the 08:06 re-entry.

### Proposed fixes (not implemented)

- Fix (a) first, by aligning on `signal_time` over the effective window.
  Then compare sizing on the **same equity basis**. Either re-run the
  Python reference from the effective start, or check
  `approved_lots / sizing_basis` against
  `mt5_lots / mt5_equity_at_signal`.
- Have stage 8 report `ACCOUNT_EQUITY` at each MT5 entry. The `ENTRY ...
  risk=` log line already gives risk money. Adding equity would make (b)
  something we measure instead of infer. That needs an `mql5/` log-line
  change, which needs owner authorisation.
- Explain the half-size Python trace vs expected_execution lots on
  2024-01-02 before any 2024-01-02 sizing comparison is trusted.

---

## (c) Every MT5 entry logs `adopted unknown position #N (restart recovery)`

### Facts

- **CODE.** The entry path in `mql5/Experts/Mql5Bot/Mql5Bot.mq5`:
  - `OnNewBar` sends the order through `g_trade.OpenMarket(...)` (`:1065`).
  - On `r.done || r.queued` it only queues the SL guard
    (`g_slguard.Enqueue(..., 0)`, `:1078`) and logs `ENTRY`.
  - It never adds the new ticket to `g_store`. `SOrderResult`
    (`mql5/Include/Mql5Bot/TradeManager.mqh:26-40`) has no position-ticket
    field; `orderTicket` is only for pending orders.
- **CODE.** The only code that adds an open position to `g_store` is
  `SyncRecords()` (`Mql5Bot.mq5:330-360`). It walks `PositionsTotal()`, and
  any position with our symbol and magic that is not in `g_store` is
  upserted and logged as
  `g_log.Warn("adopted unknown position #..." " (restart recovery)")`
  (`:357-358`).
- **CODE.** `SyncRecords()` is called from `OnTimer` (`:757`;
  `EventSetTimer(1)` at `:723`) and at the start of every `OnNewBar`
  (`:941`).
- **MEASURED.** The owner reports the WARN line on every MT5 entry.

### Explanation

**CODE + MEASURED.** The EA does not register the positions it opens.
After every fill, the next `SyncRecords()` finds a position of our magic
that it does not know and labels it restart recovery. The log is wrong:
these are fresh entries, not restart recoveries. The adoption itself
records the correct values from the live position: ticket, type, entry
(`POSITION_PRICE_OPEN`), openTime (`POSITION_TIME`), lots
(`POSITION_VOLUME`).

### Effect on sizing and risk (CODE, INFERRED; not measured in MT5)

**Sizing: none.**
- `GetLots` reads account equity and margin and the symbol spec. It never
  reads `g_store`.
- Exposure and flip checks (`CurrentExposure`, `CountBotPositions`) and
  `CloseAllPositions` (kill switch, daily loss, drawdown, `dsl_flat`) walk
  `PositionsTotal()`, not `g_store`.

So the late registration cannot change a lot size or block a risk exit.

**SL protection: covered, with a short gap.**
- Between the fill and the next `SyncRecords()` (at most about 1 s of
  timer time, or the next bar), the position is not in `g_store`.
  `ProtectManagedPositions()` and `ManageOpenPositions()` therefore skip
  it.
- The SL guard queued at `:1078` still covers the position in that gap.
- Max-bars timeout and breakeven/partial management start once the
  position is adopted. They use `POSITION_TIME`, so the timeout counts the
  same bars.

**Evidence and audit: real damage.**
- Stage 8c, the restart/adoption evidence, cannot tell a real restart
  recovery from an ordinary entry by this line. Every entry produces it.
- A real orphan adopted after a crash is hidden among the routine lines.
- `WARN` level on every trade lowers the signal value of WARN.

### Proposed fix (needs an owner-authorised `mql5/` change; NOT implemented)

1. After `OpenMarket` returns `done`, find the new position by magic,
   symbol and newest `POSITION_TIME`. Simpler and more robust: in
   `OnTradeTransaction`, on `DEAL_ADD` with `DEAL_ENTRY_IN` and our magic,
   select `DEAL_POSITION_ID`. Then `g_store.Upsert` the record and log
   `INFO registered new position #N`.
2. Keep the `adopted unknown position ... (restart recovery)` WARN for
   positions that really are unknown. Positions with
   `POSITION_TIME < g_initTime` are definitely restart orphans. A newer
   unknown position should be logged as a distinct anomaly, not as restart
   recovery.
3. Add a test that pins the change: one entry produces one `registered`
   line and zero `adopted` lines, and a pre-existing position at OnInit
   produces exactly one `adopted` line.

---

## Summary

| item | measured | inferred | fix location |
|---|---|---|---|
| (a) start moved to 01-02 | fixture 01-01..01-04 (5760 bars); Python 19 + 16 + 21 trades on 01-01/01-02/01-03; MT5 37 round trips and 2880 bars | MT5 used 01-01 as pre-history and treated ToDate as exclusive | stage-8 alignment (Python) or fixture pre-history (re-anchor) |
| (b) lot sizes | expected and trace lots per day; the trace is about half of expected on 01-02 | MT5 lots follow the 01-02 rows, scaled by a higher equity basis; 2–4% residual unexplained | align first; compare on the same equity basis |
| (c) adopted unknown | the code path; WARN on every entry (owner) | no sizing effect; short SL-guard-only gap; evidence pollution | `mql5/` (owner authorisation) |
