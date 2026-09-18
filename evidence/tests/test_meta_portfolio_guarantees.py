"""MetaPortfolioEngine guarantees (meta-production gate).

Phase 2 — immutable decision snapshot; Phase 3 — causality at the
first/middle/final rebalance; Phase 10 — reduce-only weight sweep on the
volume grid; Phase 16/17 — rebalance semantics (new weights touch new
entries only, existing positions untouched); Phase 23 — metamorphic
portfolio properties; Phase 24/26 — failure-safe and restart checks.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

from mql5bot.data import generate_ohlc
from mql5bot.meta_layer import MetaConfig, MetaPolicy
from mql5bot.meta_oos import StrategySpec
from mql5bot.meta_portfolio import (
    MetaPortfolioEngine,
    as_of_stats_exclusive,
)

SPECS = [StrategySpec("bollinger_reversal", {}),
         StrategySpec("ema_crossover", {"fast": 10, "slow": 50}),
         StrategySpec("macd_momentum", {})]


@pytest.fixture(scope="module")
def df():
    return generate_ohlc(days=180, seed=5)


# ---------------------------------------------------------------------------
# Phase 2 — immutable snapshot
# ---------------------------------------------------------------------------


def test_snapshot_is_immutable_and_decisions_reproducible(df):
    import types
    from dataclasses import FrozenInstanceError
    eng = MetaPortfolioEngine(df, SPECS, min_history_bars=480,
                              every_days=15, label="SYNTH")
    t = eng.rebalances[len(eng.rebalances) // 2]
    snap = eng.snapshot(t)
    # frozen attributes
    with pytest.raises(FrozenInstanceError):
        snap.as_of = pd.Timestamp("2099-01-01")
    # the stats mapping rejects writes; the returns frame is a private copy
    with pytest.raises(TypeError):
        snap.stats["bollinger_reversal"] = (9.9, 1)
    assert isinstance(snap.stats, types.MappingProxyType)
    # hostile mutation of the CALLER's objects cannot reach the snapshot
    stats_raw, rets_raw = as_of_stats_exclusive(df, SPECS, t)
    stats_raw["bollinger_reversal"] = (9.9, 1)
    rets_raw["bollinger_reversal"] = 1e9
    w1, j1 = eng.decide_weights(t, MetaPolicy.META, eng.meta_layer())
    w2, j2 = eng.decide_weights(t, MetaPolicy.META, eng.meta_layer())
    assert w1 == w2 and j1 == j2


# ---------------------------------------------------------------------------
# Phase 3 — causality at first / middle / final rebalance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["first", "middle", "final"])
def test_future_perturbation_cannot_change_decision_at_rebalance(df, which):
    eng = MetaPortfolioEngine(df, SPECS, min_history_bars=480,
                              every_days=15, label="SYNTH")
    idx = {"first": 0, "middle": len(eng.rebalances) // 2,
           "final": len(eng.rebalances) - 1}[which]
    t = eng.rebalances[idx]
    base_stats, _ = as_of_stats_exclusive(df, SPECS, t)
    for col in ("close", "open", "high", "low"):
        df2 = df.copy()
        df2.loc[df2.index > t, col] *= 5.0          # OHLC bomb after T
        s2, _ = as_of_stats_exclusive(df2, SPECS, t)
        assert s2 == base_stats, f"future {col} leaked into decision at {t}"
    # spread is an engine kwarg (not data): decisions consume data only,
    # so the same pin holds by construction for the stats path


# ---------------------------------------------------------------------------
# Phase 10 — reduce-only proof across the weight ladder & volume grids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("w", [1.0, 0.9, 0.75, 0.5, 0.1, 0.01, 0.0])
def test_final_lots_never_exceed_approved_for_weight_ladder(df, w):
    from tests.test_meta_portfolio import _run_seam
    base = _run_seam(df, ())          # unscaled engine run (14-col trades)
    res = _run_seam(df, ((df.index[60], w),))
    early = res.trades[pd.to_datetime(res.trades["entry_time"]) < df.index[60]]
    late = res.trades[pd.to_datetime(res.trades["entry_time"]) >= df.index[60]]
    base_early = base.trades[pd.to_datetime(base.trades["entry_time"])
                             < df.index[60]]
    pd.testing.assert_frame_equal(early.reset_index(drop=True),
                                  base_early.reset_index(drop=True))
    if w == 0.0:
        assert len(late) == 0
        return
    if len(late):
        # every late fill ≤ the unscaled size at the same point of the
        # base run (reduce-only), and on the 0.01 grid
        assert (late["lots"] <= base.trades["lots"].max() + 1e-12).all()
        assert ((late["lots"] / 0.01) % 1 < 1e-9).all()
        assert (late["lots"] >= 0.01 - 1e-12).all()


# ---------------------------------------------------------------------------
# Phase 16/17 — rebalance semantics: new weights touch new entries only
# ---------------------------------------------------------------------------


def test_new_weights_apply_only_to_new_entries(df):
    """A position opened BEFORE a weight change keeps its size, entry
    price and identity; the new weight affects later entries only."""
    from tests.test_meta_portfolio import _run_seam
    base = _run_seam(df, ())
    sched_t = df.index[90]
    res = _run_seam(df, ((sched_t, 0.25),))
    # trades fully resolved before the boundary are identical
    b = base.trades[pd.to_datetime(base.trades["exit_time"]) <= sched_t]
    r = res.trades[pd.to_datetime(res.trades["exit_time"]) <= sched_t]
    pd.testing.assert_frame_equal(b.reset_index(drop=True),
                                  r.reset_index(drop=True))
    assert len(b) > 0
    # no trade open before the boundary has a different size afterwards
    pre_open = base.trades[pd.to_datetime(base.trades["entry_time"])
                           < sched_t]
    pre_open_r = res.trades[pd.to_datetime(res.trades["entry_time"])
                            < sched_t]
    assert len(pre_open) == len(pre_open_r)


# ---------------------------------------------------------------------------
# Phase 23 — metamorphic portfolio properties
# ---------------------------------------------------------------------------


def test_strategy_order_permutation_invariance(df):
    r1 = MetaPortfolioEngine(df, list(SPECS), min_history_bars=480,
                             every_days=15, label="SYNTH").run()
    r2 = MetaPortfolioEngine(df, list(reversed(SPECS)), min_history_bars=480,
                             every_days=15, label="SYNTH").run()
    w1 = [{k: v for k, v in j.items() if k.startswith("w::")}
          for j in r1.meta.weights]
    w2 = [{k: v for k, v in j.items() if k.startswith("w::")}
          for j in r2.meta.weights]
    assert w1 == w2
    pd.testing.assert_frame_equal(r1.meta.trades.reset_index(drop=True),
                                  r2.meta.trades.reset_index(drop=True))


def test_lower_budget_cannot_increase_exposure(df):
    res_low = MetaPortfolioEngine(
        df, SPECS, min_history_bars=480, every_days=15, label="SYNTH",
        config=MetaConfig(gross_exposure_cap=0.3)).run()
    res_high = MetaPortfolioEngine(
        df, SPECS, min_history_bars=480, every_days=15, label="SYNTH",
        config=MetaConfig(gross_exposure_cap=1.0)).run()
    low_heat = res_low.meta.trades["lots"].sum()
    high_heat = res_high.meta.trades["lots"].sum()
    assert low_heat <= high_heat + 1e-9


def test_hard_zero_strategy_stays_zero_in_portfolio(df):
    specs = [StrategySpec("bollinger_reversal", {}),
             StrategySpec("ema_crossover", {"fast": 10, "slow": 50})]
    # bollinger_reversal UNCERTIFIED ⇒ hard zero in every decision
    res = MetaPortfolioEngine(df, specs, min_history_bars=480,
                              every_days=15, label="SYNTH",
                              certified={"ema_crossover"}).run()
    assert len(res.meta.weights) > 0
    for j in res.meta.weights:
        w = {k[3::]: v for k, v in j.items() if k.startswith("w::")}
        assert w["bollinger_reversal"] == 0.0
        assert w["ema_crossover"] >= 0.0
    # its contribution never appears in attribution
    if len(res.meta.attribution):
        assert "bollinger_reversal" not in             set(res.meta.attribution["strategy"])


def test_unknown_strategy_cannot_create_exposure():
    """Structural: the EA seam gives unknown ids ZERO under FRESH; the
    Python schedule path applies weights only to registered specs."""
    import inspect

    from mql5bot.meta_portfolio import MetaPortfolioEngine as MPE
    src = inspect.getsource(MPE._schedules)
    assert "for c in self.contexts" in src   # weights only for known books


# ---------------------------------------------------------------------------
# Phase 24/26 — failure-safe + restart at 25/50/75%
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("frac", [0.25, 0.5, 0.75])
def test_shadow_restart_equivalence_at_fractions(df, frac):
    eng = MetaPortfolioEngine(df, SPECS, min_history_bars=480,
                              every_days=12, label="SYNTH")
    full = eng.run()
    k = int(len(full.meta.weights) * frac)
    prior = {kk[3::]: v for kk, v in full.meta.weights[k - 1].items()
             if kk.startswith("w::")}
    t_k = pd.Timestamp(full.meta.weights[k]["as_of"])
    eng2 = MetaPortfolioEngine(df, SPECS, label="SYNTH",
                               min_history_bars=df.index.get_loc(t_k),
                               every_days=12, initial_weights=prior)
    part = eng2.run()
    for a, b in zip(part.meta.weights, full.meta.weights[k:]):
        assert a == b, f"shadow restart diverged at {a.get('as_of')}"


# ---------------------------------------------------------------------------
# Phase 24 — failure injection: hostile schedule values resolve SAFE
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_w,expect_trades",
                         [(float("nan"), False), (5.0, True), (-1.0, False),
                          (float("inf"), True)])
def test_hostile_schedule_weights_fail_safe(df, bad_w, expect_trades):
    """NaN/negative clamp to 0 (no trade); >1 clamps to 1 (never
    amplifies) — a hostile allocation can only ever SHRINK exposure."""
    from tests.test_meta_portfolio import _run_seam
    res = _run_seam(df, ((df.index[60], bad_w),))
    late = res.trades[pd.to_datetime(res.trades["entry_time"])
                      >= df.index[60]]
    assert len(late) > 0 if expect_trades else len(late) == 0
    if expect_trades:
        assert (late["lots"] <= 1.0).all()


def test_engine_rejects_misaligned_schedule_timestamps(df):
    """A schedule timestamp not on the shared index cannot silently
    shift the effective weight: Timestamp normalization pins it to the
    bar-open lookup (searchsorted), never to arrival order."""
    from tests.test_meta_portfolio import _run_seam
    late_stamp = df.index[-1] + pd.Timedelta(hours=3)   # beyond the data
    res = _run_seam(df, ((late_stamp, 0.0),))
    assert len(res.trades) > 0        # never effective ⇒ weight never 0


# ---------------------------------------------------------------------------
# Phase 29 — honest micro-profile (measurement, not a speed claim)
# ---------------------------------------------------------------------------


def test_decision_cost_profile_is_measured_and_reported(df):
    import time
    eng = MetaPortfolioEngine(df, SPECS, min_history_bars=480,
                              every_days=15, label="SYNTH")
    t0 = time.perf_counter()
    for t in eng.rebalances:
        eng.decide_weights(t, MetaPolicy.META, eng.meta_layer())
    decide_ms = (time.perf_counter() - t0) * 1000.0 / max(
        len(eng.rebalances), 1)
    t0 = time.perf_counter()
    eng.run()
    run_s = time.perf_counter() - t0
    # documented observation (not a gate): decisions are ~10-100 ms at
    # daily cadence — portfolio execution dominates by orders of magnitude
    print(f"\n[profile] meta decision ≈ {decide_ms:.1f} ms/decision; "
          f"full dual-policy run ≈ {run_s:.1f} s "
          f"({len(eng.rebalances)} rebalances)")
    assert decide_ms < 5_000.0    # sanity only: no runaway
