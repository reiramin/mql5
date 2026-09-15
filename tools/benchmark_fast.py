"""FAST engine benchmark (Phase 3 hardening, Blocker 4).

Measures wall time, bars/sec, trades/sec, peak memory and CPU
utilisation of ``mql5bot.fast_engine.run_fast`` over the documented
dataset/run matrix:

    datasets : 3,000 / 30,000 / 300,000 bars (300k only if memory
               permits)
    runs     : 1 / 100 / 1,000 distinct parameter sets (larger runs are
               capped by a wall-clock budget; see REPORT_MATRIX)

Everything is measured, nothing asserted: the bench marker in pytest is
measurement-only.  Results are printed as a markdown table and written
as JSON to the output path for reproducible before/after comparisons.

Usage:
    python tools/benchmark_fast.py [--output results.json]
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
import tracemalloc
from pathlib import Path

import pandas as pd
from mql5bot.data import generate_ohlc
from mql5bot.fast_engine import run_fast
from mql5bot.strategies import default_params

# The full matrix; each cell lists the run counts executed for that
# dataset size.  A 1,000-parameter sweep on 300k bars is ~70 minutes
# single-core in pure Python — it is opt-in via --full, not silently
# skipped.
REPORT_MATRIX = {
    3_000: [1, 100, 1_000],
    30_000: [1, 100],
    300_000: [1],
}
FULL_MATRIX = {
    3_000: [1, 100, 1_000],
    30_000: [1, 100, 1_000],
    300_000: [1, 100, 1_000],
}


def _param_sets(count: int) -> list[dict]:
    """``count`` DISTINCT deterministic parameter sets (a screening
    sweep grid shape around the ema_crossover defaults)."""
    fasts = range(5, 16)
    slows = range(20, 130, 7)
    sl_atrs = (1.5, 2.0, 2.5, 3.0)
    tp_atrs = (3.0, 4.0, 5.0, 6.0)
    out = []
    for f, s, sla, tpa in itertools.product(fasts, slows, sl_atrs, tp_atrs):
        if s <= 2 * f:
            continue
        out.append({"fast": f, "slow": s, "sl_atr": sla, "tp_atr": tpa})
        if len(out) >= count:
            break
    if len(out) < count:
        raise ValueError(
            f"grid cannot produce {count} distinct parameter sets")
    return out


def _benchmark_cell(df: pd.DataFrame, n_sets: int) -> dict:
    params_list = [default_params("ema_crossover") | p
                   for p in _param_sets(n_sets)]
    # warm-up (imports, caches) — never measured
    run_fast(df, "ema_crossover", params_list[0])

    # ---- timing WITHOUT tracemalloc (tracing distorts the loop ~20x) ----
    t0 = time.perf_counter()
    cpu0 = time.process_time()
    trades = 0
    for params in params_list:
        res = run_fast(df, "ema_crossover", params)
        trades += int(res.metrics.get("trades", 0))
    wall = time.perf_counter() - t0
    cpu = time.process_time() - cpu0

    # ---- memory: separate single-run probe ------------------------------
    tracemalloc.start()
    run_fast(df, "ema_crossover", params_list[0])
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    n = len(df) * n_sets
    return {
        "bars": len(df),
        "n_param_sets": n_sets,
        "wall_s": round(wall, 4),
        "cpu_s": round(cpu, 4),
        "cpu_utilization": round(cpu / wall, 3) if wall > 0 else None,
        "bars_per_sec": round(n / wall, 1) if wall > 0 else None,
        "trades": trades,
        "trades_per_sec": round(trades / wall, 2) if wall > 0 else None,
        "peak_memory_mb": round(peak / 1e6, 2),
        "per_run_ms": round(wall / n_sets * 1000.0, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="benchmark_fast_results.json")
    ap.add_argument("--full", action="store_true",
                    help="run the 1,000-set sweeps on every dataset "
                         "(long: ~1.5h single-core)")
    args = ap.parse_args()
    matrix = FULL_MATRIX if args.full else REPORT_MATRIX

    rows = []
    for bars, run_counts in matrix.items():
        days = max(10, int(bars / 24) + 2)
        df = generate_ohlc(days=days, seed=3)
        df = df.iloc[:bars]
        for n_sets in run_counts:
            row = _benchmark_cell(df, n_sets)
            rows.append(row)
            print(f"| {bars:>8,} | {n_sets:>5,} | {row['wall_s']:>9.3f} | "
                  f"{row['bars_per_sec']:>12,.0f} | "
                  f"{row['trades_per_sec']:>10,.1f} | "
                  f"{row['peak_memory_mb']:>8.1f} | "
                  f"{row['cpu_utilization']:>6.2f} |")

    print("\n| bars | param sets | wall s | bars/s | trades/s | peak MB |"
          " cpu/wall |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in rows:
        print(f"| {row['bars']:,} | {row['n_param_sets']:,} | "
              f"{row['wall_s']:.3f} | {row['bars_per_sec']:,.0f} | "
              f"{row['trades_per_sec']:,.1f} | "
              f"{row['peak_memory_mb']:.1f} | "
              f"{row['cpu_utilization']:.2f} |")

    out = {
        "engine": "fast",
        "python": sys_version(),
        "matrix": rows,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                     time.gmtime()),
    }
    Path(args.output).write_text(json.dumps(out, indent=2),
                                 encoding="utf-8")
    print(f"\nwritten: {args.output}")
    return 0


def sys_version() -> str:
    import platform

    return (f"{platform.python_implementation()} "
            f"{platform.python_version()} {platform.platform()}")


if __name__ == "__main__":
    raise SystemExit(main())
