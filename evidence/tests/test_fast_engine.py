"""FAST screening engine (plan Phase C) — equivalence + contract tests.

FAST (``mql5bot.fast_engine``) must reproduce the canonical TRUTH path
(``mql5bot.backtest.run_backtest`` on the legacy wrapper contract and
``mql5bot.engine.PortfolioEngine`` for engine-style signal exits) EXACTLY
on its supported subset: identical trade rows, equity within float noise,
identical metrics.  Anything outside the subset must fail loudly
(``NotImplementedError``), and results are screening-only (never
"final"/certified) by design.
"""

import time

import numpy as np
import pandas as pd
import pytest
from mql5bot.backtest import run_backtest
from mql5bot.data import generate_ohlc
from mql5bot.engine import Instrument, PortfolioEngine, RunConfig
from mql5bot.fast_engine import run_fast
from mql5bot.strategies import default_params

_STRATEGIES = ["ema_crossover", "rsi_reversal", "donchian_breakout",
               "bollinger_reversal", "macd_momentum"]


def _random_params(name: str, rng: np.random.Generator) -> dict | None:
    """Draw one random-but-valid parameter set per strategy."""
    if name == "ema_crossover":
        return {"fast": int(rng.integers(5, 20)),
                "slow": int(rng.integers(25, 60))}
    if name == "macd_momentum":
        return {"fast": int(rng.integers(5, 20)),
                "slow": int(rng.integers(25, 60))}
    if name == "rsi_reversal":
        return {"period": int(rng.integers(8, 21))}
    if name == "donchian_breakout":
        return {"n": int(rng.integers(15, 40))}
    if name == "bollinger_reversal":
        return {"period": int(rng.integers(15, 40))}
    return None


@pytest.fixture(params=_STRATEGIES, ids=_STRATEGIES)
def fx_df(request):
    """Deterministic OHLC random walk labelled with the strategy name."""
    name = request.param
    rng = np.random.default_rng(sum(ord(ch) for ch in name))
    n = 700
    idx = pd.date_range("2021-06-01", periods=n, freq="h")
    px = 1.08 + np.cumsum(rng.normal(0, 0.0006, n))
    o = px * (1 + rng.normal(0, 2e-5, n))
    c = px * (1 + rng.normal(0, 2e-5, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 2e-5, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 2e-5, n)))
    return name, pd.DataFrame({"open": o, "high": h, "low": l, "close": c},
                              index=idx)


_LEGACY_KNOBS = [
    pytest.param({}, id="default"),
    pytest.param({"risk_percent": 0.5, "spread_points": 2.5,
                  "slippage_points": 1.0, "commission_per_lot": 3.5},
                 id="costs"),
    pytest.param({"max_bars": 25, "max_daily_loss_pct": 6.0,
                  "max_drawdown_pct": 20.0}, id="exits-halts"),
    pytest.param({"trail_atr": 2.0, "breakeven_atr": 1.0,
                  "breakeven_offset_points": 2.0}, id="trail-be"),
    pytest.param({"allow_short": False, "spread_points": 0.0,
                  "slippage_points": 0.0, "commission_per_lot": 0.0},
                 id="long-only-zero-cost"),
]


def _assert_equivalent(t_truth, f_fast) -> None:
    """Trade rows identical; equity/metrics within float accumulation noise."""
    assert t_truth.trades.equals(f_fast.trades)
    assert np.allclose(t_truth.equity.values, f_fast.equity.values,
                       atol=1e-8, rtol=0.0)
    for k in t_truth.metrics:
        a, b = t_truth.metrics[k], f_fast.metrics[k]
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            assert a == pytest.approx(b, rel=1e-9, abs=1e-9), k
        else:
            assert a == b, k


@pytest.mark.parametrize("knobs", _LEGACY_KNOBS)
def test_fast_equals_legacy_wrapper(fx_df, knobs):
    """FAST reproduces the canonical legacy wrapper on the screening subset."""
    name, df = fx_df
    rng = np.random.default_rng(len(df) * 31 + len(knobs))
    params = _random_params(name, rng)
    truth = run_backtest(df, name, params, **knobs)
    fast = run_fast(df, name, params, **knobs)
    _assert_equivalent(truth, fast)
    assert fast.config["engine"] == "fast"
    assert fast.config.keys() <= set(truth.config) | {"engine"}


@pytest.mark.parametrize("fraction", [0.3, 0.6])
def test_fast_equals_engine_with_signal_exits(fx_df, fraction):
    """Engine-style signal exits (allow_signal_exit=True) match the engine
    on the same explicit broker context (wrapper contract has no flips)."""
    name, df = fx_df
    params = _random_params(name, np.random.default_rng(99))
    point, contract = 1e-5, 100_000.0

    from mql5bot.costs import CostConfig
    from mql5bot.symbolspec import SymbolSpec

    spec = SymbolSpec(
        name="BACKTEST", digits=5, point=point, tick_size=point,
        tick_value_loss=point * contract, contract_size=contract,
        volume_min=0.01, volume_max=100.0, volume_step=0.01,
        volume_limit=0.0, stops_level_points=0.0,
        freeze_level_points=0.0, currency_profit="USD",
        currency_deposit="USD")
    # wrapper-identical broker costs (module defaults are zero-cost)
    costs = CostConfig(symbol="BACKTEST", spread_points=1.0,
                       slippage_points=0.0, commission_per_lot=7.0)
    merged = default_params(name)
    if params:
        merged.update(params)
    cfg = RunConfig(initial_capital=10_000.0, mode="netting",
                    allow_short=True, sizing_mode="risk_percent_equity",
                    risk_value=1.0, max_lots=100.0, partial_atr=1.5,
                    partial_fraction=fraction, allow_signal_exit=True)
    ins = Instrument(symbol="BACKTEST", strategy=name, df=df, costs=costs,
                     spec=spec, profit_to_deposit=1.0, params=merged)
    truth = PortfolioEngine(cfg).run([ins])
    fast = run_fast(df, name, params, partial_atr=1.5,
                    partial_fraction=fraction, allow_signal_exit=True)
    truth_cols = [c for c in fast.trades.columns if c in truth.trades]
    assert truth.trades[truth_cols].equals(
        fast.trades[truth_cols].reset_index(drop=True))
    assert np.allclose(truth.equity.values, fast.equity.values,
                       atol=1e-8, rtol=0.0)
    for k in truth.metrics:
        a, b = truth.metrics[k], fast.metrics[k]
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            assert a == pytest.approx(b, rel=1e-9, abs=1e-9), k


def test_fast_matches_backtest_result_schema():
    """Drop-in contract: same result type/columns; only config gains the
    ``engine: fast`` provenance marker."""
    df = generate_ohlc(days=60, seed=3)
    fast = run_fast(df, "ema_crossover", {"fast": 8, "slow": 24},
                    risk_percent=0.5)
    from mql5bot.backtest import BacktestResult

    assert isinstance(fast, BacktestResult)
    legacy = ["entry_time", "exit_time", "side", "entry_price", "exit_price",
              "lots", "bars_held", "pnl", "pnl_pct", "fees", "costs",
              "exit_reason"]
    assert list(fast.trades.columns) == legacy
    assert fast.config["engine"] == "fast"
    assert fast.metrics["end_equity"] > 0


def test_fast_scope_gates_are_loud():
    """Anything outside the FAST subset raises, never silently differs."""
    df = generate_ohlc(days=60, seed=3)
    with pytest.raises(NotImplementedError):
        run_fast(df, "ema_crossover", schedule=((100, {"fast": 5}),))
    with pytest.raises(ValueError):
        run_fast(df, "ema_crossover", partial_fraction=1.0)
    with pytest.raises(ValueError):
        run_fast(df, "ema_crossover", risk_percent=0.0)
    with pytest.raises(KeyError):
        run_fast(df, "no_such_strategy")
    with pytest.raises(NotImplementedError):
        run_fast(df, "ema_crossover", schedule=((5, None),))


def test_fast_deterministic_and_input_pure():
    df = generate_ohlc(days=90, seed=11)
    copy = df.copy(deep=True)
    a = run_fast(df, "donchian_breakout", {"n": 30})
    b = run_fast(df, "donchian_breakout", {"n": 30})
    assert a.trades.equals(b.trades)
    assert a.equity.equals(b.equity)
    pd.testing.assert_frame_equal(df, copy)
    assert len(a.equity) == len(df)
    # no-trade fixture stays flat at initial capital
    quiet = df.iloc[:200].copy()
    for col in ("open", "high", "low", "close"):
        quiet[col] = 1.10
    flat = run_fast(quiet, "ema_crossover", {"fast": 8, "slow": 24})
    assert flat.trades.empty
    assert np.allclose(flat.equity.values, flat.config["initial_capital"])


# --------------------------------------------------------------------------
# Performance & memory (measurement-only; Blocker 4)
# --------------------------------------------------------------------------


@pytest.mark.bench
def test_bench_fast_throughput_and_memory(fx_df):
    """Measurement-only: wall time, bars/sec, trades/sec and peak
    allocation of one FAST run.  Absolute numbers live in
    docs/BENCHMARK_FAST.md (measured, never asserted)."""
    import tracemalloc

    _, df = fx_df
    params = {"fast": 8, "slow": 30}
    run_fast(df, "ema_crossover", params)  # warm
    tracemalloc.start()
    t0 = time.perf_counter()
    res = run_fast(df, "ema_crossover", params)
    wall = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    bars_per_sec = len(df) / wall
    trades = int(res.metrics.get("trades", 0))
    print(f"\n[BENCH-FAST] bars={len(df)} wall={wall * 1000:.1f} ms | "
          f"{bars_per_sec:,.0f} bars/s | trades={trades} | "
          f"peak {peak / 1e6:.2f} MB")
    assert wall > 0.0 and bars_per_sec > 0.0
    assert tracemalloc.is_tracing() is False


@pytest.mark.parametrize("strategy", ["ema_crossover", "rsi_reversal",
                                      "donchian_breakout"])
def test_fast_warmup_equivalence_between_engines(fx_df, strategy):
    """run_fast(warmup_bars=...) mirrors run_backtest(warmup_bars=...):
    identical trades (equivalence on the fold-isolation primitive)."""
    _, df = fx_df
    w = 60
    fast = run_fast(df, strategy, None, warmup_bars=w)
    truth = run_backtest(df, strategy, None, warmup_bars=w)
    _assert_equivalent(truth, fast)
