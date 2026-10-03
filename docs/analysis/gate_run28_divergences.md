# gate_run28 divergence analysis (HEAD 999126a, `-Golds gold2`, time-paired reconciliation)

Read-only analysis. Nothing in `mql5/`, `artifacts/` or any frozen input was
changed. Every claim is labelled **MEASURED** (a file/line or a locally
re-run frozen artifact) or **INFERRED** (consistent with the measurements but
needing named run evidence to confirm). The gate_run28 package itself is on
the owner terminal, not on this machine: the run28 lines below are quoted
from the owner's report of that run.

## Evidence (gate_run28, as reported)

> every_tick model: 26 PAIRED_BY_TIME, 60 MISSING_IN_MT5, 48 EXTRA_IN_MT5,
> 38 OUT_OF_TESTED_WINDOW.
>
> - Paired events agree on entry_side and entry_price exactly (e.g.
>   2024-01-02T08:01 sell 1.09589/1.09589; 2024-01-03T08:01 buy
>   1.09967/1.09969). Volumes drift: python 4.58 vs mt5 4.42, 4.58/4.34,
>   4.57/4.27 ... growing through the day.
> - Day 2 pattern: python entry 09:12 short 0.89 -> MISSING_IN_MT5; mt5
>   EXTRA entry deal #6 at 09:13. python 09:41 -> mt5 09:42; 10:12 ->
>   10:13; 10:41 -> 10:42; ... every signal-flip entry is one M1 bar later
>   in MT5. First-of-day entries (08:01, 08:46) pair exactly.
> - Day 3: python has extra long entries at 09:07, 09:21(short), 09:44,
>   10:30, 11:16, 12:02 ... that MT5 never took, while the 46-minute sell
>   sequence (10:08, 10:54, 11:40 ...) pairs.
> - 5 python entries on 2024-01-04 are MISSING_IN_MT5 but the MT5 test
>   ended at 2024.01.04 00:00 (ToDate exclusive): those are
>   OUT_OF_TESTED_WINDOW, not missing.

The 2024-01-04 item is a pairer defect, fixed in this PR (window END applied;
`python/mql5bot/stage8_package.py`, `reconciliation_events` /
`_build_reconciliation`): python entries at/after the tester ToDate
(exclusive; derived from the fixture by `mt5tester.fixture_date_range`, the
same derivation the gate's tester config uses — `tools/owner_gate.ps1:949`)
are now OUT_OF_TESTED_WINDOW, never MISSING_IN_MT5. MEASURED side note: the
python reference itself holds **zero** positions on 2024-01-04 (meta weight
0.0 that day — see §3; `artifacts/gold_2/python_trace.json` has no day-4
trade), so those five rows were risk *approvals*, not python trades.

---

## 1. The one-bar-late flip entry

**MEASURED — EA.** The EA acts once per bar: `OnTick` fires `OnNewBar()` only
when `iTime` changes (`mql5/Experts/Mql5Bot/Mql5Bot.mq5:1091-1100`). In
`OnNewBar`, when the desired direction opposes the open exposure it closes
and **returns** — the comment states the intent:

- `Mql5Bot.mq5:999-1004` — `if(exposure != 0) { // flip: close current, let
  the next bar open the new direction … CloseAllPositions("signal_flip");
  return; }`

So a flip consumes one whole bar: close at bar N, entry at bar N+1 (the next
`OnNewBar`). This is also the traced execution order in
`docs/AEGIS_REALITY_GATE_CONTINUATION.md:318` ("exposure compare → flip =
close opposite, enter next bar").

**MEASURED — python.** The engine's `reconcile(bar)`
(`python/mql5bot/engine.py:854-904`) closes the opposite book
(`engine.py:872-874`, `REASON_SIGNAL_EXIT`) and then, in the same call at the
same bar open, sizes and opens the new side (`engine.py:879-904`,
`open_order`). The frozen trace shows it: every day-3 flip's `exit_time`
equals the next trade's entry minute (`artifacts/gold_2/python_trace.json`,
e.g. short 08:32 exits `signal_exit` at 09:07:00 and the long enters at
09:07:00).

**MEASURED — what the contract says.** `artifacts/gold_2/manifest.json`
`signal_timing_contract` (written by `tools/build_gold2_standard.py:787`):

- `"action_at": "next bar open (EA: first tick of new bar)"`
- `"flip_rule": "close opposite (signal_exit); enter next bar"`

Read literally, `flip_rule` adds a clause beyond `action_at`: the close
happens at the action bar and the new entry **one bar later**. If "enter
next bar" merely restated "next bar open after the signal" it would be
redundant with `action_at`; a contract clause is read to add meaning. Under
that reading the **EA matches the contract and the python engine does not**.
The opposite reading (both actions at the signal's next bar open, python
behaviour) cannot be ruled out from the wording alone — the same tool that
wrote the clause (`build_gold2_standard.py`) also built the same-bar
expectation, so the artifact contradicts its own manifest under the literal
reading.

**Run28 fit (reported evidence).** Day-2: every flip entry is exactly one M1
bar later in MT5 (09:12→09:13, 09:41→09:42, 10:12→10:13, 10:41→10:42), while
first-of-day entries — which are not flips (EA exposure 0, no close-return
detour) — pair exactly. That is precisely the signature of the measured code
difference.

**Recommendation (no change made here).** Change the **python engine** (and
regenerate the gold artifacts under owner authorization — they are frozen):
defer the flip's new entry one bar so engine, trace, expectation and EA all
satisfy the contract as written. Rationale: the EA already implements the
literal `flip_rule`; changing python avoids another scoped `mql5/` exception,
and the contract text needs no rewording. The alternative (declare same-bar
the intent, reword `flip_rule`, change the EA in the planned scoped `mql5/`
PR) is viable but costs an `mql5/` change *and* a contract rewrite. Either
way the gold artifacts must be regenerated or re-blessed by the owner —
`artifacts/` is frozen and is NOT touched by this PR.

---

## 2. The missed day-3 long entries

**MEASURED — the python side of those events.**
`artifacts/gold_2/python_trace.json` day-3 is a strict single-position
alternation (netting): long 09:07→signal_exit 09:21, short 09:21→09:44, long
09:44→10:08, short 10:08→10:30, long 10:30→10:54 … Python does NOT hold
those as parallel/separate positions; each flip closes the previous book at
the same minute the next opens. (This answers the "separate positions while
the EA holds one" question: no — both sides are one-position-at-a-time;
`engine.py:854-874`, `Mql5Bot.mq5:996-997` `if(exposure == desired) return;`.)

**MEASURED — the desired-position series is sustained, not a pulse.**
Re-running the python DSL runtime over the frozen fixture
(`mql5bot.dsl.runtime.desired_positions`, `examples/strategies/
gold2_multifactor.json`, `artifacts/gold_2/gold2_fixture.csv`) gives, for
day-3 09:00–10:20, transitions −1→+1 at 09:06, +1→−1 at 09:20, −1→+1 at
09:43, +1→−1 at 10:07 — desired is +1 for 14 consecutive bars (09:06–09:19).
A momentary trigger cannot explain the misses: the latched state (python
`dsl/runtime.py` state mode; EA `mql5/Include/Mql5Bot/DslRuntime.mqh:303-313`
— the SAME latch algorithm) holds the long for 14 minutes.

**MEASURED — the checks the task names, none of which blocks a long:**

- `InpDslBars=500` history depth: the EA refuses a bundle only when
  `InpDslBars < 10 × longest period` (`Mql5Bot.mq5:602-607`); longest period
  here is 21 (EMA 21; RSI 14; HIGHEST/LOWEST 20) → threshold 210 < 500, and
  the init floor is 32 (`Mql5Bot.mq5:470-472`). Seeding-tail bound: EMA(21)
  re-seeded 500 bars back differs from a full-history EMA by a factor
  (20/22)^500 ≈ 2·10⁻²¹ of the seed gap; RSI(14) Wilder smoothing decays as
  (13/14)^486 ≈ 2·10⁻¹⁶. HIGHEST/LOWEST(20) are window-local and exact.
  Those tails are ~11 orders of magnitude below the 5-decimal price grid —
  **window depth and indicator seeding cannot flip a GT/LT comparison here**
  unless the two EMAs are equal to ~10⁻¹⁶, which the fixture's engineered
  zig-zags do not produce.
- Session filter: identical window on both sides — python applies
  `[08:00, 16:00)` via `_apply_filters` (`python/mql5bot/dsl/runtime.py:280`),
  the EA the same spec session in `ApplyFilters`
  (`DslRuntime.mqh:327` ff.) plus the `OnNewBar` session gate
  (`Mql5Bot.mq5:961-962`). 09:07–12:02 are inside the session.
- Max-position / already-in-position: both sides hold at most one net
  position and skip when `exposure == desired`
  (`Mql5Bot.mq5:996-997`; `engine.py:866-868`). This explains a missing
  *entry deal* only while the EA is already on that side.

**INFERRED — the two candidate mechanisms (run29 must discriminate).** Given
the desired series is sustained, the EA should enter the flip side one bar
late (§1). Two readings of "MT5 never took the longs" remain:

1. **MT5 took them one bar late, as EXTRA events** (09:08, 09:45, 10:31 …)
   — the same signature as day-2, just not re-paired because a late entry is
   MISSING(py minute) + EXTRA(py minute + 1). Run28 reports 48 EXTRA_IN_MT5
   for every_tick; if the day-3 extras sit at +1 minute of the missed longs,
   finding **1 is the single root cause** of finding 2. CHECK: the EXTRA
   event times in `reconciliation/gold2.json` of the run28 package.
2. **The EA never computed desired=+1 / never sized the long** — requires an
   EA-side desired or sizing divergence that the bounds above make
   implausible but do not measure on the owner terminal. CHECK (run29):
   capture the EA's per-bar DSL desired (a Debug line at
   `RefreshDslSignal`, `Mql5Bot.mq5:230-249`, logs `positions[n-2]`) and the
   full deal list including exits between 08:30 and 10:08 — if the EA's long
   entered late at a worse price and was stopped out (2×ATR ≈ 10 ticks in
   the small-ATR scenes), it would be flat again before the next 46-minute
   short, which is exactly why the sell sequence (10:08, 10:54, 11:40)
   pairs on time (a flat EA enters directly, no flip-close detour).

No code change is recommended for finding 2 until that evidence exists; if
(1) confirms, the finding-1 decision resolves it too.

---

## 3. Volume drift: numbers

**MEASURED — one identical sizing rule on both sides.**
`lots = floor( 1.0% × basis / (stop_distance × 100 000) / 0.01 ) × 0.01`
(risk 1.0% and `sizing_mode risk_percent_equity`:
`artifacts/gold_2/expected_execution.json`; contract size / tick / step:
`manifest.json broker_spec`; python path `mql5bot/sizer.py` via
`engine.py:662-693`; EA path `g_risk.GetLots`, `Mql5Bot.mq5:1013`). The
frozen approvals reproduce it to ≤0.07%: 4.58 lots at basis 9174.06 over
stop 0.00020018 ⇒ implied risk 0.9994%; 4.58/9161.46/0.000200127 ⇒ 1.0005%;
4.57/9148.86/0.0002001252 ⇒ 0.9997%.

**MEASURED — the paired day-3 drift, inverted through that rule.** Implied
MT5 sizing basis = mt5_lots × stop_distance × 10⁷ (floor gives a +20.0
range):

| fill (day 3) | python lots | python basis | mt5 lots | implied MT5 basis | gap |
|---|---|---|---|---|---|
| 10:54 | 4.58 | 9174.06 | 4.42 | [8847.96, 8867.98) | ≈ −306 … −326 |
| 11:40 | 4.58 | 9161.46 | 4.34 | [8685.51, 8705.52) | ≈ −456 … −476 |
| 12:26 | 4.57 | 9148.86 | 4.27 | [8545.35, 8565.36) | ≈ −584 … −604 |

Δlots = 0.16 / 0.24 / 0.30 = 16–30 volume steps of 0.01: **a rounding or
step-rule difference cannot produce this** (one step at most). The gap grows
≈ 130–150 per 46 minutes — an equity-path divergence, not a formula
difference.

**MEASURED — why the python basis falls so slowly.** The gold-2 reference
applies a day-stepped meta allocation weight — 1.0 / 0.5 / 0.1 / 0.0 for
days 1–4 (`tools/build_gold2_standard.py:105-114`, schedule passed at
`:395`). All 56 `python_trace.json` trades equal
`floor(approved_lots × day_weight / 0.01) × 0.01` (verified locally, 56/56,
0 mismatches; day-4: zero trades). Day-3 python therefore *traded* 0.45
lots while *approving* 4.58, and its equity (`sizing_basis` series) falls
6.30 per losing flip = 14 ticks × $1/tick/lot × 0.45 lots exactly
(9174.06 → 9167.76 → 9161.46 …).

**MEASURED — why the EA's cannot.** In the tester no `allocation.json`
exists, and a missing/malformed allocation falls back to the base gate
weight (`mql5/Include/Mql5Bot/Allocation.mqh:12-13`), with
`InpBaseGateWeight = 1.0` (`Mql5Bot.mq5:76`, applied at `:1022`). The EA
therefore trades the FULL 1% size every day.

**INFERRED — the drift is fully consistent with equity basis, nothing else.**
At weight 1.0 the same 14-tick losing flips cost the EA ≈ 4.4 lots × 14
ticks ≈ $62 per flip ≈ $124 per 46-minute pair; with the divergent extra/
missing trades on top, the observed implied-basis decline (≈130–150 per 46
min) matches. The residual attribution (exactly which MT5 deals account for
which dollars) needs the run's own numbers, which exist in the package:
`log_trades/*.json` carries per-deal `pnl` and `final_balance` — summing
them against the implied bases above is the confirmation step for run29.
**Recommendation (python/gate side, later PR; no change made here):** the
reconciliation should compare like with like — either compare MT5 volume
against the expected per-weight `meta.<w>.final_lots` for the weight in
force that day (the table is already in `expected_execution.json`), or have
the gate stage a day-stepped allocation file for the tester leg. Comparing
MT5's weight-1.0 fill against a weight-free approval while the python
equity ran at weight ≤0.5 guarantees drift even with identical engines.

---

## 4. "adopted unknown position" still fires on every entry

Reported for gate_run28, unchanged from gate_run25: every EA entry logs
`adopted unknown position … (restart recovery)` because the EA registers its
own fresh fills only through the recovery path — analysed in
`docs/analysis/gate_run25_divergences.md` §(c). The fix (record own entries
at entry) is owner-scoped `mql5/` work already queued with the SymbolSpec
exporter fields: see `docs/DECISIONS.md` **S8-SPEC-1** (exporter contract)
and the owner-decision entry of PR #14 (re-anchor deferred; one later scoped
`mql5/` PR bundles the exporter fields and the adopted-unknown fix — PR #14
is still open/CONFLICTING and must be rebased). No `mql5/` change here.
