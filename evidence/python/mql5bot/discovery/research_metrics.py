"""discovery/research_metrics.py — canonical MEASURED gate inputs for the
research service (mission §21/§59/P0-truthfulness).

Every function here returns a value MEASURED from a real backtest, market
data, or the actual portfolio book.  Nothing is fabricated: when a
measurement cannot be taken (too little data, no book, a single
non-searched candidate), the caller receives ``None`` and MUST leave the
corresponding gate input unset so the gate SKIPs (blocks) rather than
passes on an invented value.

These are the SAME calculations the certified end-to-end fixture
(``tests/test_factory_e2e.py``) uses to walk the real lifecycle — kept in
one place so the service and the certification reference cannot drift
apart (mission: do not duplicate numerical logic).  Heavy statistical
machinery (PBO/DSR) is delegated to :mod:`mql5bot.robustness`; regime
labelling and portfolio interaction to the canonical regime/portfolio
modules — this file only wires them to a backtest result.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..robustness import combinatorial_purged_cv, psr


def trade_metrics(res, df: pd.DataFrame) -> dict:
    """Measured gate-2 inputs from a backtest result (deterministic).

    A window with NO trades yields honest zero/degenerate values (0
    trades, PF 0) so downstream gates FAIL closed — never a KeyError and
    never an invented pass."""
    m = res.metrics
    tr = res.trades
    years = max((df.index[-1] - df.index[0]).total_seconds()
                / (365.25 * 24 * 3600), 1e-9)
    if tr.empty or "trades" not in m:
        return {"n_trades": 0.0, "years": years, "pf": 0.0,
                "max_dd_pct": abs(float(m.get("max_drawdown_pct", 0.0))),
                "top10_profit_share": 1.0, "positive_quarters_share": 0.0,
                "edge_to_cost": 0.0}
    net = tr["pnl"].sum()
    top10 = tr["pnl"].nlargest(10).sum() / net if net > 0 else 1.0
    eq = res.equity
    q = eq.resample("QE").last().pct_change().dropna()
    pos_q = float((q > 0).mean()) if len(q) else 0.0
    avg_cost = 2 * 1e-5 * 100_000 * tr["lots"].mean() if len(tr) else 1.0
    pf = m.get("profit_factor")
    if pf is None:                       # no losing trades in this window
        gwin = tr[tr["pnl"] > 0]["pnl"].sum()
        gloss = -tr[tr["pnl"] < 0]["pnl"].sum()
        pf = (gwin / gloss) if gloss > 0 else (100.0 if gwin > 0 else 0.0)
    return {"n_trades": float(m["trades"]), "years": years,
            "pf": min(float(pf), 100.0),
            "max_dd_pct": abs(float(m.get("max_drawdown_pct") or 0.0)),
            "top10_profit_share": float(top10),
            "positive_quarters_share": pos_q,
            "edge_to_cost": float(tr["pnl"].mean() / max(avg_cost, 1e-9))
            if len(tr) else 0.0}


def walk_forward_efficiency(train_res, holdout_res) -> float | None:
    """Single-window walk-forward efficiency (gate-5), the canonical WFE
    ratio of ``docs/WFA_CONTRACT.md`` §6 — ``holdout_return / IS_return`` —
    computed with the EXACT formula used by
    :func:`mql5bot.optimizer.walk_forward` (``optimizer.py`` per-window
    ``wfe``), applied to ONE rolling-origin window whose in-sample (train)
    and held-out (the window's own out-of-sample) slices are BOTH inside
    the research IS region.  The final one-look OOS certification slice is
    never touched by this measurement, so it stays selection-safe (§19).

    Returns ``None`` — never a fabricated number — when the in-sample
    return is non-positive (efficiency is undefined for a losing/flat IS
    leg); the caller then leaves the gate input unset so gate-5 SKIPs
    (blocks) rather than passing on an invented value.  This is genuine
    walk-forward efficiency, not a profit-factor delta: the metric now
    means what its certification name says."""
    is_ret = train_res.metrics.get("total_return_pct")
    oos_ret = holdout_res.metrics.get("total_return_pct")
    if not isinstance(is_ret, (int, float)) or isinstance(is_ret, bool):
        return None
    if not isinstance(oos_ret, (int, float)) or isinstance(oos_ret, bool):
        return None
    denom = float(is_ret) / 100.0
    if denom <= 0.0:                     # WFE undefined for a non-positive IS leg
        return None
    return (float(oos_ret) / 100.0) / denom


def mc_p05_dd(res, perms: int = 200, seed: int = 11) -> float:
    """Monte-Carlo trade-order shuffle → 5th percentile of maxDD%
    (gate-7).  Deterministic (seeded).  Real measurement — a resampled
    drawdown distribution of the strategy's own trade PnL."""
    pnl = res.trades["pnl"].to_numpy()
    rng = np.random.default_rng(seed)
    dds = []
    for _ in range(perms):
        eqv = 10_000.0 + np.cumsum(rng.permutation(pnl))
        peak = np.maximum.accumulate(np.maximum(eqv, 1e-9))
        dds.append(-100.0 * ((eqv - peak) / peak).min() if len(eqv) else 0.0)
    return float(np.percentile(dds, 5))


def dsr_p_daily(res) -> float | None:
    """Probabilistic Sharpe ratio P(true Sharpe > 0) on daily returns
    (gate-6 DSR leg), via the canonical closed form in
    :func:`mql5bot.robustness.psr`.  ``None`` when there are too few
    daily observations to estimate it (caller leaves the gate input
    unset → gate SKIPs)."""
    r = res.equity.resample("1D").last().pct_change().dropna()
    if len(r) < 3:
        return None
    return float(psr(r.to_numpy(), sr_ref_annual=0.0))


def regime_pf(res, df: pd.DataFrame, *, sma_period: int = 200,
              slope_lookback: int = 20) -> float | None:
    """Profit factor of the trades that EXIT inside the expected
    (trend-up) regime, where the expected regime is defined causally by a
    rising ``sma_period`` SMA (slope over ``slope_lookback`` bars > 0) of
    the market close (gate-8).

    Real measurement of the strategy's edge in the regime it is built to
    exploit.  ``None`` when no trade exits inside that regime (nothing to
    measure → gate SKIPs rather than inventing a verdict)."""
    tr = res.trades
    if tr.empty or "exit_time" not in tr:
        return None
    sma = df["close"].rolling(sma_period).mean()
    slope = sma.diff(slope_lookback)
    exit_idx = df.index.get_indexer(tr["exit_time"])
    valid = exit_idx >= 0
    if not valid.any():
        return None
    up = np.zeros(len(tr), dtype=bool)
    up[valid] = slope.to_numpy()[exit_idx[valid]] > 0
    sel = tr[pd.Series(up, index=tr.index)]
    if sel.empty:
        return None
    wins = sel[sel["pnl"] > 0]["pnl"].sum()
    losses = -sel[sel["pnl"] < 0]["pnl"].sum()
    if losses > 0:
        return float(wins / losses)
    return float("inf") if wins > 0 else 0.0


def cpcv_pbo(returns_by_config: list[pd.Series], *,
             n_splits: int = 6, seed: int = 0) -> float | None:
    """Probability of backtest overfitting across the searched grid
    (gate-6 PBO leg), via :func:`mql5bot.robustness.combinatorial_purged_cv`.

    ``returns_by_config`` is one aligned per-period (daily) return series
    per grid configuration.  Returns the measured PBO, or ``None`` when
    the search is too small to estimate it (fewer than 2 configurations or
    fewer than 8 aligned periods) — a single non-searched candidate has no
    selection multiplicity to overfit, so the caller must decide whether
    PBO applies (it does NOT inject a fake 0.0)."""
    series = [s for s in returns_by_config if s is not None and len(s)]
    if len(series) < 2:
        return None
    mat = pd.concat(series, axis=1).dropna()
    if mat.shape[0] < 8 or mat.shape[1] < 2:
        return None
    splits = min(n_splits, mat.shape[0])
    if splits < 4:
        return None
    result = combinatorial_purged_cv(mat.to_numpy(), n_splits=splits,
                                     seed=seed)
    return float(result["pbo"])


def daily_returns(res) -> pd.Series:
    """The strategy's daily equity returns (aligned key for CPCV)."""
    return res.equity.resample("1D").last().pct_change().dropna()


def portfolio_interaction(candidate_returns: pd.Series,
                          book: list[pd.Series]) -> tuple[float, float]:
    """Measured (max_correlation_with_book, marginal_heat_add) of adding a
    candidate to the CURRENT book (gate-9).

    ``book`` is the list of daily-return series of the strategies already
    in observed/live states.  An EMPTY book is the honest common case for
    a strategy researched in isolation: there is no existing strategy to
    duplicate, so the measured correlation is 0.0 and the marginal heat a
    yet-unallocated candidate adds to an empty book is 0.0.  With a real
    book, the correlation is the max |Pearson r| of the candidate's daily
    returns against each member's (aligned), and the marginal heat is the
    candidate's added return-volatility share — both MEASURED, never
    invented."""
    if not book:
        return 0.0, 0.0
    max_corr = 0.0
    for member in book:
        joined = pd.concat([candidate_returns, member], axis=1).dropna()
        if joined.shape[0] < 3:
            continue
        a = joined.iloc[:, 0].to_numpy()
        b = joined.iloc[:, 1].to_numpy()
        sa, sb = a.std(), b.std()
        if sa <= 1e-12 or sb <= 1e-12:
            continue
        rho = float(np.corrcoef(a, b)[0, 1])
        if math.isfinite(rho):
            max_corr = max(max_corr, abs(rho))
    # marginal heat: the candidate's own return volatility relative to the
    # book's mean member volatility (share of incremental risk it brings).
    cand_vol = float(candidate_returns.std())
    member_vols = [float(m.std()) for m in book if len(m) > 2]
    base_vol = float(np.mean(member_vols)) if member_vols else 0.0
    marginal_heat = (cand_vol / (base_vol + cand_vol)
                     if (base_vol + cand_vol) > 1e-12 else 0.0)
    return round(max_corr, 6), round(marginal_heat, 6)
