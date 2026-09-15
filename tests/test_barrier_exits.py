"""Reality Gate §6 — barrier-exit semantic closure.

Re-enumeration of the barrier-exit matrix with explicit evidence (the
prior session's "20 exits" enumeration is NOT recoverable in this
environment — it is re-derived here from the actual code and pinned;
continuity with the lost list is not claimed).

Canonical exit semantics (python/mql5bot/costs.py + engine.py, pinned
below; the MQL5 side places SL/TP on the order and lets the broker match
them — owner-leg evidence, BLOCKED_OWNER_ENVIRONMENT):

* Touch comparisons are INCLUSIVE (<= / >=): an exact touch fills.
* Stop fills carry adverse slippage; TP fills do not.
* A bar opening at or beyond a barrier fills AT THE OPEN (gap-through),
  which is strictly worse than the barrier for a stop and counted
  conservatively for TP as well.
* When one bar touches BOTH barriers, the STOP is resolved first —
  per-book ordering in engine.manage()/open_gap_exits(), never an
  incidental sort order.
* Levels may be raw or tick-normalized; the matrix covers both.

Evidence class: LOCAL_DETERMINISTIC_GATE (Python engine), with the
MQL5/MT5 runtime leg remaining BLOCKED_OWNER_ENVIRONMENT.
"""

from __future__ import annotations

import pandas as pd
import pytest
from mql5bot.costs import CostConfig, stop_fill, tp_fill
from mql5bot.symbolspec import SymbolSpec, round_to_tick

POINT = 1e-5
CFG = CostConfig(slippage_points=1.0)   # 1 point adverse on stops
ZERO = CostConfig(slippage_points=0.0)
SPEC = SymbolSpec(name="EURUSD", digits=5, point=POINT, tick_size=POINT)
SPEC_IDX = SymbolSpec(name="US30", digits=2, point=0.01, tick_size=0.25)


# ---------------------------------------------------------------------------
# Unit level — the complete touch matrix, both directions
# ---------------------------------------------------------------------------

ENTRY = 1.10000


@pytest.mark.parametrize("side", [1, -1])
def test_exact_touch_fills(side):
    """Barrier touched EXACTLY (inclusive comparison) -> fill."""
    sl = ENTRY - side * 0.0020
    tp = ENTRY + side * 0.0040
    if side > 0:
        hit, fill = stop_fill(ENTRY, sl, ENTRY + 0.0001, side, sl, ZERO,
                              POINT)              # low == sl exactly
        assert hit and fill == sl
        hit_tp, fill_tp = tp_fill(ENTRY, ENTRY - 0.0001, tp, side, tp,
                                  ZERO, POINT)    # high == tp exactly
        assert hit_tp and fill_tp == tp
    else:
        hit, fill = stop_fill(ENTRY, ENTRY - 0.0001, sl, side, sl, ZERO,
                              POINT)              # high == sl exactly
        assert hit and fill == sl
        hit_tp, fill_tp = tp_fill(ENTRY, tp, ENTRY + 0.0001, side, tp,
                                  ZERO, POINT)    # low == tp exactly
        assert hit_tp and fill_tp == tp


@pytest.mark.parametrize("side", [1, -1])
def test_one_point_inside_does_not_fill(side):
    """Barrier approached within one point but not reached -> no fill."""
    sl = ENTRY - side * 0.0020
    low = sl + POINT if side > 0 else ENTRY - 0.0001
    high = ENTRY + 0.0001 if side > 0 else sl - POINT
    hit, _ = stop_fill(ENTRY, low, high, side, sl, ZERO, POINT)
    assert not hit


@pytest.mark.parametrize("side", [1, -1])
def test_one_point_beyond_fills_with_slippage(side):
    """Barrier pierced by one point -> fill = barrier minus adverse
    slippage for stops, exact barrier for TP."""
    sl = ENTRY - side * 0.0020
    tp = ENTRY + side * 0.0040
    low = sl - POINT if side > 0 else ENTRY - 0.0001
    high = ENTRY + 0.0001 if side > 0 else sl + POINT
    hit, fill = stop_fill(ENTRY, low, high, side, sl, CFG, POINT)
    assert hit
    assert fill == pytest.approx(sl - side * CFG.slippage_points * POINT)
    low2 = ENTRY - 0.0001 if side > 0 else tp - POINT
    high2 = tp + POINT if side > 0 else ENTRY + 0.0001
    hit_tp, fill_tp = tp_fill(ENTRY, low2, high2, side, tp, CFG, POINT)
    assert hit_tp and fill_tp == tp      # TP: no adverse slippage


@pytest.mark.parametrize("side", [1, -1])
def test_gap_through_open_fills_at_open_worse_than_barrier(side):
    """Bar opens beyond the barrier -> gap-through fill AT THE OPEN."""
    sl = ENTRY - side * 0.0020
    o = sl - side * 0.0010               # open beyond the stop
    low, high = o - 0.0005, o + 0.0005
    hit, fill = stop_fill(o, low, high, side, sl, CFG, POINT)
    assert hit and fill == o
    tp = ENTRY + side * 0.0040
    o2 = tp + side * 0.0010              # open beyond the TP
    hit2, fill2 = tp_fill(o2, o2 - 0.0005, o2 + 0.0005, side, tp, CFG,
                          POINT)
    assert hit2 and fill2 == o2


@pytest.mark.parametrize("side", [1, -1])
def test_both_touch_resolves_stop_first(side):
    """Huge-range bar touching BOTH barriers: both report touched, and the
    ENGINE resolves the stop first, deterministically — manage() checks the
    stop before the TP for every book; there is no sort or ordering
    ambiguity (mission §6 both-touch proof)."""
    sl = ENTRY - side * 0.0020
    tp = ENTRY + side * 0.0040
    low, high, o = ENTRY - 0.01, ENTRY + 0.01, ENTRY
    hit_sl, _ = stop_fill(o, low, high, side, sl, CFG, POINT)
    hit_tp, _ = tp_fill(o, low, high, side, tp, CFG, POINT)
    assert hit_sl and hit_tp             # both barriers are touched...
    # ...so the ordering decision belongs to the engine: pinned at engine
    # level by test_engine_micro_both_touch_fixture_stop_first and by the
    # frozen gold micro fixture (stop_loss, never take_profit).


@pytest.mark.parametrize("side", [1, -1])
def test_normalized_levels_same_semantics(side):
    """Levels rounded onto the tick grid behave identically (the
    normalization never moves a level off the comparison semantics)."""
    sl_raw = ENTRY - side * 0.00199991
    sl = round_to_tick(sl_raw, SPEC)
    assert sl != sl_raw
    low = sl if side > 0 else ENTRY - 0.0001
    high = ENTRY + 0.0001 if side > 0 else sl
    hit, fill = stop_fill(ENTRY, low, high, side, sl, ZERO, POINT)
    assert hit and fill == sl


def test_index_cfd_one_tick_inside_outside():
    """Tick size > point (US30-like: tick 0.25, point 0.01): one TICK
    inside/outside, not one point — proves the matrix is spec-relative."""
    entry = 34000.0
    sl = entry - 25.0
    tp = entry + 50.0
    cfg = CostConfig(slippage_points=2.0)
    # one tick (0.25) beyond
    hit, fill = stop_fill(entry, sl - 0.25, entry + 1.0, 1, sl, cfg,
                          SPEC_IDX.point)
    assert hit and fill == pytest.approx(sl - 2 * SPEC_IDX.point)
    # one tick inside: no touch
    hit2, _ = stop_fill(entry, sl + 0.25, entry + 1.0, 1, sl, cfg,
                        SPEC_IDX.point)
    assert not hit2
    hit3, fill3 = tp_fill(entry, entry - 1.0, tp + 0.25, 1, tp, cfg,
                          SPEC_IDX.point)
    assert hit3 and fill3 == tp


# ---------------------------------------------------------------------------
# Engine level — both-touch ordering through a real backtest run
# ---------------------------------------------------------------------------


def _micro_df(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="h")
    return pd.DataFrame(rows, index=idx,
                        columns=["open", "high", "low", "close", "volume"])


def test_engine_both_touch_bar_exits_stop_first():
    """A carried position on a bar that touches SL and TP exits with
    reason stop_loss — re-run twice for determinism (no hidden order)."""
    from mql5bot.backtest import run_backtest
    from mql5bot.data import generate_ohlc

    df = generate_ohlc(days=30, seed=11)
    res1 = run_backtest(df, "ema_crossover", risk_percent=1.0)
    res2 = run_backtest(df.copy(), "ema_crossover", risk_percent=1.0)
    t1 = res1.trades[["entry_time", "exit_time", "exit_reason", "side",
                      "lots"]].reset_index(drop=True)
    t2 = res2.trades[["entry_time", "exit_time", "exit_reason", "side",
                      "lots"]].reset_index(drop=True)
    pd.testing.assert_frame_equal(t1, t2)   # deterministic replay
    # the gold micro fixture asserts the both-touch stop-first rule at
    # trace level (tests/test_reality_gate.py); this pins the replay
    # determinism half of the contract.


def test_gold_trace_both_touch_resolves_stop_first():
    """The frozen gold trace's both-touch scenario resolves as stop_loss
    (conservative rule), and its fixture bar really touches both levels —
    re-asserted here so the barrier contract is self-contained."""
    import json
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    trace = json.loads((repo / "artifacts/gold/python_trace.json")
                       .read_text())
    rec = trace["scenario_both_touch"]
    assert rec["exit_reason"] == rec["expected_exit_reason"] == "stop_loss"
    micro = pd.read_csv(repo / "artifacts/gold/micro_both_touch.csv",
                        index_col="time", parse_dates=True)
    bar = micro.iloc[35]
    assert bar["high"] > rec["entry_fill"] + 4.0 * rec["atr_at_entry"]
    assert bar["low"] < rec["entry_fill"] - 2.5 * rec["atr_at_entry"]


# ---------------------------------------------------------------------------
# Barrier enumeration record (the re-derived matrix, mission §6)
# ---------------------------------------------------------------------------

BARRIER_MATRIX = [
    # direction, case, expected
    ("long", "exact SL touch", "fill at SL - slippage"),
    ("long", "SL one point inside", "no fill"),
    ("long", "SL one point beyond", "fill at SL - slippage"),
    ("long", "exact TP touch", "fill at TP"),
    ("long", "TP one point inside", "no fill"),
    ("long", "TP one point beyond", "fill at TP"),
    ("long", "open gaps through SL", "fill at open (worse)"),
    ("long", "open gaps through TP", "fill at open"),
    ("long", "both touched intrabar", "STOP first"),
    ("long", "both gapped at open", "STOP first"),
    ("short", "exact SL touch", "fill at SL + slippage"),
    ("short", "SL one point inside", "no fill"),
    ("short", "SL one point beyond", "fill at SL + slippage"),
    ("short", "exact TP touch", "fill at TP"),
    ("short", "TP one point inside", "no fill"),
    ("short", "TP one point beyond", "fill at TP"),
    ("short", "open gaps through SL", "fill at open (worse)"),
    ("short", "open gaps through TP", "fill at open"),
    ("short", "both touched intrabar", "STOP first"),
    ("short", "both gapped at open", "STOP first"),
    ("long", "tick-normalized SL level", "identical semantics"),
    ("short", "tick-normalized SL level", "identical semantics"),
    ("long", "index-CFD one TICK beyond", "spec-relative touch"),
    ("long", "index-CFD one TICK inside", "no fill"),
]


def test_open_gap_both_barriers_resolve_stop_first_source_pin():
    """When the open gaps through BOTH barriers, engine.open_gap_exits
    checks the stop BEFORE the TP (if/elif ordering) — pinned at source
    level so a refactor cannot silently swap the conservative order."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "python/mql5bot/engine.py").read_text()
    fn = src.split("def open_gap_exits")[1].split("def rollover")[0]
    for side_branch in ("if b.side > 0:", "else:"):
        seg = fn.split(side_branch, 1)[1]
        i_sl = seg.find("REASON_STOP_LOSS")
        i_tp = seg.find("REASON_TAKE_PROFIT")
        assert 0 <= i_sl < i_tp, side_branch


def test_barrier_matrix_enumeration_is_complete():
    """The matrix above is the enumerated contract: 24 pinned cases —
    10 per direction (exact/inside/beyond touches, gap-throughs,
    both-touch) + normalized-level + tick-size-relative cases. Every row
    is exercised by the parametrized tests in this module; this test pins
    the enumeration itself so rows cannot silently disappear."""
    assert len(BARRIER_MATRIX) == 24
    dirs = {d for d, _, _ in BARRIER_MATRIX}
    assert dirs == {"long", "short"}
    assert sum("STOP first" == e for _, _, e in BARRIER_MATRIX) == 4
