"""Portfolio research tests (mql5bot.portfolio, plan Phase 12).

Exit-gate evidence: valid deterministic correlation/covariance, portfolio
volatility against direct numpy recomputation, equal-weight allocation,
HHI concentration, currency exposure, heat, pairwise strategy overlap on
synthetic ledgers, and allocation limits whose rejections leave state
untouched (zero accounting impact — engine caps, already tested in
test_engine.py, are the execution-time enforcement).
"""

import numpy as np
import pandas as pd
import pytest
from mql5bot.portfolio import (
    apply_limits,
    concentration_hhi,
    correlation_matrix,
    covariance_matrix,
    currency_exposure,
    equal_weight,
    portfolio_heat,
    portfolio_volatility,
    returns_frame,
    strategy_overlap,
)


def _equities(n=250):
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    out = {}
    for name, (mu, sigma) in {"a": (0.0006, 0.01), "b": (0.0003, 0.008),
                              "c": (0.0, 0.012)}.items():
        steps = rng.normal(mu, sigma, n)
        out[name] = pd.Series(100.0 * np.exp(np.cumsum(steps)), index=idx)
    return out


def _ledger(rows, index):
    return pd.DataFrame(rows)


def test_returns_frame_alignment_and_correlation_validity():
    eqs = _equities()
    r = returns_frame(eqs)
    assert list(r.columns) == ["a", "b", "c"]
    assert len(r) == len(eqs["a"]) - 1  # pct_change drops the first bar
    corr = correlation_matrix(r)
    assert (corr.columns == corr.index).all()
    assert np.allclose(corr.values, corr.values.T)
    assert np.allclose(np.diag(corr.values), 1.0)
    assert np.isfinite(corr.values).all()
    cov = covariance_matrix(r)
    assert (cov.columns == cov.index).all()
    assert np.allclose(cov.values, cov.values.T)


def test_portfolio_volatility_matches_direct_numpy():
    eqs = _equities()
    r = returns_frame(eqs)
    cov = covariance_matrix(r)
    w = {"a": 0.5, "b": 0.3, "c": 0.2}
    got = portfolio_volatility(w, cov)
    mat = cov.loc[["a", "b", "c"], ["a", "b", "c"]].to_numpy()
    want = float(np.sqrt(np.array([0.5, 0.3, 0.2]) @ mat
                         @ np.array([0.5, 0.3, 0.2])))
    assert got == pytest.approx(want)
    with pytest.raises(ValueError):
        portfolio_volatility({"a": 0.5, "b": 0.3}, cov)  # must sum to 1
    with pytest.raises(ValueError):
        portfolio_volatility({"a": 1.0, "zz": 0.0}, cov)  # unknown column


def test_equal_weight_and_concentration():
    w = equal_weight(["b", "a", "c"])
    assert w == {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}
    assert concentration_hhi(w) == pytest.approx(1 / 3)
    single = {"a": 1.0}
    assert concentration_hhi(single) == pytest.approx(1.0)
    concentrated = {"a": 0.9, "b": 0.1}
    assert concentration_hhi(concentrated) > concentration_hhi(w)


def test_currency_exposure_and_heat():
    notionals = {"EURUSD": 50_000.0, "GBPUSD": 25_000.0, "USDJPY": 25_000.0}
    # profit-currency grouping: EURUSD and GBPUSD both pay in USD
    expo = currency_exposure(notionals)
    assert expo == {"USD": 0.75, "JPY": 0.25}
    assert sum(expo.values()) == pytest.approx(1.0)
    assert currency_exposure({}) == {}
    with pytest.raises(KeyError):
        currency_exposure({"NOTREAL": 100.0})
    assert portfolio_heat(120_000.0, 60_000.0) == 2.0
    with pytest.raises(ValueError):
        portfolio_heat(100.0, 0.0)


def _idx():
    return pd.date_range("2024-01-01", periods=100, freq="h")


def _trades(segments, symbol="EURUSD", lots=0.1):
    idx = _idx()
    rows = []
    for s in segments:
        rows.append({"symbol": symbol,
                     "entry_time": str(idx[s[0]]), "exit_time": str(idx[s[1]]),
                     "lots": lots})
    return pd.DataFrame(rows)


def test_strategy_overlap_full_none_and_partial():
    idx = _idx()
    a = _trades([(10, 40)])
    b_full = _trades([(10, 40)])
    b_none = _trades([(50, 80)])
    b_partial = _trades([(30, 60)])
    assert strategy_overlap(a, b_full, idx) == pytest.approx(1.0)
    assert strategy_overlap(a, b_none, idx) == pytest.approx(0.0)
    # inclusive bars: a=[10..40] (31), b=[30..60] (31); intersection
    # 30..40 (11) -> union 51, overlap 11/51
    assert strategy_overlap(a, b_partial, idx) == pytest.approx(11 / 51, abs=1e-5)
    assert strategy_overlap(a, _trades([]), idx) == 0.0
    # multi-symbol: a trades EURUSD 10..40, b trades EURUSD 10..30 and
    # GBPUSD 10..40 -> overlap on EURUSD (21/31 in EUR) and none on GBP
    idx2 = pd.date_range("2024-01-01", periods=100, freq="h")
    ta = pd.concat([_trades([(10, 40)], symbol="EURUSD"),
                    _trades([(60, 70)], symbol="GBPUSD")])
    tb = pd.concat([_trades([(10, 30)], symbol="EURUSD"),
                    _trades([(10, 40)], symbol="GBPUSD")])
    o = strategy_overlap(ta, tb, idx2)
    assert 0.0 < o < 1.0


def test_apply_limits_rejection_has_zero_impact():
    w = {"a": 0.6, "b": 0.4}
    r = apply_limits(w, max_weight=0.5)
    assert r["accepted"] is False and "max_weight" in r["reason"]
    assert r["weights"] == w  # proposal NOT adopted (input returned as-is)
    ok = apply_limits({"a": 0.5, "b": 0.5}, max_weight=0.5)
    assert ok["accepted"] is True and ok["reason"] == ""
    ccy = apply_limits({"a": 0.8, "b": 0.2},
                       max_currency_share={"USD": 0.5},
                       strategy_currency={"a": "USD", "b": "EUR"})
    assert ccy["accepted"] is False and "USD" in ccy["reason"]
    with pytest.raises(ValueError):
        apply_limits({"a": 0.8, "b": 0.1})  # not summing to 1
    with pytest.raises(ValueError):
        apply_limits({"a": -0.1, "b": 1.1})


def test_portfolio_tools_deterministic():
    eqs = _equities()
    r1 = returns_frame(eqs)
    r2 = returns_frame(eqs)
    assert r1.equals(r2)
    assert correlation_matrix(r1).equals(correlation_matrix(r2))
