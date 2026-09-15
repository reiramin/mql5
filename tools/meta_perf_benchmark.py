"""Meta portfolio performance benchmark (Phase 27).

Scales required by the production gate: 1 symbol x 3 books, 3 x 5,
6 x 10 (books = (symbol, strategy) lines; the strategy registry is
fixed — books vary params, no new strategies).

Measures: decision latency (snapshot + decide, the O(books x bars)
as-of statistics), execution wall time, and total run time.  Writes
JSON results for the exit-gate report.  Correctness first: this tool
deliberately does NOT optimize anything — it profiles the canonical
path as-is.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from mql5bot.data import generate_ohlc
from mql5bot.meta_layer import MetaLayer, MetaPolicy
from mql5bot.meta_portfolio import MetaPortfolioEngine
from mql5bot.symbolspec import SymbolSpec

STRATEGIES = ("bollinger_reversal", "ema_crossover", "macd_momentum")
PARAM_VARIANTS = [
    {}, {"fast": 8}, {"fast": 12}, {"slow": 40}, {"tp_atr": 3.0},
    {"sl_atr": 3.0}, {"fast": 15}, {"slow": 20}, {"tp_atr": 5.0},
    {"sl_atr": 2.0},
]

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US500", "BTCUSD"]


def make_spec(symbol: str) -> SymbolSpec:
    fx = symbol not in ("XAUUSD", "US500", "BTCUSD")
    point = 1e-5 if fx else 0.01
    contract = 100_000.0 if fx else 10_000.0
    return SymbolSpec(name=symbol, point=point, tick_size=point,
                      tick_value_loss=point * contract,
                      contract_size=contract, volume_step=0.01,
                      volume_min=0.01)


def build_contexts(n_symbols: int, n_books: int, days: int):
    from mql5bot.costs import CostConfig
    from mql5bot.meta_portfolio import InstrumentContext
    frames = {s: generate_ohlc(symbol=s, days=days, seed=100 + i)
              for i, s in enumerate(SYMBOLS[:n_symbols])}
    # Book i -> symbol i % n_symbols, strategy (i // n_symbols) % 3:
    # the execution seam's line identity is (symbol, engine_strategy),
    # so a symbol hosts at most one book per registry strategy.
    contexts = []
    for i in range(n_books):
        sym = SYMBOLS[i % n_symbols]
        strat = STRATEGIES[(i // n_symbols) % 3]
        contexts.append(InstrumentContext(
            symbol=sym, strategy_id=f"{strat}#{i}@{sym}",
            engine_strategy=strat, df=frames[sym], spec=make_spec(sym),
            costs=CostConfig(symbol=sym, spread_points=2.0),
            params=dict(PARAM_VARIANTS[i % len(PARAM_VARIANTS)])))
    return contexts


def benchmark(n_symbols: int, n_books: int, days: int, every_days: int,
              decisions: int) -> dict:
    contexts = build_contexts(n_symbols, n_books, days)
    t0 = time.perf_counter()
    eng = MetaPortfolioEngine(contexts=contexts,
                              min_history_bars=480,
                              every_days=every_days)
    build_s = time.perf_counter() - t0
    layer = MetaLayer(eng.config)
    rebalances = eng.rebalances[:decisions]
    latencies = []
    for t in rebalances:
        t0 = time.perf_counter()
        eng.decide_weights(t, MetaPolicy.META, layer)
        latencies.append((time.perf_counter() - t0) * 1000.0)
    t0 = time.perf_counter()
    eng.run_policy(MetaPolicy.EQUAL_WEIGHT, MetaLayer(eng.config))
    exec_s = time.perf_counter() - t0
    return {
        "scale": f"{n_symbols}sym x {n_books}books",
        "n_books": n_books,
        "bars_per_symbol": len(contexts[0].df),
        "decisions_timed": len(latencies),
        "decision_ms_mean": round(sum(latencies) / len(latencies), 1),
        "decision_ms_max": round(max(latencies), 1),
        "decision_ms_per_book": round(
            sum(latencies) / len(latencies) / n_books, 1),
        "execution_wall_s": round(exec_s, 1),
        "engine_build_s": round(build_s, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--every-days", type=int, default=12)
    ap.add_argument("--decisions", type=int, default=3)
    ap.add_argument("--out", default="docs/META_PERF_BENCHMARK.json")
    args = ap.parse_args()

    results = [
        benchmark(1, 3, args.days, args.every_days, args.decisions),
        benchmark(3, 5, args.days, args.every_days, args.decisions),
        benchmark(6, 10, args.days, args.every_days, args.decisions),
    ]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "synthetic frames; decision latency is dominated by "
                "per-book as-of statistics backtests (canonical path, "
                "unoptimized by gate rule)",
        "results": results,
    }
    with open(args.out, "w") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    for r in results:
        print(f"{r['scale']:>14}: decision {r['decision_ms_mean']:>7} ms "
              f"mean / {r['decision_ms_max']:>7} ms max "
              f"({r['decision_ms_per_book']} ms/book), "
              f"exec {r['execution_wall_s']} s")
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
