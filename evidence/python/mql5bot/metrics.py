"""mql5bot.metrics — performance statistics for equity curves and trades."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def compute_metrics(
    equity: pd.Series,
    trades: pd.DataFrame | None = None,
    *,
    periods_per_year: float = 252.0,
    risk_free_annual: float = 0.0,
) -> dict:
    """Compute a full performance report from an equity curve and trade log.

    All NaN-producing statistics (e.g. Sharpe with zero variance) are
    reported as ``None``.
    """
    equity = pd.Series(equity, dtype=float).dropna()
    if len(equity) < 2:
        return _empty_metrics()

    returns = equity.pct_change().dropna()
    n_bars = len(equity)
    years = max(n_bars / periods_per_year, 1e-9)

    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0

    std = returns.std(ddof=0)
    ann_vol = std * np.sqrt(periods_per_year) if std > 0 else None
    sharpe = (
        (returns.mean() * periods_per_year - risk_free_annual) / (std * np.sqrt(periods_per_year))
        if std > 0
        else None
    )
    downside = returns[returns < 0]
    dstd = downside.std(ddof=0) if len(downside) else 0.0
    sortino = (
        (returns.mean() * periods_per_year - risk_free_annual) / (dstd * np.sqrt(periods_per_year))
        if dstd > 0
        else None
    )

    # drawdown
    running_peak = equity.cummax()
    dd = equity / running_peak - 1.0
    max_dd = dd.min()
    max_dd_duration = _longest_dd_run(dd) if max_dd < 0 else 0
    calmar = cagr / abs(max_dd) if max_dd < 0 else None

    # trade statistics
    trade_stats = _trade_stats(trades) if trades is not None and len(trades) else {}
    ext_stats = _extended_stats(equity, returns, dd, max_dd, total_return,
                                trades, n_bars, periods_per_year,
                                risk_free_annual)

    out = {
        "start": str(equity.index[0]),
        "end": str(equity.index[-1]),
        "bars": int(n_bars),
        "years": round(float(years), 4),
        "start_equity": float(equity.iloc[0]),
        "end_equity": float(equity.iloc[-1]),
        "total_return_pct": _r(total_return * 100.0),
        "cagr_pct": _r(cagr * 100.0),
        "annual_vol_pct": _r(ann_vol * 100.0) if ann_vol is not None else None,
        "sharpe": _r(sharpe),
        "sortino": _r(sortino),
        "max_drawdown_pct": _r(max_dd * 100.0) if max_dd is not None else None,
        "max_dd_duration_bars": int(max_dd_duration),
        "calmar": _r(calmar),
        "best_bar_pct": _r(returns.max() * 100.0),
        "worst_bar_pct": _r(returns.min() * 100.0),
        "avg_bar_pct": _r(returns.mean() * 100.0),
    }
    out.update(ext_stats)
    out.update(trade_stats)
    return out


def _trade_stats(trades: pd.DataFrame) -> dict:
    t = trades.copy()
    pnl = pd.to_numeric(t["pnl"], errors="coerce")
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    n = len(pnl)
    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (np.inf if gross_profit > 0 else None)
    win_rate = len(wins) / n * 100.0 if n else None
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = losses.mean() if len(losses) else 0.0
    payoff = avg_win / abs(avg_loss) if avg_loss else (np.inf if avg_win > 0 else None)
    expectancy = pnl.mean() if n else None
    return {
        "trades": int(n),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": _r(win_rate),
        "profit_factor": _r(profit_factor),
        "avg_win": _r(avg_win),
        "avg_loss": _r(avg_loss),
        "payoff_ratio": _r(payoff),
        "expectancy": _r(expectancy),
        "net_profit": _r(pnl.sum()),
    }


def _extended_stats(equity, returns, dd, max_dd, total_return, trades,
                    n_bars, ppy, risk_free_annual) -> dict:
    """Phase-8 statistics: recovery/ulcer/downside-dev, tail loss, rolling
    Sharpe, deeper trade stats (median, duration, streaks, concentration,
    top-N contribution, exposure/turnover, recent expectancy) and monthly
    consistency.  No single metric is treated as the selection driver —
    consumers compose them (see Phase 9 fitness).

    Exposure/turnover are position-based approximations from the trade log
    (no account/contract context here): ``exposure_pct`` = share of bars
    with at least one open row (interval [entry, exit] inclusive);
    ``turnover_pct`` = 100 x closed lots / open lot-bars, i.e. 100 divided
    by the lots-weighted average holding period in bars.
    """
    out: dict = {}

    # ---- drawdown-derived ------------------------------------------------
    if max_dd is not None and max_dd < 0:
        out["recovery_factor"] = _r(total_return / abs(max_dd))
        out["ulcer_index_pct"] = _r(float(np.sqrt((dd ** 2).mean())) * 100.0)
    else:
        out["recovery_factor"] = None
        out["ulcer_index_pct"] = 0.0
    neg2 = (returns.clip(upper=0.0) ** 2).mean()
    out["downside_deviation_pct"] = _r(
        float(np.sqrt(neg2)) * np.sqrt(ppy) * 100.0)

    # ---- tail loss on bar returns ----------------------------------------
    for q, suffix in ((0.05, "95"), (0.01, "99")):
        var = returns.quantile(q)
        cvar = returns[returns <= var].mean() if len(returns) else np.nan
        out[f"var_{suffix}_pct"] = _r(float(var) * 100.0)
        out[f"cvar_{suffix}_pct"] = _r(float(cvar) * 100.0)

    # ---- rolling Sharpe (median + worst of trailing windows) -------------
    window = max(20, round(ppy * 0.5))
    if len(returns) >= window + 2:
        rm = returns.rolling(window).mean() * ppy - risk_free_annual
        rs = returns.rolling(window).std(ddof=0) * np.sqrt(ppy)
        roll = (rm / rs).dropna()
        if len(roll):
            out["rolling_sharpe_median"] = _r(roll.median())
            out["rolling_sharpe_worst"] = _r(roll.min())
    if "rolling_sharpe_median" not in out:
        out["rolling_sharpe_median"] = None
        out["rolling_sharpe_worst"] = None

    # ---- monthly consistency ----------------------------------------------
    if isinstance(equity.index, pd.DatetimeIndex) and len(equity) >= 2:
        m = monthly_returns(equity)
        if len(m):
            pos = (m["return_pct"] > 0).mean()
            out["monthly_win_rate_pct"] = _r(pos * 100.0)
            out["monthly_avg_pct"] = _r(m["return_pct"].mean())
            out["monthly_std_pct"] = _r(m["return_pct"].std(ddof=0))
    out.setdefault("monthly_win_rate_pct", None)
    out.setdefault("monthly_avg_pct", None)
    out.setdefault("monthly_std_pct", None)

    # ---- trade-log statistics (all require the log) ------------------------
    if trades is None or not len(trades):
        out.update({
            "avg_trade": None, "median_trade": None,
            "avg_trade_bars": None, "median_trade_bars": None,
            "exposure_pct": None, "turnover_pct": None,
            "max_consecutive_losses": 0, "return_concentration_hhi": None,
            "top5_trades_pct": None, "expectancy_last20": None,
            "win_rate_last20_pct": None,
        })
        return out

    t = trades.copy()
    pnl = pd.to_numeric(t["pnl"], errors="coerce").dropna()
    if len(pnl):
        out["avg_trade"] = _r(pnl.mean())
        out["median_trade"] = _r(pnl.median())
        # return concentration (HHI over |pnl| shares) and top-5 contribution
        denom = pnl.abs().sum()
        if denom > 0:
            shares = (pnl.abs() / denom)
            out["return_concentration_hhi"] = _r(float((shares ** 2).sum()))
            net = pnl.sum()
            if net != 0:
                top5 = pnl.nlargest(5).sum()
                out["top5_trades_pct"] = _r(float(top5 / net) * 100.0)
        # max consecutive losing trades
        streak = best = 0
        for v in pnl:
            if v < 0:
                streak += 1
                best = max(best, streak)
            else:
                streak = 0
        out["max_consecutive_losses"] = int(best)
        # recent expectancy: trailing 20 closed trades
        last20 = pnl.tail(20)
        out["expectancy_last20"] = _r(float(last20.mean()))
        out["win_rate_last20_pct"] = _r(
            float((last20 > 0).mean()) * 100.0)
    out.setdefault("avg_trade", None)
    out.setdefault("median_trade", None)
    out.setdefault("return_concentration_hhi", None)
    out.setdefault("top5_trades_pct", None)
    out.setdefault("max_consecutive_losses", 0)
    out.setdefault("expectancy_last20", None)
    out.setdefault("win_rate_last20_pct", None)

    # ---- duration / exposure / turnover ------------------------------------
    if "bars_held" in t.columns:
        held = pd.to_numeric(t["bars_held"], errors="coerce").dropna()
        if len(held):
            out["avg_trade_bars"] = _r(float(held.mean()))
            out["median_trade_bars"] = _r(float(held.median()))
    out.setdefault("avg_trade_bars", None)
    out.setdefault("median_trade_bars", None)

    try:
        exposure, turnover = _exposure_turnover(equity, t, n_bars)
        out["exposure_pct"] = _r(exposure)
        out["turnover_pct"] = _r(turnover)
    except (KeyError, ValueError, TypeError):  # malformed log entries
        out["exposure_pct"] = None
        out["turnover_pct"] = None
    return out


def _exposure_turnover(equity: pd.Series, trades: pd.DataFrame,
                       n_bars: int) -> tuple[float, float]:
    """Position-based exposure/turnover approximations (see
    :func:`_extended_stats`)."""
    import numpy as _np

    idx = equity.index
    if not isinstance(idx, pd.DatetimeIndex) or not len(trades):
        return 0.0, 0.0
    pos = _np.zeros(n_bars, dtype=int)  # bars with >= 1 open row
    lot_bars = 0.0  # open lots x bars (area under the open-lots curve)
    closed_lots = 0.0
    for row in trades.itertuples(index=False):
        try:
            e = idx.get_loc(pd.Timestamp(row.entry_time))
            x = idx.get_loc(pd.Timestamp(row.exit_time))
        except (KeyError, ValueError, TypeError):
            continue
        if x < e:
            e, x = x, e
        # a row occupies bars [e, x] inclusive (same-bar exits = 1 bar)
        pos[e:x + 1] = 1
        lots = float(row.lots) if row.lots is not None else 0.0
        lot_bars += lots * max(x - e + 1, 0)
        closed_lots += abs(lots)
    exposure = 100.0 * float(pos.sum()) / n_bars if n_bars else 0.0
    turnover = 100.0 * closed_lots / lot_bars if lot_bars > 0 else 0.0
    return exposure, turnover


def monthly_returns(equity: pd.Series) -> pd.DataFrame:
    """Resample an equity curve into monthly % returns (pivot, month x year)."""
    eq = equity.resample("ME").last().ffill()
    rets = eq.pct_change().dropna() * 100.0
    out = pd.DataFrame(
        {
            "year": rets.index.year,
            "month": rets.index.month,
            "return_pct": rets.values.round(4),
        }
    )
    return out


def _longest_dd_run(dd: pd.Series) -> int:
    longest = run = 0
    for v in dd:
        if v < 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return longest


def _empty_metrics() -> dict:
    return {
        "start": None,
        "end": None,
        "bars": 0,
        "years": 0.0,
        "start_equity": None,
        "end_equity": None,
        "total_return_pct": None,
        "cagr_pct": None,
        "annual_vol_pct": None,
        "sharpe": None,
        "sortino": None,
        "max_drawdown_pct": None,
        "max_dd_duration_bars": 0,
        "calmar": None,
        "best_bar_pct": None,
        "worst_bar_pct": None,
        "avg_bar_pct": None,
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate_pct": None,
        "profit_factor": None,
        "avg_win": None,
        "avg_loss": None,
        "payoff_ratio": None,
        "expectancy": None,
        "net_profit": None,
        "recovery_factor": None,
        "ulcer_index_pct": None,
        "downside_deviation_pct": None,
        "var_95_pct": None,
        "cvar_95_pct": None,
        "var_99_pct": None,
        "cvar_99_pct": None,
        "rolling_sharpe_median": None,
        "rolling_sharpe_worst": None,
        "avg_trade": None,
        "median_trade": None,
        "avg_trade_bars": None,
        "median_trade_bars": None,
        "exposure_pct": None,
        "turnover_pct": None,
        "max_consecutive_losses": 0,
        "return_concentration_hhi": None,
        "top5_trades_pct": None,
        "expectancy_last20": None,
        "win_rate_last20_pct": None,
        "monthly_win_rate_pct": None,
        "monthly_avg_pct": None,
        "monthly_std_pct": None,
    }


def _r(v):
    """Round to a sane precision, keep None/NaN as None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if np.isnan(f) or np.isinf(f):
        return None
    return round(f, 4)


# ---------------------------------------------------------------------------
# Robust fitness composite score (performance & selection hardening, Phase B)
# ---------------------------------------------------------------------------
#
# One explicit, validated score for *ranking* research candidates.  It is a
# weighted blend of documented components, each mapped to a metrics key and
# a fixed monotone transform with an explicit reference point.  It is
# OPT-IN for selection (default selection metric stays "sharpe") and is a
# research gate, never a profit claim.


class RobustFitnessConfig:
    """Composite-score coefficients (every weight explicit, sum ~= 1).

    Components (direction: up = more is better):
      expectancy     avg trade PnL relative to start equity, good at
                     ``expectancy_base`` (default 0.002 = 0.2 % of equity)
      calmar         risk-adjusted return, good at ``recovery_ref``
                     (recovery factor = net return / |max DD| >= 1.0)
      stability      rolling-Sharpe median, good at ``sharpe_ref`` (>= 1.0)
      resilience     fraction of net profit kept under cost stress, good at
                     ``resilience_ref`` (keep >= half of the base profit)
    Components (direction: down = more is worse):
      drawdown       |max_drawdown_pct| fully penalised at ``drawdown_ref``
      concentration  return HHI fully penalised at ``concentration_ref``
      turnover       turnover_pct fully penalised at ``turnover_ref``
      instability    rolling-Sharpe worst magnitude penalised at
                     ``worst_sharpe_ref`` (a window worse than -1.0)

    ``validate()`` requires non-negative weights summing to ~1.0 and
    strictly positive reference values.  When ``stressed_metrics`` is not
    supplied to :func:`composite_score`, the resilience component is
    neutral (0.5) and the report flags ``resilience_measured=False``.
    """

    def __init__(
        self,
        *,
        expectancy_base: float = 0.002,
        recovery_ref: float = 1.0,
        sharpe_ref: float = 1.0,
        resilience_ref: float = 0.5,
        drawdown_ref: float = 10.0,
        concentration_ref: float = 0.5,
        turnover_ref: float = 200.0,
        worst_sharpe_ref: float = 1.0,
        w_expectancy: float = 0.25,
        w_calmar: float = 0.20,
        w_stability: float = 0.10,
        w_resilience: float = 0.15,
        w_drawdown: float = 0.10,
        w_concentration: float = 0.05,
        w_turnover: float = 0.05,
        w_instability: float = 0.10,
    ) -> None:
        self.expectancy_base = float(expectancy_base)
        self.recovery_ref = float(recovery_ref)
        self.sharpe_ref = float(sharpe_ref)
        self.resilience_ref = float(resilience_ref)
        self.drawdown_ref = float(drawdown_ref)
        self.concentration_ref = float(concentration_ref)
        self.turnover_ref = float(turnover_ref)
        self.worst_sharpe_ref = float(worst_sharpe_ref)
        self.weights = {
            "expectancy": float(w_expectancy),
            "calmar": float(w_calmar),
            "stability": float(w_stability),
            "resilience": float(w_resilience),
            "drawdown": float(w_drawdown),
            "concentration": float(w_concentration),
            "turnover": float(w_turnover),
            "instability": float(w_instability),
        }
        self.validate()

    def validate(self) -> None:
        total = 0.0
        for name, w in self.weights.items():
            if w < 0.0:
                raise ValueError(f"weight {name} must be >= 0, got {w}")
            total += w
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(f"weights must sum to ~1.0, got {total:.6f}")
        for name in (
            "expectancy_base", "recovery_ref", "sharpe_ref", "resilience_ref",
            "drawdown_ref", "concentration_ref", "turnover_ref",
            "worst_sharpe_ref",
        ):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be > 0")


def _clip01(x: float) -> float:
    return float(min(max(x, 0.0), 1.0))


def _neutral(key: str, *, up: bool) -> float:
    return 0.5  # missing metric -> the component contributes its weight/2


def composite_score(
    metrics: dict,
    config: RobustFitnessConfig,
    *,
    stressed_metrics: dict | None = None,
) -> dict:
    """Composite fitness in [0, 1] with a per-component breakdown.

    Every component contribution is explicit in ``components``; missing
    metric values contribute neutrally (weight/2).  Cost resilience uses
    ``stressed_metrics`` when supplied (same schema, e.g. the run under a
    harsher cost profile); otherwise it is neutral and
    ``resilience_measured`` is False.
    """
    if not isinstance(config, RobustFitnessConfig):
        raise TypeError("config must be a RobustFitnessConfig")
    config.validate()
    comps: dict[str, float] = {}

    def take(key: str) -> float | None:
        v = metrics.get(key)
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            return None
        return float(v)

    # up-components ------------------------------------------------------
    exp = take("expectancy")
    start = metrics.get("start_equity")
    if exp is None or start is None or start <= 0.0:
        comps["expectancy"] = _neutral("expectancy", up=True)
    else:
        comps["expectancy"] = _clip01(exp / float(start)
                                      / config.expectancy_base)

    rec = take("recovery_factor")
    comps["calmar"] = _clip01(rec / config.recovery_ref) if rec is not None \
        else _neutral("calmar", up=True)

    med = take("rolling_sharpe_median")
    comps["stability"] = _clip01(med / config.sharpe_ref) if med is not None \
        else _neutral("stability", up=True)

    if stressed_metrics is not None:
        base_net = take("net_profit")
        stress_net = stressed_metrics.get("net_profit")
        if base_net is None or stress_net is None:
            comps["resilience"] = _neutral("resilience", up=True)
        elif base_net > 0.0:
            ratio = float(stress_net) / base_net
            comps["resilience"] = _clip01(ratio / config.resilience_ref)
        else:
            # no base profit to protect: a stressed run that stays ahead is
            # resilient, a losing one is not
            comps["resilience"] = _clip01(
                float(stress_net) / config.resilience_ref) if stress_net > 0 \
                else 0.0
        resilience_measured = True
    else:
        comps["resilience"] = _neutral("resilience", up=True)
        resilience_measured = False

    # down-components (contribution = 1 - penalty) -----------------------
    dd = take("max_drawdown_pct")
    pen = _clip01(abs(dd) / config.drawdown_ref) if dd is not None else 0.5
    comps["drawdown"] = 1.0 - pen

    hhi = take("return_concentration_hhi")
    pen = _clip01(hhi / config.concentration_ref) if hhi is not None else 0.5
    comps["concentration"] = 1.0 - pen

    turn = take("turnover_pct")
    pen = _clip01(turn / config.turnover_ref) if turn is not None else 0.5
    comps["turnover"] = 1.0 - pen

    worst = take("rolling_sharpe_worst")
    if worst is not None:
        pen = _clip01(max(-worst, 0.0) / config.worst_sharpe_ref)
    else:
        pen = 0.5
    comps["instability"] = 1.0 - pen

    score = sum(config.weights[k] * comps[k] for k in config.weights)
    return {
        "score": round(score, 6),
        "components": {k: round(v, 6) for k, v in comps.items()},
        "weights": {k: v for k, v in config.weights.items()},
        "resilience_measured": resilience_measured,
    }
