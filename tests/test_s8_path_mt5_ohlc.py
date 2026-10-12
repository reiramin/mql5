"""S8-PATH-1 (gate_run51, HEAD c8bc022, -Golds gold1).

gold1 paired 18/18 entries in both models; the first divergence was trade
16 (2024-02-07T09:00): volume python 0.13 vs mt5 0.14, SIZING_MISMATCH.

Root cause, read from the published log trade list: the sizing rule
was right; the EQUITY under it was not. Two huge-range doji bars
(2024-02-06 23:00 and 2024-02-07 00:00, the manifest's "simultaneous_edge"
scenario) touch BOTH the stop-loss and the take-profit of an open short.
The engine's conservative rule fills the stop first (-103.74, -106.35);
MT5's M1-OHLC tick order reaches the low first and fills the take-profit
(+166.11, +170.10 at :20). Every exit before them matched to the cent.

The tester window run now resolves a both-touch bar in the tester's own
tick order (open, low, high, close when close >= open; else open, high,
low, close: bullish/doji bars reach the low at :20, bearish bars the high,
measured on every gate_run51 m1_ohlc exit). The frozen-trace guard still
runs the conservative rule and still reproduces the frozen trace.

A second gap: MT5 printed no "start time changed" line (it kept the
WARMUP-FROMDATE-1 start 2024.01.30), so the builder had no measured window
start and fell back to the frozen scheduled-weight column. The start is now
also measured when the leg's ini FromDate equals MT5's own first tester-
clock line.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mql5bot import costs as C
from mql5bot import owner_gate as og
from mql5bot import stage8_package as s8p
from mql5bot.costs import CostConfig

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "tests/data/owner_gate"
# byte copy of reports/gate_run51/tester_gold1_m1_ohlc_log_trades.json
# (branch gate-reports; sha256 f43c3b75...4f9fb2)
RUN51_M1 = DATA / "gate_run51_gold1_m1_ohlc_log_trades.json"
G1_START = "2024-01-30T00:00:00"
G1_END = "2024-02-09T00:00:00"
G2_START = "2024-01-02T00:00:00"
G2_END = "2024-01-04T00:00:00"
LONG, SHORT = 1, -1
MT5, SF = C.INTRABAR_MT5_OHLC, C.INTRABAR_STOP_FIRST


# --------------------------------------------------------------------------
# the order rule
# --------------------------------------------------------------------------

@pytest.mark.parametrize("side,o,c,want", [
    # bullish (close > open): low first -> long SL first, short TP first
    (LONG, 1.10, 1.11, False), (SHORT, 1.10, 1.11, True),
    # doji (close == open, gate_run51 23:00 / 00:00): low first too
    (LONG, 1.10, 1.10, False), (SHORT, 1.10, 1.10, True),
    # bearish: high first -> long TP first, short SL first
    (LONG, 1.11, 1.10, True), (SHORT, 1.11, 1.10, False),
])
def test_mt5_ohlc_order_picks_the_level_the_tester_reaches_first(
        side, o, c, want):
    sl, tp = (o - 0.05, o + 0.05) if side > 0 else (o + 0.05, o - 0.05)
    assert C.take_profit_first(o, c, side, sl, tp, MT5) is want


@pytest.mark.parametrize("side,o,c", [
    (LONG, 1.10, 1.11), (SHORT, 1.10, 1.10), (LONG, 1.11, 1.10),
    (SHORT, 1.11, 1.10)])
def test_stop_first_never_takes_profit_first(side, o, c):
    sl, tp = (o - 0.05, o + 0.05) if side > 0 else (o + 0.05, o - 0.05)
    assert C.take_profit_first(o, c, side, sl, tp, SF) is False


def test_the_open_is_the_first_tick():
    # a level the open already reaches fills there; the stop when both do
    assert C.take_profit_first(1.10, 1.09, LONG, 1.05, 1.10, MT5) is True
    assert C.take_profit_first(1.10, 1.09, LONG, 1.10, 1.10, MT5) is False
    assert C.take_profit_first(1.10, 1.11, SHORT, 1.10, 1.05, MT5) is False


def test_mt5_ohlc_is_a_tester_model_only():
    with pytest.raises(ValueError, match="price_basis must be 'bid'"):
        CostConfig(intrabar_order=MT5).validate()
    with pytest.raises(ValueError, match="intrabar_order must be one of"):
        CostConfig(intrabar_order="tp_first").validate()
    CostConfig(intrabar_order=MT5, price_basis="bid").validate()
    assert CostConfig().intrabar_order == SF          # default unchanged


# --------------------------------------------------------------------------
# gold1 against gate_run51
# --------------------------------------------------------------------------

def _run51_entries() -> list[dict]:
    deals = json.loads(RUN51_M1.read_text(encoding="utf-8"))["deals"]
    return deals[0::2]


def _window_run(gold, start, end, order):
    sd, note = s8p.expected_set_window_run(
        REPO, gold, start, end, spread_points=1.0,
        spread_source="test", intrabar_order=order)
    assert sd is not None, note
    return sd, note


def test_run51_copy_is_the_published_bytes():
    assert s8p._sha(RUN51_M1) == ("f43c3b75594d0a889c53ed985560991fe3b29fd9"
                                  "1e3b5c1e87d68b2a85649fb2")


def test_gold1_window_run_reproduces_every_run51_m1_ohlc_entry():
    sd, note = _window_run("gold1", G1_START, G1_END, MT5)
    assert "intrabar_order 'mt5_ohlc'" in note
    mt5 = _run51_entries()
    assert len(sd["rows"]) == len(mt5) == 18
    side = {"long": "buy", "short": "sell"}
    for row, deal in zip(sd["rows"], mt5, strict=True):
        assert row["fill_time"][:16] == s8p._ea_time_iso(deal["time"])[:16]
        assert side[row["side"]] == deal["side"]
        assert row["lots"] == deal["volume"], row["fill_time"]
        assert row["window_run_fill"] == deal["price"], row["fill_time"]


def test_the_conservative_rule_is_the_run51_divergence():
    # what gate_run51 compared: trade 16 (0-based) at 0.13, MT5 0.14
    sd, _ = _window_run("gold1", G1_START, G1_END, SF)
    rows = {r["fill_time"][:16]: r["lots"] for r in sd["rows"]}
    assert rows["2024-02-07T09:00"] == 0.13
    assert rows["2024-02-07T15:00"] == 0.15
    m = {s8p._ea_time_iso(d["time"])[:16]: d["volume"]
         for d in _run51_entries()}
    assert m["2024-02-07T09:00"] == 0.14 and m["2024-02-07T15:00"] == 0.16


def test_gold2_window_run_is_unchanged_by_the_order_rule():
    a, _ = _window_run("gold2", G2_START, G2_END, SF)
    b, _ = _window_run("gold2", G2_START, G2_END, MT5)
    assert a == b


# --------------------------------------------------------------------------
# window start without a "start time changed" line
# --------------------------------------------------------------------------

# measured format, gate_run51 console.txt (stage 5 tester log excerpt)
GEN = ("EF\t0\t03:33:20.428\tCore 1\tEURUSD.G1,H1 (MetaQuotes-Demo): "
       "1 minutes OHLC ticks generating")
ONINIT = ("ER\t0\t03:33:20.428\tCore 1\t2024.01.30 00:00:00   [mql5bot] "
          "DSL bundle loaded from common: Mql5Bot\\gold_bundles\\"
          "ema_crossover_ref_v1_EURUSD.G1.bundle.json")


def test_unmoved_start_is_measured_from_fromdate_and_the_tester_clock():
    text = GEN + "\n" + ONINIT + "\n"
    start, src = s8p.tested_window_start(text, "EURUSD.G1", "2024.01.30")
    assert start == G1_START
    assert "FromDate 2024.01.30" in src and ONINIT.strip() in src


@pytest.mark.parametrize("text,symbol,from_date", [
    (GEN + "\n" + ONINIT, "EURUSD.G1", None),            # no ini FromDate
    (GEN + "\n" + ONINIT, "EURUSD.G1", "2024.01.29"),    # clock disagrees
    (GEN + "\n" + ONINIT, "EURUSD.G2", "2024.01.30"),    # another symbol
    (GEN, "EURUSD.G1", "2024.01.30"),                     # no clock line
    (GEN + "\n" + ONINIT.replace("00:00:00", "01:00:00"),
     "EURUSD.G1", "2024.01.30"),                          # not at 00:00
])
def test_unmoved_start_is_never_assumed(text, symbol, from_date):
    assert s8p.tested_window_start(text, symbol, from_date) == (None, None)


def test_a_start_time_changed_line_still_wins():
    moved = ("Core 1\tEURUSD.G1: start time changed to 2024.01.31 00:00 "
             "to provide data at beginning")
    text = GEN + "\n" + moved + "\n" + ONINIT
    assert s8p.tested_window_start(text, "EURUSD.G1", "2024.01.30") == \
        ("2024-01-31T00:00:00", moved)


def test_ini_from_date():
    ini = b"[Tester]\r\nFromDate=2024.01.30\r\nToDate=2024.02.09\r\n"
    assert og.ini_from_date(ini) == "2024.01.30"
    assert og.ini_from_date(ini.decode().encode("utf-16")) == "2024.01.30"
    assert og.ini_from_date(b"[Tester]\nFromDate=30.01.2024\n") is None
    assert og.ini_from_date(b"[Common]\nFromDate=2024.01.30\n") is None
