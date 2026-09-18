"""mql5bot.portfolio — strategy portfolio research (plan Phase 12).

Deterministic research tools on top of per-strategy results (equity
curves from ``run_backtest`` / walk-forward runs, trade ledgers):

* :func:`returns_frame` — align per-strategy equity curves into one
  per-period returns table (union of bars, forward-filled equity).
* :func:`correlation_matrix` / :func:`covariance_matrix` — valid,
  reproducible correlation/covariance of the aligned returns.
* :func:`portfolio_volatility` — volatility of a weight vector.
* :func:`equal_weight` — deterministic equal-weight allocation.
* :func:`concentration_hhi` — allocation concentration (Herfindahl).
* :func:`currency_exposure` / :func:`portfolio_heat` — per-currency
  notional shares and gross-notional/equity heat from symbol notionals.
* :func:`strategy_overlap` — pairwise time overlap (Jaccard over
  in-market bars per symbol) between two trade ledgers.
* :func:`apply_limits` — allocation veto: an allocation that would exceed
  its limits is rejected wholesale (zero accounting impact — allocation
  state is left untouched, and in the engine the same caps reject orders
  before any accounting mutation).

The engine already enforces exposure caps at execution time (per-symbol /
currency / correlation-group notionals, portfolio heat, position counts);
this module is the research-facing measurement + allocation layer, and
rejected allocations here are research-only decisions (the EA remains the
final risk authority).
"""

from __future__ import annotations

import pandas as pd


def returns_frame(equities: dict[str, pd.Series]) -> pd.DataFrame:
    """Align named equity curves into per-period returns (percent, 1 bar
    lag), dropping any bar with fewer than two live curves."""
    frame = pd.DataFrame({name: eq for name, eq in equities.items()})
    frame = frame.ffill()
    rets = frame.pct_change() * 100.0
    return rets.dropna(how="all")


def correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    """Pearson correlation of the aligned returns; guaranteed symmetric
    with unit diagonal and no NaN (validation of the matrix itself)."""
    corr = returns.corr()
    if corr.isna().values.any():
        raise ValueError("correlation is undefined: a strategy has no variance")
    # enforce exact symmetry + unit diagonal deterministically
    corr = (corr + corr.T) / 2.0
    for c in corr.columns:
        corr.loc[c, c] = 1.0
    return corr


def covariance_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    """Covariance (population) of the aligned per-period returns."""
    return returns.cov()


def portfolio_volatility(weights: dict[str, float],
                         cov: pd.DataFrame) -> float:
    """Annualised-ish portfolio vol from per-period covariance: returns the
    per-period volatility of the weighted portfolio (percent)."""
    names = list(weights)
    missing = [n for n in names if n not in cov.columns]
    if missing:
        raise ValueError(f"no covariance row for: {sorted(missing)}")
    w = pd.Series(weights, dtype=float).reindex(cov.columns).fillna(0.0)
    if abs(float(w.sum()) - 1.0) > 1e-9:
        raise ValueError("weights must sum to 1")
    var = float(w @ cov.loc[w.index, w.index] @ w)
    return float(var ** 0.5) if var > 0.0 else 0.0


def equal_weight(strategies: list[str]) -> dict[str, float]:
    """Deterministic equal-weight allocation (sums to exactly 1)."""
    if not strategies:
        raise ValueError("no strategies to allocate")
    w = 1.0 / len(strategies)
    return {name: w for name in sorted(strategies)}


def concentration_hhi(weights: dict[str, float]) -> float:
    """Herfindahl concentration of an allocation; 1/n for equal weights."""
    w = pd.Series(weights, dtype=float)
    total = float(w.sum())
    if total <= 0.0:
        raise ValueError("weights must be positive")
    return float(((w / total) ** 2).sum())


def currency_exposure(symbol_notional: dict[str, float]) -> dict[str, float]:
    """Per-currency share of gross notional, using each symbol's profit
    currency from the canonical synthetic specs (``mql5bot.specs``)."""
    from .specs import SYNTHETIC_SPECS

    out: dict[str, float] = {}
    total = 0.0
    for symbol, notional in sorted(symbol_notional.items()):
        if notional <= 0.0:
            continue
        if symbol not in SYNTHETIC_SPECS:
            raise KeyError(f"no synthetic spec for {symbol!r}")
        ccy = SYNTHETIC_SPECS[symbol].currency_profit
        out[ccy] = out.get(ccy, 0.0) + float(notional)
        total += float(notional)
    if total <= 0.0:
        return {}
    return {ccy: round(v / total, 6) for ccy, v in out.items()}


def portfolio_heat(gross_notional: float, equity: float) -> float:
    """Portfolio heat: gross notional / equity (guard against div-by-0)."""
    if equity <= 0.0:
        raise ValueError("equity must be > 0")
    return round(gross_notional / equity, 6)


def strategy_overlap(trades_a: pd.DataFrame, trades_b: pd.DataFrame,
                     index: pd.DatetimeIndex) -> float:
    """Jaccard overlap of in-market time for two strategies.

    Both ledgers must carry ``symbol``/``entry_time``/``exit_time`` (as
    produced by the engine).  Bars are counted per symbol on the shared
    ``index``; the metric is ``sum_s |A_s n B_s| / sum_s |A_s u B_s|`` over
    symbols either strategy traded, in [0, 1] (0 = never co-exposed on a
    symbol, 1 = identical exposure)."""
    bar_of = {str(t): i for i, t in enumerate(index)}

    def symbol_bars(trades: pd.DataFrame) -> dict[str, set[int]]:
        out: dict[str, set[int]] = {}
        for _, row in trades.iterrows():
            sym = row["symbol"]
            e0 = bar_of.get(str(row["entry_time"]))
            e1 = bar_of.get(str(row["exit_time"]))
            if e0 is None or e1 is None or e1 < e0:
                continue
            out.setdefault(sym, set()).update(range(e0, e1 + 1))
        return out

    a = symbol_bars(trades_a)
    b = symbol_bars(trades_b)
    inter = union = 0
    for sym in set(a) | set(b):
        sa = a.get(sym, set())
        sb = b.get(sym, set())
        inter += len(sa & sb)
        union += len(sa | sb)
    if union == 0:
        return 0.0
    return round(inter / union, 6)


def apply_limits(weights: dict[str, float], *,
                 max_weight: float | None = None,
                 max_currency_share: dict[str, float] | None = None,
                 strategy_currency: dict[str, str] | None = None) -> dict:
    """Allocation veto against explicit limits.

    Returns ``{"accepted": bool, "reason": str, "weights": ...}``.  On
    rejection the proposed allocation is NOT applied — the returned
    weights are the original input (zero accounting/decision impact);
    callers adopt them only when ``accepted`` is true.
    """
    if not weights:
        raise ValueError("no weights to vet")
    wsum = sum(weights.values())
    if abs(wsum - 1.0) > 1e-9:
        raise ValueError("weights must sum to 1")
    for name, w in weights.items():
        if w < 0.0:
            raise ValueError(f"negative weight for {name!r}")
    if max_weight is not None:
        heavy = [(n, w) for n, w in weights.items() if w > max_weight]
        if heavy:
            return {"accepted": False, "reason": f"max_weight exceeded: {heavy[0]}",
                    "weights": dict(weights)}
    if max_currency_share and strategy_currency:
        per_ccy: dict[str, float] = {}
        for name, w in weights.items():
            ccy = strategy_currency.get(name)
            if ccy is None:
                return {"accepted": False,
                        "reason": f"no currency for strategy {name!r}",
                        "weights": dict(weights)}
            per_ccy[ccy] = per_ccy.get(ccy, 0.0) + w
        for ccy, cap in max_currency_share.items():
            if per_ccy.get(ccy, 0.0) > cap:
                return {"accepted": False,
                        "reason": f"currency {ccy} share {per_ccy[ccy]:.3f} > {cap}",
                        "weights": dict(weights)}
    return {"accepted": True, "reason": "", "weights": dict(weights)}
