"""Performance-statistics tests (mql5bot.metrics) — Phase 8 extension.

Covers the classic core (unchanged) plus recovery factor, ulcer index,
downside deviation, tail loss (VaR/CVaR), rolling Sharpe, median/average
trade and duration, exposure/turnover approximations, max consecutive
losses, return concentration, top-N contribution, recent expectancy and
monthly consistency.  All statistics are pinned against hand-computable
fixtures; no single metric is asserted as a selection driver.
"""

import numpy as np
import pandas as pd
import pytest
from mql5bot.metrics import compute_metrics, monthly_returns

# ---------------------------------------------------------------------------
# Fixtures (hand-computable)
# ---------------------------------------------------------------------------


def _equity() -> pd.Series:
    vals = [100.0, 102, 101, 105, 104, 108, 110, 107, 112, 116]
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    return pd.Series(vals, index=idx, name="equity")


def _pnl_trades() -> pd.DataFrame:
    pnl = [10.0, -4.0, 8.0, -2.0, 6.0, -1.0, 10.0]
    return pd.DataFrame(
        {
            "entry_time": [f"2024-01-0{i+1}" for i in range(7)],
            "exit_time": [f"2024-01-1{i+1}" for i in range(7)],
            "side": ["long"] * 7,
            "entry_price": [100.0] * 7,
            "exit_price": [101.0] * 7,
            "lots": [1.0] * 7,
            "bars_held": [1, 2, 3, 4, 5, 6, 7],
            "pnl": pnl,
            "pnl_pct": [p / 10_000.0 for p in pnl],
            "exit_reason": ["take_profit", "stop_loss", "take_profit",
                            "stop_loss", "take_profit", "stop_loss",
                            "take_profit"],
        }
    )


# ---------------------------------------------------------------------------
# core statistics stay put
# ---------------------------------------------------------------------------


def test_core_statistics_unchanged():
    m = compute_metrics(_equity(), _pnl_trades(), periods_per_year=252)
    assert m["total_return_pct"] == pytest.approx(16.0, abs=1e-3)
    assert m["start_equity"] == 100.0 and m["end_equity"] == 116.0
    assert m["bars"] == 10
    assert m["trades"] == 7
    assert m["wins"] == 4 and m["losses"] == 3
    assert m["net_profit"] == pytest.approx(27.0, abs=1e-3)
    assert m["profit_factor"] == pytest.approx(34.0 / 7.0, abs=1e-3)  # 10+8+6+10 / 4+2+1
    assert m["expectancy"] == pytest.approx(27.0 / 7.0, abs=1e-3)
    assert m["max_drawdown_pct"] == pytest.approx(-3.0 / 110.0 * 100.0, abs=1e-3)


# ---------------------------------------------------------------------------
# drawdown-derived additions
# ---------------------------------------------------------------------------


def test_recovery_factor_and_ulcer_index():
    m = compute_metrics(_equity(), periods_per_year=252)
    total = 116.0 / 100.0 - 1.0
    dd = _equity() / _equity().cummax() - 1.0
    max_dd = dd.min()
    assert m["recovery_factor"] == pytest.approx(total / abs(max_dd), abs=1e-3)
    ulcer = float(np.sqrt((dd**2).mean())) * 100.0
    assert m["ulcer_index_pct"] == pytest.approx(ulcer, abs=1e-3)
    # no-drawdown curve: recovery None, ulcer 0
    up = pd.Series(np.linspace(100, 200, 50),
                   index=pd.date_range("2024-01-01", periods=50, freq="D"))
    m2 = compute_metrics(up, periods_per_year=252)
    assert m2["recovery_factor"] is None
    assert m2["ulcer_index_pct"] == pytest.approx(0.0)
    assert m2["max_drawdown_pct"] == 0.0


def test_downside_deviation_and_tail_loss():
    eq = _equity()
    rets = eq.pct_change().dropna()
    m = compute_metrics(eq, periods_per_year=252)
    neg2 = (rets.clip(upper=0.0) ** 2).mean()
    assert m["downside_deviation_pct"] == pytest.approx(
        float(np.sqrt(neg2)) * np.sqrt(252.0) * 100.0, abs=1e-3)
    var95 = rets.quantile(0.05)
    cvar95 = rets[rets <= var95].mean()
    assert m["var_95_pct"] == pytest.approx(float(var95) * 100.0, abs=1e-3)
    assert m["cvar_95_pct"] == pytest.approx(float(cvar95) * 100.0, abs=1e-3)
    var99 = rets.quantile(0.01)
    cvar99 = rets[rets <= var99].mean()
    assert m["var_99_pct"] == pytest.approx(float(var99) * 100.0, abs=1e-3)
    assert m["cvar_99_pct"] == pytest.approx(float(cvar99) * 100.0, abs=1e-3)
    # losses are all -1/102-ish days; VaR must be negative
    assert m["var_95_pct"] < 0.0 and m["cvar_95_pct"] < 0.0


# ---------------------------------------------------------------------------
# trade-log additions
# ---------------------------------------------------------------------------


def test_trade_median_duration_streaks_and_concentration():
    m = compute_metrics(_equity(), _pnl_trades(), periods_per_year=252)
    # pnl = [10, -4, 8, -2, 6, -1, 10]
    assert m["avg_trade"] == pytest.approx(27.0 / 7.0, abs=1e-3)
    assert m["median_trade"] == pytest.approx(6.0, abs=1e-3)
    assert m["avg_trade_bars"] == pytest.approx(4.0, abs=1e-3)
    assert m["median_trade_bars"] == pytest.approx(4.0, abs=1e-3)
    assert m["max_consecutive_losses"] == 1
    # |pnl| = [10,4,8,2,6,1,10] -> HHI = 321/1681
    assert m["return_concentration_hhi"] == pytest.approx(321.0 / 1681.0, abs=1e-3)
    # top-5 pnl = 10+10+8+6-1 = 33 of net 27
    assert m["top5_trades_pct"] == pytest.approx(33.0 / 27.0 * 100.0, abs=1e-3)
    # trailing-20 (all rows) expectancy = mean pnl, win rate 4/7
    assert m["expectancy_last20"] == pytest.approx(27.0 / 7.0, abs=1e-3)
    assert m["win_rate_last20_pct"] == pytest.approx(4.0 / 7.0 * 100.0, abs=1e-3)


def test_consecutive_loss_streak():
    trades = _pnl_trades().copy()
    trades["pnl"] = [-4.0, -3.0, 10.0, -2.0, -1.0, -0.5, 8.0]
    m = compute_metrics(_equity(), trades, periods_per_year=252)
    assert m["max_consecutive_losses"] == 3


def test_exposure_and_turnover_approximations():
    n = 200
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    eq = pd.Series(np.linspace(100, 110, n), index=idx)
    rows = []
    # bars 5..15, 10..20 (overlap), 100..110 — union 5..20 and 100..110
    for e, x in ((5, 15), (10, 20), (100, 110)):
        rows.append({
            "entry_time": str(idx[e]), "exit_time": str(idx[x]),
            "side": "long", "entry_price": 100.0, "exit_price": 101.0,
            "lots": 1.0, "bars_held": x - e, "pnl": 1.0, "pnl_pct": 1e-4,
            "exit_reason": "take_profit",
        })
    m = compute_metrics(eq, pd.DataFrame(rows), periods_per_year=24 * 365.25)
    # union = bars 5..20 (16 bars) + bars 100..110 (11 bars) = 27/200
    assert m["exposure_pct"] == pytest.approx(27.0 / 200.0 * 100.0, abs=1e-3)
    # each row occupies 11 inclusive bars at 1.0 lots; closed lots = 3
    assert m["turnover_pct"] == pytest.approx(3.0 / 33.0 * 100.0, abs=1e-3)
    assert m["avg_trade_bars"] == pytest.approx(10.0, abs=1e-3)  # bars_held = x - e


# ---------------------------------------------------------------------------
# monthly / rolling additions
# ---------------------------------------------------------------------------


def test_monthly_consistency_statistics():
    # daily equity over 3 calendar months; February is a down month
    idx = pd.date_range("2024-01-01", periods=91, freq="D")  # jan+feb+mar1
    vals = []
    v = 100.0
    for t in idx:
        if t.month == 2:
            v *= 0.99  # monotone decline inside February
        else:
            v *= 1.01
        vals.append(v)
    eq = pd.Series(vals, index=idx)
    m = compute_metrics(eq, periods_per_year=252)
    mr = monthly_returns(eq)
    assert m["monthly_win_rate_pct"] == pytest.approx(
        float((mr["return_pct"] > 0).mean()) * 100.0, abs=1e-3)
    assert m["monthly_avg_pct"] == pytest.approx(mr["return_pct"].mean(), abs=1e-3)
    assert m["monthly_std_pct"] == pytest.approx(
        mr["return_pct"].std(ddof=0), abs=1e-3)
    # Jan up, Feb down, so exactly one losing month out of two full months
    assert m["monthly_win_rate_pct"] == pytest.approx(50.0, abs=1e-3)


def test_rolling_sharpe_present_on_long_series():
    rng = np.random.default_rng(7)
    steps = rng.normal(0.0005, 0.01, 2000)
    eq = pd.Series(100.0 * np.exp(np.cumsum(steps)),
                   index=pd.date_range("2020-01-01", periods=2000, freq="D"))
    m = compute_metrics(eq, periods_per_year=252)
    assert m["rolling_sharpe_median"] is not None
    assert m["rolling_sharpe_worst"] is not None
    assert m["rolling_sharpe_worst"] <= m["rolling_sharpe_median"]
    # median of the rolling series equals recomputation
    rets = eq.pct_change().dropna()
    window = max(20, round(252 * 0.5))
    rm = rets.rolling(window).mean() * 252
    rs = rets.rolling(window).std(ddof=0) * np.sqrt(252)
    roll = (rm / rs).dropna()
    assert m["rolling_sharpe_median"] == pytest.approx(roll.median(), abs=1e-3)
    assert m["rolling_sharpe_worst"] == pytest.approx(roll.min(), abs=1e-3)


def test_short_series_and_empty_schema():
    short = pd.Series([100.0], index=pd.date_range("2024-01-01", periods=1))
    m = compute_metrics(short, _pnl_trades(), periods_per_year=252)
    assert m["bars"] == 0 and m["total_return_pct"] is None
    for key in (
        "recovery_factor", "ulcer_index_pct", "downside_deviation_pct",
        "var_95_pct", "cvar_99_pct", "rolling_sharpe_median",
        "avg_trade", "median_trade", "exposure_pct", "turnover_pct",
        "return_concentration_hhi", "top5_trades_pct",
        "expectancy_last20", "monthly_win_rate_pct",
    ):
        assert key in m
    assert m["max_consecutive_losses"] == 0
    # deterministic: same input -> same report
    m2 = compute_metrics(_equity(), _pnl_trades(), periods_per_year=252)
    assert m2 == compute_metrics(_equity(), _pnl_trades(),
                                 periods_per_year=252)


# ---------------------------------------------------------------------------
# robust fitness composite score (Phase B)
# ---------------------------------------------------------------------------


def _rich_metrics():
    """Full-schema metrics whose components map to clean contributions."""
    return {
        "start_equity": 10_000.0,
        "expectancy": 40.0,            # 0.4 % of equity = 2x base -> 1.0
        "recovery_factor": 3.0,        # 3x ref -> 1.0
        "rolling_sharpe_median": 2.0,  # 2x ref -> 1.0
        "net_profit": 1_000.0,
        "max_drawdown_pct": -25.0,     # 2.5x ref -> penalty 1.0 -> 0.0
        "return_concentration_hhi": 0.8,
        "turnover_pct": 500.0,
        "rolling_sharpe_worst": -3.0,
    }


def test_composite_score_pinned_fixtures():
    from mql5bot.metrics import RobustFitnessConfig, composite_score

    cfg = RobustFitnessConfig()
    m = _rich_metrics()
    out = composite_score(m, cfg, stressed_metrics={"net_profit": 600.0})
    # 600/1000 = 0.6 vs resilience_ref 0.5 -> 1.0
    assert out["score"] == pytest.approx(0.70, abs=1e-6)
    assert out["resilience_measured"] is True
    comps = out["components"]
    assert comps["expectancy"] == pytest.approx(1.0)
    assert comps["calmar"] == pytest.approx(1.0)
    assert comps["stability"] == pytest.approx(1.0)
    assert comps["resilience"] == pytest.approx(1.0)
    assert comps["drawdown"] == pytest.approx(0.0)
    assert comps["concentration"] == pytest.approx(0.0)
    assert comps["turnover"] == pytest.approx(0.0)
    assert comps["instability"] == pytest.approx(0.0)

    # moderate fixture: every component at exactly its 0.5 contribution
    half = {
        "start_equity": 10_000.0,
        "expectancy": 10.0,            # 0.1 % of equity = 0.5 x base
        "recovery_factor": 0.5,        # 0.5 x ref
        "rolling_sharpe_median": 0.5,  # 0.5 x ref
        "net_profit": 1_000.0,
        "max_drawdown_pct": -5.0,      # penalty 0.5
        "return_concentration_hhi": 0.25,
        "turnover_pct": 100.0,
        "rolling_sharpe_worst": -0.5,
    }
    out2 = composite_score(half, cfg, stressed_metrics={"net_profit": 200.0})
    # resilience: 200/1000 = 0.2 vs ref 0.5 -> 0.4, not neutral
    assert out2["components"]["resilience"] == pytest.approx(0.4)
    # all non-resilience components land on 0.5
    for k in ("expectancy", "calmar", "stability", "drawdown",
              "concentration", "turnover", "instability"):
        assert out2["components"][k] == pytest.approx(0.5), k


def test_composite_score_missing_metrics_are_neutral_and_stress_opt_in():
    from mql5bot.metrics import RobustFitnessConfig, composite_score

    cfg = RobustFitnessConfig()
    bare = {"start_equity": 10_000.0, "net_profit": 100.0}
    out = composite_score(bare, cfg)  # no stressed metrics -> neutral
    assert out["resilience_measured"] is False
    for k in cfg.weights:
        assert out["components"][k] == pytest.approx(0.5), k
    assert out["score"] == pytest.approx(0.5, abs=1e-6)
    # a degenerate run (None everywhere except equity) still scores neutrally
    degenerate = {k: None for k in _rich_metrics()}
    degenerate["start_equity"] = 10_000.0
    out3 = composite_score(degenerate, cfg)
    assert out3["score"] == pytest.approx(0.5, abs=1e-6)


def test_composite_config_validation_and_determinism():
    from mql5bot.metrics import RobustFitnessConfig, composite_score

    with pytest.raises(ValueError):
        RobustFitnessConfig(w_expectancy=0.8, w_calmar=0.1)  # sum != 1
    with pytest.raises(ValueError):
        RobustFitnessConfig(drawdown_ref=0.0)
    with pytest.raises(ValueError):
        RobustFitnessConfig(w_stability=-0.1)
    a = composite_score(_rich_metrics(), RobustFitnessConfig())
    b = composite_score(_rich_metrics(), RobustFitnessConfig())
    assert a == b
