"""Execution stress scenarios (AEGIS Phase 10).

Runs the SAME strategy/params fixture across data-level execution stresses
and reports the OBSERVED degradation per scenario. Per the Mission-3 rules
"30–50% degradation" (or any other fixed number) is informative context,
NEVER a pass/fail gate — the gate is that every scenario runs the full
engine, preserves the accounting identity, is deterministic, and reports
its ACTUAL deltas.

Modelled (Python engine, data/cost level):
    spread widening, adverse slippage, commission, swap, price spikes
    (adverse intrabar wicks), opens gapping away from the prior close
    (gap-through stop fills at the open), gap-rejection thresholds,
    combined profiles.

NOT modelled in Python (execution-path behaviours, owner/demo evidence
via the MQL5 audit + RetryQueue/SlGuard pins): order latency, partial
fills, broker rejections. The report marks them explicitly instead of
inventing numbers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .backtest import run_backtest

STRATEGY = "bollinger_reversal"
PARAMS: dict = {}

BASE_COSTS = {"spread_points": 1.0, "slippage_points": 0.0,
              "commission_per_lot": 7.0}


# ---- data mutators (frame-level stresses) ----------------------------------


def spikes(df: pd.DataFrame, n: int = 40, seed: int = 9) -> pd.DataFrame:
    """Adverse intrabar wicks on n random bars (stop-hunt style): extend
    high/low far beyond the bar's range in a random direction."""
    rng = np.random.default_rng(seed)
    out = df.copy()
    idx = rng.choice(len(out), size=min(n, len(out)), replace=False)
    for i in idx:
        o, c = out.iloc[i]["open"], out.iloc[i]["close"]
        span = abs(c - o) + 1e-9
        adverse = rng.choice((-1.0, 1.0))
        wick = span * 40.0
        if adverse < 0:
            out.iloc[i, out.columns.get_loc("low")] = \
                min(out.iloc[i]["low"], min(o, c) - wick)
        else:
            out.iloc[i, out.columns.get_loc("high")] = \
                max(out.iloc[i]["high"], max(o, c) + wick)
    return out


def gaps(df: pd.DataFrame, n: int = 40, seed: int = 11) -> pd.DataFrame:
    """Open gapping away from the prior close on n random bars (weekend/
    news gaps): exercises gap-through stop fills at the open."""
    rng = np.random.default_rng(seed)
    out = df.copy()
    idx = rng.choice(np.arange(1, len(out)), size=min(n, len(out) - 1),
                     replace=False)
    for i in idx:
        prev_close = out.iloc[i - 1]["close"]
        rng_frac = rng.uniform(0.5, 2.0) * rng.choice((-1.0, 1.0))
        out.iloc[i, out.columns.get_loc("open")] = \
            prev_close * (1.0 + rng_frac * 0.01)
        # keep OHLC consistency: the bar must span its open
        lo = min(out.iloc[i]["low"], out.iloc[i]["open"])
        hi = max(out.iloc[i]["high"], out.iloc[i]["open"])
        out.iloc[i, out.columns.get_loc("low")] = lo
        out.iloc[i, out.columns.get_loc("high")] = hi
    return out


# ---- scenario registry ------------------------------------------------------


@dataclass
class Scenario:
    name: str
    dimension: str                      # spread|slippage|commission|swap|spikes|gaps|combined|gap_rejection
    description: str
    mutate: Callable[[pd.DataFrame], pd.DataFrame] = field(default=lambda d: d)
    costs: dict = field(default_factory=dict)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("BASE", "baseline", "fixture costs, untouched data",
             costs=dict(BASE_COSTS)),
    Scenario("SPREAD_X3", "spread", "spread 1→3 points",
             costs={**BASE_COSTS, "spread_points": 3.0}),
    Scenario("SPREAD_X10", "spread", "spread 1→10 points",
             costs={**BASE_COSTS, "spread_points": 10.0}),
    Scenario("SLIPPAGE_X3", "slippage", "adverse slippage 0→2 points/fill",
             costs={**BASE_COSTS, "slippage_points": 2.0}),
    Scenario("COMMISSION_X2", "commission", "commission 7→14 per lot/side",
             costs={**BASE_COSTS, "commission_per_lot": 14.0}),
    Scenario("SWAP_STRESS", "swap", "swap 5/6 per lot/day (positive cost)",
             costs={**BASE_COSTS, "swap_long_per_lot_day": 5.0,
                    "swap_short_per_lot_day": 6.0}),
    Scenario("SPIKES", "spikes", "40 adverse intrabar wicks (×40 range)",
             mutate=lambda d: spikes(d)),
    Scenario("GAPS", "gaps", "40 opens gapped 0.5–2% off prior close",
             mutate=lambda d: gaps(d)),
    Scenario("GAP_REJECT_1PCT", "gap_rejection",
             "same gapped data as GAPS, but entries on |gap|>1% bars skipped",
             mutate=lambda d: gaps(d),
             costs={**BASE_COSTS, "max_gap_fraction": 0.01}),
    Scenario("COMBINED_SEVERE", "combined",
             "spread×5 + slippage×3 + spikes + gaps",
             mutate=lambda d: gaps(spikes(d)),
             costs={**BASE_COSTS, "spread_points": 5.0,
                    "slippage_points": 2.0}),
)

#: Live-path stresses the Python engine does NOT model — reported as
#: NOT-MODELLED with the evidence path, never with invented numbers.
NOT_MODELLED = {
    "latency": "MQL5 path: EXEC audit lines carry latencyMs; owner/demo evidence",
    "partial_fills": "MQL5 path: DONE_PARTIAL handling + RetryQueue (source-pinned)",
    "rejections": "MQL5 path: retryable-vs-final retcode ladder (source-pinned)",
}


def run_scenario(df: pd.DataFrame, sc: Scenario, **kwargs) -> dict:
    res = run_backtest(sc.mutate(df), STRATEGY, PARAMS,
                       **{**BASE_COSTS, **sc.costs, **kwargs})
    return res


def observed_table(df: pd.DataFrame, **kwargs) -> list[dict]:
    """Run every scenario; return the observed-degradation rows vs BASE."""
    rows = []
    base_metrics = None
    for sc in SCENARIOS:
        res = run_scenario(df, sc, **kwargs)
        m = res.metrics
        row = {
            "scenario": sc.name,
            "dimension": sc.dimension,
            "description": sc.description,
            "net_profit": float(m.get("net_profit", float("nan"))),
            "profit_factor": float(m.get("profit_factor", 0.0) or 0.0),
            "sharpe": float(m.get("sharpe", float("nan"))),
            "max_drawdown": float(m.get("max_drawdown_pct", float("nan"))),
            "trades": int(m.get("trades", len(res.trades))),
        }
        if sc.name == "BASE":
            base_metrics = row
            row["delta_net"] = 0.0
        else:
            b = base_metrics["net_profit"]
            row["delta_net"] = row["net_profit"] - b
        rows.append(row)
    return rows


def render_report(rows: list[dict]) -> str:
    lines = [
        "# EXECUTION STRESS — OBSERVED DEGRADATION (AEGIS Phase 10)",
        "",
        "Fixture: Bollinger reversal (default params) on 1y synthetic H1,",
        "BASE costs spread=1pt, commission=7/lot/side. Every number below",
        "is the",
        "**observed** engine output for that scenario — no target, no",
        "threshold. Per Mission-3 rules a fixed figure like \"30–50%\"",
        "degradation is context, never a gate.",
        "",
        "| scenario | dimension | net | Δnet vs BASE | PF | sharpe | maxDD | trades |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['scenario']} | {r['dimension']} | {r['net_profit']:.2f} "
            f"| {r['delta_net']:+.2f} | {r['profit_factor']:.3f} "
            f"| {r['sharpe']:.3f} | {r['max_drawdown']:.4f} "
            f"| {r['trades']} |")
    lines += [
        "",
        "## NOT modelled in Python (live-path, owner/demo evidence)",
        "",
    ]
    for dim, where in NOT_MODELLED.items():
        lines.append(f"- **{dim}** — {where}")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(days: int = 365, seed: int = 5) -> int:
    from .data import generate_ohlc
    df = generate_ohlc(days=days, seed=seed)
    print(render_report(observed_table(df)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
