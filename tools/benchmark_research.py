"""tools/benchmark_research.py — measured research-engine benchmarks (plan Phase 18).

Deterministic throughput ladder for the fast research engine (plan Phase
10): single-run cost, then grid-search at 100 / 1,000 / 10,000 parameter
sets, each at ``n_jobs = 1`` (baseline) and ``n_jobs = cores`` (parallel),
with peak traced memory and a numerical-equivalence check between the two
execution modes.  Everything runs on one synthetic frame built with a
fixed seed; outputs are printed and optionally written as JSON.

Usage::

    python tools/benchmark_research.py [--days 20] [--sets 100 1000 10000]
                                       [--n-jobs auto] [--json PATH]

Run from the repository root (module import path ``python/`` must be on
``PYTHONPATH`` or the package installed editable).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from mql5bot.data import generate_ohlc
from mql5bot.perf import grid_metrics, single_run_metrics


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=20,
                    help="synthetic hourly bars (default 20 = 480 bars)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sets", type=int, nargs="+", default=[100, 1000, 10_000])
    ap.add_argument("--n-jobs", default="auto",
                    help="parallel workers (default: cpu count)")
    ap.add_argument("--json", default=None, help="write the report to a JSON file")
    args = ap.parse_args(argv)

    if args.n_jobs == "auto":
        n_jobs = max(1, os.cpu_count() or 1)
    else:
        n_jobs = max(1, int(args.n_jobs))

    report: dict = {
        "host": {"cpu_count": os.cpu_count(), "n_jobs": n_jobs},
        "frame": {"days": args.days, "seed": args.seed},
        "single_run": None,
        "grids": [],
    }

    # ---- data load ------------------------------------------------------
    t0 = time.perf_counter()
    df = generate_ohlc(days=args.days, seed=args.seed)
    load_s = time.perf_counter() - t0
    print(f"data load: {len(df)} bars in {load_s:.3f}s (synthetic, seed={args.seed})")
    report["data_load_seconds"] = round(load_s, 4)

    # ---- single run -----------------------------------------------------
    single = single_run_metrics(df, n_repeats=5)
    report["single_run"] = single
    print("\n-- single backtest (ema_crossover defaults) -------------------")
    print(f"  {single['seconds']:.3f}s per run | "
          f"{single['bars_per_sec']:,.0f} bars/s | "
          f"{single['trades_per_sec']:.1f} trades/s | "
          f"{single['trades_total']} trades/5 runs | "
          f"peak {single['peak_memory_mb']:.1f} MB")

    # ---- grid ladder ----------------------------------------------------
    print("\n-- grid search ladder (fast/slow EMA axes) --------------------")
    for n_sets in args.sets:
        row = {"param_sets": n_sets}
        seq = grid_metrics(df, n_sets, n_jobs=1)
        par = grid_metrics(df, n_sets, n_jobs=n_jobs)
        eq = seq["signature"] == par["signature"]
        speedup = seq["seconds"] / par["seconds"] if par["seconds"] > 0 else 0.0
        row.update({
            "sequential_seconds": seq["seconds"],
            "parallel_seconds": par["seconds"],
            "speedup": round(speedup, 2),
            "sequential_runs_per_sec": seq["runs_per_sec"],
            "parallel_runs_per_sec": par["runs_per_sec"],
            "peak_memory_mb": max(seq["peak_memory_mb"], par["peak_memory_mb"]),
            "equivalent": eq,
            "best_params": seq["best_params"],
            "best_sharpe": seq["best_sharpe"],
        })
        report["grids"].append(row)
        print(f"  {n_sets:>6,} sets | seq {seq['seconds']:7.2f}s | "
              f"par {par['seconds']:7.2f}s | speedup {speedup:4.2f}x | "
              f"par {par['runs_per_sec']:6.1f} runs/s | "
              f"peak {row['peak_memory_mb']:6.1f} MB | "
              f"equivalence {'PASS' if eq else 'FAIL'}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
        print(f"\nreport written to {args.json}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
    raise SystemExit(main())
