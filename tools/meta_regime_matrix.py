"""Meta regime matrix (Phases 21–23).

RUNS THE FROZEN CANONICAL CONFIGURATION and partitions decisions and
trade PnL by the causal regime label that was KNOWN at each entry
decision (from the weight journals' regime provenance — strictly
pre-decision information).

NO TUNING: the engine configuration below is frozen before any
regime-partitioned result is observed, and this tool exposes no knobs
that could tune it after the fact.  The output is measurement only —
it must not feed back into strategy, regime-threshold or drift
parameters (gate rule, Phase 21).

Writes docs/REGIME_MATRIX.md + docs/REGIME_MATRIX.json.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd

from mql5bot.data import generate_ohlc
from mql5bot.meta_portfolio import MetaPortfolioEngine

from tests.test_meta_multi_asset import _contexts  # canonical fixtures

# ---- frozen configuration (do not touch after seeing results) ----------
DAYS = 300
SEEDS = {"fx": 5, "au": 12}
EVERY_DAYS = 12
MIN_HISTORY = 480
BOOKS = ("boll@EURUSD", "ema@EURUSD", "macd@XAUUSD")


def build_engine() -> MetaPortfolioEngine:
    frames = {"fx": generate_ohlc(days=DAYS, seed=SEEDS["fx"]),
              "au": generate_ohlc(days=DAYS, seed=SEEDS["au"])}
    ctxs = [c for c in _contexts(frames)
            if c.strategy_id in BOOKS and c.symbol in ("EURUSD", "XAUUSD")]
    return MetaPortfolioEngine(contexts=ctxs, every_days=EVERY_DAYS,
                               min_history_bars=MIN_HISTORY)


def main() -> int:
    eng = build_engine()
    res = eng.run()
    meta = res.meta

    # decisions with their as-known regime labels
    decision_regimes = []               # (t, {sym: label}, {sid: weight})
    for j in meta.weights:
        t = pd.Timestamp(j["as_of"])
        decision_regimes.append((t, {s: r["regime"] for s, r
                                     in j["regimes"].items()},
                                 {k[3:]: v for k, v in j.items()
                                  if k.startswith("w::")}))

    trades = meta.trades.copy()
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    # trade rows carry the ENGINE strategy name; map (strategy, symbol)
    # back to the allocation book id for the weight journal
    book_of = {(c.engine_strategy, c.symbol): c.strategy_id
               for c in eng.contexts}

    # assign each trade the regime labels known at its covering decision
    rows = []
    for tr in trades.itertuples():
        covering = None
        for t, regimes, weights in decision_regimes:
            if t <= tr.entry_time:
                covering = (t, regimes, weights)
            else:
                break
        if covering is None:
            continue
        _, regimes, weights = covering
        book = book_of.get((tr.strategy, tr.symbol), "")
        rows.append({"symbol": tr.symbol, "strategy": tr.strategy,
                     "book": book,
                     "regime": regimes.get(tr.symbol, "UNKNOWN"),
                     "pnl": float(tr.pnl),
                     "weight": weights.get(book, float("nan"))})
    df = pd.DataFrame(rows)

    per_regime = {}
    for regime, g in df.groupby("regime"):
        per_regime[regime] = {
            "trades": int(len(g)),
            "pnl_sum": round(float(g["pnl"].sum()), 2),
            "pnl_mean": round(float(g["pnl"].mean()), 2),
            "hit_rate": round(float((g["pnl"] > 0).mean()), 4),
            "mean_weight": (round(float(g["weight"].mean()), 4)
                            if g["weight"].notna().any() else None),
            "books": sorted(g["book"].unique().tolist()),
        }

    # decision-level: how often was each label live per symbol
    label_counts = defaultdict(lambda: defaultdict(int))
    for _, regimes, _ in decision_regimes:
        for sym, label in regimes.items():
            label_counts[sym][label] += 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "frozen_config": {"days": DAYS, "seeds": SEEDS,
                          "every_days": EVERY_DAYS,
                          "min_history": MIN_HISTORY, "books": BOOKS},
        "rebalances": len(meta.weights),
        "labels_live": {s: dict(v) for s, v in label_counts.items()},
        "per_regime": per_regime,
        "manifest": res.manifest,
        "no_tuning_rule": "configuration frozen before results; this "
                          "measurement must not feed back into any "
                          "strategy/regime/drift parameter",
    }
    with open("docs/REGIME_MATRIX.json", "w") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")

    lines = ["# Regime matrix (Phases 21–23)", "",
             "Frozen canonical config; decisions/trades partitioned by "
             "the regime label KNOWN at the covering decision "
             "(causal, as-of).  Measurement only — no tuning.",
             "",
             f"Run: {len(meta.weights)} rebalances, "
             f"{len(trades)} trades.", "",
             "## Labels live per symbol (decision counts)", ""]
    for sym, counts in sorted(label_counts.items()):
        lines.append(f"- **{sym}**: " + ", ".join(
            f"{k}={v}" for k, v in sorted(counts.items())))
    lines += ["", "## Per-regime trade statistics", "",
              "| regime | trades | pnl sum | pnl mean | hit rate | "
              "mean weight |", "|---|---|---|---|---|---|"]
    for regime in sorted(per_regime):
        r = per_regime[regime]
        lines.append(
            f"| {regime} | {r['trades']} | {r['pnl_sum']} | "
            f"{r['pnl_mean']} | {r['hit_rate']} | {r['mean_weight']} |")
    lines += ["", "## Full manifest digest", "",
              f"- git_commit: `{res.manifest['git_commit']}`",
              f"- regime_version: `{res.manifest['regime_version']}`",
              f"- drift_version: `{res.manifest['drift_version']}`",
              f"- config_hash: `{res.manifest['config_hash']}`", ""]
    with open("docs/REGIME_MATRIX.md", "w") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines[9:20]))
    print("written: docs/REGIME_MATRIX.md, docs/REGIME_MATRIX.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
