"""WARMUP-FROMDATE-1: the gold1 legs start where the EA has its InpDslBars
of history (gate_run48).

gate_run48 (gold1, fdd7b58): both gold1 legs stopped at OnInit with
"[mql5bot] DSL series build failed:" at tester time 2024.01.06 00:00. The
leg started at the fixture's first day (FromDate 2024.01.01); MT5 moved the
start to 2024.01.06 "to provide data at beginning", and the history cache
held 120 H1 bars (2024.01.01 00:00 - 2024.01.05 23:00), fewer than
InpDslBars=500. The gold1 fixture was BUILT for this: 600 bars of constant
close before the scenario week (tools/build_gold_standard.py), so the EA's
500-bar window is bit-identical to the full-history EMA. Only the tester
start was wrong. The frozen artifacts are untouched.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from mql5bot import gate_selfcheck as gs
from mql5bot import mt5tester as mt

REPO = Path(__file__).resolve().parents[1]
GOLD1 = (REPO / "artifacts/gold/manifest.json",
         REPO / "artifacts/gold/gold_fixture.csv")
GOLD2 = (REPO / "artifacts/gold_2/manifest.json",
         REPO / "artifacts/gold_2/gold2_fixture.csv")
DSL_BARS = int(mt.EA_INPUT_DEFAULTS["InpDslBars"])


def _rows(fixture: Path) -> list[list[str]]:
    with fixture.open(encoding="utf-8") as fh:
        return list(csv.reader(fh))[1:]


def test_gold1_starts_where_500_bars_of_its_own_warm_up_precede():
    r = gs.derive_tester_inputs(*GOLD1)
    assert r["ok"], r["reasons"]
    assert (r["date_from"], r["date_to"]) == ("2024.01.30", "2024.02.09")
    rows = _rows(GOLD1[1])
    before = [x for x in rows if x[0] < "2024-01-30"]
    assert len(before) == r["dsl_bars_before_start"] == 504 >= DSL_BARS
    # the day before has fewer: 2024.01.30 is the EARLIEST such start
    assert len([x for x in rows if x[0] < "2024-01-29"]) < DSL_BARS


def test_the_eas_window_is_inside_the_constant_warm_up():
    # the 500 bars before the start are all close 1.12500: EMA10 == EMA30
    # exactly, so the EA's 500-bar EMA equals Python's full-history EMA
    rows = [x for x in _rows(GOLD1[1]) if x[0] < "2024-01-30"]
    assert {x[4] for x in rows[-DSL_BARS:]} == {"1.1250000000"}


def test_no_expected_gold1_trade_precedes_the_start():
    ee = json.loads((REPO / "artifacts/gold/expected_execution.json")
                    .read_text(encoding="utf-8"))
    assert gs._earliest_expected_day(
        REPO / "artifacts/gold/expected_execution.json") == "2024.02.05"
    assert ee  # the frozen expectation is read, never rewritten


def test_gold2_is_unchanged():
    r = gs.derive_tester_inputs(*GOLD2)
    assert r["ok"], r["reasons"]
    assert (r["date_from"], r["date_to"]) == ("2024.01.01", "2024.01.04")
    assert r["dsl_bars_before_start"] == 0
    assert "first day alone holds 1440" in r["date_from_source"]


def test_the_old_start_is_what_failed():
    # the fixture's first day holds 24 H1 bars; MT5's start shift gave 120
    rows = _rows(GOLD1[1])
    assert len([x for x in rows if x[0].startswith("2024-01-01")]) == 24
    assert len([x for x in rows if x[0] < "2024-01-06"]) == 120 < DSL_BARS


# ------------------------------------------------- named refusals (synthetic)

def _gold(tmp_path: Path, days: int, first_trade: str | None,
          expected: bool = True) -> tuple[Path, Path]:
    man = json.loads(GOLD1[0].read_text(encoding="utf-8"))
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(man), encoding="utf-8")
    lines = ["time,open,high,low,close,volume"]
    for d in range(days):
        for h in range(24):
            lines.append(f"2024-03-{d + 1:02d} {h:02d}:00:00,1.1,1.1,1.1,1.1,1")
    fx = tmp_path / "fixture.csv"
    fx.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if expected:
        (tmp_path / "expected_execution.json").write_text(json.dumps(
            {"trades": [{"signal_time": first_trade}]}), encoding="utf-8")
    return mp, fx


def test_a_fixture_too_short_for_the_warm_up_is_refused(tmp_path):
    r = gs.derive_tester_inputs(*_gold(tmp_path, 20, "2024-03-20T00:00:00"))
    assert r["ok"] is False and r["missing"] == "date_from"
    assert "no day has InpDslBars=500 bars before it" in r["reasons"][0]


def test_an_expected_trade_before_the_moved_start_is_refused(tmp_path):
    # 25 days: the start moves to 2024.03.22 (504 bars before it)
    r = gs.derive_tester_inputs(*_gold(tmp_path, 25, "2024-03-10T05:00:00"))
    assert r["ok"] is False and r["missing"] == "date_from"
    assert "is after the earliest expected trade day 2024.03.10" \
        in r["reasons"][0]


def test_a_moved_start_without_an_expected_run_is_refused(tmp_path):
    r = gs.derive_tester_inputs(*_gold(tmp_path, 25, None, expected=False))
    assert r["ok"] is False
    assert "cannot prove no expected trade precedes it" in r["reasons"][0]


def test_a_synthetic_gold_with_room_starts_after_its_warm_up(tmp_path):
    r = gs.derive_tester_inputs(*_gold(tmp_path, 25, "2024-03-23T01:00:00"))
    assert r["ok"], r["reasons"]
    assert r["date_from"] == "2024.03.22" and r["dsl_bars_before_start"] == 504
