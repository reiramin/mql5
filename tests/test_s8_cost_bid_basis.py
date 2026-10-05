"""S8-COST-1 (owner decision, Sal 2026-10-05): an explicit CostConfig
``price_basis``. "mid" (default) is unchanged; "bid" models the MT5 tester
on a bid-quoted symbol: bar prices are BID, a buy fills at open + spread, a
sell at open, a long closes at the bid, a short at the ask (bid + spread;
its SL/TP trigger on the ask), slippage 0.

Used ONLY in the stage-8 package window run; the frozen-trace self-check
stays at the manifest cost ("mid") and must still reproduce.

MEASURED on the recorded gate_run29 log trade lists (REAL MT5 deals from
gate_run29, whose tester filled buys at bid + 2 points) -- NOT a gate run,
and not a prediction for gate_run35:

  window-run spread 1 (manifest): volume equal mid 14/37, bid 17/37
    (m1_ohlc) and 18/37 (every_tick);
  window-run spread 2: volume equal mid 11/37, bid 37/37 (m1_ohlc) and
    25/37 (every_tick).
  entry_price, side, timestamp and pairing are unchanged by the basis.

fast_engine is not used by the stage-8 window run (it runs
engine.PortfolioEngine) and builds its own mid CostConfig from kwargs, so
no "bid" path reaches it; it is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from mql5bot import stage8_package as s8p
from mql5bot.costs import (
    PRICE_BASIS_BID,
    PRICE_BASIS_MID,
    CostConfig,
    ask_offset,
    entry_fill,
    exit_fill,
)
from mql5bot.engine import Instrument, PortfolioEngine, RunConfig

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "tests" / "data" / "owner_gate"
MANIFEST = json.loads((REPO / "artifacts/gold_2/manifest.json").read_text())
EXPECTED = json.loads(
    (REPO / "artifacts/gold_2/expected_execution.json").read_text())
FIXTURE = REPO / "artifacts/gold_2/gold2_fixture.csv"
START = "2024-01-02T00:00:00"
END = "2024-01-04T00:00:00"
MODELS = ("every_tick", "m1_ohlc")
LINES = {m: f"EURUSD.G2: start time changed to 2024.01.02 00:00 to "
            f"provide data at beginning ({m})" for m in MODELS}
POINT = 1e-5


# --------------------------------------------------------------- costs.py

def test_mid_is_the_default_and_unchanged():
    assert CostConfig().price_basis == PRICE_BASIS_MID
    # mid: buy pays +spread/2 +slip, sell the mirror (convention 1)
    assert entry_fill(1.1, 1, 2.0, 1.0, POINT) == pytest.approx(1.10002)
    assert entry_fill(1.1, -1, 2.0, 1.0, POINT) == pytest.approx(1.09998)
    assert exit_fill(1.1, 1, 2.0, 1.0, POINT) == pytest.approx(1.09998)
    assert exit_fill(1.1, -1, 2.0, 1.0, POINT) == pytest.approx(1.10002)
    assert ask_offset(-1, 2.0, POINT) == 0.0


def test_bid_basis_fills():
    b = PRICE_BASIS_BID
    # bar open is the BID: buy at the ask, sell at the bid
    assert entry_fill(1.1, 1, 2.0, 0.0, POINT, b) == pytest.approx(1.10002)
    assert entry_fill(1.1, -1, 2.0, 0.0, POINT, b) == 1.1
    # a long closes at the bid, a short at the ask
    assert exit_fill(1.1, 1, 2.0, 0.0, POINT, b) == 1.1
    assert exit_fill(1.1, -1, 2.0, 0.0, POINT, b) == pytest.approx(1.10002)
    assert ask_offset(1, 2.0, POINT, b) == 0.0
    assert ask_offset(-1, 2.0, POINT, b) == pytest.approx(2 * POINT)


@pytest.mark.parametrize("kwargs, msg", [
    ({"price_basis": "ask"}, "price_basis must be one of"),
    ({"price_basis": "bid", "slippage_points": 1.0}, "slippage_points"),
    ({"price_basis": "bid", "entry_mode": "pending_stop"}, "market entries"),
])
def test_bid_basis_validation_refuses(kwargs, msg):
    with pytest.raises(ValueError, match=msg):
        CostConfig(**kwargs).validate()


# --------------------------------------------------------------- engine.py

def _frame(n=60, price=1.1, half=0.0005):
    idx = pd.date_range("2024-01-02 00:00", periods=n, freq="min")
    o = np.full(n, price)
    return pd.DataFrame({"open": o, "high": o + half, "low": o - half,
                         "close": o, "volume": 1.0}, index=idx)


def _run(df, signal, basis, spread=20.0):
    costs = CostConfig(symbol="EURUSD", spread_points=spread,
                       slippage_points=0.0, price_basis=basis)
    ins = Instrument(symbol="EURUSD", strategy="s8_cost_probe", df=df,
                     costs=costs, params={"sl_atr": 2.0, "tp_atr": 1000.0},
                     signal=pd.Series(signal, index=df.index))
    return PortfolioEngine(RunConfig(initial_capital=10_000.0)).run([ins])


def test_engine_bid_basis_entry_prices():
    df = _frame()
    sig = np.zeros(len(df), dtype=int)
    sig[20:] = 1
    long_t = _run(df, sig, PRICE_BASIS_BID).trades.iloc[0]
    assert long_t["entry_price"] == pytest.approx(1.1 + 20 * POINT)  # ask
    assert long_t["exit_reason"] == "end_of_data"
    assert long_t["exit_price"] == pytest.approx(1.1)                # bid
    short_t = _run(df, -sig, PRICE_BASIS_BID).trades.iloc[0]
    assert short_t["entry_price"] == pytest.approx(1.1)              # bid
    assert short_t["exit_price"] == pytest.approx(1.1 + 20 * POINT)  # ask


def test_engine_short_stop_triggers_on_the_ask_under_bid_only():
    """ATR = 2*half = 0.001, sl = 2*ATR. Under "bid" the short sells at
    1.1 (sl 1.102); a bar whose BID high is 1.10185 puts the ASK at
    1.10205 >= sl -> stop at the sl. Under "mid" the short sells at
    1.0999 (sl 1.1019) and the bid high 1.10185 never reaches it."""
    df = _frame()
    df.iloc[40, df.columns.get_loc("high")] = 1.10185
    sig = np.zeros(len(df), dtype=int)
    sig[20:] = -1
    bid = _run(df, sig, PRICE_BASIS_BID).trades.iloc[0]
    assert bid["exit_reason"] == "stop_loss"
    assert bid["exit_time"] == str(df.index[40])
    assert bid["exit_price"] == pytest.approx(1.102)
    mid = _run(df, sig, PRICE_BASIS_MID).trades.iloc[0]
    assert mid["exit_reason"] == "end_of_data"


def test_engine_long_stop_still_triggers_on_the_bid():
    df = _frame()
    df.iloc[40, df.columns.get_loc("low")] = 1.1 + 20 * POINT - 0.00205
    sig = np.zeros(len(df), dtype=int)
    sig[20:] = 1
    t = _run(df, sig, PRICE_BASIS_BID).trades.iloc[0]
    # long bought at the ask 1.1002, sl 1.0982; bid low 1.09815 hits it
    assert t["exit_reason"] == "stop_loss"
    assert t["exit_price"] == pytest.approx(1.1002 - 0.002)


# ------------------------------------------------- stage-8 window run (S8)

@pytest.fixture(scope="module")
def run29_logs():
    py, _ = s8p.python_entries(EXPECTED, MANIFEST["timeframe"])
    mt5 = {}
    for m in MODELS:
        deals = json.loads((DATA / f"gate_run29_gold2_{m}_log_trades.json"
                            ).read_text())["deals"]
        mt5[m], why = s8p.mt5_entries(deals)
        assert mt5[m] is not None, why
    return py, mt5


def _counts(run29_logs, spread, basis):
    py, mt5 = run29_logs
    fill = s8p.fill_spec_of(
        MANIFEST, None if spread is None else {"spread_points": spread})[0]
    sd, note = s8p.expected_set_window_run(REPO, "gold2", START, END,
                                           spread_points=spread,
                                           price_basis=basis)
    assert sd is not None, note   # the frozen-trace self-check reproduced
    events, summary = s8p.reconciliation_events(
        py, mt5, "EURUSD.G2",
        window_starts={m: (START, LINES[m]) for m in MODELS},
        window_end=END, fixture_opens=s8p.fixture_minute_opens(FIXTURE),
        fill=fill, expected_sets={m: (sd, note) for m in MODELS})
    out = {}
    for m in MODELS:
        paired = [e for e in events if e.get("model") == m
                  and e.get("pairing") == s8p.PAIRED_BY_TIME]

        def eq(k, paired=paired):
            return sum(1 for e in paired if e["fields"][k].get("python")
                       == e["fields"][k]["mt5"])
        out[m] = (len(paired), summary[m]["missing_in_mt5"],
                  summary[m]["extra_in_mt5"], eq("entry_side"),
                  eq("entry_price"), eq("volume"))
    return out, note


def test_bid_window_run_keeps_the_frozen_self_check_and_names_the_basis(
        run29_logs):
    _, note = _counts(run29_logs, None, PRICE_BASIS_BID)
    assert "price_basis 'bid'" in note
    assert "frozen trace reproduced (manifest cost, price_basis 'mid')" \
        in note


def test_measured_counts_mid_vs_bid_on_the_gate_run29_logs(run29_logs):
    """MEASURED, never predicted (gate_run29 MT5 deals; the tester's
    spread there was 2). Tuple: paired, missing, extra, side equal,
    entry_price equal, volume equal."""
    mid1, _ = _counts(run29_logs, None, PRICE_BASIS_MID)
    bid1, _ = _counts(run29_logs, None, PRICE_BASIS_BID)
    mid2, _ = _counts(run29_logs, 2.0, PRICE_BASIS_MID)
    bid2, _ = _counts(run29_logs, 2.0, PRICE_BASIS_BID)
    for m in MODELS:
        assert mid1[m] == (37, 0, 0, 37, 18, 14), (m, mid1[m])
        assert mid2[m] == (37, 0, 0, 37, 37, 11), (m, mid2[m])
    assert bid1 == {"every_tick": (37, 0, 0, 37, 18, 18),
                    "m1_ohlc": (37, 0, 0, 37, 18, 17)}
    assert bid2 == {"every_tick": (37, 0, 0, 37, 37, 25),
                    "m1_ohlc": (37, 0, 0, 37, 37, 37)}
