"""tools/meta_real_validation.py — REAL-data META vs EQUAL_WEIGHT
validation (empirical-gate mission, Phases 11-16).

Sandbox mode (no arguments): runs the committed REAL CBOE VIX daily
OHLC series across five documented periods + full history, with the
causal replay, the Phase-14 metric set, regime breakdowns, per-strategy
ledgers, block bootstrap and PSR.  FX/metal/crypto providers are
unreachable from the sandbox (egress allowlist) and are reported
UNAVAILABLE — never fabricated.

Owner mode (normal machine with market access):

    python tools/meta_real_validation.py \\
        --csv EURUSD=eurusd_daily.csv --csv GBPUSD=gbpusd_daily.csv ...

Each CSV needs columns date,open,high,low,close (any order, any case)
and a `--instrument SYMBOL=point,contract,spread,commission` spec per
symbol.  Every symbol runs the identical replay; results are reported
per symbol and never merged across instruments.

Usage (sandbox):
    PYTHONPATH=python python tools/meta_real_validation.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import pandas as pd
from mql5bot.backtest import run_backtest
from mql5bot.meta_oos import StrategySpec
from mql5bot.meta_replay import (
    block_bootstrap_sharpe_diff,
    probabilistic_sharpe,
    regime_breakdown,
    regime_labels,
    run_replay,
)

SPECS = [StrategySpec("ema_fast", {"fast": 8, "slow": 30},
                      "ema_crossover"),
         StrategySpec("ema_slow", {"fast": 12, "slow": 40},
                      "ema_crossover"),
         StrategySpec("donchian_20", {"lookback": 20},
                      "donchian_breakout")]

PERIODS = {
    "trending": ("2016-10-01", "2017-12-31"),
    "range": ("2004-01-01", "2006-12-31"),
    "high_volatility": ("2020-01-01", "2020-12-31"),
    "stress": ("2008-01-01", "2009-06-30"),
    "recent": ("2025-09-01", "2026-09-03"),
}
VIX_INSTRUMENT = {"point": 0.01, "contract_size": 1.0,
                  "spread_points": 10.0, "commission_per_lot": 0.0}


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df[["open", "high", "low", "close"]].astype(float).sort_index()


def per_strategy_ledgers(df: pd.DataFrame, specs, instrument) -> list[dict]:
    rows = []
    for spec in sorted(specs, key=lambda s: s.name):
        res = run_backtest(df, spec.engine_strategy, spec.params,
                           **instrument)
        m = res.metrics
        rows.append({"strategy": spec.name,
                     "trades": len(res.trades),
                     "pf": float(m.get("profit_factor", 0.0) or 0.0),
                     "net": float(m.get("net_profit", 0.0) or 0.0)})
    return rows


def run_symbol(name: str, df: pd.DataFrame, instrument: dict,
               rebalances: int = 10) -> dict:
    t0 = time.perf_counter()
    meta, eq = run_replay(df, SPECS, n_rebalances=rebalances,
                          min_history=min(400, len(df) // 6),
                          label=name, instrument=instrument)
    regs = regime_labels(meta.equity) if len(meta.equity) else \
        pd.Series(dtype=object)
    sig = block_bootstrap_sharpe_diff(meta.equity, eq.equity) \
        if len(meta.equity) > 100 else {"p_value": None}
    return {
        "symbol": name, "bars": len(df),
        "first": str(df.index[0].date()), "last": str(df.index[-1].date()),
        "meta": meta.metrics, "equal": eq.metrics,
        "meta_weights": meta.weights[-1] if meta.weights else {},
        "regimes": regime_breakdown(meta.equity, regs)
        if len(meta.equity) else {},
        "regime_counts": regs.value_counts().to_dict(),
        "bootstrap": sig,
        "psr": float(probabilistic_sharpe(meta.equity, eq.equity))
        if len(meta.equity) > 100 else float("nan"),
        "ledgers": per_strategy_ledgers(df, SPECS, instrument),
        "turnover": (meta.turnover["per_year"], eq.turnover["per_year"]),
        "wall_s": time.perf_counter() - t0,
    }


def report(rows: list[dict]) -> None:
    print("# REAL-DATA META vs EQUAL-WEIGHT VALIDATION\n")
    for r in rows:
        print(f"\n## {r['symbol']} — REAL data {r['first']}..{r['last']}"
              f" ({r['bars']:,} bars, replay {r['wall_s']:.1f}s)\n")
        keys = ["net_return", "cagr", "sharpe", "sortino", "calmar",
                "max_dd", "recovery", "expectancy", "pf", "cvar_5",
                "turnover", "exposure", "concentration_hhi",
                "worst_month", "worst_week", "longest_dd_days",
                "max_consec_losses", "n_trades"]
        print("| metric | META | EQUAL_WEIGHT |")
        print("|---|---:|---:|")
        for k in keys:
            m = r["meta"].get(k)
            e = r["equal"].get(k)
            print(f"| {k} | {m:.4f} | {e:.4f} |")
        print(f"\nFinal weights (META): "
              f"{ {k: round(v, 4) for k, v in sorted(r['meta_weights'].items()) if k != 'as_of'} }")
        print(f"turnover/yr meta vs equal: {r['turnover'][0]:.3f} vs "
              f"{r['turnover'][1]:.3f}")
        b = r["bootstrap"]
        if b.get("p_value") is not None:
            print(f"bootstrap Δsharpe: observed {b['observed_diff']:.4f}, "
                  f"95% CI [{b['ci_low']:.4f}, {b['ci_high']:.4f}], "
                  f"p={b['p_value']:.3f}, PSR={r['psr']:.3f}")
        print("\nPer-regime Sharpe (META):")
        for reg, v in sorted(r["regimes"].items()):
            sh = f"{v['sharpe']:.2f}" if v["sharpe"] is not None else "n/a"
            print(f"- {reg}: {sh} ({v['days']} days)")
        print("\nPer-strategy ledgers (identical inputs for both policies):")
        print("| strategy | trades | PF | net |")
        print("|---|---:|---:|---:|")
        for l in r["ledgers"]:
            print(f"| {l['strategy']} | {l['trades']} | {l['pf']:.3f} | "
                  f"{l['net']:.1f} |")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="append", default=[],
                    help="SYMBOL=path.csv (owner mode; repeatable)")
    ap.add_argument("--instrument", action="append", default=[],
                    help="SYMBOL=point,contract,spread,commission")
    ap.add_argument("--rebalances", type=int, default=10)
    args = ap.parse_args()

    rows = []
    if args.csv:
        spec_map = {kv.split("=", 1)[0]: kv.split("=", 1)[1]
                    for kv in args.instrument}
        for kv in args.csv:
            sym, path = kv.split("=", 1)
            point, contract, spread, comm = spec_map[sym].split(",")
            instrument = {"point": float(point),
                          "contract_size": float(contract),
                          "spread_points": float(spread),
                          "commission_per_lot": float(comm)}
            rows.append(run_symbol(sym, load_csv(path), instrument,
                                   args.rebalances))
    else:
        print("Sandbox mode: only the committed REAL VIX series is "
              "available (egress allowlist).  The suggested basket is "
              "reported UNAVAILABLE, not fabricated.\n")
        df = load_csv(str(Path(__file__).resolve().parents[1]
                          / "tests/data/real/vix_daily.csv"))
        rows.append(run_symbol("VIX", df, VIX_INSTRUMENT,
                               args.rebalances))
        print("\nUNAVAILABLE IN SANDBOX (no reliable data reachable):"
              " EURUSD, GBPUSD, USDJPY, XAUUSD, index CFD, crypto."
              "  Owner: re-run with --csv/--instrument per symbol.\n")
        # per-period breakdown on the real series
        print("\n## Per-period replay (same symbol, independent windows)"
              "\n")
        for pname, (lo, hi) in PERIODS.items():
            sub = df.loc[lo:hi]
            if len(sub) < 150:
                print(f"- {pname}: insufficient bars, skipped")
                continue
            r = run_symbol(f"VIX/{pname}", sub, VIX_INSTRUMENT,
                           min(args.rebalances, 4))
            print(f"- {pname} ({lo}..{hi}, {r['bars']} bars): "
                  f"sharpe meta {r['meta']['sharpe']:.3f} vs equal "
                  f"{r['equal']['sharpe']:.3f}; maxDD {r['meta']['max_dd']:.3f}"
                  f" vs {r['equal']['max_dd']:.3f}; p="
                  f"{(r['bootstrap'].get('p_value') or float('nan')):.3f}")
    report(rows)
    print("\nREADING: this comparison is measurement, not promotion "
          "evidence.  Meta activation requires the Phase 27 promotion "
          "rule (real data + MT5 truth + demo evidence).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
