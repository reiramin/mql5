"""mql5bot.perf — measured research-throughput benchmarks (plan Phase 10).

Nothing here tunes weights, features or selection: it measures only.
Three deterministic instruments are provided:

* :func:`ema_grid_axes` — factorises a requested parameter-set count into a
  ``fast``/``slow`` EMA-crossover grid with exactly that many combinations
  (fast always below slow), so runtimes are comparable across sizes;
* :func:`single_run_metrics` — per-run wall time, bars/sec and trades/sec
  averaged over ``n_repeats`` (timing runs clean, without tracing);
* :func:`grid_metrics` — end-to-end ``grid_search`` time for ``n``
  parameter sets at a given ``n_jobs``, with the best run's signature.

Memory is reported as a parent-process retention estimate: one extra
*untimed* run under ``tracemalloc`` at a capped probe size, scaled linearly
to the requested set count (grid search retains every run result in the
parent, so retention scales with the result list; worker processes hold no
result lists).  Reported as an approximation.

``grid_signature`` extracts the top-N ``(params, sharpe)`` records of a
grid result so two execution modes can be compared for numerical
equivalence (the parallel path must reproduce the sequential ordering and
values exactly — pinned by unit tests and by the benchmark tool).
"""

from __future__ import annotations

import gc
import math
import time

DEFAULT_STRATEGY = "ema_crossover"
DEFAULT_METRIC = "sharpe"


def ema_grid_axes(n_param_sets: int, fast_start: int = 5,
                  slow_start: int | None = None) -> tuple[list[int], list[int]]:
    """Return ``(fast_values, slow_values)`` with product ``n_param_sets``.

    The axes are factored into the two closest divisors; slow values always
    start above the largest fast value so every combination is a valid
    EMA-crossover parameter pair.
    """
    if n_param_sets < 1:
        raise ValueError("n_param_sets must be >= 1")
    a = math.isqrt(n_param_sets)
    while a >= 1 and n_param_sets % a != 0:
        a -= 1
    b = n_param_sets // a
    if a > b:
        a, b = b, a
    fast = list(range(fast_start, fast_start + a))
    slow0 = fast_start + a + 10 if slow_start is None else slow_start
    slow = list(range(slow0, slow0 + b))
    return fast, slow


def grid_signature(runs, top: int = 5) -> list:
    """Deterministic top-N ``((params...), metric)`` signature of a grid run."""
    out = []
    for r in runs[:top]:
        out.append((tuple(sorted(r.params.items())),
                    r.result.metrics.get(DEFAULT_METRIC)))
    return out


def _retention_peak_mb(fn, n_probe: int, n_scale: int) -> float | None:
    """Peak parent-allocation bytes of one untimed ``fn`` run, scaled up."""
    import tracemalloc

    gc.collect()
    tracemalloc.start()
    fn()
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    if peak <= 0:
        return None
    return round(peak * (n_scale / n_probe) / 1e6, 3)


def single_run_metrics(df, strategy: str = DEFAULT_STRATEGY,
                       params: dict | None = None, *,
                       risk_percent: float = 0.5,
                       n_repeats: int = 3) -> dict:
    """Wall time and throughput of one backtest, averaged over repeats."""
    from .backtest import run_backtest

    if n_repeats < 1:
        raise ValueError("n_repeats must be >= 1")
    run_backtest(df, strategy, params, risk_percent=risk_percent)  # warm-up

    def timed() -> int:
        trades_total = 0
        t0 = time.perf_counter()
        for _ in range(n_repeats):
            res = run_backtest(df, strategy, params, risk_percent=risk_percent)
            trades_total += len(res.trades)
        return trades_total, time.perf_counter() - t0

    trades_total, dt = timed()
    n = len(df)
    mem = _retention_peak_mb(
        lambda: run_backtest(df, strategy, params, risk_percent=risk_percent),
        n_probe=1, n_scale=1)
    return {
        "bars": int(n),
        "repeats": int(n_repeats),
        "seconds": round(dt, 6),
        "seconds_per_run": round(dt / n_repeats, 6),
        "bars_per_sec": round(n * n_repeats / dt, 1),
        "trades_per_sec": round(trades_total / dt, 3),
        "trades_total": int(trades_total),
        "peak_memory_mb": mem,
    }


_MEM_PROBE_SETS = 300  # untimed tracemalloc probe size


def grid_metrics(df, n_param_sets: int, *, n_jobs: int = 1,
                 strategy: str = DEFAULT_STRATEGY,
                 risk_percent: float = 0.5) -> dict:
    """End-to-end grid-search timing for exactly ``n_param_sets`` runs."""
    from .optimizer import grid_search

    fast, slow = ema_grid_axes(n_param_sets)

    def run_grid() -> list:
        return grid_search(df, strategy, grid={"fast": fast, "slow": slow},
                           n_jobs=int(n_jobs), metric=DEFAULT_METRIC,
                           risk_percent=risk_percent)

    t0 = time.perf_counter()
    runs = run_grid()
    dt = time.perf_counter() - t0
    if len(runs) != n_param_sets:
        raise RuntimeError(
            f"grid returned {len(runs)} runs, expected {n_param_sets}")
    n_probe = min(_MEM_PROBE_SETS, n_param_sets)
    mem = _retention_peak_mb(
        lambda: grid_search(df, strategy,
                            grid={"fast": fast[:n_probe],
                                  "slow": slow[:1]},
                            n_jobs=1, metric=DEFAULT_METRIC,
                            risk_percent=risk_percent),
        n_probe=n_probe, n_scale=n_param_sets)
    best = runs[0]
    return {
        "param_sets": int(n_param_sets),
        "n_jobs": int(n_jobs),
        "seconds": round(dt, 6),
        "runs_per_sec": round(n_param_sets / dt, 3),
        "peak_memory_mb": mem,
        "best_params": dict(best.params),
        "best_sharpe": best.result.metrics.get(DEFAULT_METRIC),
        "signature": grid_signature(runs),
    }
