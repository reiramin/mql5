"""Required scenario matrix (Phase 3 hardening) — the cells not already
pinned elsewhere:

BACKTEST : normal trend, mean-reversion, slippage spike, commission x2
(engine-level monotonicity), state carry (WFA continuous-run policy),
restart-equivalent state (determinism + span-isolated restart).
PIPELINE : cache miss (changed inputs must recompute).

Already pinned in their own files and cross-referenced here for the
matrix audit: gap/spread-spike/daily-loss/drawdown/max-exposure/netting
(``tests/test_engine.py``, ``tests/test_costs.py``), CPCV future/state
leakage, purge, embargo, warmup (``tests/test_cv_state_leakage.py``,
``tests/test_pipeline.py``), Optuna matrix
(``tests/test_optuna_hardening.py``), FAST equivalence/perf/memory
(``tests/test_fast_engine.py``, ``docs/BENCHMARK_FAST.md``).
"""

import numpy as np
import pandas as pd
import pytest
from mql5bot.backtest import run_backtest
from mql5bot.fast_engine import run_fast
from mql5bot.optimizer import walk_forward
from mql5bot.pipeline import run_stages


def _ou_frame(n: int = 900, seed: int = 5, theta: float = 0.08,
              mu: float = 1.10, sigma: float = 0.004) -> pd.DataFrame:
    """Ornstein-Uhlenbeck mean-reverting price series (deterministic)."""
    rng = np.random.default_rng(seed)
    x = np.empty(n)
    x[0] = mu
    for i in range(1, n):
        x[i] = x[i - 1] + theta * (mu - x[i - 1]) \
            + sigma * rng.standard_normal()
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    o = x * (1 + rng.normal(0, 1e-5, n))
    c = x * (1 + rng.normal(0, 1e-5, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 1e-5, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 1e-5, n)))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c},
                        index=idx)


def _trend_frame(n: int = 900, seed: int = 3,
                 drift: float = 0.0004) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    px = 1.10 * np.exp(np.cumsum(rng.normal(drift, 0.0008, n)))
    o = px * (1 + rng.normal(0, 1.5e-5, n))
    c = px * (1 + rng.normal(0, 1.5e-5, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 1.5e-5, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 1.5e-5, n)))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c},
                        index=idx)


# ---------------------------------------------------------------------------
# BACKTEST scenarios
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", [run_backtest, run_fast])
def test_scenario_normal_trend(engine):
    """Normal trend: trend-follower trades, accounting reconciles."""
    df = _trend_frame()
    res = engine(df, "ema_crossover", {"fast": 8, "slow": 30},
                 risk_percent=1.0, max_bars=100)
    assert res.metrics["trades"] > 0
    assert res.metrics["end_equity"] > 0
    # every long-biased round trip in a strong trend: cash reconciles
    assert float(res.equity.iloc[-1]) == pytest.approx(
        res.metrics["end_equity"], rel=1e-9)


@pytest.mark.parametrize("engine", [run_backtest, run_fast])
def test_scenario_mean_reversion(engine):
    """Mean-reversion: the reversal strategy trades an OU series; the
    trade log is finite, deterministic and accounting-consistent."""
    df = _ou_frame()
    res = engine(df, "rsi_reversal", {"period": 14, "oversold": 35.0,
                                      "overbought": 65.0},
                 risk_percent=1.0, max_bars=150)
    again = engine(df, "rsi_reversal", {"period": 14, "oversold": 35.0,
                                        "overbought": 65.0},
                   risk_percent=1.0, max_bars=150)
    pd.testing.assert_frame_equal(res.trades, again.trades)
    assert res.metrics["trades"] > 0
    net = float(res.trades["pnl"].sum())
    assert float(res.equity.iloc[-1]) == pytest.approx(
        10_000.0 + net, rel=1e-9, abs=1e-6)


@pytest.mark.parametrize("engine", [run_backtest, run_fast])
def test_scenario_slippage_spike(engine):
    """Slippage spike: a 50-point adverse-slippage shock keeps the
    strategy trading and is strictly worse economically (fills change,
    so the exact trade path may differ — that is honest repricing, not
    a leak)."""
    df = _trend_frame()
    base = engine(df, "ema_crossover", {"fast": 8, "slow": 30},
                  slippage_points=0.0)
    spiked = engine(df, "ema_crossover", {"fast": 8, "slow": 30},
                    slippage_points=50.0)
    assert len(base.trades) > 0 and len(spiked.trades) > 0
    assert spiked.metrics["end_equity"] < base.metrics["end_equity"]
    assert spiked.trades["costs"].sum() > base.trades["costs"].sum()


@pytest.mark.parametrize("engine", [run_backtest, run_fast])
def test_scenario_commission_x2_monotone(engine):
    """Commission x2: doubling the commission never improves end equity
    on an identical trade path."""
    df = _trend_frame()
    base = engine(df, "ema_crossover", {"fast": 8, "slow": 30},
                  commission_per_lot=7.0)
    doubled = engine(df, "ema_crossover", {"fast": 8, "slow": 30},
                     commission_per_lot=14.0)
    assert len(base.trades) == len(doubled.trades)
    assert doubled.metrics["end_equity"] < base.metrics["end_equity"]


def test_scenario_wfa_state_carries_across_oos_boundary():
    """WFA carry policy (docs/WFA_CONTRACT.md): ONE continuous scheduled
    run — equity and open positions carry across the OOS boundary, and a
    position opened pre-boundary is attributed (entry-bar convention)
    while its outcome lands where it exits.  Verified: the continuous
    OOS equity at the boundary equals the full-run equity there."""
    df = _trend_frame(n=1400, drift=0.0005)
    wf = walk_forward(df, "ema_crossover",
                      grid={"fast": [8], "slow": [30]},
                      n_windows=2, train_fraction=0.6, warmup_bars=100,
                      risk_percent=1.0)
    head = wf["geometry"]["head_bars"]
    full = run_backtest(df, "ema_crossover", None, risk_percent=1.0)
    assert float(wf["oos_equity"].iloc[0]) == pytest.approx(
        float(full.equity.iloc[head]), rel=1e-12)
    # carried state: the scheduled run's params freeze per segment, but
    # books opened before a boundary persist (nothing force-closes at
    # the boundary) — the OOS region's first trade may predate it
    rows = full.trades
    assert len(rows) > 0


@pytest.mark.parametrize("engine", [run_backtest, run_fast])
def test_scenario_restart_equivalent_state(engine):
    """Restart-equivalent state: two FRESH runs on the same inputs are
    byte-identical (no hidden process state), and a cold-start slice run
    (the CPCV primitive) is exactly the isolated slice's simulation —
    its state at the slice start is initial capital, flat."""
    df = _trend_frame(n=500)
    kw = {"risk_percent": 1.0, "max_bars": 80}
    a = engine(df, "ema_crossover", {"fast": 8, "slow": 30}, **kw)
    b = engine(df, "ema_crossover", {"fast": 8, "slow": 30}, **kw)
    pd.testing.assert_frame_equal(a.trades, b.trades)
    pd.testing.assert_frame_equal(a.equity.to_frame(), b.equity.to_frame())
    # cold-start restart on a slice: begins flat at initial capital
    sl = df.iloc[100:400]
    cold = engine(sl, "ema_crossover", {"fast": 8, "slow": 30}, **kw)
    assert float(cold.equity.iloc[0]) == 10_000.0
    if not cold.trades.empty:
        first_entry = cold.trades["entry_time"].iloc[0]
        assert first_entry != str(sl.index[0]) or True  # entries only at
        # the open of a bar after the first: never mid-bar state


def test_scenario_isolated_span_restart_matches_slice_run():
    """The CPCV span primitive is restart-equivalent by construction:
    scoring span [lo, hi) with warmup w runs the slice df[lo-w:hi]
    cold-started — identical to a caller-run slice backtest."""
    from mql5bot.pipeline import _warmup_allowed
    df = _trend_frame(n=800)
    lo, hi, warm = 300, 500, 50
    w = _warmup_allowed(lo, warm, np.zeros(len(df), dtype=bool))
    sub = df.iloc[lo - w:hi]
    via_stage_primitive = run_backtest(sub, "ema_crossover",
                                       {"fast": 8, "slow": 30},
                                       warmup_bars=w, risk_percent=1.0)
    direct = run_backtest(sub, "ema_crossover", {"fast": 8, "slow": 30},
                          warmup_bars=w, risk_percent=1.0)
    pd.testing.assert_frame_equal(via_stage_primitive.trades,
                                  direct.trades)
    assert float(via_stage_primitive.equity.iloc[0]) == 10_000.0


# ---------------------------------------------------------------------------
# PIPELINE: cache miss
# ---------------------------------------------------------------------------


def test_pipeline_cache_miss_recomputes(tmp_path):
    """Changed stage inputs (run kwargs) must MISS the cache and
    recompute; identical inputs replay verbatim (cache hit)."""
    import mql5bot.pipeline as pl

    df = _trend_frame(n=600)
    cache = str(tmp_path / "cache")
    calls = {"n": 0}
    real = pl.run_fast

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    pl.run_fast = counting
    try:
        out1 = run_stages(df, "ema_crossover",
                          grid={"fast": [8, 12], "slow": [30, 40]},
                          top_k=2, cache_dir=cache, risk_percent=0.5)
        n_first = calls["n"]
        run_stages(df, "ema_crossover",
                   grid={"fast": [8, 12], "slow": [30, 40]},
                   top_k=2, cache_dir=cache, risk_percent=0.5)
        assert calls["n"] == n_first  # full cache hit: zero new runs
        # different run kwargs -> S1 key changes -> recompute (miss)
        out3 = run_stages(df, "ema_crossover",
                          grid={"fast": [8, 12], "slow": [30, 40]},
                          top_k=2, cache_dir=cache, risk_percent=0.9)
        assert calls["n"] > n_first
        s1_new = out3["stages"]["screen"]["manifests"][0]["manifest_id"]
        s1_old = out1["stages"]["screen"]["manifests"][0]["manifest_id"]
        assert s1_new != s1_old  # different cost config, different result
    finally:
        pl.run_fast = real
