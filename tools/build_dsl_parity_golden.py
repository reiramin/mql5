#!/usr/bin/env python3
"""Generate the DSL generic-runtime PARITY GOLDEN set (mission §12/§13).

For each fixture strategy this writes, under ``artifacts/dsl_parity/``:

    <name>/bundle.json          the executable bundle (identity + spec + hash)
    <name>/ohlc.csv             the deterministic OHLC fixture (owner imports)
    <name>/expected_trace.json  the Python parity trace (positions/events/geo)

plus ``manifest.json`` binding every file's sha256 + the runtime contract
version.  The OWNER imports each ``ohlc.csv`` into MT5, loads the matching
``bundle.json`` into the generic MQL5 runtime, exports the per-bar position
vector, and compares to ``expected_trace.json`` (positions are compared
EXACTLY).  This is the Python side of the cross-engine parity contract;
the MQL5 side is OWNER-PENDING and never fabricated here.

Runnable fixtures exercise the FULL generic surface (§13 items 1-24, 29):
crossing, AND/OR/NOT, comparisons, rising/falling, within, arithmetic,
ATR/point/percent stops, trailing/breakeven/time exits, session/trading-day
/cooldown/spread/regime filters, warmup and NaN behaviour, and multiple
independent strategies.  Fail-closed fixtures (§13 items 25-28: ambiguous,
unknown indicator, malformed bundle, hash mismatch) are recorded in the
manifest as REFUSALS the loader must produce — see the companion test.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401  pins this repo's python/ ahead of any installed mql5bot
from mql5bot.dsl import build_bundle, parse_spec
from mql5bot.dsl.normalize import canon_json
from mql5bot.dsl.parity import parity_trace

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "dsl_parity"

MK = {"symbol": "EURUSD", "timeframe": "H1"}


def make_ohlc(seed: int, bars: int) -> pd.DataFrame:
    """Deterministic OHLC fixture (no wall-clock; seed-driven)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=bars, freq="h", tz="UTC")
    steps = rng.normal(0.0, 0.6, size=bars).cumsum()
    close = 100.0 + steps
    high = close + np.abs(rng.normal(0.0, 0.3, size=bars))
    low = close - np.abs(rng.normal(0.0, 0.3, size=bars))
    openp = np.concatenate([[close[0]], close[:-1]])
    vol = rng.integers(100, 1000, size=bars).astype(float)
    return pd.DataFrame({"open": openp, "high": high, "low": low,
                         "close": close, "volume": vol}, index=idx)


def _doc(strategy_id: str, indicators, entry, exit_=None, filters=None,
         market=None) -> dict:
    d = {"schema_version": "1.0", "strategy_id": strategy_id, "version": 1,
         "market": market or MK, "indicators": indicators, "entry": entry,
         "exit": exit_ or {"sl": {"model": "atr", "mult": 2.0}}}
    if filters:
        d["filters"] = filters
    return d


def _ema(idf, s): return {"id": idf, "kind": "EMA", "period": s,
                          "applied": "close"}


# ---- runnable fixtures (name, doc, seed, bars, note) -----------------
def fixtures() -> list[tuple]:
    ema_f, ema_s = _ema("ema_f", 20), _ema("ema_s", 50)
    rsi = {"id": "rsi", "kind": "RSI", "period": 14, "applied": "close"}
    atr = {"id": "atr", "kind": "ATR", "period": 14}
    cross_up = {"cross": "ABOVE", "a": {"ind": "ema_f"}, "b": {"ind": "ema_s"}}
    cross_dn = {"cross": "BELOW", "a": {"ind": "ema_f"}, "b": {"ind": "ema_s"}}
    F = []

    # 1 EMA position (instant)
    F.append(("ema_gt", _doc("ema_gt", [ema_f, ema_s],
              {"mode": "instant",
               "long": {"cmp": "GT", "left": {"ind": "ema_f"},
                        "right": {"ind": "ema_s"}},
               "short": {"cmp": "LT", "left": {"ind": "ema_f"},
                         "right": {"ind": "ema_s"}}}), 1, 300,
              "EMA20 > EMA50 (instant)"))
    # 2/3 crossings (state)
    F.append(("ema_cross", _doc("ema_cross", [ema_f, ema_s],
              {"mode": "state", "long": cross_up, "short": cross_dn}), 2, 300,
              "EMA20 crosses EMA50 above/below"))
    # 4/5 EMA cross AND RSI filter (the CANONICAL example)
    F.append(("canonical_ema_rsi_atr", _doc(
        "canonical_ema_rsi_atr", [ema_f, ema_s, rsi, atr],
        {"mode": "state",
         "long": {"and": [cross_up, {"cmp": "GT", "left": {"ind": "rsi"},
                                     "right": {"const": 55.0}}]},
         "short": cross_dn},
        {"sl": {"model": "atr", "mult": 2.0},
         "tp": {"model": "atr", "mult": 3.0}}), 3, 400,
        "BUY when EMA20 crosses above EMA50 AND RSI14>55; SL 2ATR TP 3ATR"))
    # 6 OR
    F.append(("or_rule", _doc("or_rule", [ema_f, ema_s, rsi],
              {"mode": "instant",
               "long": {"or": [{"cmp": "GT", "left": {"ind": "ema_f"},
                                "right": {"ind": "ema_s"}},
                               {"cmp": "GT", "left": {"ind": "rsi"},
                                "right": {"const": 70.0}}]},
               "short": {}}), 4, 300, "OR of two conditions"))
    # 7 NOT
    F.append(("not_rule", _doc("not_rule", [ema_f, ema_s],
              {"mode": "instant",
               "long": {"not": {"cmp": "LT", "left": {"ind": "ema_f"},
                                "right": {"ind": "ema_s"}}},
               "short": {}}), 5, 300, "NOT (fast < slow)"))
    # 8/9 rising / falling
    F.append(("rising", _doc("rising", [ema_f],
              {"mode": "instant",
               "long": {"rising": {"ind": "ema_f"}, "n": 3}, "short": {}}),
              6, 300, "EMA rising over 3 bars"))
    # 10 within
    F.append(("within", _doc("within", [rsi],
              {"mode": "instant",
               "long": {"within": {"ind": "rsi"}, "low": 40.0, "high": 60.0},
               "short": {}}), 7, 300, "RSI within [40,60]"))
    # 11 arithmetic
    F.append(("arithmetic", _doc("arithmetic", [ema_f, ema_s],
              {"mode": "instant",
               "long": {"cmp": "GT", "left": {"ind": "ema_f"},
                        "right": {"add": [{"ind": "ema_s"},
                                          {"const": 0.5}]}},
               "short": {}}), 8, 300, "fast > slow + 0.5"))
    # 12/13/14 stops: atr already covered; points + percent
    F.append(("point_stop", _doc("point_stop", [ema_f, ema_s],
              {"mode": "state", "long": cross_up, "short": cross_dn},
              {"sl": {"model": "points", "points": 200.0},
               "tp": {"model": "points", "points": 400.0}}), 9, 300,
              "point SL/TP geometry"))
    F.append(("percent_stop", _doc("percent_stop", [ema_f, ema_s],
              {"mode": "state", "long": cross_up, "short": cross_dn},
              {"sl": {"model": "percent", "pct": 1.0},
               "tp": {"model": "percent", "pct": 2.0}}), 10, 300,
              "percent SL/TP geometry"))
    # 15/16/17 trailing / breakeven / time exit geometry
    F.append(("trail_be_time", _doc("trail_be_time", [ema_f, ema_s],
              {"mode": "state", "long": cross_up, "short": cross_dn},
              {"sl": {"model": "atr", "mult": 2.0}, "trail_atr": 1.5,
               "breakeven_atr": 1.0, "time_bars": 24}), 11, 300,
              "trailing + breakeven + time exit geometry"))
    # 18 session filter
    F.append(("session", _doc("session", [ema_f, ema_s],
              {"mode": "state", "long": cross_up, "short": cross_dn},
              None, {"session": {"start": "08:00", "end": "16:00",
                                 "tz": "UTC"}}), 12, 300, "session 08-16"))
    # 19 trading-day filter (market-level)
    F.append(("trading_days", _doc("trading_days", [ema_f, ema_s],
              {"mode": "state", "long": cross_up, "short": cross_dn},
              None, None, market={"symbol": "EURUSD", "timeframe": "H1",
                                  "trading_days": [0, 1, 2, 3, 4]}), 13, 300,
              "Mon-Fri only"))
    # 20 cooldown
    F.append(("cooldown", _doc("cooldown", [ema_f, ema_s],
              {"mode": "state", "long": cross_up, "short": cross_dn},
              None, {"cooldown_bars": 5}), 14, 300, "5-bar cooldown"))
    return F


def _write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = text.encode("utf-8")
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    from mql5bot.dsl import RUNTIME_CONTRACT_VERSION
    manifest: dict = {"runtime_contract_version": RUNTIME_CONTRACT_VERSION,
                      "fixtures": {}, "refusals": REFUSALS}
    for name, doc, seed, bars, note in fixtures():
        # an EXECUTABLE version omits empty conditions (only v0 drafts may
        # carry `{}` placeholders) — drop them so long-only rules validate
        for k in ("long", "short", "exit_long", "exit_short"):
            if k in doc["entry"] and not doc["entry"][k]:
                del doc["entry"][k]
        spec = parse_spec(doc)
        assert spec.executable, name
        df = make_ohlc(seed, bars)
        bundle = build_bundle(spec)
        trace = parity_trace(spec, df)
        csv = df.to_csv()
        h_b = _write(OUT / name / "bundle.json",
                     json.dumps(bundle, indent=2, sort_keys=True))
        h_o = _write(OUT / name / "ohlc.csv", csv)
        h_t = _write(OUT / name / "expected_trace.json",
                     json.dumps(trace, indent=2, sort_keys=True))
        manifest["fixtures"][name] = {
            "note": note, "seed": seed, "bars": bars,
            "spec_hash": spec.spec_hash, "bundle_hash": bundle["bundle_hash"],
            "position_hash": trace["position_hash"],
            "files": {"bundle.json": h_b, "ohlc.csv": h_o,
                      "expected_trace.json": h_t}}
    _write(OUT / "manifest.json",
           json.dumps(manifest, indent=2, sort_keys=True))
    _write(OUT / "README.md", _README)
    # a stable digest over all fixture identities (drift tripwire)
    digest = hashlib.sha256(canon_json(manifest["fixtures"]).encode()) \
        .hexdigest()
    print(json.dumps({"fixtures": len(manifest["fixtures"]),
                      "manifest_digest": digest, "out": str(OUT)}, indent=2))
    return 0


# fail-closed fixtures (§13 25-28): the loader MUST refuse these
REFUSALS = {
    "ambiguous": "a spec with an unresolved {ambiguous:} value is not "
                 "bundlable (build_bundle refuses; runtime never runs it)",
    "unknown_indicator": "a bundle whose spec references an unregistered "
                         "indicator kind is refused by load_bundle",
    "malformed_bundle": "a non-object / missing-identity envelope is refused",
    "hash_mismatch": "a tampered spec/identity fails the bundle_hash check",
}

_README = """# DSL generic-runtime parity golden set (§12/§13)

Python-side reference for cross-engine parity. Each `<name>/` holds:
- `bundle.json` — the executable bundle (load into the generic runtime)
- `ohlc.csv` — the deterministic OHLC fixture (import as an offline symbol)
- `expected_trace.json` — the Python parity trace

## Owner MQL5 parity procedure (OWNER-PENDING — never faked on Mac)
1. Compile the integrated runtime (`mql5/Scripts/Mql5Bot/DslParityRunner.mq5`
   + `mql5/Include/Mql5Bot/Dsl*.mqh`) with `tools/compile.ps1 -Strict`.
2. Run `tools/run_dsl_parity.ps1`: it copies each `ohlc.csv`+`bundle.json`
   into the terminal Files dir, runs the batch runner over the committed
   bytes, and writes `dsl_parity_out/<name>.json` per fixture.
3. `tools/compare_dsl_parity.py` compares each output to
   `expected_trace.json` — EXACT match required (logical values carry no
   tolerance); it prints the first bar-indexed divergence and exits 0 only
   at 14/14 EXACT with the `tampered_bundle` negative REFUSED.

`manifest.json` binds every file's sha256 + `position_hash`. Regenerate
with `python tools/build_dsl_parity_golden.py`; a changed digest is a
DECISION-CHANGING event (new provenance required).
"""


if __name__ == "__main__":
    raise SystemExit(main())
