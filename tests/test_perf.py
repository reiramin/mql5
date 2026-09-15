"""Tests for the research-benchmark instrumentation (mql5bot.perf, plan Phase 10)."""

import pytest
from mql5bot.data import generate_ohlc
from mql5bot.optimizer import grid_search
from mql5bot.perf import ema_grid_axes, grid_metrics, grid_signature, single_run_metrics


@pytest.fixture(scope="module")
def df():
    return generate_ohlc(days=25, seed=7)


def test_ema_grid_axes_factor_exact_and_valid():
    for n in (100, 1000, 10_000):
        fast, slow = ema_grid_axes(n)
        assert len(fast) * len(slow) == n
        assert max(fast) < min(slow)  # every combination is a valid pair
    fast, slow = ema_grid_axes(6)
    assert len(fast) * len(slow) == 6
    with pytest.raises(ValueError):
        ema_grid_axes(0)


def test_single_run_metrics_shape_and_throughput(df):
    m = single_run_metrics(df, n_repeats=2)
    assert m["bars"] == len(df)
    assert m["seconds"] > 0.0
    assert m["bars_per_sec"] > 100.0
    assert m["peak_memory_mb"] >= 0.0
    assert m["trades_total"] >= 0
    with pytest.raises(ValueError):
        single_run_metrics(df, n_repeats=0)


def test_grid_metrics_exact_set_count_and_best_report(df):
    m = grid_metrics(df, 16, n_jobs=1)
    assert m["param_sets"] == 16
    assert m["seconds"] > 0.0 and m["runs_per_sec"] > 0.0
    assert {"fast", "slow"} <= set(m["best_params"])
    assert len(m["signature"]) == 5


def test_parallel_grid_matches_sequential_exactly(df):
    """The plan-10 contract: parallel evaluation reproduces the sequential
    ordering and values exactly (deterministic backtests, independent
    workers)."""
    fast, slow = ema_grid_axes(16)
    kw = {"metric": "sharpe", "risk_percent": 0.5}
    seq = grid_search(df, "ema_crossover", {"fast": fast, "slow": slow},
                      n_jobs=1, **kw)
    par = grid_search(df, "ema_crossover", {"fast": fast, "slow": slow},
                      n_jobs=2, **kw)
    assert grid_signature(seq) == grid_signature(par)
    assert [r.result.metrics.get("sharpe") for r in seq] == \
        [r.result.metrics.get("sharpe") for r in par]
