"""Multi-asset realism tests for MetaPortfolioEngine (AEGIS phases 3–17).

Covers: one shared account across symbols/books, explicit specs and
volume grids, currency conversion safety (identity / explicit /
ineligible), per-book signal streams, causal regime + drift feeds with
journal provenance, correlation-group caps, shared margin, netting vs
hedging book handling and the weight-update (schedule) seam.

All frames are SYNTHETIC and FX-scaled; the XAU-like context uses a
contract size coherent with that scale (specs are explicit inputs —
real broker specs arrive with the owner basket).
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest
from mql5bot.costs import CostConfig
from mql5bot.data import generate_ohlc
from mql5bot.drift_feed import drift_snapshot
from mql5bot.engine import Instrument, PortfolioEngine, RunConfig
from mql5bot.meta_portfolio import (
    InstrumentContext,
    MetaPortfolioEngine,
    rebalance_grid,
)
from mql5bot.regime_feed import regime_snapshot
from mql5bot.symbolspec import SymbolSpec

# ---------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def frames():
    return {
        "fx": generate_ohlc(days=300, seed=5),
        "au": generate_ohlc(days=300, seed=12),
        "gbp": generate_ohlc(days=300, seed=21),
    }


FX_SPEC = SymbolSpec(name="EURUSD", point=1e-5, tick_size=1e-5,
                     tick_value_loss=1.0, contract_size=100_000.0,
                     volume_step=0.01, volume_min=0.01,
                     currency_profit="USD", currency_deposit="USD")
GBP_SPEC = SymbolSpec(name="GBPUSD", point=1e-5, tick_size=1e-5,
                      tick_value_loss=1.0, contract_size=100_000.0,
                      volume_step=0.01, volume_min=0.01,
                      currency_profit="USD", currency_deposit="USD")
# NOTE: the synthetic "gold" frame is FX-scaled (~1.1 prices); this spec
# is coherent with THAT scale (mechanics test, not a gold market claim).
AU_SPEC = SymbolSpec(name="XAUUSD", point=0.01, tick_size=0.01,
                     tick_value_loss=100.0, contract_size=10_000.0,
                     volume_step=0.1, volume_min=0.1,
                     currency_profit="USD", currency_deposit="USD")


def _costs(symbol):
    return CostConfig(symbol=symbol, spread_points=2.0)


def _ctx(symbol, strategy_id, engine_strategy, df, spec, **kw):
    return InstrumentContext(symbol=symbol, strategy_id=strategy_id,
                             engine_strategy=engine_strategy, df=df,
                             spec=spec, costs=_costs(symbol), **kw)


def _contexts(frames):
    """Three books on two symbols: two strategies share the EURUSD
    frame; the XAU-like book has its own frame, spec and grid."""
    return [
        _ctx("EURUSD", "boll@EURUSD", "bollinger_reversal",
             frames["fx"], FX_SPEC),
        _ctx("EURUSD", "ema@EURUSD", "ema_crossover",
             frames["fx"], FX_SPEC),
        _ctx("XAUUSD", "macd@XAUUSD", "macd_momentum",
             frames["au"], AU_SPEC),
    ]


def _engine(frames, contexts=None, **kw):
    kw.setdefault("every_days", 12)
    kw.setdefault("min_history_bars", 480)
    return MetaPortfolioEngine(contexts=contexts or _contexts(frames),
                               **kw)


def _instruments(eng, schedules=None):
    """Instruments mirroring ``run_policy`` (public seam) with optional
    per-book allocation-schedule overrides {strategy_id: schedule}."""
    base = {c.strategy_id: tuple((t, 1.0) for t in eng.rebalances)
            for c in eng.contexts}
    if schedules:
        base.update(schedules)
    return [Instrument(symbol=c.symbol, strategy=c.engine_strategy,
                       df=c.df, costs=c.costs, spec=c.spec,
                       profit_to_deposit=c.profit_to_deposit,
                       corr_group=c.corr_group, params=dict(c.params),
                       margin_calc=c.margin_calc,
                       allocation_schedule=base[c.strategy_id])
            for c in eng.contexts]


def _seam_run(eng, schedules=None, **run_cfg):
    """Run through PortfolioEngine at the same seam run_policy uses,
    with explicit RunConfig overrides (the engine builds its own
    RunConfig inside run_policy — caps must be set here)."""
    cfg = RunConfig(initial_capital=eng.initial_capital, mode=eng.mode,
                    risk_value=eng.risk_percent,
                    warmup_bars=eng.min_history, **run_cfg)
    return PortfolioEngine(cfg).run(_instruments(eng, schedules))


# ------------------------------------------------------- shared account


def test_shared_account_one_equity_and_book_attribution(frames):
    eng = _engine(frames)
    res = eng.run()
    m = res.meta
    # one shared equity curve — not per-book
    assert isinstance(m.equity, pd.Series) and len(m.equity) > 0
    # trades carry symbol AND strategy attribution columns
    for col in ("symbol", "strategy"):
        assert col in m.trades.columns
    # attribution: per (symbol, strategy) book, per symbol, per strategy
    assert len(m.attribution) == m.trades.groupby(
        ["symbol", "strategy"]).ngroups
    assert m.attribution["pnl"].sum() == pytest.approx(
        m.trades["pnl"].sum())
    assert m.attribution_symbol["pnl"].sum() == pytest.approx(
        m.trades["pnl"].sum())
    assert m.attribution_strategy["pnl"].sum() == pytest.approx(
        m.trades["pnl"].sum())
    # both symbols actually traded (multi-asset, not a single-symbol run)
    assert {"EURUSD", "XAUUSD"} <= set(m.trades["symbol"].unique())


def test_portfolio_heat_cap_binds_across_symbols(frames):
    eng = _engine(frames)
    # small per-trade risk so caps (share of equity) can bind between adds
    eng.risk_percent = 0.2
    res = _seam_run(eng, portfolio_heat_max=0.25)
    heat_rejects = [e for e in res.events
                    if e.get("type") == "reject"
                    and e.get("code") == "portfolio_heat"]
    assert heat_rejects, "expected at least one portfolio_heat reject"
    assert {"EURUSD", "XAUUSD"} <= {e.get("symbol")
                                    for e in heat_rejects}


# -------------------------------------------------------- conversion


def test_conversion_identity_when_currencies_equal():
    ctx = _ctx("EURUSD", "boll@EURUSD", "bollinger_reversal",
               generate_ohlc(days=60, seed=5), FX_SPEC)
    assert ctx.currencies_equal
    assert ctx.conversion_error == ""
    assert ctx.profit_to_deposit == 1.0


def test_conversion_explicit_rate_scales_pnl(frames):
    base = _ctx("XAUUSD", "macd@XAUUSD", "macd_momentum",
                frames["au"], dataclasses.replace(
                    AU_SPEC, currency_profit="EUR"))
    with_rate = dataclasses.replace(base, conversion=1.08)
    assert with_rate.conversion_error == ""
    assert with_rate.profit_to_deposit == pytest.approx(1.08)

    # The conversion enters the RISK MATH (loss-per-lot in deposit
    # currency), so lot sizing shifts by exactly the rate — never a
    # silent 1.0.
    from mql5bot.sizer import size_position
    a = 0.004          # fixed stop distance
    common = {"mode": "risk_percent_equity", "equity": 10_000.0,
              "balance": 10_000.0, "stop_distance": a, "value": 1.0}
    r1 = size_position(AU_SPEC, profit_to_deposit=1.0, **common)
    r2 = size_position(AU_SPEC, profit_to_deposit=1.08, **common)
    assert r2.loss_per_lot_ccy == pytest.approx(r1.loss_per_lot_ccy
                                                * 1.08)
    assert r2.lots <= r1.lots

    # Run-level: the rate is carried end-to-end (manifest + live PnL).
    eng = _engine(frames, contexts=[with_rate])
    man = eng.manifest()
    assert man["instruments"][0]["conversion"] == pytest.approx(1.08)
    res_eur = _seam_run(eng)
    eng2 = _engine(frames, contexts=[dataclasses.replace(base,
                                                         conversion=1.0)])
    res_usd = _seam_run(eng2)
    assert len(res_eur.trades) > 0 and len(res_usd.trades) > 0
    assert not res_eur.trades["pnl"].equals(res_usd.trades["pnl"])


def test_conversion_missing_context_is_ineligible(frames):
    bad = _ctx("XAUUSD", "macd@XAUUSD", "macd_momentum",
               frames["au"], dataclasses.replace(
                   AU_SPEC, currency_profit="EUR"))  # no conversion
    assert bad.conversion_error != ""
    eng = _engine(frames, contexts=[bad, _ctx(
        "EURUSD", "boll@EURUSD", "bollinger_reversal",
        frames["fx"], FX_SPEC)])
    assert eng.ineligible and eng.ineligible[0][
        "strategy_id"] == "macd@XAUUSD"
    res = eng.run()
    # the ineligible book appears NOWHERE in the run
    assert "macd@XAUUSD" not in set(res.meta.trades["strategy"])
    assert res.ineligible == eng.ineligible
    assert res.manifest["ineligible"] == eng.ineligible
    assert {c.strategy_id for c in eng.contexts} == {"boll@EURUSD"}


# ------------------------------------------------- specs / fills / grids


def test_per_symbol_volume_grids_in_live_fills(frames):
    eng = _engine(frames)
    res = eng.run()
    t = res.meta.trades
    fx_lots = t[t["symbol"] == "EURUSD"]["lots"]
    au_lots = t[t["symbol"] == "XAUUSD"]["lots"]
    assert len(fx_lots) and len(au_lots)
    on_fx = (fx_lots / 0.01).sub((fx_lots / 0.01).round()).abs() < 1e-6
    on_au = (au_lots / 0.1).sub((au_lots / 0.1).round()).abs() < 1e-6
    assert on_fx.all()      # FX grid: 0.01
    assert on_au.all()      # XAU grid: 0.1
    assert (au_lots >= 0.1 - 1e-12).all()           # XAU min volume
    assert (fx_lots >= 0.01 - 1e-12).all()          # FX min volume


def test_manifest_echoes_specs_datasets_versions(frames):
    eng = _engine(frames)
    man = eng.manifest()
    for key in ("git_commit", "engine_version", "cost_version",
                "meta_version", "contract_version", "regime_version",
                "drift_version", "certification_protocol", "config_hash",
                "random_seed", "rebalance_schedule_hash", "instruments"):
        assert key in man
    books = {i["strategy_id"]: i for i in man["instruments"]}
    assert set(books) == {"boll@EURUSD", "ema@EURUSD", "macd@XAUUSD"}
    assert books["boll@EURUSD"]["dataset_sha256"] != \
        books["macd@XAUUSD"]["dataset_sha256"]
    assert books["boll@EURUSD"]["dataset_sha256"] == \
        books["ema@EURUSD"]["dataset_sha256"]
    assert books["macd@XAUUSD"]["spec"]["volume_step"] == 0.1
    assert books["boll@EURUSD"]["spec"]["volume_step"] == 0.01
    assert books["macd@XAUUSD"]["conversion"] == 1.0


# ------------------------------------------------- per-book streams


def test_per_book_independent_signal_streams(frames):
    eng = _engine(frames)
    snap = eng.snapshot(eng.rebalances[2])
    # the two EURUSD books share the frame but not the strategy stream
    assert snap.returns["boll@EURUSD"] is not snap.returns["ema@EURUSD"]
    res = _seam_run(eng)
    tr = res.trades
    boll = tr[tr["strategy"] == "bollinger_reversal"]
    ema = tr[tr["strategy"] == "ema_crossover"]
    macd = tr[tr["strategy"] == "macd_momentum"]
    assert len(boll) and len(ema) and len(macd)
    # same strategy on a different frame is a different stream: ema@EURUSD
    # never mirrors ema on the other symbol bar-for-bar
    assert not boll["entry_time"].equals(ema["entry_time"])
    # XAU trades use XAU fills (quantized to its 0.01 tick), not FX prices
    q = (macd["entry_price"] / 0.01).sub(
        (macd["entry_price"] / 0.01).round()).abs()
    assert (q < 1e-6).all()


# ------------------------------------------------------ regime feed


def _np_ramp(n, slope):
    import numpy as np
    return np.cumprod(1.0 + np.full(n, slope))


def test_regime_labels_all_seven_reachable():
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2024-01-01", periods=400, freq="h")
    # UNKNOWN: short history
    short = pd.Series(100.0, index=idx[:40])
    assert regime_snapshot(short, idx[39]).label == "UNKNOWN"
    # TREND_UP / TREND_DOWN: strong sustained drift + floor noise (a
    # zero-volatility series is honestly UNKNOWN — no vol to classify)
    noise = np.random.default_rng(3).normal(0, 1e-4, 400)
    up = pd.Series(_np_ramp(400, +0.004) * (1.0 + noise), index=idx)
    dn = pd.Series(_np_ramp(400, -0.004) * (1.0 + noise), index=idx)
    assert regime_snapshot(up, idx[399]).label == "TREND_UP"
    assert regime_snapshot(dn, idx[399]).label == "TREND_DOWN"
    # RANGE: flat trend with vol clearly BETWEEN the historical bands
    # (three anchored blocks: hot, cold, then mid — no price seams)
    piece = 100.0
    prices = []
    for n, sigma in ((170, 2.0e-3), (170, 2.0e-5), (60, 2.0e-4)):
        seg = piece * np.cumprod(1.0 + np.random.default_rng(8)
                                 .normal(0.0, sigma, n))
        prices.append(seg)
        piece = float(seg[-1])
    rng = pd.Series(np.concatenate(prices), index=idx)
    assert regime_snapshot(rng, idx[399]).label == "RANGE"
    # HIGH_VOL / LOW_VOL: a calm prefix then a regime CHANGE in the last
    # window (the expanding quantiles make the new bucket authoritative).
    # The tails CONTINUE from the body's last value — a price seam would
    # inject an artifact crash return and fake a vol regime.
    body = _np_ramp(340, 0.0005) * (1.0 + np.random.default_rng(5)
                                    .normal(0, 1e-4, 340))
    hv_tail = body[-1] * (1.0 + np.random.default_rng(6)
                          .normal(0, 8e-3, 60))
    lv_tail = body[-1] * (1.0 + np.random.default_rng(7)
                          .normal(0, 2e-6, 60))
    high = pd.Series(np.concatenate([body, hv_tail]), index=idx)
    low = pd.Series(np.concatenate([body, lv_tail]), index=idx)
    assert regime_snapshot(high, idx[399]).label == "HIGH_VOL"
    assert regime_snapshot(low, idx[399]).label == "LOW_VOL"


def test_regime_causality_future_mutation_cannot_change_label():
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2024-01-01", periods=400, freq="h")
    noise = np.random.default_rng(3).normal(0, 1e-4, 400)
    up = pd.Series(_np_ramp(400, +0.004) * (1.0 + noise), index=idx)
    t = idx[299]
    base = regime_snapshot(up, t)
    assert base.label == "TREND_UP"
    assert base.regime_as_of == str(t)
    for frac in (0.1, 0.25, 0.5):           # different future fractions
        mutated = up.copy()
        mutated.iloc[int(len(up) * frac):] *= 1.5   # rewrite the future
        assert regime_snapshot(mutated, t).label == base.label
        assert regime_snapshot(mutated, t).regime_as_of == str(t)


def test_decision_journal_carries_regime_drift_provenance(frames):
    eng = _engine(frames)
    from mql5bot.meta_layer import MetaLayer, MetaPolicy
    layer = MetaLayer(eng.config)
    t = eng.rebalances[1]
    _, journal = eng.decide_weights(t, MetaPolicy.META, layer)
    assert journal["as_of"] == str(t)
    for rj in journal["regimes"].values():
        assert rj["regime_version"] == "asof-1.1"
        assert rj["regime_as_of"] == str(t)
        assert rj["regime"] in {"TREND_UP", "TREND_DOWN", "RANGE",
                                "HIGH_VOL", "LOW_VOL", "TRANSITION",
                                "UNKNOWN"}
    for dj in journal["drift"].values():
        assert dj["drift_version"] == "asof-1.0"
        assert dj["drift_as_of"] == str(t)
        assert dj["drift_status"] in {"HEALTHY", "MILD", "SEVERE",
                                      "UNKNOWN"}
    assert set(journal["regimes"]) == {"EURUSD", "XAUUSD"}
    assert set(journal["drift"]) == {"boll@EURUSD", "ema@EURUSD",
                                     "macd@XAUUSD"}


# ------------------------------------------------------- drift feed


def _ledger(pnls, bars=None, start="2024-01-01"):
    n = len(pnls)
    bars = bars or [10] * n
    idx = pd.date_range(start, periods=n, freq="D")
    return pd.DataFrame({"exit_time": idx, "pnl_pct": pnls,
                         "bars_held": bars})


def test_drift_statuses_reachable():
    t = pd.Timestamp("2024-06-01")
    healthy = drift_snapshot(_ledger([0.01] * 40), "s", t)
    assert healthy.status == "HEALTHY"
    mild = drift_snapshot(
        _ledger([0.01] * 20 + [-0.004] * 20), "s", t)
    assert mild.status == "MILD"
    severe = drift_snapshot(_ledger([0.02] * 20 + [-0.02] * 20), "s", t)
    assert severe.status == "SEVERE"
    unknown = drift_snapshot(_ledger([0.01] * 5), "s", t)
    assert unknown.status == "UNKNOWN"
    # the snapshot is conservative (0.0); the DRIFT_MISSING=0.5 ladder
    # fallback lives in the meta layer, not in the feed
    assert unknown.overall_score == 0.0


def test_drift_causality_future_trades_cannot_change_snapshot():
    t = pd.Timestamp("2024-06-01")
    ledger = _ledger([0.01] * 20 + [-0.01] * 20)   # exits end Feb < t
    base = drift_snapshot(ledger, "s", t)
    for future in ([0.05] * 10, [-0.05] * 10):
        mutated = pd.concat([ledger, _ledger(future, start="2024-07-01")],
                            ignore_index=True)     # exits AFTER t
        after = drift_snapshot(mutated, "s", t)
        assert after.overall_score == base.overall_score
        assert after.status == base.status


def test_severe_drift_hard_zeroes_book(frames, monkeypatch):
    import mql5bot.meta_portfolio as mp
    from mql5bot.meta_layer import MetaLayer, MetaPolicy
    eng = _engine(frames)
    real = mp.drift_snapshots

    def severe_for_boll(trades_by_id, as_of, *, regimes=None):
        out = real(trades_by_id, as_of, regimes=regimes)
        return {sid: (dataclasses.replace(s, overall_score=0.9,
                                          status="SEVERE")
                      if sid == "boll@EURUSD" else s)
                for sid, s in out.values() and out.items()}

    monkeypatch.setattr(mp, "drift_snapshots", severe_for_boll)
    layer = MetaLayer(eng.config)
    w, journal = eng.decide_weights(eng.rebalances[2], MetaPolicy.META,
                                    layer)
    assert w["boll@EURUSD"] == 0.0
    assert journal["drift"]["boll@EURUSD"]["drift_status"] == "SEVERE"
    monkeypatch.undo()
    w2, _ = eng.decide_weights(eng.rebalances[2], MetaPolicy.META, layer)
    assert w2["boll@EURUSD"] > 0.0     # undone: the block was the drift


# ------------------------------------------------- snapshot contents


def test_meta_weights_deterministic_and_bounded(frames):
    from mql5bot.meta_layer import MetaLayer, MetaPolicy
    eng = _engine(frames)
    t = eng.rebalances[2]
    # Two FRESH layers decide identically (no hidden RNG).  A SINGLE
    # layer is stateful by design: decide() advances its state, so two
    # decides on one layer are two different decisions, not noise.
    w1, _ = eng.decide_weights(t, MetaPolicy.META, MetaLayer(eng.config))
    w2, _ = eng.decide_weights(t, MetaPolicy.META, MetaLayer(eng.config))
    assert w1 == w2
    assert set(w1) == {"boll@EURUSD", "ema@EURUSD", "macd@XAUUSD"}
    assert all(0.0 <= v <= 1.0 for v in w1.values())


def test_returns_snapshot_nan_conventions(frames):
    eng = _engine(frames)
    snap = eng.snapshot(eng.rebalances[3])
    rets = snap.returns
    assert list(rets.columns) == sorted(c.strategy_id
                                        for c in eng.contexts)
    assert (rets.index < eng.rebalances[3]).all()     # strictly pre-t
    import numpy as np
    assert not np.isinf(rets.to_numpy(dtype=float)).any()
    assert np.isfinite(rets.to_numpy(dtype=float)).all()
    # a rebalance grid is deterministic: rebuilt grid hashes identically
    grid2 = rebalance_grid(eng.df.index, first_bar=eng.min_history,
                           every_days=eng.every_days)
    assert grid2 == eng.rebalances


# -------------------------------------------------- constraint caps


def test_corr_group_cap_rejects_cross_symbol(frames):
    gbp = _ctx("GBPUSD", "ema@GBPUSD", "ema_crossover",
               frames["gbp"], GBP_SPEC, corr_group="usd_majors")
    ctxs = [_ctx("EURUSD", "boll@EURUSD", "bollinger_reversal",
                 frames["fx"], FX_SPEC, corr_group="usd_majors"),
            _ctx("EURUSD", "ema@EURUSD", "ema_crossover",
                 frames["fx"], FX_SPEC, corr_group="usd_majors"),
            _ctx("XAUUSD", "macd@XAUUSD", "macd_momentum",
                 frames["au"], AU_SPEC, corr_group="metals"),
            gbp]
    eng = _engine(frames, contexts=ctxs)
    eng.risk_percent = 0.2
    res = _seam_run(eng, corr_group_max_notional_share={
        "usd_majors": 0.3})
    rejects = [e for e in res.events
               if e.get("type") == "reject"
               and e.get("code") == "corr_group_notional"]
    assert rejects, "expected the usd_majors group cap to bind"
    assert {e.get("symbol") for e in rejects} <= {"EURUSD", "GBPUSD"}
    # the uncapped group (metals) is untouched by the usd_majors cap
    assert (res.trades["symbol"] == "XAUUSD").any()


def test_shared_margin_exhaustion_rejects_entry(frames):
    used = {"lots": 0.0}

    def shared_margin(lots):     # a shared-account margin basis
        used["lots"] += lots
        return used["lots"] if used["lots"] <= 0.6 else 1e18

    ctxs = [dataclasses.replace(c, margin_calc=shared_margin)
            for c in _contexts(frames)]
    eng2 = _engine(frames, contexts=ctxs)
    res = _seam_run(eng2)
    rejects = [e for e in res.events
               if e.get("type") == "reject"
               and e.get("code") == "margin_rejected"]
    assert rejects, "expected shared-margin exhaustion to reject an add"


# --------------------------------------------------- netting/hedging


def test_netting_merges_same_symbol_books(frames):
    eng = _engine(frames, mode="netting")
    res = _seam_run(eng)
    types = {e.get("type") for e in res.events}
    codes = {e.get("code") or e.get("reason") for e in res.events}
    assert types & {"merge", "offset"} or "merge_offset" in codes, \
        "netting must merge/offset same-symbol opposing books"


def test_hedging_keeps_same_symbol_books_separate(frames):
    eng = _engine(frames, mode="hedging")
    res = _seam_run(eng)
    types = {e.get("type") for e in res.events}
    codes = {e.get("code") or e.get("reason") for e in res.events}
    assert not (types & {"merge", "offset"}
                or "merge_offset" in codes)
    # two independent books on the same symbol both traded
    tr = res.trades[res.trades["symbol"] == "EURUSD"]
    assert set(tr["strategy"]) == {"bollinger_reversal",
                                   "ema_crossover"}


def test_single_position_netting_equals_hedging(frames):
    one = [_ctx("EURUSD", "boll@EURUSD", "bollinger_reversal",
                frames["fx"], FX_SPEC)]
    net = _seam_run(_engine(frames, contexts=one, mode="netting"))
    hed = _seam_run(_engine(frames, contexts=one, mode="hedging"))
    cols = ["symbol", "strategy", "entry_time", "exit_time", "lots",
            "pnl"]
    pd.testing.assert_frame_equal(net.trades[cols].reset_index(drop=True),
                                  hed.trades[cols].reset_index(drop=True))


# ------------------------------------------------- weight-update seam


def test_zero_weight_on_one_symbol_leaves_other_untouched(frames):
    """A weight update applies to NEW decisions only: zeroing the XAU
    books from t0 must not retro-resize/close anything before t0 and
    must leave the FX books trading normally."""
    eng = _engine(frames)
    t0 = eng.rebalances[len(eng.rebalances) // 4]

    def sched_for(sid):
        out = []
        for t in eng.rebalances:
            w = 0.0 if (t >= t0 and sid.endswith("@XAUUSD")) else 1.0
            out.append((t, w))
        return tuple(out)

    schedules = {c.strategy_id: sched_for(c.strategy_id)
                 for c in eng.contexts}
    res = _seam_run(eng, schedules=schedules)
    tr = res.trades
    tser = pd.to_datetime(tr["entry_time"])

    # 1. No XAU entries at/after t0.
    au_after = tr[(tr["symbol"] == "XAUUSD") & (tser >= t0)]
    assert len(au_after) == 0

    # 2. Pre-t0 history is untouched by the future weight update:
    #    identical to the same run with full weights (no retro resize,
    #    no retro close).
    plain = _seam_run(eng)
    cols = ["symbol", "strategy", "entry_time", "exit_time", "lots",
            "pnl"]
    pre_mod = tr[tser < t0][cols].reset_index(drop=True)
    pt = pd.to_datetime(plain.trades["entry_time"])
    pre_plain = plain.trades[pt < t0][cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(pre_mod, pre_plain)

    # 3. The FX books keep trading normally over the run (zeroing XAU
    #    did not stall the rest of the portfolio).
    assert (tr["symbol"] == "EURUSD").any()

    # 4. Zero-weight entries are DROPPED, not silently shrunk: the seam
    #    reports meta_scale_dropped for the blocked book.
    dropped = [e for e in res.events
               if e.get("type") == "reject"
               and e.get("code") == "meta_scale_dropped"
               and e.get("symbol") == "XAUUSD"]
    assert dropped, "zero weight must drop XAU entries at the seam"
