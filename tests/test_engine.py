"""Canonical portfolio engine tests (mql5bot.engine) — Phases 1/4/5.

Covers: tick-valued PnL with profit/loss tick values, netting merge /
FIFO offset / remainder reopen, hedging opposite books, strategy flips,
server-time daily-loss resets, drawdown kill switch, exposure caps,
variable spread / reject masks / gaps, swap at day boundaries, walk-forward
segment params, and the "no direct risk formula in the canonical path" guard.
"""

import itertools

import mql5bot.strategies as st
import numpy as np
import pandas as pd
import pytest
from mql5bot.costs import CostConfig, cost_profile, entry_fill
from mql5bot.dayclock import DayClock
from mql5bot.engine import (
    EXIT_REASONS,
    MODE_HEDGING,
    MODE_NETTING,
    Instrument,
    PortfolioEngine,
    RunConfig,
    leg_cash,
)
from mql5bot.specs import SYNTHETIC_SPECS, synthetic_spec
from mql5bot.symbolspec import enforce_min_stop, round_to_tick


@pytest.fixture(autouse=True)
def _restore_strategy_registry():
    """Engine tests register throwaway strategies; keep the module-level
    STRATEGIES registry pristine for the shared optimizer tests."""
    before = dict(st.STRATEGIES)
    yield
    st.STRATEGIES.clear()
    st.STRATEGIES.update(before)


def make_frame(n: int, price: float = 100.0, half: float = 0.001,
               start: str = "2024-01-01 00:00", closes: list[float] | None = None,
               lows: list[float] | None = None,
               highs: list[float] | None = None) -> pd.DataFrame:
    """Hourly frame; default quiet bars (o=c=price, h/l = price ± half) give a
    CONSTANT ATR of 2*half after bar 14 (sl = 2*atr = 0.004 -> $400/lot loss
    on the EURUSD fixture, so 1% risk on 10k = exactly 0.25 lots)."""
    idx = pd.date_range(start, periods=n, freq="h")
    o = np.full(n, price)
    c = np.full(n, price) if closes is None else np.asarray(closes, dtype=float)
    for i in range(1, n):
        o[i] = c[i - 1]
    h = np.maximum(o, c) + half if highs is None else np.asarray(highs, dtype=float)
    l = np.minimum(o, c) - half if lows is None else np.asarray(lows, dtype=float)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "volume": 1000.0}, index=idx)


def register_signal(name: str, series: np.ndarray,
                    defaults: dict | None = None) -> None:
    def fn(df: pd.DataFrame, p: dict | None = None) -> pd.Series:
        return pd.Series(series[: len(df)], index=df.index)

    st.STRATEGIES[name] = (fn, dict(defaults or {"sl_atr": 2.0, "tp_atr": 1000.0}))


def zero_costs(symbol: str = "EURUSD") -> CostConfig:
    return CostConfig(symbol=symbol, spread_points=0.0, slippage_points=0.0,
                      commission_per_lot=0.0)


EUR = "EURUSD"
GBP = "GBPUSD"
N = 200
Q = np.zeros(N, dtype=int)


def engine(cfg: RunConfig | None = None) -> PortfolioEngine:
    return PortfolioEngine(cfg or RunConfig(initial_capital=10_000.0))


def run_single(series: np.ndarray, cfg: RunConfig | None = None,
               costs: CostConfig | None = None, symbol: str = EUR,
               start: str = "2024-01-01 00:00") -> tuple:
    df = make_frame(N, start=start)
    register_signal("eng_one", series)
    res = engine(cfg).run([Instrument(symbol=symbol, strategy="eng_one",
                                      df=df, costs=costs or zero_costs(symbol))])
    return res


# ---------------------------------------------------------------------------
# canonical-path guard + valuation units
# ---------------------------------------------------------------------------


def test_no_legacy_risk_formula_in_canonical_path():
    """The engine must never size with risk/(stop*contract_size): that
    arithmetic belongs to the legacy module only and is removed there."""
    import re

    import mql5bot.engine as mod

    with open(mod.__file__) as fh:
        src = fh.read()
    # scan code only: docstrings legitimately describe what the module bans
    code = re.sub(r'"""(?:[^"\\]|\\.|"(?!""))*"""', "", src,
                  flags=re.DOTALL)
    for banned in ("risk_amount", "/(stop_dist", "stop_distance * contract_size",
                   "risk / (", "risk/("):
        assert banned not in code, f"legacy risk formula fragment found: {banned!r}"


def test_tick_value_profit_side_used_for_favourable_moves():
    spec = SYNTHETIC_SPECS[EUR]
    # symmetric spec: both sides use tick_value_loss
    assert leg_cash(+1, 1.0, 100.0, 100.01, spec, 1.0) == pytest.approx(1000.0)
    assert leg_cash(+1, 1.0, 100.0, 99.99, spec, 1.0) == pytest.approx(-1000.0)
    assert leg_cash(-1, 1.0, 100.0, 99.99, spec, 1.0) == pytest.approx(1000.0)
    assert leg_cash(-1, 1.0, 100.0, 100.01, spec, 1.0) == pytest.approx(-1000.0)
    # sub-tick float noise on equal prices is not a tradable move
    assert leg_cash(+1, 0.25, 100.00000000000001, 100.0, spec, 1.0) == 0.0

    from dataclasses import replace

    asym = replace(spec, tick_value_profit=2.0)  # favourable ticks worth 2x
    assert leg_cash(+1, 1.0, 100.0, 100.01, asym, 1.0) == pytest.approx(2000.0)
    assert leg_cash(+1, 1.0, 100.0, 99.99, asym, 1.0) == pytest.approx(-1000.0)
    assert leg_cash(-1, 1.0, 100.0, 99.99, asym, 1.0) == pytest.approx(2000.0)
    assert leg_cash(-1, 1.0, 100.0, 100.01, asym, 1.0) == pytest.approx(-1000.0)


# ---------------------------------------------------------------------------
# netting
# ---------------------------------------------------------------------------


def test_netting_same_direction_merges_into_one_book():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1  # long from the first actionable bar
    b = np.zeros(N, dtype=int)
    b[19:] = 1  # second strategy joins later
    df["s_a"] = a
    df["s_b"] = b
    register_signal("eng_na", a, {"sl_atr": 2.0, "tp_atr": 1000.0})
    register_signal("eng_nb", b, {"sl_atr": 5.0, "tp_atr": 1000.0})
    res = engine().run([
        Instrument(symbol=EUR, strategy="eng_na", df=df, costs=zero_costs()),
        Instrument(symbol=EUR, strategy="eng_nb", df=df, costs=zero_costs()),
    ])
    t = res.trades
    assert len(t) == 2  # one row per LEG, not per order
    assert set(t["strategy"]) == {"eng_na", "eng_nb"}
    assert (t["exit_reason"] == "end_of_data").all()
    # sizing: A risks 1% of 10k over $400/lot -> 0.25; B (sl 4*atr) -> 0.125
    lots = dict(zip(t["strategy"], t["lots"]))
    assert lots["eng_na"] == pytest.approx(0.25)
    assert lots["eng_nb"] == pytest.approx(0.10)
    # exactly one open + one merge: netting keeps ONE book per symbol
    kinds = [(e["type"], e["bar"]) for e in res.events if e["type"] in ("open", "merge")]
    assert kinds == [("open", 15), ("merge", 20)]
    merge = next(e for e in res.events if e["type"] == "merge")
    # weighted-average book SL from the legs' own levels
    spec = synthetic_spec(EUR)
    atr = 0.002
    sl_a = round_to_tick(100.0 - enforce_min_stop(2.0 * atr, spec), spec)
    sl_b = round_to_tick(100.0 - enforce_min_stop(5.0 * atr, spec), spec)
    assert merge["sl"] == pytest.approx((0.25 * sl_a + 0.10 * sl_b) / 0.35)
    # flat market: no hidden PnL
    assert t["pnl"].sum() == pytest.approx(0.0, abs=1e-9)
    assert res.equity.iloc[-1] == pytest.approx(10_000.0)
    # gross notional reflects BOTH legs in one book
    assert res.notional.iloc[100] == pytest.approx(0.35 * 100_000.0 * 100.0)


def test_netting_opposite_partial_offset_splits_leg_fifo():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[0:120] = 1
    b = np.zeros(N, dtype=int)
    b[40] = -1  # one-shot short, acts at bar 41's open
    df["s_a"] = a
    df["s_b"] = b
    register_signal("eng_oa", a)
    register_signal("eng_ob", b)
    costs = CostConfig(symbol=EUR, spread_points=0.0, slippage_points=0.0,
                       commission_per_lot=7.0, commission_per_round_trip=True)
    cfg = RunConfig(initial_capital=10_000.0, strategy_risk={
        "eng_ob": _fixed(0.10)})
    res = engine(cfg).run([
        Instrument(symbol=EUR, strategy="eng_oa", df=df, costs=costs),
        Instrument(symbol=EUR, strategy="eng_ob", df=df, costs=costs),
    ])
    t = res.trades
    # A's 0.25 leg is split FIFO: 0.10 offset at bar 41, 0.15 exits at the flip
    assert len(t) == 2
    assert list(t["strategy"]) == ["eng_oa", "eng_oa"]
    assert list(t["lots"]) == [pytest.approx(0.10), pytest.approx(0.15)]
    assert t["exit_reason"].iloc[0] == "merge_offset"
    assert t["exit_reason"].iloc[1] == "signal_exit"
    # offset slice pays its entry-fee share (0.35) + exit fee (0.35) = 0.70
    assert t["pnl"].iloc[0] == pytest.approx(-0.70, abs=1e-6)
    # remainder keeps its own entry: full round trip on 0.15 = 1.05
    assert t["pnl"].iloc[1] == pytest.approx(-1.05, abs=1e-6)
    assert t["pnl"].sum() == pytest.approx(-1.75, abs=1e-6)  # 7.0 * 0.25


def test_netting_full_offset_remainder_reopens_fresh():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[0:120] = 1
    b = np.zeros(N, dtype=int)
    b[40] = -1  # single short order, acts at bar 41
    df["s_a"] = a
    df["s_b"] = b
    register_signal("eng_fa", a)
    register_signal("eng_fb", b)
    cfg = RunConfig(initial_capital=10_000.0, strategy_risk={
        "eng_fb": _fixed(0.30)})  # bigger than A's 0.25 book
    res = engine(cfg).run([
        Instrument(symbol=EUR, strategy="eng_fa", df=df, costs=zero_costs()),
        Instrument(symbol=EUR, strategy="eng_fb", df=df, costs=zero_costs()),
    ])
    t = res.trades
    assert len(t) == 3
    assert list(t["strategy"]) == ["eng_fa", "eng_fb", "eng_fa"]
    # bar 41: B's 0.30 offsets A's whole 0.25 book; 0.05 remainder opens short
    assert list(t["exit_reason"]) == [
        "merge_offset", "merge_offset", "signal_exit"]
    assert t["lots"].iloc[0] == pytest.approx(0.25)
    assert t["side"].iloc[1] == "short"
    assert t["lots"].iloc[1] == pytest.approx(0.05)
    # bar 42: A (still +1, no legs) offsets B's remainder and keeps 0.20 long
    assert t["lots"].iloc[2] == pytest.approx(0.20)
    opens = [e for e in res.events if e["type"] == "open"]
    assert [round(e["lots"], 6) for e in opens] == [0.25, 0.05, 0.2]
    offsets = [e for e in res.events if e["type"] == "offset"]
    assert [round(e["lots"], 6) for e in offsets] == [0.25, 0.05]
    assert res.equity.iloc[-1] == pytest.approx(10_000.0)


def test_netting_strategy_flip_reverses_and_allow_signal_exit_false_holds():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[0:39] = 1
    a[39:80] = -1  # flip at bar 40's open
    a[80:] = 0
    df["s_a"] = a
    register_signal("eng_xa", a)
    on = engine(RunConfig(initial_capital=10_000.0)).run(
        [Instrument(symbol=EUR, strategy="eng_xa", df=df, costs=zero_costs())])
    t = on.trades
    assert len(t) == 2
    # long closes when the desired flips (bar 40); the fresh short closes
    # when the strategy goes flat (bar 81) — both are signal exits
    assert list(t["exit_reason"]) == ["signal_exit", "signal_exit"]
    assert list(t["side"]) == ["long", "short"]
    assert list(t["lots"]) == [pytest.approx(0.25)] * 2
    assert res_equity_flat(on)

    off = engine(RunConfig(initial_capital=10_000.0,
                           allow_signal_exit=False)).run(
        [Instrument(symbol=EUR, strategy="eng_xa", df=df, costs=zero_costs())])
    t2 = off.trades
    assert len(t2) == 1  # hands-off: SL/TP/max-bars exits only
    assert t2["side"].iloc[0] == "long"
    assert t2["exit_reason"].iloc[0] == "end_of_data"


def test_netting_two_persistent_opponents_churn_is_deterministic():
    """Two strategies that permanently desire opposite sides on one symbol
    net against each other every bar (real netting outcome), paying the
    spread each cycle — deterministic, no runaway books."""
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[14:] = 1
    b = np.zeros(N, dtype=int)
    b[40:120] = -1
    df["s_a"] = a
    df["s_b"] = b
    register_signal("eng_pa", a)
    register_signal("eng_pb", b)
    res = engine().run([
        Instrument(symbol=EUR, strategy="eng_pa", df=df, costs=zero_costs()),
        Instrument(symbol=EUR, strategy="eng_pb", df=df, costs=zero_costs()),
    ])
    assert len(res.trades) >= 1
    assert set(res.trades["exit_reason"]) <= set(EXIT_REASONS)
    # no exposure is ever stranded: final equity back to initial
    assert res.equity.iloc[-1] == pytest.approx(10_000.0)
    assert res.notional.iloc[-1] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# hedging
# ---------------------------------------------------------------------------


def test_hedging_allows_simultaneous_opposite_books():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    b = np.zeros(N, dtype=int)
    b[40:59] = -1  # short lives bars 41..60, then goes flat
    df["s_a"] = a
    df["s_b"] = b
    register_signal("eng_ha", a)
    register_signal("eng_hb", b)
    res = engine(RunConfig(mode=MODE_HEDGING)).run([
        Instrument(symbol=EUR, strategy="eng_ha", df=df, costs=zero_costs()),
        Instrument(symbol=EUR, strategy="eng_hb", df=df, costs=zero_costs()),
    ])
    t = res.trades
    assert len(t) == 2
    sides = dict(zip(t["strategy"], t["side"]))
    assert sides == {"eng_ha": "long", "eng_hb": "short"}
    # while both are open the gross notional is the SUM of both books
    overlap = res.notional.iloc[50]
    assert overlap == pytest.approx(0.5 * 100_000.0 * 100.0)
    # no merge/offset events in hedging mode
    assert not [e for e in res.events if e["type"] in ("merge", "offset")]
    assert res.equity.iloc[-1] == pytest.approx(10_000.0)


def test_hedging_same_symbol_two_strategies_per_symbol_cap():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    b = np.zeros(N, dtype=int)
    b[40:] = 1
    df["s_a"] = a
    df["s_b"] = b
    register_signal("eng_ca", a)
    register_signal("eng_cb", b)
    # per-symbol notional share 250x equity: exactly one EURUSD book fits
    cfg = RunConfig(mode=MODE_HEDGING, per_symbol_max_notional_share=250.0)
    res = engine(cfg).run([
        Instrument(symbol=EUR, strategy="eng_ca", df=df, costs=zero_costs()),
        Instrument(symbol=EUR, strategy="eng_cb", df=df, costs=zero_costs()),
    ])
    assert len(res.trades) == 1
    codes = [e["code"] for e in res.events if e["type"] == "reject"]
    assert "per_symbol_notional" in codes


def test_hedging_flip_full_reverse():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[0:39] = 1
    a[39:80] = -1
    a[80:] = 0
    df["s_a"] = a
    register_signal("eng_ha2", a)
    res = engine(RunConfig(mode=MODE_HEDGING)).run(
        [Instrument(symbol=EUR, strategy="eng_ha2", df=df, costs=zero_costs())])
    t = res.trades
    assert len(t) == 2
    assert list(t["exit_reason"]) == ["signal_exit", "signal_exit"]
    assert list(t["side"]) == ["long", "short"]


# ---------------------------------------------------------------------------
# exposure caps (Phase 4)
# ---------------------------------------------------------------------------


def _two_symbol_runs(cfg: RunConfig) -> tuple:
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    df["s"] = a
    register_signal("eng_cap1", a)
    register_signal("eng_cap2", a)
    costs_e = zero_costs(EUR)
    costs_g = zero_costs(GBP)
    res = engine(cfg).run([
        Instrument(symbol=EUR, strategy="eng_cap1", df=df, costs=costs_e),
        Instrument(symbol=GBP, strategy="eng_cap2", df=df, costs=costs_g),
    ])
    return res


def test_max_total_positions_cap():
    res = _two_symbol_runs(RunConfig(max_total_positions=1))
    assert len(res.trades) == 1
    assert res.trades["symbol"].iloc[0] == EUR
    codes = [e["code"] for e in res.events if e["type"] == "reject"]
    assert "max_total_positions" in codes


def test_max_strategy_positions_cap():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    df["s"] = a
    register_signal("eng_ms", a)
    cfg = RunConfig(strategy_risk={"eng_ms": _positions(1)})
    res = engine(cfg).run([
        Instrument(symbol=EUR, strategy="eng_ms", df=df, costs=zero_costs(EUR)),
        Instrument(symbol=GBP, strategy="eng_ms", df=df, costs=zero_costs(GBP)),
    ])
    assert len(res.trades) == 1
    codes = [e["code"] for e in res.events if e["type"] == "reject"]
    assert "max_strategy_positions" in codes


def test_portfolio_heat_cap():
    # one EURUSD book is 2.5M notional; 400x equity allows one, not two
    res = _two_symbol_runs(RunConfig(portfolio_heat_max=400.0))
    assert len(res.trades) == 1
    codes = [e["code"] for e in res.events if e["type"] == "reject"]
    assert "portfolio_heat" in codes


def test_corr_group_cap():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    df["s"] = a
    register_signal("eng_gr1", a)
    register_signal("eng_gr2", a)
    cfg = RunConfig(corr_group_max_notional_share={"fx": 400.0})
    res = engine(cfg).run([
        Instrument(symbol=EUR, strategy="eng_gr1", df=df,
                   costs=zero_costs(EUR), corr_group="fx"),
        Instrument(symbol=GBP, strategy="eng_gr2", df=df,
                   costs=zero_costs(GBP), corr_group="fx"),
    ])
    assert len(res.trades) == 1
    codes = [e["code"] for e in res.events if e["type"] == "reject"]
    assert "corr_group_notional" in codes


def test_currency_exposure_cap():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    df["s"] = a
    register_signal("eng_cc1", a)
    register_signal("eng_cc2", a)
    cfg = RunConfig(currency_max_notional_share={"USD": 400.0})
    res = engine(cfg).run([
        Instrument(symbol=EUR, strategy="eng_cc1", df=df, costs=zero_costs(EUR)),
        Instrument(symbol=GBP, strategy="eng_cc2", df=df, costs=zero_costs(GBP)),
    ])
    assert len(res.trades) == 1
    codes = [e["code"] for e in res.events if e["type"] == "reject"]
    assert "currency_notional" in codes


def test_netting_merge_respects_per_symbol_notional_cap():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    b = np.zeros(N, dtype=int)
    b[19:] = 1
    df["s_a"] = a
    df["s_b"] = b
    register_signal("eng_pn1", a)
    register_signal("eng_pn2", b)
    # one book (0.25 lots = 2.5M) fits; the merge would push past 300x equity
    cfg = RunConfig(per_symbol_max_notional_share=300.0)
    res = engine(cfg).run([
        Instrument(symbol=EUR, strategy="eng_pn1", df=df, costs=zero_costs()),
        Instrument(symbol=EUR, strategy="eng_pn2", df=df, costs=zero_costs()),
    ])
    assert len(res.trades) == 1  # second strategy rejected at the merge
    codes = [e["code"] for e in res.events if e["type"] == "reject"]
    assert "per_symbol_notional" in codes


def test_multisymbol_portfolio_and_notional_curve():
    df_e = make_frame(N)
    df_g = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    register_signal("eng_mp1", a)
    register_signal("eng_mp2", a)
    from mql5bot.specs import synthetic_profit_to_deposit

    g_conv = synthetic_profit_to_deposit(GBP)  # 1.27 (GBPUSD fixture)
    cfg = RunConfig(initial_capital=10_000.0, strategy_risk={
        "eng_mp1": _fixed(0.25), "eng_mp2": _fixed(0.25)})
    res = engine(cfg).run([
        Instrument(symbol=EUR, strategy="eng_mp1", df=df_e, costs=zero_costs(EUR)),
        Instrument(symbol=GBP, strategy="eng_mp2", df=df_g, costs=zero_costs(GBP)),
    ])
    assert len(res.trades) == 2
    assert set(res.trades["symbol"]) == {EUR, GBP}
    assert list(res.trades["lots"]) == [pytest.approx(0.25)] * 2
    # gross notional is in DEPOSIT currency: the EUR leg converts at 1.0,
    # the GBP leg at its profit->deposit conversion
    assert res.notional.iloc[100] == pytest.approx(
        0.25 * (1.0 + g_conv) * 100_000.0 * 100.0)
    assert res.equity.iloc[-1] == pytest.approx(10_000.0)


def _fixed(lots: float):
    from mql5bot.engine import StrategyRisk

    return StrategyRisk(mode="fixed_lot", value=lots)


def _positions(n: int):
    from mql5bot.engine import StrategyRisk

    return StrategyRisk(max_open_positions=n)


def res_equity_flat(res) -> bool:
    return res.equity.iloc[-1] == pytest.approx(10_000.0)


# ---------------------------------------------------------------------------
# risk stops + server-time day resets (Phase 3)
# ---------------------------------------------------------------------------


def test_daily_loss_limit_uses_server_day_start_and_resets():
    # start exactly at the 17:00 reset instant; boundaries at 17:00 daily
    df = make_frame(N, start="2024-01-01 17:00")
    a = np.zeros(N, dtype=int)
    a[24:70] = 1  # entry at bar 25's open
    df["s_a"] = a
    register_signal("eng_dl", a)
    cfg = RunConfig(initial_capital=10_000.0,
                    clock=DayClock(reset_hour=17, reset_minute=0),
                    max_daily_loss_pct=0.5)
    # waterfall right after the entry bar: bar 25 low pierces the stop
    closes = np.full(N, 100.0)
    for i in range(25, 28):
        closes[i] = 99.9 - (i - 25) * 0.05
    df["close"] = closes
    df.loc[df.index[1:], "open"] = closes[:-1]
    df["high"] = np.maximum(df["open"], df["close"]) + 0.001
    df["low"] = np.minimum(df["open"], df["close"]) - 0.001
    res = engine(cfg).run(
        [Instrument(symbol=EUR, strategy="eng_dl", df=df, costs=zero_costs())])

    # entry at 25, intrabar stop the same bar (full 1% risk = $100)
    t = res.trades
    assert t["exit_reason"].iloc[0] == "stop_loss"
    assert t["entry_time"].iloc[0] == "2024-01-02 18:00:00"
    # equity 9900 <= day-start 10000 * 0.995 -> halt at bar 26
    halts = [e for e in res.events if e["type"] == "halt"]
    assert halts and halts[0]["code"] == "daily_loss_limit"
    assert halts[0]["bar"] == 26
    # no entries until the NEXT 17:00 server-day boundary (bar 48)
    opens = [e for e in res.events if e["type"] == "open"]
    assert opens[0]["bar"] == 25
    assert len(opens) == 2
    assert opens[1]["bar"] == 48
    assert opens[1]["time"] == "2024-01-03 17:00:00"
    day_resets = [e for e in res.events if e["type"] == "day_reset"]
    assert day_resets[0]["day_id"] == 20240102
    assert day_resets[1]["day_id"] == 20240103
    assert res.equity.iloc[-1] > 0


def test_max_drawdown_kill_switch_is_permanent():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    df["s_a"] = a
    register_signal("eng_dd", a)
    closes = np.full(N, 100.0)
    for i in range(25, 28):
        closes[i] = 99.9 - (i - 25) * 0.05
    df["close"] = closes
    df.loc[df.index[1:], "open"] = closes[:-1]
    df["high"] = np.maximum(df["open"], df["close"]) + 0.001
    df["low"] = np.minimum(df["open"], df["close"]) - 0.001
    cfg = RunConfig(initial_capital=10_000.0,
                    strategy_risk={"eng_dd": _fixed(1.5)},  # 6% risk
                    max_drawdown_pct=5.0)
    res = engine(cfg).run(
        [Instrument(symbol=EUR, strategy="eng_dd", df=df, costs=zero_costs())])
    halts = [e for e in res.events if e["type"] == "halt"]
    assert halts and halts[0]["code"] == "max_drawdown"
    halt_bar = halts[0]["bar"]
    # permanent: not even the next server day re-enables entries
    opens = [e for e in res.events if e["type"] == "open"]
    assert all(e["bar"] < halt_bar for e in opens)
    assert res.trades["exit_reason"].iloc[-1] == "stop_loss"
    assert res.equity.iloc[-1] < 9400.01


# ---------------------------------------------------------------------------
# costs in the engine (Phase 2)
# ---------------------------------------------------------------------------


def test_variable_spread_changes_entry_fill():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    df["s_a"] = a
    register_signal("eng_vs", a)
    spread = [1.0] * N
    for i in range(15, 30):
        spread[i] = 20.0  # entry happens at bar 15 (first ATR-valid bar)
    costs = CostConfig(symbol=EUR, spread_mode="variable",
                       spread_series=spread, slippage_points=0.0)
    res = engine().run([Instrument(symbol=EUR, strategy="eng_vs", df=df,
                                   costs=costs)])
    assert res.trades["entry_price"].iloc[0] == pytest.approx(
        round_to_tick(entry_fill(100.0, 1, 20.0, 0.0, 1e-5),
                      synthetic_spec(EUR)))


def test_reject_mask_and_gap_block_entries():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    df["s_a"] = a
    register_signal("eng_rm", a)
    mask = [False] * N
    mask[15] = True
    costs = CostConfig(symbol=EUR, spread_points=0.0, reject_mask=mask)
    res = engine().run([Instrument(symbol=EUR, strategy="eng_rm", df=df,
                                   costs=costs)])
    # entry rejected at 15, retried and taken at 16
    rejects = [e for e in res.events if e["type"] == "reject"]
    assert any(e["code"] == "rejected_execution" and e["bar"] == 15
               for e in rejects)
    assert res.trades["entry_time"].iloc[0] == "2024-01-01 16:00:00"

    # same reject at 15, but now the retry bar 16 opens with a >0.1% gap
    df2 = make_frame(N)
    df2["s_a"] = a
    costs2 = CostConfig(symbol=EUR, spread_points=0.0,
                        max_gap_fraction=0.001, reject_mask=mask)
    at16 = df2.index[16]
    df2.loc[at16, "open"] = 101.0  # >0.1% gap at the retry bar
    df2.loc[at16, "high"] = max(df2.loc[at16, "high"], 101.0)
    df2.loc[at16, "low"] = min(df2.loc[at16, "low"], 101.0)
    # fixed lots keep sizing independent of the ATR shock the gap bar
    # injects (risk sizing would shrink below volume_min for several bars)
    cfg2 = RunConfig(initial_capital=10_000.0,
                     strategy_risk={"eng_rm": _fixed(0.25)})
    res2 = engine(cfg2).run([Instrument(symbol=EUR, strategy="eng_rm", df=df2,
                                        costs=costs2)])
    gaps = [e for e in res2.events if e["type"] == "reject"
            and e["code"] == "gap_skipped"]
    assert gaps and gaps[0]["bar"] == 16
    # the gap only blocks that bar: the same desire retries at 17's open
    assert res2.trades["entry_time"].iloc[0] == "2024-01-01 17:00:00"


def test_swap_charged_at_every_server_day_boundary():
    df = make_frame(N)  # hourly from Jan 1 -> 8 midnight boundaries (bars 24..192)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    b = np.zeros(N, dtype=int)
    b[:] = 1
    df["s_a"] = a
    df["s_b"] = b
    register_signal("eng_sw1", a)
    register_signal("eng_sw2", b)
    costs = CostConfig(symbol=EUR, spread_points=0.0,
                       swap_long_per_lot_day=8.0)
    cfg = RunConfig(strategy_risk={"eng_sw1": _fixed(0.25),
                                   "eng_sw2": _fixed(0.25)})
    res = engine(cfg).run([
        Instrument(symbol=EUR, strategy="eng_sw1", df=df, costs=costs),
        Instrument(symbol=EUR, strategy="eng_sw2", df=df, costs=costs),
    ])
    t = res.trades
    # merged book of 0.5 lots * 8.0/lot/day * 8 boundaries = 32, split per leg
    assert len(t) == 2
    assert t["pnl"].iloc[0] == pytest.approx(-16.0, abs=1e-6)
    assert t["pnl"].iloc[1] == pytest.approx(-16.0, abs=1e-6)
    assert res.equity.iloc[-1] == pytest.approx(10_000.0 - 32.0)


def test_equity_reflects_commission_round_trip_on_merged_book():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    b = np.zeros(N, dtype=int)
    b[19:] = 1
    df["s_a"] = a
    df["s_b"] = b
    register_signal("eng_cm1", a)
    register_signal("eng_cm2", b)
    costs = CostConfig(symbol=EUR, spread_points=0.0, slippage_points=0.0,
                       commission_per_lot=10.0, commission_per_round_trip=True)
    cfg = RunConfig(strategy_risk={"eng_cm1": _fixed(0.25),
                                   "eng_cm2": _fixed(0.25)})
    res = engine(cfg).run([
        Instrument(symbol=EUR, strategy="eng_cm1", df=df, costs=costs),
        Instrument(symbol=EUR, strategy="eng_cm2", df=df, costs=costs),
    ])
    # per-leg round trip: 10.0 * lots (half charged at entry, half at exit)
    assert res.trades["pnl"].iloc[0] == pytest.approx(-2.5, abs=1e-6)
    assert res.trades["pnl"].iloc[1] == pytest.approx(-2.5, abs=1e-6)
    assert res.equity.iloc[-1] == pytest.approx(10_000.0 - 5.0)
    # ledger columns: zero spread/slippage, so costs == fees == commission
    assert res.trades["fees"].tolist() == pytest.approx([2.5, 2.5], abs=1e-6)
    assert res.trades["costs"].tolist() == pytest.approx([2.5, 2.5], abs=1e-6)


def test_trade_rows_report_spread_and_slippage_costs():
    # flat round trip at 100 with a 10-point spread and 2-point slippage:
    # every fill pays (spread/2 + slippage) = 7 ticks against the quote
    df = make_frame(N)
    a = np.ones(N, dtype=int)
    df["s_a"] = a
    register_signal("eng_ledger", a)
    costs = CostConfig(symbol=EUR, spread_points=10.0, slippage_points=2.0,
                       commission_per_lot=0.0)
    cfg = RunConfig(strategy_risk={"eng_ledger": _fixed(0.25)})
    res = engine(cfg).run([Instrument(symbol=EUR, strategy="eng_ledger",
                                      df=df, costs=costs)])
    assert len(res.trades) == 1
    row = res.trades.iloc[0]
    assert row["exit_reason"] == "end_of_data"
    # no commission/swap: fees == 0; costs == 7 ticks x 2 legs x $1 x 0.25
    assert row["fees"] == pytest.approx(0.0, abs=1e-9)
    assert row["costs"] == pytest.approx(14 * 0.25, abs=1e-6)
    # a flat round trip loses exactly its costs (pnl is net)
    assert row["pnl"] == pytest.approx(-14 * 0.25, abs=1e-6)


def test_cost_profiles_monotone_on_identical_trade_path():
    # same long trade (flat frame, one round trip held to end of data)
    # under every profile: ZERO is cost-free, BASE < STRESSED < SEVERE
    from mql5bot.costs import COST_PROFILES

    totals = {}
    for profile in COST_PROFILES:
        df = make_frame(N)
        desired = np.ones(N, dtype=int)
        df["s_a"] = desired
        register_signal("eng_prof", desired)
        res = engine().run([Instrument(
            symbol=EUR, strategy="eng_prof", df=df,
            costs=cost_profile(profile, symbol=EUR))])
        assert len(res.trades) == 1
        row = res.trades.iloc[0]
        totals[profile] = {
            "costs": float(row["costs"]), "fees": float(row["fees"]),
            "pnl": float(row["pnl"]), "lots": float(row["lots"]),
        }
    z = totals["ZERO"]
    assert z["costs"] == pytest.approx(0.0, abs=1e-9)
    assert z["fees"] == pytest.approx(0.0, abs=1e-9)
    assert z["pnl"] == pytest.approx(0.0, abs=1e-9)
    # identical trade path: same volume, monotone harsher ledger outcome
    assert len({t["lots"] for t in totals.values()}) == 1
    order = ("BASE", "STRESSED", "SEVERE")
    for a, b in itertools.pairwise(order):
        assert totals[b]["fees"] > totals[a]["fees"]
        assert totals[b]["costs"] > totals[a]["costs"]
        assert totals[b]["pnl"] < totals[a]["pnl"]


# ---------------------------------------------------------------------------
# sizing behaviour in the engine (Phase 1)
# ---------------------------------------------------------------------------


def test_margin_calc_rejects_when_margin_exceeds_free_margin():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    df["s_a"] = a
    register_signal("eng_mg", a)

    def huge_margin(lots: float) -> float:
        return 1e12

    res = engine().run([Instrument(symbol=EUR, strategy="eng_mg", df=df,
                                   costs=zero_costs(), margin_calc=huge_margin)])
    assert len(res.trades) == 0
    codes = [e["code"] for e in res.events if e["type"] == "reject"]
    assert "margin_rejected" in codes


def test_fixed_lot_override_and_below_min_rejection():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    df["s_a"] = a
    register_signal("eng_fx1", a)
    register_signal("eng_fx2", a)
    cfg = RunConfig(strategy_risk={"eng_fx1": _fixed(0.4)})
    res = engine(cfg).run([
        Instrument(symbol=EUR, strategy="eng_fx1", df=df, costs=zero_costs()),
    ])
    assert res.trades["lots"].iloc[0] == pytest.approx(0.4)

    # a 1% risk budget that cannot fit the 0.01 minimum lot is rejected
    tiny = RunConfig(initial_capital=100.0)
    df2 = make_frame(N)
    df2["s_a"] = a
    res2 = engine(tiny).run(
        [Instrument(symbol=EUR, strategy="eng_fx1", df=df2, costs=zero_costs())])
    assert len(res2.trades) == 0
    codes = [e["code"] for e in res2.events if e["type"] == "reject"]
    assert "below_min_volume" in codes


def test_walkforward_schedule_freezes_params_per_segment():
    df = make_frame(N)
    seq = np.zeros(N, dtype=int)
    seq[0:31] = 1
    seq[31:51] = -1
    seq[51:81] = 1
    seq[81:91] = 0    # flat: closes the bar-52 long at bar 82
    seq[91:] = 1     # re-entry at bar 92 with the post-60 params (sl 5*atr)
    df["s_a"] = seq
    register_signal("eng_wf", seq)
    ins = Instrument(symbol=EUR, strategy="eng_wf", df=df,
                     costs=zero_costs(), schedule=((60, {"sl_atr": 5.0}),))
    res = engine().run([ins])
    t = res.trades
    assert len(t) == 4
    # entries at bars 15/32/52 use sl_atr 2 (0.25 lots); bar 92 uses 5 (0.1)
    assert list(t["lots"].iloc[:3]) == [pytest.approx(0.25)] * 3
    assert t["lots"].iloc[-1] == pytest.approx(0.1)
    assert t["exit_reason"].iloc[-1] == "end_of_data"
    assert res.equity.iloc[-1] == pytest.approx(10_000.0)


# ---------------------------------------------------------------------------
# manage: max-bars and trailing ratchet
# ---------------------------------------------------------------------------


def test_max_bars_closes_after_held_bars():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    a[19:] = 0  # flat only AFTER the max-bars bar (reconcile uses a[18]=1)
    df["s_a"] = a
    register_signal("eng_mb", a)
    cfg = RunConfig(initial_capital=10_000.0, max_bars=5)
    res = engine(cfg).run([Instrument(symbol=EUR, strategy="eng_mb",
                                      df=df, costs=zero_costs())])
    t = res.trades
    # entry bar 15; the entry bar counts as held bar 1, so max_bars fires
    # at bar 19 and the flat desire afterwards never re-enters
    assert len(t) == 1
    row = t.iloc[0]
    assert row["exit_reason"] == "max_bars"
    assert row["exit_time"] == "2024-01-01 19:00:00"
    assert row["bars_held"] == 4
    assert res.equity.iloc[-1] == pytest.approx(10_000.0)


def test_trailing_stop_ratchets_from_previous_close():
    # steady +0.001 rise: the 2*atr trail ratchets every bar and sits at
    # c[i-1] - 0.004 (decisions use the PREVIOUS close only)
    n = 80
    closes = 100.0 + np.arange(n) * 0.001
    closes[60] = 100.045  # waterfall pierces the trailed stop
    df = make_frame(n, closes=list(closes))
    a = np.zeros(n, dtype=int)
    a[:60] = 1  # flat from row 60: the stop-out bar's close kills the desire
    df["s_a"] = a
    register_signal("eng_tr", a)
    cfg = RunConfig(initial_capital=10_000.0, trail_atr=2.0)
    res = engine(cfg).run([Instrument(symbol=EUR, strategy="eng_tr",
                                      df=df, costs=zero_costs())])
    t = res.trades
    # entry at bar 15 open (close[14]).  On this rising frame the ATR is
    # 0.003, so the 2*atr trail sits at c[i-1] - 0.006; exit at bar 60
    # intrabar on the trailed stop c[59] - 0.006 = 100.053
    entry = closes[14]
    sl = closes[59] - 0.006
    assert len(t) == 1
    assert t["exit_reason"].iloc[0] == "stop_loss"
    assert t["entry_price"].iloc[0] == pytest.approx(round_to_tick(
        entry, synthetic_spec(EUR)))
    assert t["exit_price"].iloc[0] == pytest.approx(round_to_tick(
        sl, synthetic_spec(EUR)))
    ticks = round((sl - entry) / 1e-5)
    assert t["pnl"].iloc[0] == pytest.approx(ticks * t["lots"].iloc[0])
    assert t["bars_held"].iloc[0] == 45


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def test_engine_validation_errors():
    df = make_frame(N)
    a = np.zeros(N, dtype=int)
    a[:] = 1
    df["s_a"] = a
    register_signal("eng_val", a)
    eng = engine()
    with pytest.raises(ValueError):
        eng.run([])
    with pytest.raises(ValueError):
        eng.run([Instrument(symbol=EUR, strategy="eng_val", df=df,
                            costs=zero_costs()),
                 Instrument(symbol=EUR, strategy="eng_val", df=df,
                            costs=zero_costs())])  # duplicate line
    bad = df.copy()
    bad.index = pd.date_range("2024-02-01", periods=N, freq="h")
    with pytest.raises(ValueError):
        eng.run([Instrument(symbol=EUR, strategy="eng_val", df=df,
                            costs=zero_costs()),
                 Instrument(symbol=GBP, strategy="eng_val", df=bad,
                            costs=zero_costs())])  # unaligned
    missing = df.drop(columns=["volume"])
    with pytest.raises(ValueError):
        eng.run([Instrument(symbol=EUR, strategy="eng_val",
                            df=missing.drop(columns=["close"]),
                            costs=zero_costs())])
    with pytest.raises(KeyError):
        eng.run([Instrument(symbol=EUR, strategy="no_such_strategy", df=df,
                            costs=zero_costs())])
    with pytest.raises(ValueError):
        eng.run([Instrument(symbol=EUR, strategy="eng_val", df=df,
                            costs=zero_costs(), schedule=((0, {}),))])


# ---------------------------------------------------------------------------
# plan-gate integration pins (Phase 2 partial scale-out / Phase 5 mode equivalence)
# ---------------------------------------------------------------------------


def test_partial_scale_out_closes_fraction_at_breakeven_then_holds():
    # rising series (+0.002/bar after bar 40): profit >= 1 ATR triggers the
    # partial scale-out at the next bar open; the remainder carries on with
    # a breakeven SL to the end of data
    closes = np.full(N, 100.0)
    closes[40:] = 100.0 + 0.002 * np.arange(N - 40)
    df = make_frame(N, closes=closes)
    desired = np.zeros(N, dtype=int)
    desired[45:] = 1
    df["s_a"] = desired
    register_signal("eng_partial", desired)
    cfg = RunConfig(partial_atr=1.0, partial_fraction=0.5)
    res = engine(cfg).run(
        [Instrument(symbol=EUR, strategy="eng_partial", df=df,
                    costs=zero_costs())])
    t = res.trades
    assert len(t) == 2
    assert t["exit_reason"].iloc[0] == "partial_exit"
    assert t["exit_reason"].iloc[1] == "end_of_data"
    full = t["lots"].iloc[0] + t["lots"].iloc[1]
    assert t["lots"].iloc[0] == pytest.approx(t["lots"].iloc[1], abs=1e-9)
    # risk-derived volume: 1% of 10k at an ATR-based SL distance
    assert 0.1 < full < 0.5
    assert t["pnl"].iloc[0] > 0.0  # scaled out in profit
    assert t["entry_price"].iloc[0] == pytest.approx(t["entry_price"].iloc[1])
    # remainder survived to the end: the breakeven SL was never hit
    assert t["exit_time"].iloc[1] == str(df.index[-1])


def test_netting_and_hedging_single_position_equivalence():
    # one (symbol, strategy) line, never overlapping itself: the netting and
    # hedging engines must produce the identical ledger and equity curve
    desired = np.zeros(N, dtype=int)
    desired[20:60] = 1  # long  -> flat
    desired[90:130] = -1  # short -> flat
    desired[150:190] = 1  # long  -> flat
    df = make_frame(N)
    df["s_a"] = desired
    register_signal("eng_eq_mode", desired)
    runs = {}
    for mode in (MODE_NETTING, MODE_HEDGING):
        cfg = RunConfig(mode=mode)
        runs[mode] = engine(cfg).run(
            [Instrument(symbol=EUR, strategy="eng_eq_mode", df=df,
                        costs=zero_costs())])
    a, b = runs[MODE_NETTING], runs[MODE_HEDGING]
    assert len(a.trades) == len(b.trades) == 3
    for col in ("side", "entry_time", "exit_time", "lots", "pnl", "costs"):
        assert a.trades[col].equals(b.trades[col]), col
    assert np.array_equal(a.equity.to_numpy(), b.equity.to_numpy())
    assert np.array_equal(a.notional.to_numpy(), b.notional.to_numpy())
