"""Convergence §25–§28/§59: explicit concentration reporting, honest
correlation classification, portfolio-value-score preference for
diversifiers, and the concentrated-factor capital example."""

from __future__ import annotations

import numpy as np
from mql5bot.discovery.portfolio import (
    build_portfolio,
    classify_correlation,
    concentration_report,
    marginal_contribution,
)


def _ret(seed: int, n: int = 300) -> tuple:
    return tuple(float(x) for x in
                 np.random.default_rng(seed).normal(0.0006, 0.005, n))


def test_classify_correlation_bands_and_unknown():
    rng = np.random.default_rng(5)
    a = tuple(float(x) for x in rng.normal(0, 0.01, 300))
    indep = tuple(float(x) for x in rng.normal(0, 0.01, 300))
    rho, band = classify_correlation(a, a)              # perfect
    assert band == "HIGH" and rho is not None and rho > 0.99
    _, band2 = classify_correlation(a, indep)
    assert band2 in ("LOW", "MEDIUM")
    # insufficient sample → UNKNOWN, never zero
    assert classify_correlation(a[:30], indep[:30]) == (None, "UNKNOWN")
    # constant series → UNKNOWN
    assert classify_correlation((1.0,) * 300, indep) == (None, "UNKNOWN")
    # length mismatch → UNKNOWN
    assert classify_correlation(a, indep[:100]) == (None, "UNKNOWN")


def test_concentration_report_axes():
    rets = _ret(9)
    positions = [
        {"strategy_id": "s1", "symbol": "EURUSD", "direction": "long",
         "currency": "USD", "asset_class": "fx", "weight": 0.06,
         "returns": rets},
        {"strategy_id": "s2", "symbol": "GBPUSD", "direction": "short",
         "currency": "USD", "asset_class": "fx", "weight": 0.04,
         "returns": _ret(10)},
    ]
    rep = concentration_report(positions)
    assert rep["positions"] == 2
    assert rep["strategy_id"]["max_share"] == pytest_approx(0.6)
    assert rep["currency"]["max_share"] == pytest_approx(1.0)  # both USD
    assert rep["symbol"]["buckets"] == 2
    assert rep["correlation"]["n_pairs"] == 1
    # empty portfolio: no concentration problem, no invented correlation
    empty = concentration_report([])
    assert empty["strategy_id"]["max_share"] == 0.0
    assert empty["correlation"]["mean_abs"] == 0.0
    assert empty["correlation"]["unknown_pairs"] == 0


def pytest_approx(x):
    return round(x, 6)


def test_portfolio_value_score_prefers_diversifier_over_clone():
    """§27: a slightly weaker standalone strategy that diversifies can
    be preferable — the clone is excluded, the diversifier admitted."""
    base = _ret(11)
    clone = tuple(x * 1.0 + 0.0 for x in base)          # identical stream
    diversifier = _ret(31)
    cands = [
        {"strategy_id": "winner", "score": 0.90, "symbol": "EURUSD",
         "direction": "long", "asset_class": "fx", "weight": 1.0,
         "returns": base},
        {"strategy_id": "weaker_diversifier", "score": 0.72,
         "symbol": "XAUUSD", "direction": "long", "asset_class": "metal",
         "weight": 1.0, "returns": diversifier},
    ]
    pf = build_portfolio(cands + [
        {"strategy_id": "clone", "score": 0.89, "symbol": "EURUSD",
         "direction": "long", "asset_class": "fx", "weight": 1.0,
         "returns": clone}], min_score=0.4)
    ids = [p["strategy_id"] for p in pf["positions"]]
    assert "winner" in ids and "weaker_diversifier" in ids
    assert "clone" not in ids
    # marginal view agrees: clone denied, diversifier admitted
    pool = [c for c in cands]
    m_clone = marginal_contribution(pool, {
        "strategy_id": "clone2", "score": 0.89, "symbol": "EURUSD",
        "direction": "long", "asset_class": "fx", "weight": 1.0,
        "returns": clone})
    m_div = marginal_contribution(pool, {
        "strategy_id": "div2", "score": 0.72, "symbol": "XAUUSD",
        "direction": "long", "asset_class": "metal", "weight": 1.0,
        "returns": diversifier})
    assert m_clone["admitted"] is False
    assert m_div["admitted"] is True


def test_capital_case_concentrated_factor_gets_reduced_allocation():
    """§59: four 0.5%-risk strategies all riding the SAME factor must
    see portfolio concentration controls reduce total allocation —
    independent per-strategy limits are NOT sufficient."""
    base = _ret(11)
    def like_base(seed: int) -> tuple:
        noise = np.random.default_rng(seed).normal(0, 1e-3, 300)
        return tuple(b + float(n) for b, n in zip(base, noise))
    cands = [
        {"strategy_id": f"f{i}", "score": 0.9 - i * 0.01,
         "symbol": "EURUSD", "direction": "long", "asset_class": "fx",
         "weight": 1.0, "returns": like_base(20 + i)}
        for i in range(4)
    ]
    limits = _limits()
    pf = build_portfolio(cands, limits=limits, min_score=0.4)
    # all four try to enter; per-symbol + correlation caps admit fewer
    admitted = len(pf["positions"])
    assert admitted < 4
    # effective gross is bounded well below the naive 4× target share
    assert pf["gross_exposure_pct"] <= _limits().max_per_symbol_pct
    # realized exposure per symbol (percent of CAPITAL) respects caps
    total_scaled = sum(p["scaled_weight"] for p in pf["positions"])
    if total_scaled > 0:
        sym_pct = {}
        for p in pf["positions"]:
            sym_pct[p["strategy_id"]] = p["scaled_weight"] / total_scaled \
                * pf["gross_exposure_pct"]
        assert all(v <= _limits().max_per_symbol_pct + 1e-9
                   for v in sym_pct.values())
    # and a diversified control group admits MORE strategies
    diverse = [
        {"strategy_id": f"d{i}", "score": 0.9 - i * 0.01,
         "symbol": sym, "direction": "long", "asset_class": ac,
         "weight": 1.0, "returns": _ret(40 + i)}
        for i, (sym, ac) in enumerate([("EURUSD", "fx"),
                                       ("XAUUSD", "metal"),
                                       ("US500", "index"),
                                       ("USDJPY", "fx")])]
    pf2 = build_portfolio(diverse, limits=_limits(), min_score=0.4)
    assert len(pf2["positions"]) > admitted


def _limits():
    from mql5bot.discovery.portfolio import ConcentrationLimits
    return ConcentrationLimits(max_per_symbol_pct=30.0,
                               max_per_asset_class_pct=40.0,
                               max_corr_avg=0.7)
