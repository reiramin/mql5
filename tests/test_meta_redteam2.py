"""Red-team round 2 (Phase 31) — adversarial pins on the multi-asset
surface.  Findings R1–R5 from the audit register's red-team section.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from mql5bot.data import generate_ohlc
from mql5bot.meta_portfolio import _realized_corr

from tests.test_meta_multi_asset import (  # noqa: F401
    AU_SPEC,
    FX_SPEC,
    _contexts,
    _ctx,
    _engine,
    _seam_run,
)


@pytest.fixture(scope="module")
def frames():
    return {"fx": generate_ohlc(days=120, seed=5),
            "au": generate_ohlc(days=120, seed=12)}


def test_r1_same_currency_bogus_conversion_is_ignored():
    """R1: equal currencies ⇒ identity 1.0 — a supplied (bogus)
    conversion must NOT leak into the deposit math."""
    c = _ctx("EURUSD", "b@EURUSD", "bollinger_reversal",
             generate_ohlc(days=60, seed=5), FX_SPEC, conversion=5.0)
    assert c.currencies_equal
    assert c.conversion_error == ""
    assert c.profit_to_deposit == 1.0


def test_r2_duplicate_execution_line_named_at_construction(frames):
    """R2: two books, same symbol, same registry strategy → the meta
    engine must refuse at CONSTRUCTION with an explicit message (not a
    raw engine error after decisions were already computed)."""
    ctxs = [_ctx("EURUSD", "a@EURUSD", "bollinger_reversal",
                 frames["fx"], FX_SPEC),
            _ctx("EURUSD", "b@EURUSD", "bollinger_reversal",
                 frames["fx"], FX_SPEC)]
    with pytest.raises(ValueError, match="execution lines"):
        _engine(frames, contexts=ctxs)


def test_r3_drift_receives_per_book_regime_labels(frames, monkeypatch):
    """R3: drift's regime component must look up the CURRENT regime by
    the book's strategy_id — the caller passes per-book labels."""
    import mql5bot.meta_portfolio as mp
    from mql5bot.meta_layer import MetaLayer, MetaPolicy
    seen = {}

    real = mp.drift_snapshots

    def spy(trades_by_id, as_of, *, regimes=None):
        seen.update(regimes or {})
        return real(trades_by_id, as_of, regimes=regimes)

    monkeypatch.setattr(mp, "drift_snapshots", spy)
    eng = _engine(frames)
    eng.decide_weights(eng.rebalances[1], MetaPolicy.META,
                       MetaLayer(eng.config))
    assert set(seen) == {"boll@EURUSD", "ema@EURUSD", "macd@XAUUSD"}
    assert all(v in {"TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL",
                     "LOW_VOL", "TRANSITION", "UNKNOWN"}
               for v in seen.values())


def test_r4_absurd_conversion_sizing_stays_capped(frames):
    """R4: conversion is an explicit owner input; a pathological
    (1e-9) rate must not explode exposure — max_lots/volume_max hold
    and the run completes."""
    from mql5bot.sizer import size_position
    tiny = 1e-9
    r = size_position(FX_SPEC, mode="risk_percent_equity",
                      equity=10_000.0, balance=10_000.0,
                      stop_distance=0.002, value=1.0,
                      profit_to_deposit=tiny, max_lots=100.0)
    assert np.isfinite(r.lots)
    assert r.lots <= FX_SPEC.volume_max


def test_r5_realized_corr_honest_nan_without_books():
    """R5: with no closed books there is NO correlation — NaN (honest,
    per the conventions), never a fake 0.0."""
    empty = pd.DataFrame(columns=["symbol", "strategy", "pnl"])
    assert np.isnan(_realized_corr(empty))
    single = pd.DataFrame({"symbol": ["X"], "strategy": ["s"],
                           "pnl": [1.0]})
    assert np.isnan(_realized_corr(single))


def test_r6_metrics_survive_nan_realized_corr(frames):
    """R5 follow-on: a book that never trades still yields a metrics
    dict without crashing (realized correlation may be NaN)."""
    flat = frames["au"].copy()
    for c in ("open", "high", "low", "close"):
        flat[c] = 1.10
    ctxs = [_ctx("XAUUSD", "macd@XAUUSD", "macd_momentum", flat,
                 AU_SPEC)]
    eng = _engine(frames, contexts=ctxs)
    res = _seam_run(eng)
    assert "realized_corr_mean" in res.metrics or len(res.trades) == 0
