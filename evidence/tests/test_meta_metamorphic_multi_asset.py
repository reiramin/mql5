"""Metamorphic invariants for the multi-asset Meta engine (Phase 24).

Each test re-runs the engine under a semantics-preserving (or
safety-tightening) transformation and pins the REQUIRED relationship:
permutation/timestamp invariance, caps can only reduce exposure, cost
degradation cannot reduce costs, certification zeros stay zero,
unrelated symbols cannot change a book's decision inputs, and a restart
from the runtime state reproduces the decision suffix.
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest
from mql5bot.data import generate_ohlc
from mql5bot.meta_layer import MetaLayer, MetaPolicy, MetaState
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
    # smaller than the realism suite: these are invariance pins, the
    # snapshot restart test is the only decide-level test here
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


def _full_schedules(eng, weight=1.0):
    return {c.strategy_id: tuple((t, weight) for t in eng.rebalances)
            for c in eng.contexts}


# ------------------------------------------------------- transformations


def test_symbol_and_book_permutation_invariance(frames):
    """Context list order and book-id sort order never change the run."""
    eng_a = _engine(frames)
    perm = [_contexts(frames)[i] for i in (2, 0, 1)]
    eng_b = _engine(frames, contexts=perm)
    ra = _seam_run(eng_a, schedules=_full_schedules(eng_a, 0.5))
    rb = _seam_run(eng_b, schedules=_full_schedules(eng_b, 0.5))
    cols = ["symbol", "strategy", "entry_time", "exit_time", "lots",
            "pnl"]
    pd.testing.assert_frame_equal(
        ra.trades[cols].reset_index(drop=True),
        rb.trades[cols].reset_index(drop=True))
    pd.testing.assert_series_equal(ra.equity, rb.equity)


def test_input_order_normalized_to_sorted_book_ids(frames):
    """The engine canonicalizes context order to sorted(strategy_id):
    any input permutation yields the SAME engine layout.  (The sorted
    order itself is load-bearing — it arbitrates shared-account budget
    consumption across lines — so it is run identity, and book renames
    that reorder it are a NEW run, documented in the audit register.)"""
    perm = [_contexts(frames)[i] for i in (2, 0, 1)]
    eng = _engine(frames, contexts=perm)
    assert [c.strategy_id for c in eng.contexts] == \
        ["boll@EURUSD", "ema@EURUSD", "macd@XAUUSD"]


def test_timestamp_shift_invariance(frames):
    """Shifting every frame (and the grid) by +30 days shifts trade
    timestamps 1:1 and changes nothing else."""
    def shift(df, days):
        out = df.copy()
        out.index = out.index + pd.Timedelta(days=days)
        return out

    fx2 = shift(frames["fx"], 30)
    au2 = shift(frames["au"], 30)
    ctxs2 = [_ctx("EURUSD", "boll@EURUSD", "bollinger_reversal",
                  fx2, FX_SPEC),
             _ctx("XAUUSD", "macd@XAUUSD", "macd_momentum", au2, AU_SPEC)]
    eng_a = _engine(frames, contexts=_contexts(frames)[:1]
                    + _contexts(frames)[2:])
    eng_b = _engine(frames, contexts=ctxs2)
    ra = _seam_run(eng_a, schedules=_full_schedules(eng_a))
    rb = _seam_run(eng_b, schedules=_full_schedules(eng_b))
    assert len(ra.trades) == len(rb.trades) > 0
    a = ra.trades.reset_index(drop=True)
    b = rb.trades.reset_index(drop=True)
    for col in ("entry_time", "exit_time"):
        assert (pd.to_datetime(b[col]) - pd.to_datetime(a[col])
                == pd.Timedelta(days=30)).all()
    for col in ("symbol", "strategy", "side", "entry_price", "lots",
                "pnl"):
        assert (a[col] == b[col]).all()


# ------------------------------------------------- safety tightening


def test_lower_heat_cap_cannot_increase_exposure(frames):
    eng = _engine(frames)
    loose = _seam_run(eng, schedules=_full_schedules(eng, 0.5),
                      portfolio_heat_max=0.9)
    tight = _seam_run(eng, schedules=_full_schedules(eng, 0.5),
                      portfolio_heat_max=0.25)

    def traded_notional(res):
        # notional put at risk across all opens (deposit currency)
        contracts = {"EURUSD": 100_000.0, "XAUUSD": 10_000.0}
        return sum(r.lots * r.entry_price * contracts[r.symbol]
                   for r in res.trades.itertuples())

    assert traded_notional(tight) <= traded_notional(loose)
    tight_rejects = sum(1 for e in tight.events
                        if e.get("type") == "reject"
                        and e.get("code") == "portfolio_heat")
    assert tight_rejects > 0


def test_lower_margin_budget_cannot_increase_exposure(frames):
    ctxs = _contexts(frames)

    def run(budget_lots):
        used = {"lots": 0.0}

        def shared_margin(lots):
            used["lots"] += lots
            return used["lots"] if used["lots"] <= budget_lots else 1e18

        ctxs2 = [dataclasses.replace(c, margin_calc=shared_margin)
                 for c in ctxs]
        eng = _engine(frames, contexts=ctxs2)
        return _seam_run(eng)

    loose = run(3.0)
    tight = run(0.8)
    assert tight.trades["lots"].sum() < loose.trades["lots"].sum()
    assert any(e.get("code") == "margin_rejected" for e in tight.events)


def test_wider_spread_cannot_improve_costs(frames):
    """Doubling the spread must never reduce the per-lot cost of the
    same symbol's executions (paths may diverge; per-lot cost cannot)."""
    def run(spread):
        ctxs = [dataclasses.replace(
            c, costs=dataclasses.replace(c.costs,
                                         spread_points=spread))
            for c in _contexts(frames)]
        eng = _engine(frames, contexts=ctxs)
        return _seam_run(eng, schedules=_full_schedules(eng))

    tight = run(1.0)
    wide = run(2.0)

    def per_lot_cost(res, symbol):
        t = res.trades[res.trades["symbol"] == symbol]
        return t["costs"].sum() / t["lots"].sum()

    for symbol in ("EURUSD", "XAUUSD"):
        assert per_lot_cost(wide, symbol) >= per_lot_cost(tight, symbol)


# ------------------------------------------------------ hard zeros


def test_uncertified_books_stay_zero(frames):
    """certified=set() → every book UNCERTIFIED → weight 0 by the
    certification gate, at this decision and every later one."""
    eng = _engine(frames, certified=set())
    layer = MetaLayer(eng.config)
    for t in eng.rebalances[:2]:
        w, _ = eng.decide_weights(t, MetaPolicy.META, layer)
        assert w and all(v == 0.0 for v in w.values())


# ------------------------------------------- unrelated-symbol independence


def test_unrelated_symbol_does_not_change_book_inputs(frames):
    """Removing an unrelated symbol leaves the remaining book's decision
    INPUTS (stats, regime, drift) bit-identical.  Weights may still
    differ through the correlation matrix — that coupling is documented,
    the per-book causal inputs are not allowed to move."""
    both = _engine(frames)
    only_fx = _engine(frames, contexts=_contexts(frames)[:2])
    t = both.rebalances[3]
    sa = both.snapshot(t)
    sb = only_fx.snapshot(t)
    assert sa.stats["boll@EURUSD"] == sb.stats["boll@EURUSD"]
    assert sa.stats["ema@EURUSD"] == sb.stats["ema@EURUSD"]
    assert sa.regimes["EURUSD"].label == sb.regimes["EURUSD"].label
    da, db = sa.drift["boll@EURUSD"], sb.drift["boll@EURUSD"]
    assert (da.overall_score, da.status) == (db.overall_score, db.status)


# ------------------------------------------------------ restart equivalence


def test_restart_at_rebalance_reproduces_suffix(frames):
    """A layer restarted from the runtime state (final weights + zero
    reasons) after decision k reproduces the decision suffix exactly."""
    eng = _engine(frames)
    t1, t2 = eng.rebalances[2], eng.rebalances[3]
    layer = MetaLayer(eng.config)
    eng.decide_weights(t1, MetaPolicy.META, layer)
    state_after_t1 = MetaState(
        config_hash=layer.state.config_hash,
        as_of=layer.state.as_of,
        weights=dict(layer.state.weights),
        zeroed=dict(layer.state.zeroed),
        activation=layer.state.activation)
    w2_full, j2_full = eng.decide_weights(t2, MetaPolicy.META, layer)

    restarted = MetaLayer(eng.config, state=state_after_t1)
    w2_restart, _ = eng.decide_weights(t2, MetaPolicy.META, restarted)
    for k in w2_full:
        assert w2_restart[k] == pytest.approx(w2_full[k])
    for k in w2_full:
        assert j2_full[f"w::{k}"] == w2_full[k]
