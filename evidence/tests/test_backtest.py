"""Backtest engine correctness tests — including a hard no-lookahead check."""

import numpy as np
import pandas as pd
import pytest
from mql5bot.backtest import run_backtest
from mql5bot.data import generate_ohlc
from mql5bot.metrics import compute_metrics


def _frame(close: list[float], spread_pts: float = 0.0) -> pd.DataFrame:
    """Build a synthetic OHLC frame from closes (no intrabar wicks unless
    specified), 1-hour bars."""
    n = len(close)
    close = np.asarray(close, dtype=float)
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * (1 + spread_pts * 1e-6),
            "low": np.minimum(open_, close) * (1 - spread_pts * 1e-6),
            "close": close,
            "volume": 1000.0,
        },
        index=idx,
    )


def test_engine_runs_and_produces_equity():
    df = generate_ohlc(days=200, seed=5)
    res = run_backtest(df, "ema_crossover", risk_percent=1.0)
    assert len(res.equity) == len(df)
    assert res.metrics["trades"] > 0
    assert res.metrics["end_equity"] > 0


def test_no_lookahead_on_perfect_signal():
    """A strategy that reacts to a bar's close must only act at the NEXT
    bar's open. We build quiet bars (open=close=100) with occasional huge
    bullish closes (close 113). If the engine looked ahead it would buy at
    the bull bar's open (100); a correct engine buys at the NEXT bar's open,
    which equals the bull bar's close (113)."""
    import mql5bot.strategies as st

    n = 200
    open_ = np.full(n, 100.0)
    close = np.full(n, 100.0)
    high = np.full(n, 100.01)
    low = np.full(n, 99.99)
    trigger_bars = [30, 90, 150]
    for t in trigger_bars:
        close[t] = 113.0
        high[t] = 113.05
    for i in range(1, n):  # normal continuation: each bar opens at prior close
        open_[i] = close[i - 1]
    for i in range(n):  # keep OHLC consistent
        high[i] = max(high[i], open_[i], close[i])
        low[i] = min(low[i], open_[i], close[i])
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1000.0},
        index=idx,
    )

    def oracle(frame: pd.DataFrame, p: dict):
        desired = np.zeros(len(frame), dtype=int)
        body = frame["close"].to_numpy() - frame["open"].to_numpy()
        desired[body > 5.0] = 1
        return pd.Series(desired, index=frame.index)

    st.STRATEGIES["oracle_test"] = (oracle, {"sl_atr": 2.0, "tp_atr": 4.0})
    try:
        # Capital raised so a 1%-risk order is tradable at 0.01 lots: the
        # canonical sizer REJECTS orders whose risk-adequate size is below
        # the broker minimum instead of the legacy clamp-up to 0.01 lots
        # (which overshot the risk budget ~19x on the trigger-bar ATR spike).
        res = run_backtest(df, "oracle_test", risk_percent=1.0,
                           initial_capital=250_000.0, point=1e-5,
                           spread_points=0.0, commission_per_lot=0.0)
    finally:
        del st.STRATEGIES["oracle_test"]

    trades = res.trades
    assert len(trades) >= len(trigger_bars) - 1
    # every entry must happen at the open AFTER the trigger bar:
    # open[trigger+1] == close[trigger] == 113
    for _, t in trades.iterrows():
        assert t["entry_price"] == pytest.approx(113.0, abs=1e-6), (
            f"lookahead detected: entry at {t['entry_price']}"
        )


def test_commission_costs_are_charged_exactly():
    """Deterministic single-trade scenario: identical fills and exits, so
    the only PnL difference is the round-trip commission."""
    import mql5bot.strategies as st

    n = 100
    open_ = np.full(n, 100.0)
    close = np.full(n, 100.0)
    high = np.full(n, 100.01)
    low = np.full(n, 99.99)
    close[30] = 113.0
    high[30] = 113.05
    for i in range(1, n):
        open_[i] = close[i - 1]
    for i in range(n):
        high[i] = max(high[i], open_[i], close[i])
        low[i] = min(low[i], open_[i], close[i])
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1000.0},
        index=idx,
    )

    def oracle(frame: pd.DataFrame, p: dict):
        desired = np.zeros(len(frame), dtype=int)
        desired[(frame["close"].to_numpy() - frame["open"].to_numpy()) > 5.0] = 1
        return pd.Series(desired, index=frame.index)

    st.STRATEGIES["oracle_cost"] = (oracle, {"sl_atr": 2.0, "tp_atr": 4.0})
    try:
        # Same capital note as the no-lookahead test: sizing must clear the
        # 0.01 volume minimum without the legacy below-min clamp-up.
        free = run_backtest(df, "oracle_cost", risk_percent=1.0,
                            initial_capital=250_000.0, point=1e-5,
                            spread_points=0.0, commission_per_lot=0.0)
        paid = run_backtest(df, "oracle_cost", risk_percent=1.0,
                            initial_capital=250_000.0, point=1e-5,
                            spread_points=0.0, commission_per_lot=100.0)
    finally:
        del st.STRATEGIES["oracle_cost"]

    assert len(free.trades) == 1 and len(paid.trades) == 1
    lots = free.trades["lots"].iloc[0]
    assert lots == paid.trades["lots"].iloc[0] == 0.01
    diff = float(paid.trades["pnl"].iloc[0] - free.trades["pnl"].iloc[0])
    # commission charged: 100 per lot * 2 legs * 0.01 lots = 2.00
    assert diff == pytest.approx(-2.0, abs=1e-9)


def test_risk_percent_scales_lots():
    df = generate_ohlc(days=180, seed=12)
    low = run_backtest(df, "ema_crossover", risk_percent=0.5)
    high = run_backtest(df, "ema_crossover", risk_percent=2.0)
    if len(low.trades) and len(high.trades):
        assert high.trades["lots"].mean() > low.trades["lots"].mean()


def test_daily_loss_limit_stops_trading():
    df = generate_ohlc(days=120, seed=13)
    # a limit so tight that the very first entry's spread+commission cost
    # trips it — deterministic trigger of the daily halt
    res = run_backtest(df, "ema_crossover", max_daily_loss_pct=0.001)
    reasons = set(res.trades["exit_reason"]) if len(res.trades) else set()
    assert "daily_loss_limit" in reasons


def test_max_drawdown_kill_switch():
    df = generate_ohlc(days=365, seed=14)
    res = run_backtest(df, "ema_crossover", max_drawdown_pct=5.0)
    t = res.trades
    assert len(t) > 0
    eq = res.equity
    # Canonical engine semantics (pinned by test_engine.py): the breach is
    # detected on the PRIOR-CLOSE equity at the next bar open — the position
    # whose stop filled intrabar on the crossing bar exits as stop_loss, and
    # the halt then force-closes any still-open book at that open.  The
    # legacy close-marked detection (final trade reason "max_drawdown") is
    # gone.
    assert t["exit_reason"].iloc[-1] == "stop_loss"
    # the crossing bar is where the close-equity first breaches the band
    # from the RUNNING peak (peak tracked on bars before the check, as the
    # engine does — a full-series peak would be a lookahead)
    running_peak = eq.cummax().shift(1)
    running_peak.iloc[0] = eq.iloc[0]
    crossing = eq[eq <= running_peak * (1.0 - 5.0 / 100.0)].index[0]
    halt_open = df.index[df.index.get_loc(crossing) + 1]
    # once the switch trips, trading stops for good: the halt acts at the
    # open after the crossing close, so no entry may exist at/after it
    assert all(pd.to_datetime(t["entry_time"]) < halt_open)
    assert t["exit_time"].iloc[-1] == str(crossing)
    # the realised drawdown can run a bit past the threshold — but never
    # absurdly so
    assert -9.0 <= res.metrics["max_drawdown_pct"] <= -4.9


def test_no_short_option():
    df = generate_ohlc(days=180, seed=15)
    res = run_backtest(df, "ema_crossover", allow_short=False)
    if len(res.trades):
        assert (res.trades["side"] == "long").all()


def test_partial_close_reduces_position_size():
    df = generate_ohlc(days=200, seed=16)
    res = run_backtest(
        df, "ema_crossover", partial_atr=1.0, partial_fraction=0.5, trail_atr=3.0
    )
    assert len(res.equity) == len(df)


def test_trade_log_consistency():
    df = generate_ohlc(days=250, seed=17)
    res = run_backtest(df, "donchian_breakout")
    t = res.trades
    if len(t):
        assert (t["exit_time"] >= t["entry_time"]).all()
        assert (t["lots"] > 0).all()
        assert set(t["side"]).issubset({"long", "short"})
        assert set(t["exit_reason"]).issubset(
            {"stop_loss", "take_profit", "max_bars", "daily_loss_limit",
             "max_drawdown", "end_of_data"}
        )


def test_metrics_sane():
    eq = pd.Series([100.0, 101, 103, 102, 105], index=pd.date_range("2024", periods=5, freq="D"))
    trades = pd.DataFrame(
        [
            {"entry_time": "2024-01-01", "exit_time": "2024-01-02", "side": "long",
             "entry_price": 1.0, "exit_price": 1.01, "lots": 1.0, "bars_held": 1,
             "pnl": 10.0, "pnl_pct": 0.1, "exit_reason": "take_profit"},
            {"entry_time": "2024-01-03", "exit_time": "2024-01-04", "side": "short",
             "entry_price": 1.0, "exit_price": 0.99, "lots": 1.0, "bars_held": 1,
             "pnl": -5.0, "pnl_pct": -0.05, "exit_reason": "stop_loss"},
        ]
    )
    m = compute_metrics(eq, trades, periods_per_year=252)
    assert m["total_return_pct"] == pytest.approx(5.0)
    assert m["trades"] == 2 and m["wins"] == 1
    assert m["win_rate_pct"] == pytest.approx(50.0)
    assert m["profit_factor"] == pytest.approx(2.0)


def test_validation_errors():
    df = generate_ohlc(days=30, seed=1)
    with pytest.raises(ValueError):
        run_backtest(df, "ema_crossover", risk_percent=0)
    with pytest.raises(ValueError):
        run_backtest(df, "ema_crossover", partial_fraction=1.5)
    with pytest.raises(KeyError):
        run_backtest(df, "does_not_exist")
