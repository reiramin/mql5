# gate_run29 — the one MISSING_IN_MT5: python short 0.02 at 2024-01-02T08:08

Run: gate_run29, HEAD 5392cc4, `-Golds gold2`, re-anchored frozen inputs.
Both log-sourced legs (m1_ohlc, every_tick) report it identically:
74 deals → 37 entries PAIRED_BY_TIME, **1 MISSING_IN_MT5**, 0 EXTRA_IN_MT5.

> python: `entry 2024-01-02T08:08:00 short 0.02 lots` (signal bar 08:07)
> mt5: `MISSING_IN_MT5: no entry deal at minute 2024-01-02T08:08`

Analysis only. **Nothing was changed** to resolve it: the event stays a
MISSING_IN_MT5 divergence in the package (stage8_package now also records,
beside it, that the window-basis re-run does not enter there; see §4).

Labels: **MEASURED** = read from a committed file or a gate_run29 file, with
the source named. **INFERRED** = a conclusion drawn from measured facts.

## 1. What python says around 08:00–08:08

**MEASURED — `artifacts/gold_2/python_trace.json` bars** (desired_position):
`-1` on every bar from 2024-01-02T08:00 through 08:09 and beyond (0 at
07:58/07:59). The signal goes 0 → −1 once, at 08:00, and does not change.

**MEASURED — `artifacts/gold_2/python_trace.json` trades** (the frozen run):
there is **no** trade entering at 08:01. The first 2024-01-02 trade is

| entry | side | lots | exit | exit_reason | pnl |
|---|---|---|---|---|---|
| 2024-01-02T08:08 | short | 0.01 | 2024-01-02T08:45 | signal_exit | −0.47 |

So the 08:01 position was **not** closed at 08:07: in the frozen run no
08:01 position ever existed.

**MEASURED — `artifacts/gold_2/expected_execution.json` entries:**

| signal_time | entry_kind | approved_lots | sizing_basis | meta 0.5 | meta 1.0 |
|---|---|---|---|---|---|
| 08:00 | signal_transition | 0.01 | 9085.75 | DROP 0.0 | SEND 0.01 |
| 08:07 | persistence_reentry | 0.02 | 9085.75 | SEND 0.01 | SEND 0.02 |

**MEASURED — engine events** of the frozen-schedule run. The run uses the
generator's own `META_SCHEDULE`, which puts the 2024-01-02 weight at 0.5.
It reproduces the frozen trace trade for trade; the builder's
`window_basis_volumes` self-check asserts this. The events are:

- 08:01, 08:02, … 08:07: `reject meta_scale_dropped lots 0.01` (7 bars)
- 08:08: `open lots 0.01 side -1 meta_weight 0.5`

**MEASURED — `tools/build_gold2_standard.py`** (the frozen generator)
defines `persistence_reentry` rows from the frozen run's own trades: an
entry at bar i+1 where the desired side did not change at bar i
(`s[i] == s[i-1]`).

**INFERRED (follows directly from the four facts above).** On 2024-01-02
the generator's meta weight is 0.5. At 08:00 the risk approval was 0.01
lots, because ATR was large: stop_distance 0.0701. Then 0.01 × 0.5 = 0.005,
which floors to 0 below volume_min. The engine DROPPED the entry and stayed
flat. While flat with desired = −1, it retried every bar. At signal bar
08:07 the ATR had decayed (stop 0.0423), approval was 0.02, and
0.02 × 0.5 = 0.01 was sendable, so it entered at 08:08. The 08:07
`persistence_reentry` row exists **only because of the 0.5-weight drop**.
Its `meta["1.0"]` = 0.02 is the weight-1.0 size of an entry that only
happens at weight 0.5.

## 2. What the EA does

**MEASURED — gate_run29 m1_ohlc log trades** (byte copy in
`tests/data/owner_gate/gate_run29_gold2_m1_ohlc_log_trades.json`):

- deal #2 `sell 0.01 EURUSD.G2 at 1.09589`, 2024.01.02 08:01:00 (entry, pnl 0)
- deal #3 `buy 0.01 EURUSD.G2 at 1.09705`, 2024.01.02 08:45:00 (close, pnl −1.16)
- deal #4 `buy 0.28 … at 1.09727`, 2024.01.02 08:46:00 (next entry)

So the EA's 08:01 short **was still open at 08:08**. Nothing happened
between 08:01 and 08:45.

**MEASURED — `mql5/Experts/Mql5Bot/Mql5Bot.mq5` `OnNewBar`** (read, not
modified): `int exposure = CurrentExposure(); if(exposure == desired)
return;` (line 997). If the desired side equals the open exposure, the EA
does nothing: one position, no same-side add or re-entry.

**MEASURED — gate_run29 `tester_gold2_m1_ohlc.ini`:** `InpBaseGateWeight=1.0`.
No allocation file is staged. The tester runs at weight 1.0, so the 0.01
approval at 08:01 is sent (it is not dropped as at 0.5).

## 3. Python at the tester weight agrees with the EA

**MEASURED — the window-basis re-run** (`stage8_package.window_basis_
volumes`). It is the frozen generator's engine (config_hash equal to the
manifest), at weight 1.0, flat before the measured 2024-01-02 start, from
equity_start 10000. Its first trades are:

| entry | side | lots | exit | exit_reason | pnl |
|---|---|---|---|---|---|
| 2024-01-02T08:01 | short | 0.01 | 08:45 | signal_exit | −1.17 |
| 2024-01-02T08:46 | long | 0.28 | 09:12 | signal_exit | −14.28 |

It has **no entry at 08:08**. Its trade sequence matches MT5's at the first
entries: 08:01 short 0.01 held until 08:45, then 08:46 long 0.28. MT5's
deal #3 pnl is −1.16 against python's −1.17. That difference is the fill
model: python pays mid ± 1.5 points per side, MT5 fills at bid / bid + 2
points.

## 4. Verdict and recommendation

**Measured.** The EA was short 0.01 from 08:01 to 08:45 and correctly did
nothing at 08:08: same side, already open. Python's frozen run never held an
08:01 position. Its 08:08 entry is a re-entry after seven
`meta_scale_dropped` bars, caused by the 2024-01-02 weight 0.5. At the
weight the tester applies (1.0), python itself does not enter at 08:08.

**Inferred.** The divergence is not an EA defect. It is a **python-side
comparison-column defect**. `expected_execution.json` takes its entry ROWS
from the scheduled-weight run but its compared VOLUME from the weight-1.0
meta column. A row that exists only because of a weight < 1 drop
(`persistence_reentry` after `meta_scale_dropped`) is not an expected entry
of a weight-1.0 tester leg.

**Recommendation: the python side must change; the EA must not.** Two
options, both owner decisions:

1. Take the tester comparison's expected entry SET from a weight-1.0 run
   (the same re-run `window_basis_volumes` already performs and
   self-checks), not from the scheduled-weight trace. The 08:08 row would
   then not be expected.
2. Or regenerate `artifacts/gold_2` so expected_execution carries a
   per-weight entry set (scoped exception; frozen artifacts and the anchor
   would change).

Not done here, by instruction. The event stays MISSING_IN_MT5 and keeps
counting as a divergence. The package now records
`window_basis_run_entered_here: false` beside it, as information only.
That field changes no classification.
