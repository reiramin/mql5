"""tools/meta_validation.py — Meta Layer vs Equal-Weight comparison +
performance profile (mandate Phases 27-29).

Runs the frozen deterministic comparison on SYNTHETIC data and prints
a markdown report (regime/symbol/strategy/time breakdowns where the
research stack actually has the data — missing dimensions are stated,
never faked).  Nothing here is an optimization: it is measurement.

Usage:
    PYTHONPATH=python python tools/meta_validation.py
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import numpy as np
import pandas as pd
from mql5bot.data import generate_ohlc
from mql5bot.meta_layer import MetaConfig, MetaLayer, StrategyMetaInput
from mql5bot.meta_oos import (
    StrategySpec,
    run_meta_oos,
)

SPECS = [
    StrategySpec("ema_fast", {"fast": 8, "slow": 30}, "ema_crossover"),
    StrategySpec("ema_slow", {"fast": 12, "slow": 40}, "ema_crossover"),
    StrategySpec("donchian_20", {"lookback": 20}, "donchian_breakout"),
    StrategySpec("donchian_55", {"lookback": 55}, "donchian_breakout"),
]


def main() -> int:
    dev = generate_ohlc(days=150, seed=8)
    oos = generate_ohlc(days=45, seed=12, start="2025-01-01")

    # ---- frozen comparison (no registry look consumed: synthetic demo) --
    t0 = time.perf_counter()
    out = run_meta_oos(dev, oos, SPECS, MetaConfig(), registry=None,
                       n_folds=3)
    frozen_s = time.perf_counter() - t0

    print("# META LAYER VALIDATION — measured output\n")
    print(f"(frozen comparison wall time: {frozen_s:.1f}s)\n")

    # ---- Phase 27: portfolio table ---------------------------------------
    print("## OOS portfolio metrics (45-day OOS window, 4 strategies)\n")
    print("| metric | META | EQUAL_WEIGHT |")
    print("|---|---:|---:|")
    keys = ["cagr", "sharpe", "sortino", "calmar", "max_dd", "recovery",
            "cvar_5", "expectancy_per_bar", "turnover", "gross_exposure",
            "concentration_hhi", "n_trades"]
    for k in keys:
        m = out["oos"]["meta"].get(k)
        e = out["oos"]["equal_weight"].get(k)
        print(f"| {k} | {m:.4f} | {e:.4f} |")

    # ---- time-period breakdown (folds) -----------------------------------
    print("\n## Time-period breakdown (development folds, train-side stats "
          "only)\n")
    print("| fold | test bars | meta sharpe | equal sharpe | meta max_dd |"
          " equal max_dd |")
    print("|---:|---:|---:|---:|---:|---:|")
    for row in out["folds"]:
        print(f"| {row['fold']} | {row['test_bars']} | "
              f"{row['meta']['sharpe']:.3f} | "
              f"{row['equal_weight']['sharpe']:.3f} | "
              f"{row['meta']['max_dd']:.3f} | "
              f"{row['equal_weight']['max_dd']:.3f} |")

    # ---- per-strategy OOS breakdown ---------------------------------------
    print("\n## Per-strategy OOS evidence (the factors see exactly this)\n")
    print("| strategy | OOS trades | expectancy/trade | OOS net |")
    print("|---|---:|---:|---:|")
    for name in sorted(out["per_strategy"]):
        ps = out["per_strategy"][name]
        print(f"| {name} | {ps['oos_trades']} | "
              f"{ps['oos_expectancy']:.5f} | {ps['oos_net']:.2f} |")

    print("\n## Weights (frozen from development-side statistics)\n")
    print("| strategy | META weight | EQUAL weight |")
    print("|---|---:|---:|")
    for sid in sorted(out["weights"]["meta"]):
        print(f"| {sid} | {out['weights']['meta'][sid]:.4f} | "
              f"{out['weights']['equal_weight'][sid]:.4f} |")

    # ---- unavailable dimensions (honest) ----------------------------------
    print("\n## Dimensions NOT measurable in this research stack\n")
    print("- **Regime breakdown**: the Python research stack has no regime")
    print("  classifier (regime metadata is static per strategy); a regime")
    print("  table would be fabricated.  Regime behavior is pinned by the")
    print("  regime matrix tests instead.")
    print("- **Symbol breakdown**: synthetic single-symbol data; the")
    print("  weighting math is symbol-agnostic (book groups by symbol).")
    print("- **Profit factor / expectancy at portfolio level**: portfolio")
    print("  trades do not exist under fixed weights; per-strategy OOS")
    print("  expectancy and trade counts are reported above.")

    # ---- Phase 29: profile --------------------------------------------------
    print("\n## Performance profile (10 strategies, 500-bar window, "
          "shared sandbox)\n")
    ids = [f"s{i:02d}" for i in range(10)]
    inputs = [StrategyMetaInput(i, "EURUSD", (1 if k % 2 == 0 else -1),
                                "TREND_UP", frozenset({"TREND_UP"}),
                                frozenset({"TREND_UP"}), frozenset(),
                                "VERIFIED", drift_available=True,
                                drift_score=0.0)
              for k, i in enumerate(ids)]
    idx = pd.date_range("2026-01-01", periods=500, freq="h")
    rng = np.random.default_rng(9)
    rets = pd.DataFrame({i: rng.normal(0, 1, 500) for i in ids},
                        index=idx)
    stats = {i: (0.01, 100) for i in ids}
    lay = MetaLayer(MetaConfig())
    lay.decide(inputs, as_of=datetime.now(timezone.utc), returns=rets,
               oos_stats=stats)

    def bench(fn, n=20):
        t = time.perf_counter()
        for _ in range(n):
            fn()
        return (time.perf_counter() - t) / n * 1000.0

    corr_ms = bench(lambda: MetaLayer.correlation_matrix(
        rets, ids, as_of=datetime.now(timezone.utc)))
    dec_ms = bench(lambda: lay.decide(inputs, as_of=datetime.now(
        timezone.utc), returns=rets, oos_stats=stats))
    decision = lay.decide(inputs, as_of=datetime.now(timezone.utc),
                          returns=rets, oos_stats=stats)
    json_ms = bench(lambda: decision.canonical_json())
    from mql5bot.meta_layer import MetaDecisionJournal
    journal = MetaDecisionJournal()
    journal.append(decision)
    save_ms = bench(lambda: journal.canonical_json())
    print("| step | ms (mean of 20) |")
    print("|---|---:|")
    print(f"| correlation matrix (10x10, 500 bars) | {corr_ms:.2f} |")
    print(f"| full decision | {dec_ms:.2f} |")
    print(f"| journal serialization | {json_ms:.2f} |")
    print(f"| journal canonical json | {save_ms:.2f} |")

    # ---- Phase 28: activation decision -----------------------------------
    better = (out["oos"]["meta"]["sharpe"] > out["oos"]["equal_weight"]
              ["sharpe"])
    print("\n## Activation decision input (SYNTHETIC data — not "
          "activation-grade)\n")
    print(f"- meta OOS sharpe > equal-weight OOS sharpe on this synthetic "
          f"run: {better}")
    print("- decision per the empirical gate: SYNTHETIC comparison CANNOT")
    print("  activate anything.  The Meta Layer ships DISABLED by default;")
    print("  the maximum honest state today is SHADOW_ONLY, pending real")
    print("  data validation, MT5 truth validation, shadow results and")
    print("  demo evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
