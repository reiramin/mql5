"""tools/meta_real_basket.py — REAL-data multi-asset basket runner
(AEGIS Phase 20).

Preferred real basket: EURUSD, GBPUSD, USDJPY, XAUUSD, one index CFD,
one crypto CFD.  Each instrument REQUIRES

    data/real/<SYMBOL>.csv         — OHLC data (date,open,high,low,close)
    data/real/<SYMBOL>.spec.json   — explicit broker spec + provenance

where the spec sidecar carries: point, tick_size, tick_value_loss,
contract_size, volume_min, volume_step, currency_profit,
currency_deposit, conversion (if profit != deposit), corr_group, and
provenance {source, timezone, retrieved_at, bars, notes}.  Specs are
OWNER INPUTS — this tool never invents broker facts.

Rules enforced here:
- an unavailable instrument is REPORTED unavailable, never substituted;
- the committed VIX series is a diagnostic only and NEVER counts as
  basket completion;
- missing conversion pair ⇒ the context is INELIGIBLE (journaled by
  the engine), never a fake 1.0;
- fewer than the full basket ⇒ no basket run (exit 2), per-symbol
  diagnostics remain possible via tools/meta_real_validation.py.

Sandbox: data/real/ is absent ⇒ every symbol is UNAVAILABLE and the
tool exits 2 with the report.  Owner: place the files and re-run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

BASKET = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US500", "BTCUSD"]
REAL_DIR = Path("data/real")
REQUIRED_SPEC = {"point", "tick_size", "tick_value_loss", "contract_size",
                 "volume_min", "volume_step", "currency_profit",
                 "currency_deposit", "provenance"}
REQUIRED_PROVENANCE = {"source", "timezone", "retrieved_at"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_instrument(symbol: str) -> dict:
    """Return {'status': 'ok', ...} or {'status': 'unavailable', 'why'}."""
    csv_path = REAL_DIR / f"{symbol}.csv"
    spec_path = REAL_DIR / f"{symbol}.spec.json"
    if not csv_path.exists():
        return {"symbol": symbol, "status": "unavailable",
                "why": f"missing {csv_path}"}
    if not spec_path.exists():
        return {"symbol": symbol, "status": "unavailable",
                "why": f"missing {spec_path}"}
    try:
        spec = json.loads(spec_path.read_text())
    except json.JSONDecodeError as e:
        return {"symbol": symbol, "status": "unavailable",
                "why": f"spec JSON unreadable: {e}"}
    missing = REQUIRED_SPEC - set(spec)
    if missing:
        return {"symbol": symbol, "status": "unavailable",
                "why": f"spec missing keys {sorted(missing)}"}
    prov = spec.get("provenance") or {}
    miss_prov = REQUIRED_PROVENANCE - set(prov)
    if miss_prov:
        return {"symbol": symbol, "status": "unavailable",
                "why": f"provenance missing {sorted(miss_prov)}"}
    df = pd.read_csv(csv_path)
    df.columns = [c.lower() for c in df.columns]
    need = {"date", "open", "high", "low", "close"}
    if not need <= set(df.columns):
        return {"symbol": symbol, "status": "unavailable",
                "why": f"CSV missing columns {sorted(need - set(df.columns))}"}
    df["date"] = pd.to_datetime(df["date"])
    return {"symbol": symbol, "status": "ok", "df": df, "spec": spec,
            "csv_sha256": sha256_file(csv_path),
            "spec_sha256": sha256_file(spec_path),
            "timezone": prov["timezone"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-history-bars", type=int, default=480)
    ap.add_argument("--every-days", type=int, default=5)
    args = ap.parse_args()

    loaded = [load_instrument(s) for s in BASKET]
    unavailable = [r for r in loaded if r["status"] != "ok"]

    print("== REAL basket availability ==")
    for r in loaded:
        if r["status"] == "ok":
            print(f"  {r['symbol']:>7}: OK  bars={len(r['df'])} "
                  f"tz={r['timezone']} csv_sha256={r['csv_sha256'][:12]}…")
        else:
            print(f"  {r['symbol']:>7}: UNAVAILABLE — {r['why']}")
    print("  NOTE: the committed VIX series is a diagnostic only and "
          "never substitutes for basket completion.")

    if unavailable:
        print(f"\nBASKET INCOMPLETE: {len(unavailable)}/{len(BASKET)} "
              "instruments unavailable — no basket run "
              "(never fabricate, never substitute).")
        return 2

    # ---- full basket present: build contexts and run -------------------
    from mql5bot.costs import CostConfig
    from mql5bot.meta_portfolio import InstrumentContext, \
        MetaPortfolioEngine
    from mql5bot.symbolspec import SymbolSpec

    specs = {r["symbol"]: r["spec"] for r in loaded}
    frames = {r["symbol"]: r["df"].set_index("date")[["open", "high",
                                                      "low", "close"]]
              for r in loaded}
    # one shared clock: inner-join on the intersection of dates
    shared = None
    for df in frames.values():
        idx = df.index
        shared = idx if shared is None else shared.intersection(idx)
    contexts = []
    for i, r in enumerate(loaded):
        s = specs[r["symbol"]]
        df = frames[r["symbol"]].loc[shared]
        strat = ["bollinger_reversal", "ema_crossover",
                 "macd_momentum"][i % 3]
        contexts.append(InstrumentContext(
            symbol=r["symbol"], strategy_id=f"{strat}@{r['symbol']}",
            engine_strategy=strat, df=df,
            spec=SymbolSpec(name=r["symbol"], point=s["point"],
                            tick_size=s["tick_size"],
                            tick_value_loss=s["tick_value_loss"],
                            contract_size=s["contract_size"],
                            volume_min=s["volume_min"],
                            volume_step=s["volume_step"],
                            currency_profit=s["currency_profit"],
                            currency_deposit=s["currency_deposit"]),
            costs=CostConfig(symbol=r["symbol"], spread_points=2.0),
            corr_group=s.get("corr_group", ""),
            conversion=s.get("conversion")))
    eng = MetaPortfolioEngine(contexts=contexts,
                              min_history_bars=args.min_history_bars,
                              every_days=args.every_days)
    res = eng.run()
    print(f"\n== BASKET RUN == ineligible={eng.ineligible}")
    print(res.meta.attribution_symbol.to_string(index=False))
    print("\nmanifest keys:", sorted(res.manifest.keys()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
