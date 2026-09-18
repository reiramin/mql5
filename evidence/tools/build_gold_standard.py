#!/usr/bin/env python3
"""Build the AEGIS Gold Standard execution-parity artifacts (Reality Gate
§3–§7, §41, §60).

Everything here is DETERMINISTIC: the fixture is constructed from
explicit piecewise segments (no RNG), every artifact is written with a
stable serialization, and every artifact carries the SHA-256 of its
inputs.  The gold strategy is the repo's canonical reference migration
`ema_crossover_ref` (EMA 10/30 state mode, ATR(14) SL 2.5 / TP 4.0) —
the SAME parameterization as the EA's compiled default strategy
(STRAT_EMA_CROSSOVER, InpFastEma=10, InpSlowEma=30, InpSlAtr=2.5,
InpTpAtr=4.0, iATR period 14).

Outputs (artifacts/gold/):
    manifest.json           frozen identity + hashes (§4)
    gold_fixture.csv        deterministic H1 OHLCV fixture (§5)
    python_trace.json       canonical Python per-bar reference (§6)
    dsl_trace.json          DSL-runtime per-bar trace (§7)
    expected_execution.json sizing/meta/execution expectations (§12/§15)
    reconciliation.json     field-by-field reconciliation state (§41)

Run:  python tools/build_gold_standard.py [--out artifacts/gold]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

import numpy as np
import pandas as pd
from mql5bot.backtest import run_backtest
from mql5bot.dsl import desired_positions, parse_file
from mql5bot.strategies import STRATEGIES

GOLD_DIR = REPO / "artifacts" / "gold"
GOLD_SPEC = REPO / "examples" / "strategies" / "ema_crossover.json"

STRATEGY_ID = "ema_crossover_ref"
STRATEGY_VERSION = 1
DSL_VERSION = "1.0"
SYMBOL = "EURUSD"
TIMEFRAME = "H1"
TIMEZONE = ("UTC (naive stamps; broker server-time mapping is an "
            "owner-env reconciliation item)")
RISK_PERCENT = 1.0
EQUITY_START = 10_000.0
BROKER_SPEC = {                       # mirrors the parity-fixture EURUSD
    "name": SYMBOL, "digits": 5, "point": 1e-05,
    "tick_size": 1e-05, "tick_value_profit": 1.0,
    "tick_value_loss": 1.0, "contract_size": 100_000.0,
    "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01,
    "volume_limit": 0.0, "stops_level_points": 0,
    "freeze_level_points": 0, "currency_profit": "USD",
}
COSTS = {"spread_points": 1.0, "slippage_points": 1.0,
         "commission_per_lot": 0.0}
CODE_VERSION_REF = "python/mql5bot@artifacts-gold-1"


# ---------------------------------------------------------------- fixture
def _mk(closes, spike_bars=None):
    n = len(closes)
    o = [closes[0]] + closes[:-1]
    h = [max(a, b) + 0.00025 for a, b in zip(o, closes)]
    l = [min(a, b) - 0.00025 for a, b in zip(o, closes)]
    if spike_bars:
        for i, up, dn in spike_bars:
            h[i] = o[i] + up
            l[i] = o[i] - dn
    idx = pd.date_range("2024-01-01 00:00:00", periods=n, freq="h")
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": closes,
                       "volume": [1000.0 + 10 * i for i in range(n)]},
                      index=idx)
    df.index.name = "time"
    return df


def build_fixture() -> pd.DataFrame:
    """Explicit-timestamp H1 fixture engineered for the §5 scenarios
    (every close is hand-set; no RNG):

      bars 0-29   flat warmup: EMA30/ATR still NaN then settling
                  [no_signal; invalid_signal = NaN guard + no-op]
      bars 30-54  clean ramp up: long entries, repeated TP hits
                  [long_signal; tp_hit]
      bars 55-58  vertical drop: longs stopped [sl_hit]
      bars 59-76  clean ramp down: short hold, TP hit [short_signal]
      bars 77-78  huge-range bars [both_touch candidate; stop-first]
      bars 79-96  ramp up: FLIP short→long [opposite_signal]
      bars 97-119 flat: state-mode hold, no new event [position_exists]
    """
    flat = [1.1000 + 0.00005 * (i % 3) for i in range(30)]
    up = [1.1000 + 0.0011 * i for i in range(1, 26)]
    drop = [1.1275 - 0.005 * i for i in range(1, 5)]
    dn = [1.1075 - 0.0013 * i for i in range(1, 19)]
    spikes = [dn[-1], dn[-1]]
    up2 = [dn[-1] + 0.0014 * i for i in range(1, 19)]
    hold = [up2[-1] + 0.00002 * (i % 2) for i in range(23)]
    closes = flat + up + drop + dn + spikes + up2 + hold
    k = len(flat) + len(up) + len(drop) + len(dn)
    return _mk(closes, spike_bars=[(k, 0.006, 0.008),
                                   (k + 1, 0.009, 0.012)])


def build_both_touch_micro() -> pd.DataFrame:
    """§61 edge: one position open, ONE bar touching BOTH the stop and
    the target.  Canonical rule under test: the STOP is assumed hit
    first (conservative) — the engine must exit stop_loss, never
    take_profit, on that bar."""
    flat = [1.1000 + 0.00002 * (i % 2) for i in range(35)]
    giant = [flat[-1]]
    return _mk(flat + giant, spike_bars=[(35, 0.0060, 0.0060)])


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(GOLD_DIR))
    ap.add_argument("--git-commit", default=None,
                    help="pin the recorded commit (freezes the gold "
                         "identity across code changes)")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    df = build_fixture()
    csv_path = out / "gold_fixture.csv"
    df.to_csv(csv_path, float_format="%.10f")
    micro = build_both_touch_micro()
    (out / "micro_both_touch.csv").write_text(
        micro.to_csv(float_format="%.10f"))

    spec = parse_file(GOLD_SPEC)
    fn, defaults = STRATEGIES["ema_crossover"]
    params = dict(defaults)             # fast 10 / slow 30 / 2.5 / 4.0

    # --- indicator values: canonical Python implementation -------------
    from mql5bot.indicators import atr as atr14
    from mql5bot.indicators import ema as ema_py
    close = df["close"].to_numpy()
    ema_f, ema_s = ema_py(close, 10), ema_py(close, 30)
    atr = atr14(df["high"].to_numpy(), df["low"].to_numpy(), close, 14)

    # --- canonical traces ----------------------------------------------
    ref_sig = fn(df, params)                       # compiled reference
    dsl_sig = desired_positions(spec, df)          # DSL runtime
    sig_equal = bool((ref_sig.to_numpy() == dsl_sig.to_numpy()).all())

    common = {"risk_percent": RISK_PERCENT, "allow_short": True,
              "slippage_points": 1.0, "spread_points": 1.0}
    res_ref = run_backtest(df, "dsl:" + spec.strategy_id, params,
                           signal=ref_sig, **common)
    res_dsl = run_backtest(df, "dsl:" + spec.strategy_id, params,
                           signal=dsl_sig, **common)

    def trace(sig_series, res, label):
        bars = []
        pos = 0
        trades = res.trades.reset_index(drop=True)
        tmap = {}
        for _, t in trades.iterrows():
            tmap.setdefault(pd.Timestamp(t["entry_time"]), []).append(t)
        for i, (ts, row) in enumerate(df.iterrows()):
            sig = int(sig_series.iloc[i])
            entry = "hold"
            if sig != pos:
                entry = ("flip_long" if sig == 1 else "flip_short") \
                    if pos != 0 else ("enter_long" if sig == 1
                                      else "enter_short")
            pos = sig
            bars.append({
                "i": i, "timestamp": ts.isoformat(),
                "open": round(float(row["open"]), 10),
                "high": round(float(row["high"]), 10),
                "low": round(float(row["low"]), 10),
                "close": round(float(row["close"]), 10),
                "ema_fast": None if np.isnan(ema_f[i]) else round(float(ema_f[i]), 10),
                "ema_slow": None if np.isnan(ema_s[i]) else round(float(ema_s[i]), 10),
                "atr14": None if np.isnan(atr[i]) else round(float(atr[i]), 10),
                "desired_position": sig,
                "bar_event": entry,
            })
        tr = []
        for _, t in res.trades.iterrows():
            tr.append({
                "strategy_id": STRATEGY_ID,
                "signal_time": pd.Timestamp(t["entry_time"]).isoformat(),
                "side": str(t["side"]),
                "entry_fill": round(float(t["entry_price"]), 10),
                "lots": round(float(t["lots"]), 6),
                "exit_time": pd.Timestamp(t["exit_time"]).isoformat(),
                "exit_price": round(float(t["exit_price"]), 10),
                "exit_reason": t["exit_reason"],
                "pnl": round(float(t["pnl"]), 6),
            })
        return {"label": label, "bars": bars, "trades": tr}

    py_trace = trace(ref_sig, res_ref, "python-canonical")

    # --- §61 both-touch micro-scenario: stop assumed hit first ---------
    micro_df = build_both_touch_micro()
    micro_res = run_backtest(micro_df, "dsl:" + spec.strategy_id, params,
                             signal=fn(micro_df, params),
                             risk_percent=RISK_PERCENT, allow_short=True,
                             slippage_points=1.0, spread_points=1.0)
    mt = micro_res.trades.iloc[-1]
    from mql5bot.indicators import atr as _atr
    _ma = _atr(micro_df["high"].to_numpy(), micro_df["low"].to_numpy(),
               micro_df["close"].to_numpy(), 14)
    _gbar = micro_df.iloc[35]
    micro_record = {
        "fixture": "micro_both_touch.csv",
        "entry_time": pd.Timestamp(mt["entry_time"]).isoformat(),
        "entry_fill": round(float(mt["entry_price"]), 10),
        "atr_at_entry": round(float(_ma[33]), 10),
        "giant_bar": {"timestamp": micro_df.index[35].isoformat(),
                      "high": round(float(_gbar["high"]), 10),
                      "low": round(float(_gbar["low"]), 10)},
        "exit_reason": str(mt["exit_reason"]),
        "expected_exit_reason": "stop_loss",
        "rule": "both levels touched in one bar -> STOP assumed hit "
                "first (conservative); TP must NOT win",
    }
    dsl_trace = trace(dsl_sig, res_dsl, "dsl-runtime")

    trade_match = (py_trace["trades"] == dsl_trace["trades"])
    if not trade_match:
        for a, b in zip(py_trace["trades"], dsl_trace["trades"]):
            if a != b:
                print("TRADE MISMATCH", a, b, file=sys.stderr)
                break

    # --- expected execution (sizing + meta seam) ------------------------
    from mql5bot.sizer import size_position
    from mql5bot.symbolspec import SymbolSpec
    bs = dict(BROKER_SPEC)
    spec_obj = SymbolSpec(**bs)
    exec_rows = []
    for t in py_trace["trades"]:
        # the engine's own geometry is authoritative; recompute risk
        # lots with the canonical sizer over the PREVIOUS closed bar's
        # ATR (the same causal geometry the engine and the EA use)
        idx0 = df.index.get_loc(pd.Timestamp(t["signal_time"]))
        a_prev = atr[max(idx0 - 1, 0)]
        dist = 2.5 * float(a_prev)
        r = size_position(spec_obj, mode="risk_percent_equity",
                          equity=EQUITY_START, stop_distance=dist,
                          value=RISK_PERCENT)
        row = {"signal_time": t["signal_time"], "side": t["side"],
               "entry_fill": t["entry_fill"],
               "stop_distance": round(dist, 10),
               "risk_approved_lots": round(float(t["lots"]), 6),
               "sizer_lots": round(float(r.lots), 6),
               "sizer_reason": r.reason,
               "meta": {}}
        for w in (1.0, 0.5, 0.1, 0.01, 0.0):
            lots = float(t["lots"]) * w
            final = np.floor(lots / bs["volume_step"] + 1e-9) \
                * bs["volume_step"]
            if final < bs["volume_min"] or final > float(t["lots"]):
                row["meta"][str(w)] = {"final_lots": 0.0, "action": "DROP"}
            else:
                row["meta"][str(w)] = {"final_lots": round(final, 6),
                                       "action": "SEND"}
        exec_rows.append(row)

    # --- manifest + hashes ----------------------------------------------
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    dataset_hash = sha(csv_path)
    manifest = {
        "gold_standard": "AEGIS-GOLD-1",
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "spec_hash": spec.spec_hash,
        "dsl_version": DSL_VERSION,
        "indicator_versions": {"EMA": "contract-v1 (indicators.ema, "
                                        "alpha=2/(n+1), SMA seed)",
                               "ATR": "contract-v1 (indicators.atr, "
                                      "Wilder, period 14)"},
        "code_version": CODE_VERSION_REF,
        "git_commit": args.git_commit or _git_commit(),
        "dataset_id": "gold-fixture-h1-2024",
        "dataset_hash": dataset_hash,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "timezone": TIMEZONE,
        "cost_config": COSTS,
        "risk_config": {"mode": "risk_percent_equity",
                        "risk_percent": RISK_PERCENT,
                        "equity_start": EQUITY_START},
        "broker_spec": BROKER_SPEC,
        "seed": 0,
        "signal_timing_contract": {
            "signal_on": "closed bar (shift 1)",
            "action_at": "next bar open (EA: first tick of new bar)",
            "order_type": "market",
            "both_touch_rule": "SL assumed hit first (conservative)",
            "flip_rule": "close opposite; enter next bar",
        },
        "scenario_map": {
            "no_signal": "warmup bars 0-29 + hold segment",
            "long_signal": "uptrend segment",
            "short_signal": "downtrend segment",
            "invalid_signal": "desired==exposure no-op + warmup NaN guard",
            "sl_hit": "reversal spike segment",
            "tp_hit": "huge-range bar 79",
            "simultaneous_edge": "huge-range bar 80 (stop-first rule)",
            "spread_increase": "variable-spread trace leg "
                               "(spread_series spike, see tests)",
            "slippage": "slippage_points=1.0 on every fill",
            "insufficient_capital": "sizer leg: equity floor scenarios "
                                    "(tests/test_reality_gate.py)",
            "volume_below_minimum": "meta 0.01/0.0 weights → DROP",
            "position_exists": "state-mode hold bars",
            "opposite_signal": "flip segment",
            "daily_loss_block": "tests/test_failsafe.py + EA S2",
            "kill_switch_block": "EA seam pin (AllowsNewTrades first "
                                 "gate) + entry-chain test",
            "stale_allocation": "Allocation.mqh IsStale pin + digest "
                                "roundtrip test",
            "zero_allocation": "weight 0.0 → DROP (meta seam test)",
            "partial_fill": "S1/S3 evidence: RetryQueue + SL guard; "
                            "MT5 actuals PENDING_OWNER",
            "retry": "RetryQueue exponential backoff (S3) source tests",
            "restart": "StateStore hot reload (S2/S6) source tests",
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest_hash = hashlib.sha256(
        (out / "manifest.json").read_bytes()).hexdigest()

    (out / "python_trace.json").write_text(
        json.dumps({"manifest_hash": manifest_hash,
                    "signal_timing": manifest["signal_timing_contract"],
                    "scenario_both_touch": micro_record,
                    **py_trace}, indent=2, sort_keys=True) + "\n")
    (out / "dsl_trace.json").write_text(
        json.dumps({"manifest_hash": manifest_hash,
                    "signal_parity_vs_python": sig_equal,
                    **dsl_trace}, indent=2, sort_keys=True) + "\n")
    (out / "expected_execution.json").write_text(
        json.dumps({"manifest_hash": manifest_hash,
                    "sizing_mode": "risk_percent_equity",
                    "risk_percent": RISK_PERCENT,
                    "equity_start": EQUITY_START,
                    "trades": exec_rows}, indent=2, sort_keys=True) + "\n")

    recon = {
        "manifest_hash": manifest_hash,
        "fields": ["signal_time", "strategy_id", "symbol", "side",
                   "risk_approved", "meta_weight", "requested_lots",
                   "broker_normalized_lots", "fill_volume", "entry_price",
                   "sl", "tp", "position_identifier", "exit_time",
                   "exit_price", "realized_pnl"],
        "python_vs_dsl": "MATCHED" if (sig_equal and trade_match)
                         else "MISMATCH",
        "python_vs_mql5": "PENDING_OWNER",
        "python_vs_mt5_tester": "PENDING_OWNER",
        "note": "Python↔DSL proven here; MQL5/MT5 legs require the "
                "owner terminal protocol (docs/AEGIS_REALITY_GATE_AUDIT"
                ".md §owner-protocol; docs/MT5_ROUNDTRIP.md).",
        "trades": [{"signal_time": t["signal_time"], "side": t["side"],
                    "python": t, "dsl": d, "mt5": None,
                    "mt5_status": "PENDING_OWNER"}
                   for t, d in zip(py_trace["trades"],
                                   dsl_trace["trades"])],
    }
    (out / "reconciliation.json").write_text(
        json.dumps(recon, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        "bars": len(df), "trades": len(py_trace["trades"]),
        "signal_parity": sig_equal, "trade_parity": trade_match,
        "python_vs_dsl": recon["python_vs_dsl"],
        "manifest_hash": manifest_hash,
        "legs": sorted({t["exit_reason"] for t in py_trace["trades"]}),
    }, indent=2))
    return 0 if (sig_equal and trade_match) else 1


def _git_commit() -> str:
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO,
            text=True).strip()[:12]
    except Exception:  # noqa: BLE001 — artifact must build outside git too
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
