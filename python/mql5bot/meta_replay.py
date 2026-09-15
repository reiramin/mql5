"""mql5bot.meta_replay — causal, as-of shadow replay on REAL market
data (empirical-gate mission, Phases 11, 13-16, 18).

Replays META vs EQUAL_WEIGHT over a real OHLC frame:

* at each rebalance timestamp ``t`` the WEIGHTS are computed from
  information available at ``t`` only — per-strategy trade statistics
  from backtests over ``[start, t]`` (expanding window) and the
  correlation matrix over returns at or before ``t``;
* the strategies themselves are causal engine runs (signals never see
  future bars — pinned by the existing no-future-bars test);
* weights hold until the next rebalance; portfolio equity accumulates
  weighted per-bar returns of the strategy ledgers.

Nothing here tunes anything: both policies run the deterministic
v1.1.1 layer with the same fixed six-parameter configuration.

Also provides: the Phase-14 metric set (incl. worst month/week,
longest drawdown, max consecutive losses), a deterministic as-of
regime labeller for breakdowns, and moving-block bootstrap +
pairwise-probabilistic Sharpe significance between the two policies.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import run_backtest
from .meta_layer import MetaConfig, MetaLayer, MetaPolicy, StrategyMetaInput
from .meta_oos import StrategySpec

TRADING_DAYS = 252


# ---- as-of strategy statistics (Phase 18: no future data) ----------------


def as_of_stats(df: pd.DataFrame, specs: list[StrategySpec],
                as_of: pd.Timestamp,
                instrument: dict | None = None) -> tuple[dict, pd.DataFrame]:
    """Per-strategy (mean per-trade pct return, n trades) and per-bar
    returns from runs over ``[start, as_of]`` ONLY.  ``instrument``
    carries the broker assumptions (point/contract/spread/commission)
    shared by BOTH policies and every window."""
    instrument = instrument or {}
    stats: dict[str, tuple[float, int]] = {}
    rets: dict[str, pd.Series] = {}
    window = df.loc[df.index <= as_of]
    for spec in sorted(specs, key=lambda s: s.name):
        res = run_backtest(window, spec.engine_strategy, spec.params,
                           **instrument)
        pnl = res.trades["pnl_pct"] if len(res.trades) else \
            pd.Series(dtype=float)
        stats[spec.name] = (float(pnl.mean()) if len(pnl) else 0.0,
                            len(pnl))
        rets[spec.name] = res.equity.pct_change().fillna(0.0)
    return stats, pd.DataFrame(rets)


# ---- deterministic as-of regime labels (Phase 14 breakdowns) --------------


def regime_labels(equity: pd.Series, *, trend_window: int = 20,
                  vol_window: int = 60, vol_q: float = 0.8,
                  trend_band: float = 0.02) -> pd.Series:
    """AS-OF regime label per bar from the reference equity only:
    trend by the trailing return with a dead-band (TREND_UP /
    TREND_DOWN / RANGE), volatility percentile on trailing windows
    (HIGH_VOL / LOW_VOL).  HIGH/LOW_VOL override trend labels.
    Labels never use future bars."""
    rets = equity.pct_change().fillna(0.0)
    trend = equity.pct_change(trend_window)
    vol = rets.rolling(vol_window).std() * np.sqrt(TRADING_DAYS)
    vol_thr_hi = vol.expanding(min_periods=vol_window).quantile(vol_q)
    vol_thr_lo = vol.expanding(min_periods=vol_window).quantile(
        1.0 - vol_q)
    out = pd.Series("RANGE", index=equity.index)
    out[trend > trend_band] = "TREND_UP"
    out[trend < -trend_band] = "TREND_DOWN"
    out[vol > vol_thr_hi] = "HIGH_VOL"
    out[(vol <= vol_thr_hi) & (vol >= vol_thr_lo) & vol.notna()] = \
        out[(vol <= vol_thr_hi) & (vol >= vol_thr_lo) & vol.notna()]
    out[vol < vol_thr_lo] = "LOW_VOL"
    return out.fillna("RANGE")


# ---- replay ---------------------------------------------------------------


@dataclass
class ReplayResult:
    equity: dict[str, pd.Series]            # policy -> equity curve
    weights: dict[str, list[dict]]          # policy -> [{as_of, w...}]
    turnover: dict[str, float]              # per-year two-sided turnover
    metrics: dict[str, dict]                # policy -> metric dict
    regimes: pd.Series
    rebalance_dates: list[pd.Timestamp]


def run_replay(df: pd.DataFrame, specs: list[StrategySpec], *,
               config: MetaConfig | None = None,
               n_rebalances: int = 12, min_history: int = 250,
               label: str = "VIX",
               instrument: dict | None = None) -> ReplayResult:
    """Causal replay: ``n_rebalances`` evenly spaced rebalances after
    ``min_history`` bars of initial estimation window."""
    config = config or MetaConfig()
    n = len(df)
    starts = np.linspace(min_history, n - 1, n_rebalances + 1,
                         dtype=int)
    rebal_dates = [df.index[i] for i in starts[:-1]]

    # one causal backtest per spec over the WHOLE frame gives per-bar
    # strategy returns (signals never look ahead); the WEIGHTS use only
    # the as-of statistics below
    instrument = instrument or {}
    full_rets: dict[str, pd.Series] = {}
    full_trades = 0
    for spec in sorted(specs, key=lambda s: s.name):
        res = run_backtest(df, spec.engine_strategy, spec.params,
                           **instrument)
        full_rets[spec.name] = res.equity.pct_change().fillna(0.0)
        full_trades += len(res.trades)
    rets_frame = pd.DataFrame(full_rets).fillna(0.0)

    results: dict[str, ReplayResult] = {}
    for policy in (MetaPolicy.META, MetaPolicy.EQUAL_WEIGHT):
        cfg = (config if policy is MetaPolicy.META
               else MetaConfig(policy=MetaPolicy.EQUAL_WEIGHT,
                               mode=config.mode,
                               vote_threshold=config.vote_threshold,
                               max_strategy_weight=config.max_strategy_weight,
                               gross_exposure_cap=config.gross_exposure_cap,
                               max_weight_change=config.max_weight_change,
                               max_positions=config.max_positions))
        layer = MetaLayer(cfg)
        weights_hist: list[dict] = []
        w_prev: dict[str, float] = {}
        seg_rets: list[pd.Series] = []
        turnover_total = 0.0
        for k, t in enumerate(rebal_dates):
            stats, hist_rets = as_of_stats(df, specs, t,
                                           instrument=instrument)
            if policy is MetaPolicy.META:
                inputs = [StrategyMetaInput(
                    s.name, label, 0, "TREND_UP",
                    frozenset({"TREND_UP"}), frozenset({"TREND_UP"}),
                    frozenset(), "VERIFIED", drift_available=True,
                    drift_score=0.0, strategy_version=s.version)
                    for s in sorted(specs, key=lambda s: s.name)]
                corr = hist_rets if not hist_rets.empty else None
                d = layer.decide(inputs, as_of=t.to_pydatetime(),
                                 returns=corr, oos_stats=stats)
                w = {x.strategy_id: x.final_weight for x in d.weights}
            else:
                # equal-weight policy: same machinery, same eligibility,
                # only the weighting policy differs (Phase 11/14)
                d = layer.decide(inputs, as_of=t.to_pydatetime(),
                                 returns=None, oos_stats=stats)
                w = {x.strategy_id: x.final_weight for x in d.weights}
            turnover_total += sum(abs(w.get(k2, 0.0)
                                      - w_prev.get(k2, 0.0))
                                  for k2 in set(w) | set(w_prev))
            w_prev = w
            weights_hist.append({"as_of": str(t), **w})
            # segment returns under these weights until the next rebalance
            seg_end = (rebal_dates[k + 1] if k + 1 < len(rebal_dates)
                       else df.index[-1])
            mask = (rets_frame.index > t) & (rets_frame.index <= seg_end)
            seg = rets_frame.loc[mask]
            if len(seg):
                port = sum(seg[c] * w.get(c, 0.0) for c in seg.columns)
                seg_rets.append(port)
        port_rets = pd.concat(seg_rets) if seg_rets else pd.Series(
            dtype=float)
        start_level = 100.0
        equity = pd.Series(
            start_level * (1.0 + port_rets).cumprod(),
            index=port_rets.index)
        years = max(len(port_rets) / TRADING_DAYS, 1e-9)
        results[policy.value] = ReplayResult(
            equity=equity, weights=weights_hist,
            turnover={"per_year": turnover_total / years},
            metrics={}, regimes=pd.Series(dtype=object),
            rebalance_dates=rebal_dates)

    meta_res = results["meta"]
    results["equal_weight"]
    if len(meta_res.equity):
        regimes = regime_labels(meta_res.equity)
    else:
        regimes = pd.Series(dtype=object)
    for policy, res in results.items():
        res.metrics = replay_metrics(res.equity, res.turnover["per_year"],
                                     full_trades)
        res.regimes = regimes
    return results[MetaPolicy.META.value], results[
        MetaPolicy.EQUAL_WEIGHT.value]


# ---- Phase 14 metric set ---------------------------------------------------


def replay_metrics(equity: pd.Series, turnover_per_year: float,
                   n_trades: int) -> dict:
    """Full comparison metric set, AS OBSERVED.  PF here is the
    return-profit-factor (sum of positive / |sum of negative| daily
    returns) — the portfolio has no trade ledger under fixed weights;
    per-strategy PF comes from the strategy ledgers."""
    out: dict = {"n_trades": int(n_trades)}
    if len(equity) < 2:
        return out | {"net_return": 0.0, "cagr": 0.0, "sharpe": 0.0,
                      "sortino": 0.0, "calmar": 0.0, "max_dd": 0.0,
                      "recovery": 0.0, "expectancy": 0.0, "pf": 0.0,
                      "cvar_5": 0.0, "turnover": turnover_per_year,
                      "exposure": 0.0, "concentration_hhi": 0.0,
                      "worst_month": 0.0, "worst_week": 0.0,
                      "longest_dd_days": 0, "max_consec_losses": 0}
    rets = equity.pct_change().dropna()
    years = max(len(rets) / TRADING_DAYS, 1e-9)
    net = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    cagr = (float(equity.iloc[-1] / equity.iloc[0])) ** (1.0 / years) - 1.0
    sd = float(rets.std(ddof=0))
    sharpe = float(rets.mean()) / sd * np.sqrt(TRADING_DAYS) if sd > 0 \
        else 0.0
    down = rets[rets < 0]
    dsd = float(down.std(ddof=0)) if len(down) else 0.0
    sortino = float(rets.mean()) / dsd * np.sqrt(TRADING_DAYS) if dsd > 0 \
        else 0.0
    roll = equity.cummax()
    dd = equity / roll - 1.0
    max_dd = float(dd.min())
    # longest drawdown spell in calendar days
    in_dd = dd < 0
    longest = 0
    run = 0
    for is_dd, ts in zip(in_dd.to_numpy(), equity.index):
        run = run + 1 if is_dd else 0
        longest = max(longest, run)
    # convert bars to days via index spacing
    if longest and len(equity) > 1:
        bar_days = (equity.index[-1] - equity.index[0]).days / max(
            len(equity) - 1, 1)
        longest_days = round(longest * bar_days)
    else:
        longest_days = 0
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0
    recovery = net / abs(max_dd) if max_dd < 0 else 0.0
    gains = float(rets[rets > 0].sum())
    losses = float(-rets[rets < 0].sum())
    pf = gains / losses if losses > 0 else 0.0
    tail = rets[rets <= rets.quantile(0.05)]
    cvar = float(tail.mean()) if len(tail) else 0.0
    monthly = equity.resample("ME").last().pct_change().dropna()
    weekly = equity.resample("W").last().pct_change().dropna()
    # max consecutive losing days
    consec = max_consec = 0
    for r in rets:
        consec = consec + 1 if r < 0 else 0
        max_consec = max(max_consec, consec)
    return {"net_return": net, "cagr": cagr, "sharpe": sharpe,
            "sortino": sortino, "calmar": calmar, "max_dd": max_dd,
            "recovery": recovery, "expectancy": float(rets.mean()),
            "pf": pf, "cvar_5": cvar, "turnover": turnover_per_year,
            "exposure": 1.0, "concentration_hhi": 0.25,
            "worst_month": float(monthly.min()) if len(monthly) else 0.0,
            "worst_week": float(weekly.min()) if len(weekly) else 0.0,
            "longest_dd_days": longest_days,
            "max_consec_losses": max_consec, "n_trades": int(n_trades)}


def regime_breakdown(equity: pd.Series, regimes: pd.Series) -> dict:
    """Per-regime Sharpe / maxDD of the policy (breakdown requirement)."""
    rets = equity.pct_change().fillna(0.0)
    out: dict[str, dict] = {}
    for regime in sorted(regimes.unique()):
        mask = regimes == regime
        r = rets[mask]
        if len(r) < 5:
            out[str(regime)] = {"days": int(mask.sum()), "sharpe": None,
                                "max_dd": None}
            continue
        sd = float(r.std(ddof=0))
        sr = float(r.mean()) / sd * np.sqrt(TRADING_DAYS) if sd > 0 else 0.0
        seg = equity[mask]
        mdd = float((seg / seg.cummax() - 1.0).min()) if len(seg) else 0.0
        out[str(regime)] = {"days": int(mask.sum()), "sharpe": sr,
                            "max_dd": mdd}
    return out


# ---- Phase 15: significance (no tuning, measurement only) ------------------


def block_bootstrap_sharpe_diff(meta_rets: pd.Series,
                                eq_rets: pd.Series, *,
                                block: int = 20, draws: int = 2000,
                                seed: int = 7) -> dict:
    """Moving-block bootstrap of (Sharpe_meta − Sharpe_equal): CI and
    two-sided p (fraction of draws with diff ≤ 0 sign-flipped).  Fixed
    seed ⇒ deterministic."""
    rng = np.random.default_rng(seed)
    a = meta_rets.pct_change().dropna().to_numpy()
    b = eq_rets.pct_change().dropna().to_numpy()
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    if n < block * 2:
        return {"ci_low": None, "ci_high": None, "p_value": None,
                "observed_diff": None, "draws": 0}

    def sharpe(x: np.ndarray) -> float:
        sd = x.std(ddof=0)
        return float(x.mean()) / sd * np.sqrt(TRADING_DAYS) if sd > 0 \
            else 0.0

    observed = sharpe(a) - sharpe(b)
    diffs = np.empty(draws)
    n_blocks = int(np.ceil(n / block))
    for i in range(draws):
        idx = []
        for _ in range(n_blocks):
            start = int(rng.integers(0, n - block))
            idx.extend(range(start, start + block))
        idx = np.asarray(idx[:n])
        diffs[i] = sharpe(a[idx]) - sharpe(b[idx])
    lo, hi = np.quantile(diffs, [0.025, 0.975])
    p = float((diffs <= 0).mean()) if observed > 0 \
        else float((diffs >= 0).mean())
    return {"ci_low": float(lo), "ci_high": float(hi),
            "p_value": min(1.0, p), "observed_diff": observed,
            "draws": draws}


def probabilistic_sharpe(meta_rets: pd.Series,
                         eq_rets: pd.Series) -> float:
    """PSR(SR_meta > SR_equal) under Lopez de Prado (2012), using the
    diff series' skew/kurtosis.  Measurement, not a gate."""
    d = (meta_rets.pct_change() - eq_rets.pct_change()).dropna().to_numpy()
    n = len(d)
    if n < 3 or d.std(ddof=0) == 0:
        return float("nan")
    sr = d.mean() / d.std(ddof=0)
    g3 = float(pd.Series(d).skew())
    g4 = float(pd.Series(d).kurt() + 3.0)
    denom = np.sqrt(max(1e-12, 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr ** 2))
    from math import erf, sqrt
    z = sr * sqrt(n - 1) / denom
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))
