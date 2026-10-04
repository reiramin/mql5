"""Stage 8: named expected fill model + window-consistent sizing basis.

gate_run29 (HEAD 5392cc4, -Golds gold2, re-anchored) paired 37 MT5 entries
BY TIME. Two systematic per-trade differences were measured there:

  (a) entry_price: 19/37 (every buy) mt5 - python == +0.00002; every sell
      equal. The python column was the BARE fixture open.
  (b) volume: 36/37 differ, ratio mt5/python 1.12 falling to 0.93. The
      python column was sized on the frozen run's equity, which carries the
      2024-01-01 trades MT5 never ran and the generator's day weights
      0.5/0.1 that the tester leg does not apply.

The MT5 side here is the REAL gate_run29 m1_ohlc log trade list (74 deals,
tests/data/owner_gate/gate_run29_gold2_m1_ohlc_log_trades.json, a byte copy
of owner_mt5_package/log_trades/gold2_m1_ohlc.json from that run). The
window start is the one MT5 stated in that run ("EURUSD.G2: start time
changed to 2024.01.02 00:00 to provide data at beginning").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mql5bot import owner_gate as og
from mql5bot import stage8_package as s8p
from mql5bot.sizer import size_position
from mql5bot.symbolspec import SymbolSpec

REPO = Path(__file__).resolve().parents[1]
RUN29 = REPO / "tests" / "data" / "owner_gate" / \
    "gate_run29_gold2_m1_ohlc_log_trades.json"
MANIFEST = json.loads((REPO / "artifacts/gold_2/manifest.json").read_text())
EXPECTED = json.loads(
    (REPO / "artifacts/gold_2/expected_execution.json").read_text())
FIXTURE = REPO / "artifacts/gold_2/gold2_fixture.csv"
START = "2024-01-02T00:00:00"
START_LINE = ("LH\t3\t01:56:38.082\tCore 1\tEURUSD.G2: start time changed "
              "to 2024.01.02 00:00 to provide data at beginning")
END = "2024-01-04T00:00:00"


def _events(window_volumes=None, fill="manifest"):
    py, _ = s8p.python_entries(EXPECTED, MANIFEST["timeframe"])
    deals = json.loads(RUN29.read_text())["deals"]
    entries, _ = s8p.mt5_entries(deals)
    if fill == "manifest":
        fill = s8p.fill_spec_of(MANIFEST)[0]
    if window_volumes is None:
        window_volumes = {"m1_ohlc": s8p.window_basis_volumes(
            REPO, "gold2", START)}
    events, summary = s8p.reconciliation_events(
        py, {"m1_ohlc": entries}, "EURUSD.G2",
        window_starts={"m1_ohlc": (START, START_LINE)}, window_end=END,
        fixture_opens=s8p.fixture_minute_opens(FIXTURE), fill=fill,
        window_volumes=window_volumes)
    return events, summary


@pytest.fixture(scope="module")
def run29():
    return _events()


def _paired(events):
    return [e for e in events if e.get("pairing") == s8p.PAIRED_BY_TIME]


def test_gate_run29_pairing_is_unchanged(run29):
    _, summary = run29
    s = summary["m1_ohlc"]
    assert (s["paired"], s["missing_in_mt5"], s["extra_in_mt5"]) == (37, 1, 0)


# ---------------------------------------------------------------- TASK A

def test_fill_model_is_named_on_every_python_event(run29):
    events, _ = run29
    with_python = [e for e in events if "python_side_declared" in e]
    assert len(with_python) == 37 + 1 + 24
    for e in with_python:
        want = (s8p.FILL_MODEL_BUY if e["python_side_declared"] == "long"
                else s8p.FILL_MODEL_SELL)
        assert e["fill_model"] == want
    assert s8p.FILL_MODEL_SELL == "bid_open"
    assert s8p.FILL_MODEL_BUY == "ask_open=bid+spread"


def test_the_19_gate_run29_buys_use_ask_and_the_residual_stays_divergent(
        run29):
    events, _ = run29
    opens = s8p.fixture_minute_opens(FIXTURE)
    point = MANIFEST["broker_spec"]["point"]
    spread = MANIFEST["cost_config"]["spread_points"]
    buys = [e for e in _paired(events) if e["python_side_declared"] == "long"]
    sells = [e for e in _paired(events)
             if e["python_side_declared"] == "short"]
    assert (len(buys), len(sells)) == (19, 18)
    for e in buys:
        price = e["fields"]["entry_price"]
        bid = opens[e["time"][:16]]
        # python = ask = bid + spread_points * point (never the bare open,
        # never + slippage)
        assert price["python"] == round(bid + spread * point, 5)
        assert price["python"] != bid
        # MEASURED gate_run29: MT5 bought at bid + 2 points on all 19, so
        # +1 point remains and is STILL a divergence (zero tolerance)
        assert round((price["mt5"] - bid) / point) == 2
        assert round((price["mt5"] - price["python"]) / point) == 1
        assert og._field_divergent(price)
    for e in sells:
        price = e["fields"]["entry_price"]
        assert price["python"] == price["mt5"] == opens[e["time"][:16]]
        assert not og._field_divergent(price)


def test_no_fill_spec_means_no_python_price_and_the_builder_refuses():
    events, _ = _events(fill=None)
    for e in _paired(events):
        assert "python" not in e["fields"]["entry_price"]
        assert e["fill_model"] is None
    spec, why = s8p.fill_spec_of({"broker_spec": {"point": 1e-05,
                                                  "digits": 5}})
    assert spec is None and "spread_points" in why


def test_expected_fill_never_adds_slippage():
    fill = s8p.fill_spec_of(MANIFEST)[0]
    assert MANIFEST["cost_config"]["slippage_points"] == 1.0
    assert s8p.expected_fill(1.09725, "buy", fill) == (1.09726,
                                                      s8p.FILL_MODEL_BUY)
    assert s8p.expected_fill(1.09725, "sell", fill) == (1.09725,
                                                       s8p.FILL_MODEL_SELL)


# ---------------------------------------------------------------- TASK B

def test_window_basis_collapses_the_volume_ratio_toward_one(run29):
    events, _ = run29
    paired = _paired(events)
    frozen = [e["fields"]["volume"]["mt5"] / e["python_volume_frozen_basis"]
              for e in paired]
    window = [e["fields"]["volume"]["mt5"] / e["fields"]["volume"]["python"]
              for e in paired]
    print("\ngate_run29 m1_ohlc mt5/python volume ratios (frozen -> window):")
    for e, f, w in zip(paired, frozen, window):
        print(f"  {e['time']}  {f:.3f} -> {w:.3f}")
    # before: 1.12 at 01-02 08:46 falling to 0.93 at 01-03 15:30
    assert round(max(frozen), 2) == 1.12 and round(min(frozen), 2) == 0.94
    assert round(frozen[1], 2) == 1.12 and round(frozen[-1], 3) == 0.939
    # after: every ratio in [1.000, 1.016]; equal volume on 14/37
    assert all(1.0 <= w <= 1.016 for w in window)
    assert sum(1 for e in paired
               if e["fields"]["volume"]["python"]
               == e["fields"]["volume"]["mt5"]) == 14
    # the first 5 in-window entries (through 01-02 10:13) match exactly
    assert all(w == 1.0 for w in window[:5])


def test_both_volume_columns_are_recorded_and_the_basis_stated(run29):
    events, _ = run29
    for e in _paired(events):
        assert e["fields"]["volume"]["python"] == \
            e["python_volume_window_basis"]
        assert e["python_volume_frozen_basis"] is not None
        assert e["python_volume_basis"].startswith("WINDOW: ")
        assert "2024-01-02T00:00:00" in e["python_volume_basis"]
        assert "equity_start 10000.0" in e["python_volume_basis"]
    e46 = next(e for e in _paired(events)
               if e["time"] == "2024-01-02T08:46:00")
    assert (e46["python_volume_frozen_basis"],
            e46["python_volume_window_basis"]) == (0.25, 0.28)


def test_window_basis_starts_at_equity_start():
    wv, note = s8p.window_basis_volumes(REPO, "gold2", START)
    assert wv is not None, note
    assert wv["2024-01-02T08:01"]["basis"] == 10000.0
    # frozen basis at the same signal bar carries 2024-01-01 (19 trades)
    first = next(r for r in EXPECTED["entries"]
                 if r["signal_time"] == "2024-01-02T08:00:00")
    assert first["sizing_basis"] == 9085.75


def test_mt5_volumes_follow_the_same_sizing_rule_on_mt5_balance():
    """Diagnostic, never the compared column: the frozen sizing rule on
    MT5's OWN balance (10000 + its closed-deal pnl) reproduces all 37 MT5
    volumes, so the residual window-basis gap is the equity path, not the
    sizing rule."""
    spec = SymbolSpec(**MANIFEST["broker_spec"])
    py, _ = s8p.python_entries(EXPECTED, "M1")
    by_signal = {r["signal_time"]: r for r in EXPECTED["entries"]}
    stops = {p["fill_time"][:16]: by_signal[p["signal_time"]]["stop_distance"]
             for p in py}
    balance, hits, n = 10000.0, 0, 0
    for d in json.loads(RUN29.read_text())["deals"]:
        minute = s8p._ea_time_iso(d["time"])[:16]
        if d["entry"] == "open":
            lots = size_position(spec, mode="risk_percent_equity",
                                 equity=balance, stop_distance=stops[minute],
                                 value=1.0).lots
            n += 1
            hits += round(lots, 2) == d["volume"]
        else:
            balance += d["pnl"]
    assert (hits, n) == (37, 37)


def test_missing_0808_stays_a_divergence_and_the_rerun_does_not_enter(run29):
    events, _ = run29
    (m,) = [e for e in events if e.get("pairing") == s8p.MISSING_IN_MT5]
    assert m["python_signal_time"] == "2024-01-02T08:07:00"
    assert m["fields"]["state"]["mt5"].startswith(s8p.MISSING_IN_MT5)
    assert og._field_divergent(m["fields"]["state"])
    # recorded only: at tester weight 1.0 the python engine itself does not
    # enter at 08:08 (the 08:01 short is still open)
    assert m["window_basis_run_entered_here"] is False
    assert m["python_volume_frozen_basis"] == 0.02


def test_refused_window_basis_compares_the_frozen_column(run29):
    events, _ = _events(window_volumes={"m1_ohlc": (None, "refused (test)")})
    for e in _paired(events):
        assert e["fields"]["volume"]["python"] == \
            e["python_volume_frozen_basis"]
        assert e["python_volume_window_basis"] is None
        assert e["python_volume_basis"].startswith("FROZEN: ")
        assert "refused (test)" in e["python_volume_basis"]


def test_window_drop_is_compared_as_zero_never_dropped(run29):
    wv, note = s8p.window_basis_volumes(REPO, "gold2", START)
    wv = dict(wv)
    wv["2024-01-02T08:46"] = dict(wv["2024-01-02T08:46"], lots=0.0,
                                  action="DROP")
    events, _ = _events(window_volumes={"m1_ohlc": (wv, note)})
    e46 = next(e for e in _paired(events)
               if e["time"] == "2024-01-02T08:46:00")
    assert e46["fields"]["volume"] == {"python": 0.0, "mt5": 0.28}
    assert og._field_divergent(e46["fields"]["volume"])


def test_window_basis_is_refused_for_a_foreign_generator(monkeypatch):
    class Fake:
        @staticmethod
        def _config_hash():
            return "not-the-manifest-hash"
    monkeypatch.setattr(s8p, "_gold_generator", lambda repo, rel: Fake)
    wv, why = s8p.window_basis_volumes(REPO, "gold2", START)
    assert wv is None and "config_hash" in why


def test_window_basis_is_refused_when_the_trace_is_not_reproduced(
        monkeypatch, tmp_path):
    real = s8p._load

    def tampered(path):
        doc = real(path)
        if Path(path).name == "python_trace.json":
            doc["trades"][0]["pnl"] += 0.01
        return doc
    monkeypatch.setattr(s8p, "_load", tampered)
    wv, why = s8p.window_basis_volumes(REPO, "gold2", START)
    assert wv is None and "does not reproduce the frozen trace" in why


def test_gold_without_a_wired_generator_is_refused():
    wv, why = s8p.window_basis_volumes(REPO, "gold1", START)
    assert wv is None and "no frozen generator" in why
