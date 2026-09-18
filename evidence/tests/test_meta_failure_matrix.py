"""Multi-asset failure matrix (Phase 25).

Every injected failure must end in a SAFE HOLD, a documented safe
baseline, or a journaled INELIGIBLE refusal — never a crash, never a
silent full-risk fallback.  Each test name doubles as a matrix row in
``docs/META_REALISM_AUDIT.md`` (§ Failure matrix).
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest
from mql5bot.data import generate_ohlc
from mql5bot.meta_layer import MetaLayer, MetaPolicy
from mql5bot.meta_portfolio import MetaPortfolioEngine

from tests.test_meta_multi_asset import (
    AU_SPEC,
    FX_SPEC,
    _contexts,
    _ctx,
    _seam_run,
)


@pytest.fixture(scope="module")
def frames():
    return {
        "fx": generate_ohlc(days=180, seed=5),
        "au": generate_ohlc(days=180, seed=12),
    }


def _engine(frames, contexts=None, **kw):
    kw.setdefault("every_days", 12)
    kw.setdefault("min_history_bars", 480)
    return MetaPortfolioEngine(
        contexts=contexts if contexts is not None else _contexts(frames),
        **kw)


# F1: corrupt dataset (NaN bar) --------------------------------------------


def test_f1_nan_bar_frame_is_refused_not_crashed(frames):
    """A NaN OHLC bar would crash the tick math (round(NaN)); the
    context gate refuses the book BEFORE the mechanics and journals it."""
    bad = frames["au"].copy()
    bad.iloc[500:540] = np.nan
    ctxs = _contexts(frames)[:1] + [
        _ctx("XAUUSD", "macd@XAUUSD", "macd_momentum", bad, AU_SPEC)]
    eng = _engine(frames, contexts=ctxs)
    assert eng.ineligible and "non-finite OHLC" in eng.ineligible[0][
        "reason"]
    res = eng.run()                      # the EURUSD book still runs
    assert "macd@XAUUSD" not in set(res.meta.trades["strategy"])
    assert (res.meta.trades["symbol"] == "EURUSD").any()


def test_f1b_missing_ohlc_column_is_refused(frames):
    bad = frames["au"].drop(columns=["low"])
    ctx = _ctx("XAUUSD", "macd@XAUUSD", "macd_momentum", bad, AU_SPEC)
    assert "missing OHLC columns" in ctx.data_error


# F2: degenerate market (flat line) ----------------------------------------


def test_f2_flat_frame_trades_nothing_baseline_stands(frames):
    """Zero volatility ⇒ ATR 0 ⇒ no valid stop ⇒ that book simply never
    trades; the rest of the portfolio is unaffected (documented
    baseline, not a failure)."""
    flat = frames["au"].copy()
    for c in ("open", "high", "low", "close"):
        flat[c] = 1.10
    ctxs = [_ctx("EURUSD", "boll@EURUSD", "bollinger_reversal",
                 frames["fx"], FX_SPEC),
            _ctx("XAUUSD", "macd@XAUUSD", "macd_momentum", flat, AU_SPEC)]
    eng = _engine(frames, contexts=ctxs)
    res = _seam_run(eng)
    assert (res.trades["symbol"] == "XAUUSD").sum() == 0
    assert (res.trades["symbol"] == "EURUSD").sum() > 0


# F3: broker margin always refused -----------------------------------------


def test_f3_margin_always_refused_is_safe_hold(frames):
    used = {"calls": 0}

    def no_margin(lots):
        used["calls"] += 1
        return 1e18

    ctxs = [dataclasses.replace(c, margin_calc=no_margin)
            for c in _contexts(frames)]
    eng = _engine(frames, contexts=ctxs)
    res = _seam_run(eng)
    assert used["calls"] > 0                     # the seam was exercised
    assert len(res.trades) == 0                  # SAFE HOLD: no entries
    assert res.equity.iloc[-1] == pytest.approx(eng.initial_capital)
    assert not any(e.get("type") == "open" for e in res.events)


# F4: conversion missing -----------------------------------------------------


def test_f4_missing_conversion_is_journaled_ineligible(frames):
    bad = _ctx("XAUUSD", "macd@XAUUSD", "macd_momentum",
               frames["au"], dataclasses.replace(
                   AU_SPEC, currency_profit="EUR"))
    eng = _engine(frames, contexts=[bad, _ctx(
        "EURUSD", "boll@EURUSD", "bollinger_reversal",
        frames["fx"], FX_SPEC)])
    assert [i["strategy_id"] for i in eng.ineligible] == ["macd@XAUUSD"]
    res = eng.run()
    assert (res.meta.trades["symbol"] == "EURUSD").any()
    assert "macd@XAUUSD" not in set(res.meta.trades["strategy"])


# F5: regime feed starved (too little history) -------------------------------


def test_f5_regime_starved_symbol_is_unknown_not_fatal(frames):
    eng = _engine(frames)
    tiny = frames["au"].iloc[:40]                # < VOL_WINDOW + 2 bars
    snap = eng.snapshot(eng.rebalances[0])
    assert snap.regimes["XAUUSD"].label in {"UNKNOWN", "RANGE",
                                            "HIGH_VOL", "LOW_VOL"}
    from mql5bot.regime_feed import regime_snapshot
    starved = regime_snapshot(tiny["close"], tiny.index[-1])
    assert starved.label == "UNKNOWN"
    # decisions still produce weights with an UNKNOWN regime input
    layer = MetaLayer(eng.config)
    w, _ = eng.decide_weights(eng.rebalances[0], MetaPolicy.META, layer)
    assert set(w) == {"boll@EURUSD", "ema@EURUSD", "macd@XAUUSD"}


# F6: correlation matrix degenerate (no closed trades) -----------------------


def test_f6_no_trade_books_yield_equal_weight_fallback(frames):
    """Warmup longer than history ⇒ no stats, no returns variance ⇒ the
    documented GLOBAL source failure baseline: equal weight over the
    eligible books (never a crash, never full-risk on one book)."""
    # warmup=5 bars: every decision input is still MISSING at t (no
    # indicator can have signalled, no trade can have closed)
    eng = _engine(frames, min_history_bars=5)
    t = eng.rebalances[0]
    snap = eng.snapshot(t)
    assert all(n == 0 for _, n in snap.stats.values())
    layer = MetaLayer(eng.config)
    w, _ = eng.decide_weights(t, MetaPolicy.META, layer)
    assert w and len(set(w.values())) == 1        # all-equal fallback


# F7: drift ledger empty ------------------------------------------------------


def test_f7_empty_drift_ledger_is_missing_fallback_baseline(frames):
    from mql5bot.drift_feed import drift_snapshot
    empty = pd.DataFrame({"exit_time": pd.Series(dtype="datetime64[ns]"),
                          "pnl_pct": pd.Series(dtype=float),
                          "bars_held": pd.Series(dtype=float)})
    snap = drift_snapshot(empty, "fresh", pd.Timestamp("2024-06-01"))
    assert snap.status == "UNKNOWN"
    assert snap.overall_score == 0.0              # conservative feed
    # the layer's MISSING ladder applies the 0.5 fallback, not neutral
    from mql5bot.meta_layer import DRIFT_MISSING
    assert DRIFT_MISSING == 0.5
    eng = _engine(frames)
    layer = MetaLayer(eng.config)
    w, _ = eng.decide_weights(eng.rebalances[0], MetaPolicy.META, layer)
    assert len(w) == 3 and all(0.0 <= v <= 1.0 for v in w.values())
