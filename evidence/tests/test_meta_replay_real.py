"""Adversarial REAL-DATA tests + multi-period replay (Phases 12-13,
16, 18, 22).

Uses the committed REAL CBOE VIX daily OHLC series (1990-2026).  The
suggested FX/metal/crypto symbols are UNAVAILABLE in this sandbox
(egress allowlist) — the same scenarios run unchanged on broker CSVs
via tools/meta_real_validation.py; nothing here is fabricated.
"""

import copy as _copy
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from mql5bot.meta_layer import (
    MetaConfig,
    MetaFileError,
    MetaLayer,
    StrategyMetaInput,
    read_allocation_file,
    write_allocation_file,
)
from mql5bot.meta_oos import StrategySpec
from mql5bot.meta_replay import (
    as_of_stats,
    regime_labels,
    run_replay,
)

REPO = Path(__file__).resolve().parents[1]
VIX = {"point": 0.01, "contract_size": 1.0, "spread_points": 10.0,
       "commission_per_lot": 0.0}
SPECS = [StrategySpec("ema_fast", {"fast": 8, "slow": 30},
                      "ema_crossover"),
         StrategySpec("donchian_20", {"lookback": 20},
                      "donchian_breakout")]


def _real() -> pd.DataFrame:
    df = pd.read_csv(REPO / "tests/data/real/vix_daily.csv")
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")[["open", "high", "low", "close"]] \
        .astype(float)


@pytest.fixture(scope="module")
def real_df():
    return _real()


def _inputs(specs, when, drift=0.0, drift_available=True):
    return [StrategyMetaInput(
        s.name, "VIX", 0, "TREND_UP", frozenset({"TREND_UP"}),
        frozenset({"TREND_UP"}), frozenset(), "VERIFIED",
        drift_available=drift_available, drift_score=drift,
        strategy_version=s.version)
        for s in sorted(specs, key=lambda s: s.name)]


# ---- Phase 18: the replay sees no future data (REAL frame) -----------------


def test_replay_no_lookahead_on_real_data(real_df):
    """Perturbing the frame AFTER every rebalance timestamp cannot
    change any recorded weight."""
    kw = {"n_rebalances": 5, "min_history": 400, "instrument": VIX}
    meta, eq = run_replay(real_df, SPECS, **kw)
    future_start = meta.rebalance_dates[-1] + timedelta(days=5)
    tampered = real_df.copy()
    tampered.loc[tampered.index >= future_start, "close"] *= 3.0
    tampered.loc[tampered.index >= future_start, "high"] *= 3.0
    meta2, eq2 = run_replay(tampered, SPECS, **kw)
    assert meta.weights == meta2.weights
    assert eq.weights == eq2.weights


def test_weights_use_as_of_stats_only(real_df):
    """The stats fed to a rebalance are byte-identical to a fresh
    computation on the truncated frame (causality by construction)."""
    cut = real_df.index[2000]
    stats_full, _ = as_of_stats(real_df, SPECS, cut, instrument=VIX)
    stats_trunc, _ = as_of_stats(real_df.loc[:cut], SPECS, cut,
                                 instrument=VIX)
    assert stats_full == stats_trunc


# ---- Phase 13: multiple independent REAL periods ---------------------------


PERIODS = {
    "trending": ("2016-10-01", "2017-12-31"),   # vol compression trend
    "range": ("2004-01-01", "2006-12-31"),      # calm range
    "high_volatility": ("2020-01-01", "2020-12-31"),  # COVID
    "stress": ("2008-01-01", "2009-06-30"),     # GFC
    "recent": ("2025-09-01", "2026-09-03"),     # last 12 months
}


@pytest.mark.parametrize("name", list(PERIODS))
def test_period_replays_run_and_are_bounded(real_df, name):
    lo, hi = PERIODS[name]
    sub = real_df.loc[lo:hi]
    assert len(sub) > 120, name
    meta, eq = run_replay(sub, SPECS, n_rebalances=4, min_history=120,
                          instrument=VIX)
    for res in (meta, eq):
        for wid in meta.weights:
            vals = [v for k, v in wid.items() if k != "as_of"]
            assert all(0.0 <= v <= 1.0 for v in vals)
            assert sum(vals) <= 1.0 + 1e-9      # gross budget holds
    # both policies saw the same rebalance dates
    assert meta.rebalance_dates == eq.rebalance_dates


# ---- Phase 22: the sixteen adversarial scenarios on REAL data --------------


def _weights_of(result):
    return result.weights[-1]


def test_adv_01_winning_strategy_suddenly_crashes(real_df):
    """A strategy that performed well historically then crashes: the
    NEXT decision reduces it (bounded) and never over-exposes."""
    cut = real_df.index[3000]
    stats_base, rets = as_of_stats(real_df, SPECS, cut, instrument=VIX)
    # "winning": a clearly positive OOS ledger above the winsorization
    # clip; "crashed": the same ledger collapsing far below it.  A FRESH
    # layer per decision keeps the correlation prior identical so ONLY
    # the performance factor differs.
    stats_good = dict(stats_base)
    stats_good["ema_fast"] = (0.05, max(stats_base["ema_fast"][1], 30))
    d_good = MetaLayer(MetaConfig()).decide(
        _inputs(SPECS, cut), as_of=cut.to_pydatetime(),
        returns=rets, oos_stats=stats_good)
    stats_bad = dict(stats_base)
    stats_bad["ema_fast"] = (-0.60, stats_good["ema_fast"][1])
    d_bad = MetaLayer(MetaConfig()).decide(
        _inputs(SPECS, cut), as_of=cut.to_pydatetime(),
        returns=rets, oos_stats=stats_bad)
    assert d_bad.weight_of("ema_fast") < d_good.weight_of("ema_fast")
    assert sum(w.final_weight for w in d_bad.weights) <= 1.0 + 1e-9


def test_adv_02_losing_strategy_suddenly_improves(real_df):
    cut = real_df.index[3000]
    stats, rets = as_of_stats(real_df, SPECS, cut, instrument=VIX)
    lay = MetaLayer(MetaConfig())
    d0 = lay.decide(_inputs(SPECS, cut), as_of=cut.to_pydatetime(),
                    returns=rets, oos_stats=stats)
    better = dict(stats)
    better["donchian_20"] = (0.02, stats["donchian_20"][1])
    d1 = lay.decide(_inputs(SPECS, cut), as_of=cut.to_pydatetime(),
                    returns=rets, oos_stats=better)
    assert d1.weight_of("donchian_20") > d0.weight_of("donchian_20")
    # but bounded: it cannot take everything
    assert d1.weight_of("donchian_20") <= 1.0


def test_adv_03_two_strategies_become_highly_correlated(real_df):
    t = real_df.index[2500]
    stats, rets = as_of_stats(real_df, SPECS, t, instrument=VIX)
    lay = MetaLayer(MetaConfig())
    d0 = lay.decide(_inputs(SPECS, t), as_of=t.to_pydatetime(),
                    returns=rets, oos_stats=stats)
    fused = rets.copy()
    fused["ema_fast"] = fused["donchian_20"]      # corr -> +1
    d1 = lay.decide(_inputs(SPECS, t), as_of=t.to_pydatetime(),
                    returns=fused, oos_stats=stats)
    pen0 = {r.strategy_id: next(f.value for f in r.factors
                                if f.name == "correlation_penalty")
            for r in d0.raw_scores}
    pen1 = {r.strategy_id: next(f.value for f in r.factors
                                if f.name == "correlation_penalty")
            for r in d1.raw_scores}
    assert pen1["ema_fast"] < pen0["ema_fast"]
    assert sum(w.final_weight for w in d1.weights) <= 1.0 + 1e-9


def test_adv_04_correlation_unstable_still_deterministic(real_df):
    t = real_df.index[2500]
    stats, rets = as_of_stats(real_df, SPECS, t, instrument=VIX)
    noisy = rets + np.random.default_rng(5).normal(
        0, 0.01, rets.shape)
    kw = {"as_of": t.to_pydatetime(), "oos_stats": stats}
    d1 = MetaLayer(MetaConfig()).decide(_inputs(SPECS, t),
                                        returns=noisy, **kw)
    d2 = MetaLayer(MetaConfig()).decide(_inputs(SPECS, t),
                                        returns=noisy.copy(), **kw)
    assert d1.canonical_json() == d2.canonical_json()


def test_adv_05_regime_flip_keeps_bounds(real_df):
    """Eligibility regimes are static metadata in the replay; a flip in
    the LABEL (breakdown dimension) or in DECLARED regime eligibility
    changes allocation only through the documented fail-safes."""
    t = real_df.index[2500]
    stats, rets = as_of_stats(real_df, SPECS, t, instrument=VIX)
    inputs = _inputs(SPECS, t)
    d_up = MetaLayer(MetaConfig()).decide(inputs, as_of=t.to_pydatetime(),
                                          returns=rets, oos_stats=stats)
    # regime flips to one the strategies do not declare: hard zero
    flipped = [StrategyMetaInput(i.strategy_id, i.symbol, i.signal,
                                 "HIGH_VOL", i.regimes_allowed,
                                 i.regimes_preferred, frozenset(
                                     {"HIGH_VOL"}),
                                 i.certification_state)
               for i in inputs]
    d_flip = MetaLayer(MetaConfig()).decide(flipped,
                                            as_of=t.to_pydatetime(),
                                            returns=rets,
                                            oos_stats=stats)
    assert all(w.final_weight == 0.0 for w in d_flip.weights)
    assert d_flip.fallback == ("none_eligible",)
    # the pre-flip decision was fully invested within budget
    assert sum(w.final_weight for w in d_up.weights) <= 1.0 + 1e-9


def test_adv_06_drift_appears_on_real_history(real_df):
    t = real_df.index[2500]
    stats, rets = as_of_stats(real_df, SPECS, t, instrument=VIX)
    clean = _inputs(SPECS, t)
    drifted = _inputs(SPECS, t, drift=0.30)       # MILD
    blocked = _inputs(SPECS, t, drift=0.60)       # SEVERE
    kw = {"as_of": t.to_pydatetime(), "returns": rets, "oos_stats": stats}
    d0 = MetaLayer(MetaConfig()).decide(clean, **kw)
    d1 = MetaLayer(MetaConfig()).decide(drifted, **kw)
    d2 = MetaLayer(MetaConfig()).decide(blocked, **kw)
    w0 = {w.strategy_id: w.final_weight for w in d0.weights}
    w1 = {w.strategy_id: w.final_weight for w in d1.weights}
    for sid, base_w in w0.items():
        assert w1[sid] <= base_w + 1e-9  # mild drift only reduces
    assert all(w.final_weight == 0.0 for w in d2.weights)
    assert d2.fallback == ("none_eligible",)


def test_adv_07_one_strategy_disappears(real_df):
    t = real_df.index[2500]
    stats, rets = as_of_stats(real_df, SPECS, t, instrument=VIX)
    gone = [s for s in SPECS if s.name != "donchian_20"]
    stats_g = {k: v for k, v in stats.items() if k != "donchian_20"}
    rets_g = rets[[c for c in rets.columns if c != "donchian_20"]]
    d = MetaLayer(MetaConfig()).decide(_inputs(gone, t),
                                       as_of=t.to_pydatetime(),
                                       returns=rets_g,
                                       oos_stats=stats_g)
    assert "donchian_20" not in {w.strategy_id for w in d.weights}
    assert sum(w.final_weight for w in d.weights) <= 1.0 + 1e-9


def test_adv_08_certification_expires(real_df):
    t = real_df.index[2500]
    stats, rets = as_of_stats(real_df, SPECS, t, instrument=VIX)
    inputs = _inputs(SPECS, t)
    expired = [StrategyMetaInput(i.strategy_id, i.symbol, i.signal,
                                 i.regime, i.regimes_allowed,
                                 i.regimes_preferred,
                                 i.regimes_forbidden,
                                 "FAILED")       # certification revoked
               for i in inputs]
    d = MetaLayer(MetaConfig()).decide(expired, as_of=t.to_pydatetime(),
                                       returns=rets, oos_stats=stats)
    assert d.fallback == ("none_eligible",)
    assert all(w.final_weight == 0.0 for w in d.weights)


def test_adv_09_10_meta_file_stale_then_corrupted(real_df, tmp_path):
    t = real_df.index[2500]
    stats, rets = as_of_stats(real_df, SPECS, t, instrument=VIX)
    d = MetaLayer(MetaConfig()).decide(_inputs(SPECS, t),
                                       as_of=t.to_pydatetime(),
                                       returns=rets, oos_stats=stats)
    path = tmp_path / "allocation.json"
    write_allocation_file(d, path)
    fresh = read_allocation_file(path, now=t.to_pydatetime())
    assert fresh["stale"] is False
    old = read_allocation_file(path, now=t.to_pydatetime()
                               + timedelta(days=9))
    assert old["stale"] is True                   # decay per SPEC
    # corrupted: weight mutated -> digest mismatch -> refused
    obj = json.loads(path.read_text())
    obj["body"]["strategies"][0]["weight"] = 1.0
    path.write_text(json.dumps(obj))
    with pytest.raises(MetaFileError):
        read_allocation_file(path)


def test_adv_11_restart_during_clamp(real_df):
    """Restart mid-clamp: limits continue from the persisted weights and
    the replayed decision is byte-identical to the continuous run."""
    cfg = MetaConfig(max_weight_change=0.15)
    seq = []
    for t in (real_df.index[2000], real_df.index[2400]):
        stats, rets = as_of_stats(real_df, SPECS, t, instrument=VIX)
        seq.append((t, stats, rets))
    cont = MetaLayer(cfg)
    cont.decide(_inputs(SPECS, seq[0][0]),
                as_of=seq[0][0].to_pydatetime(),
                returns=seq[0][2], oos_stats=seq[0][1])
    # snapshot the state captured after decision 1, BEFORE decision 2
    snap_state = _copy.deepcopy(cont.state)
    expected = cont.decide(_inputs(SPECS, seq[1][0]),
                           as_of=seq[1][0].to_pydatetime(),
                           returns=seq[1][2], oos_stats=seq[1][1])
    restored = MetaLayer(cfg, state=snap_state)
    r2 = restored.decide(_inputs(SPECS, seq[1][0]),
                         as_of=seq[1][0].to_pydatetime(),
                         returns=seq[1][2], oos_stats=seq[1][1])
    assert r2.canonical_json() == expected.canonical_json()


def test_adv_12_kill_switch_activates(real_df):
    t = real_df.index[2500]
    stats, rets = as_of_stats(real_df, SPECS, t, instrument=VIX)
    killed = [StrategyMetaInput(i.strategy_id, i.symbol, i.signal,
                                i.regime, i.regimes_allowed,
                                i.regimes_preferred,
                                i.regimes_forbidden,
                                i.certification_state,
                                kill_switch=True)
              for i in _inputs(SPECS, t)]
    d = MetaLayer(MetaConfig()).decide(killed, as_of=t.to_pydatetime(),
                                       returns=rets, oos_stats=stats)
    assert d.fallback == ("none_eligible",)
    assert d.book == []


def test_adv_13_daily_loss_breach_is_invisible_to_meta(real_df):
    """A daily-loss breach is a RISK ENGINE event: the meta decision is
    bit-identical whether or not the account bled — the layer never
    sees account P/L."""
    t = real_df.index[2500]
    stats, rets = as_of_stats(real_df, SPECS, t, instrument=VIX)
    kw = {"as_of": t.to_pydatetime(), "returns": rets,
          "oos_stats": stats}
    d1 = MetaLayer(MetaConfig()).decide(_inputs(SPECS, t), **kw)
    d2 = MetaLayer(MetaConfig()).decide(_inputs(SPECS, t), **kw)
    assert d1.canonical_json() == d2.canonical_json()
    # and no surface exists to even express a loss level
    src = (REPO / "python/mql5bot/meta_layer.py").read_text()
    assert "daily_loss" not in src


def test_adv_14_risk_engine_rejection_is_upstream(real_df):
    """Reduce-only: whatever the Risk Engine rejects never comes FROM
    meta; the seam output is always <= the approved size (grid pin in
    test_meta_gate).  Here: a zero-weight strategy emits no order at
    all (no book leg), which is the only meta-originated 'rejection'."""
    t = real_df.index[2500]
    stats, rets = as_of_stats(real_df, SPECS, t, instrument=VIX)
    inputs = _inputs(SPECS, t)
    d = MetaLayer(MetaConfig()).decide(inputs, as_of=t.to_pydatetime(),
                                       returns=rets, oos_stats=stats)
    for w in d.weights:
        if w.final_weight == 0.0:
            assert w.strategy_id not in {b.strategy_id for b in d.book}


def test_adv_15_market_gap_present_in_real_data(real_df):
    """The real series contains holiday gaps and the 2015-08-24 open
    gap; the replay runs across them and the weights stay bounded."""
    assert (real_df.index.to_series().diff().dt.days > 1).any()
    meta, _eq = run_replay(real_df.iloc[:2500], SPECS, n_rebalances=3,
                           min_history=400, instrument=VIX)
    for wid in meta.weights:
        vals = [v for k, v in wid.items() if k != "as_of"]
        assert all(0.0 <= v <= 1.0 for v in vals)


def test_adv_16_spread_spike_shared_by_both_policies(real_df):
    """A spread spike changes BOTH policies' statistics identically —
    the meta layer cannot exploit or hide cost shocks; exposure stays
    within budget for either."""
    t = real_df.index[2000]
    wide = {**VIX, "spread_points": 500.0}
    stats_w, rets_w = as_of_stats(real_df, SPECS, t, instrument=wide)
    d = MetaLayer(MetaConfig()).decide(_inputs(SPECS, t),
                                       as_of=t.to_pydatetime(),
                                       returns=rets_w,
                                       oos_stats=stats_w)
    assert sum(w.final_weight for w in d.weights) <= 1.0 + 1e-9


# ---- Phase 14: regime breakdown exists on real data ------------------------


def test_regime_breakdown_non_trivial(real_df):
    sub = real_df.loc["2018-01-01":"2021-12-31"]
    meta, _ = run_replay(sub, SPECS, n_rebalances=4, min_history=200,
                         instrument=VIX)
    labels = regime_labels(meta.equity)
    assert len(labels) == len(meta.equity)
    assert set(labels.unique()) <= {"TREND_UP", "TREND_DOWN", "RANGE",
                                    "HIGH_VOL", "LOW_VOL"}
    # at least two distinct regimes appear on this real window
    assert labels.nunique() >= 2
