#!/usr/bin/env python3
"""Build the AEGIS Gold Standard (gold1) execution-parity artifacts
(Reality Gate §3–§7, §41, §60), regenerated on the gold2 path
(S8-GOLD1-REGEN, 2026-10-07; CLAUDE.md owner-scoped exception 2).

Everything here is DETERMINISTIC: the fixture is constructed from
explicit piecewise segments (no RNG), every artifact is written with a
stable serialization, and every artifact carries the SHA-256 of its
inputs.  Expected values are NEVER hand-typed: they come from running the
canonical Python reference and the DSL runtime over the fixture through
the SAME canonical portfolio engine (``mql5bot.engine``) the gold2
builder uses, with an explicit, recorded configuration.

The gold strategy is the repo's canonical reference migration
``ema_crossover_ref`` (EMA 10/30 state mode, ATR(14) SL 2.5 / TP 4.0) —
the SAME parameterization as the EA's compiled default strategy.

Engine contract (recorded in the manifest ``engine_config``): netting
mode, allow_short=True, allow_signal_exit=True (an opposite desired closes
the book: flip rule ``close opposite (signal_exit); enter next bar``),
risk_percent_equity sizing on the PREVIOUS closed bar's ATR, market
entries at next bar open, SL-first both-touch rule.  The frozen trace is
built on the manifest cost (mid basis, slippage 1); the stage-8 window
run re-prices it on the tester's BID basis with the fixed spread the
importer sets from ``cost_config.spread_points`` (S8-COST-1).

Fixture (H1, Monday-Friday only, no RNG):
  * 25 weekdays (600 bars) of CONSTANT close 1.12500 with a fixed
    +-0.00025 wick: EMA10 == EMA30 EXACTLY (1.125 is dyadic, so the SMA
    seed and ``prev + alpha*(x - prev)`` stay exact in both runtimes) ->
    desired 0, no trade; ATR settles at the wick range.  It covers MT5's
    pre-start history reserve and the EA's InpDslBars=500 readiness, and
    keeps the EA's 500-bar EMA window seeded inside the constant region
    (bit-identical to the full-history EMA).
  * one scenario week (Mon 2024-02-05 ..): the §5 scenarios, all signals
    Monday-Thursday so every fill is signal + 1 bar.
  * Friday 2024-02-09 is the tail day (MT5 ToDate is exclusive).

Outputs (artifacts/gold/):
    manifest.json           frozen identity + engine_config + hashes (§4)
    gold_fixture.csv        deterministic H1 OHLCV fixture (§5)
    micro_both_touch.csv    §61 both-touch micro fixture
    python_trace.json       canonical Python per-bar reference (§6)
    dsl_trace.json          DSL-runtime per-bar trace (§7)
    expected_execution.json sizing/meta/execution expectations (§12/§15)
    reconciliation.json     field-by-field reconciliation state (§41)
    provenance.json         provenance + artifact hashes

Run:  python tools/build_gold_standard.py [--out artifacts/gold]
      [--git-commit <pin>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # pins this repo's python/ ahead of any installed mql5bot

REPO = _bootstrap.REPO_ROOT

import numpy as np
import pandas as pd
from mql5bot.costs import CostConfig
from mql5bot.dsl import desired_positions, parse_file
from mql5bot.engine import (
    FLIP_RULE_ENTER_NEXT_BAR,
    MODE_NETTING,
    Instrument,
    PortfolioEngine,
    RunConfig,
)
from mql5bot.indicators import atr as atr_fn
from mql5bot.indicators import ema as ema_fn
from mql5bot.sizer import RISK_PERCENT_EQUITY, size_position
from mql5bot.strategies import STRATEGIES
from mql5bot.symbolspec import SymbolSpec

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
FAST = 10
SLOW = 30
SL_ATR = 2.5
TP_ATR = 4.0
ATR_PERIOD = 14
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
CODE_VERSION_REF = "python/mql5bot@artifacts-gold-1-regen"
META_WEIGHTS = (1.0, 0.5, 0.1, 0.01, 0.0)
# gold1 has no allocation ladder: the weight in force is 1.0 throughout,
# the same weight the tester leg applies (InpBaseGateWeight=1.0)
META_SCHEDULE = ((pd.Timestamp("2024-01-01 00:00:00"), 1.0),)
FIXTURE_START = pd.Timestamp("2024-01-01 00:00:00")      # a Monday
WARMUP_DAYS = 25
BASE = 1.125                          # dyadic: exact in binary floating point
WICK = 0.00025
TEST_COMMAND = ".venv/bin/python -m pytest tests/test_reality_gate.py -q"


# ---------------------------------------------------------------- fixture
def _weekday_hours(start: pd.Timestamp, n: int) -> pd.DatetimeIndex:
    """n H1 stamps from ``start``, Monday-Friday only."""
    out: list[pd.Timestamp] = []
    t = start
    while len(out) < n:
        if t.weekday() < 5:
            out.append(t)
        t += pd.Timedelta(hours=1)
    return pd.DatetimeIndex(out, name="time")


def _mk(closes: list[float], index: pd.DatetimeIndex,
        spike_bars=None) -> pd.DataFrame:
    closes = [round(c, 5) for c in closes]
    o = [closes[0]] + closes[:-1]
    h = [round(max(a, b) + WICK, 5) for a, b in zip(o, closes)]
    lo = [round(min(a, b) - WICK, 5) for a, b in zip(o, closes)]
    for i, up, dn in spike_bars or []:
        h[i] = round(o[i] + up, 5)
        lo[i] = round(o[i] - dn, 5)
    df = pd.DataFrame({"open": o, "high": h, "low": lo, "close": closes,
                       "volume": [1000.0 + 10 * (i % 100)
                                  for i in range(len(closes))]},
                      index=index)
    df.index.name = "time"
    return df


def build_fixture() -> pd.DataFrame:
    """Explicit-timestamp H1 fixture engineered for the §5 scenarios
    (every close is hand-set; no RNG):

      warmup (600 bars)  constant close: EMA10 == EMA30 exactly -> flat
                         [no_signal; invalid_signal = NaN guard + no-op]
      Mon 02-05 00:00    clean ramp up: long entry, repeated TP hits with
                         persistence re-entries [long_signal; tp_hit]
      then               vertical drop: long stopped [sl_hit], flips short
      then               clean ramp down: short hold [short_signal]
      then               huge-range bars [both_touch; stop-first]
      then               ramp up: FLIP short->long [opposite_signal]
      then               flat-ish hold through Friday (tail day, outside
                         MT5's exclusive ToDate) [position_exists]
    """
    flat = [BASE] * (WARMUP_DAYS * 24)
    up = [BASE + 0.0011 * i for i in range(1, 26)]
    drop = [up[-1] - 0.005 * i for i in range(1, 5)]
    dn = [drop[-1] - 0.0013 * i for i in range(1, 19)]
    spikes = [dn[-1], dn[-1]]
    up2 = [dn[-1] + 0.0014 * i for i in range(1, 19)]
    scen = up + drop + dn + spikes + up2
    # hold to the end of Friday: the scenario week has 120 bars
    hold = [up2[-1] + 0.00002 * (i % 2) for i in range(120 - len(scen))]
    closes = flat + scen + hold
    k = len(flat) + len(up) + len(drop) + len(dn)
    idx = _weekday_hours(FIXTURE_START, len(closes))
    return _mk(closes, idx, spike_bars=[(k, 0.006, 0.008),
                                        (k + 1, 0.009, 0.012)])


def build_both_touch_micro() -> pd.DataFrame:
    """§61 edge: one position open, ONE bar touching BOTH the stop and
    the target.  Canonical rule under test: the STOP is assumed hit
    first (conservative) — the engine must exit stop_loss, never
    take_profit, on that bar."""
    flat = [1.1000 + 0.00002 * i for i in range(35)]   # steady: state long
    giant = [flat[-1]]
    idx = pd.date_range("2024-01-01 00:00:00", periods=36, freq="h",
                        name="time")
    return _mk(flat + giant, idx, spike_bars=[(35, 0.0060, 0.0060)])


# ------------------------------------------------------------- execution
def _engine_run(df: pd.DataFrame, sig: pd.Series):
    spec_obj = SymbolSpec(**BROKER_SPEC)
    costs = CostConfig(symbol=SYMBOL,
                       spread_points=COSTS["spread_points"],
                       slippage_points=COSTS["slippage_points"],
                       commission_per_lot=COSTS["commission_per_lot"])
    cfg = RunConfig(initial_capital=EQUITY_START, mode=MODE_NETTING,
                    allow_short=True, sizing_mode=RISK_PERCENT_EQUITY,
                    risk_value=RISK_PERCENT, max_lots=100.0,
                    allow_signal_exit=True)
    ins = Instrument(symbol=SYMBOL, strategy=STRATEGY_ID, df=df,
                     costs=costs, spec=spec_obj, profit_to_deposit=1.0,
                     params={"sl_atr": SL_ATR, "tp_atr": TP_ATR},
                     signal=sig, allocation_schedule=META_SCHEDULE)
    return PortfolioEngine(cfg).run([ins])


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _git_commit() -> str:
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO,
            text=True).strip()[:12]
    except Exception:  # noqa: BLE001 — artifact must build outside git
        return "unknown"


def _config_hash() -> str:
    canon = {"broker_spec": BROKER_SPEC, "costs": COSTS,
             "risk": {"mode": "risk_percent_equity",
                      "risk_percent": RISK_PERCENT,
                      "equity_start": EQUITY_START},
             "engine": {"mode": MODE_NETTING, "allow_short": True,
                        "allow_signal_exit": True,
                        "sizing_mode": RISK_PERCENT_EQUITY},
             "symbol": SYMBOL, "timeframe": TIMEFRAME,
             "warmup_bars": 0,
             "clock": "DayClock default (midnight server-day roll)",
             "geometry": {"sl_atr": SL_ATR, "tp_atr": TP_ATR,
                          "atr_period": ATR_PERIOD},
             "strategy": {"fast": FAST, "slow": SLOW},
             "meta_schedule": [[str(ts), w] for ts, w in META_SCHEDULE]}
    return _sha_bytes(json.dumps(canon, sort_keys=True).encode())


def _meta_ladder(r) -> dict:
    out = {}
    for w in META_WEIGHTS:
        lots = float(r.lots) * w
        final = np.floor(lots / BROKER_SPEC["volume_step"] + 1e-9) \
            * BROKER_SPEC["volume_step"]
        if final < BROKER_SPEC["volume_min"] or final > float(r.lots) + 1e-12:
            out[str(w)] = {"final_lots": 0.0, "action": "DROP"}
        else:
            out[str(w)] = {"final_lots": round(final, 6), "action": "SEND"}
    return out


def expected_entries(df: pd.DataFrame, sig: pd.Series, res) -> tuple[
        list[dict], list[dict], int]:
    """The sizing expectation of every entry the engine made, on the gold2
    path: an entry triggered by the signal on bar i is sized on atr[i]
    against equity[i] (the signal bar's closing equity). Flip deferrals
    are read from the engine's ``flip_deferred`` events, never inferred."""
    spec_obj = SymbolSpec(**BROKER_SPEC)
    s = sig.to_numpy()
    atr_v = atr_fn(df["high"].to_numpy(dtype=float),
                   df["low"].to_numpy(dtype=float),
                   df["close"].to_numpy(dtype=float), ATR_PERIOD)
    basis_at = res.equity.to_numpy()
    flip_bars = {int(e["bar"]) for e in res.events
                 if e.get("type") == "flip_deferred"}
    rows, flips, vetoes = [], [], 0

    def row_for(i: int, kind: str) -> dict:
        a = atr_v[i]
        dist = SL_ATR * float(a) if np.isfinite(a) else None
        r = (size_position(spec_obj, mode="risk_percent_equity",
                           equity=float(basis_at[i]), stop_distance=dist,
                           value=RISK_PERCENT) if dist else None)
        row = {"signal_time": df.index[i].isoformat(),
               "side": "long" if s[i] == 1 else "short",
               "entry_kind": kind,
               "atr_signal_bar": None if not np.isfinite(a)
               else round(float(a), 10),
               "stop_distance": None if dist is None else round(dist, 10),
               "sizing_basis": round(float(basis_at[i]), 6),
               "risk": (None if r is None else
                        {"approved_lots": round(float(r.lots), 6),
                         "reason": r.reason, "rejected": bool(r.rejected)}),
               "meta": {}}
        if r is not None and not r.rejected and r.lots > 0:
            row["meta"] = _meta_ladder(r)
        return row

    for i in range(1, len(df)):
        if s[i] == 0 or s[i] == s[i - 1]:
            continue
        if (i + 1) in flip_bars:
            flips.append({"signal_time": df.index[i].isoformat(),
                          "close_time": df.index[i + 1].isoformat(),
                          "side": "long" if s[i] == 1 else "short",
                          "rule": FLIP_RULE_ENTER_NEXT_BAR})
            continue
        row = row_for(i, "signal_transition")
        if row["risk"] is not None and row["risk"]["rejected"]:
            vetoes += 1
        rows.append(row)
    for _, t in res.trades.iterrows():
        j = df.index.get_loc(pd.Timestamp(t["entry_time"]))
        i = j - 1
        if i < 1 or s[i] == 0 or s[i] != s[i - 1]:
            continue                                 # covered above
        rows.append(row_for(i, "flip_deferred_entry" if i in flip_bars
                            else "persistence_reentry"))
    rows.sort(key=lambda r: r["signal_time"])
    return rows, flips, vetoes


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
    csv_text = df.to_csv(float_format="%.10f")
    micro = build_both_touch_micro()

    spec = parse_file(GOLD_SPEC)
    fn, defaults = STRATEGIES["ema_crossover"]
    params = dict(defaults)             # fast 10 / slow 30 / 2.5 / 4.0
    if (params.get("fast"), params.get("slow"), params.get("sl_atr"),
            params.get("tp_atr")) != (FAST, SLOW, SL_ATR, TP_ATR):
        raise AssertionError(f"registry defaults moved: {params}")

    ref_sig = fn(df, params)                       # compiled reference
    dsl_sig = desired_positions(spec, df)          # DSL runtime
    sig_equal = bool((ref_sig.to_numpy() == dsl_sig.to_numpy()).all())
    res_ref = _engine_run(df, ref_sig)
    res_dsl = _engine_run(df, dsl_sig)
    trade_match = res_ref.trades.equals(res_dsl.trades)

    close = df["close"].to_numpy(dtype=float)
    ema_f, ema_s = ema_fn(close, FAST), ema_fn(close, SLOW)
    atr_v = atr_fn(df["high"].to_numpy(dtype=float),
                   df["low"].to_numpy(dtype=float), close, ATR_PERIOD)

    def trace(sig_series: pd.Series, res, label: str) -> dict:
        bars = []
        pos = 0
        for i, (ts, row) in enumerate(df.iterrows()):
            sig = int(sig_series.iloc[i])
            entry = "hold"
            if sig != pos:
                entry = ("flat" if sig == 0 else
                         ("flip_long" if sig == 1 else "flip_short")
                         if pos != 0 else
                         ("enter_long" if sig == 1 else "enter_short"))
            pos = sig
            bars.append({
                "i": i, "timestamp": ts.isoformat(),
                "open": round(float(row["open"]), 10),
                "high": round(float(row["high"]), 10),
                "low": round(float(row["low"]), 10),
                "close": round(float(row["close"]), 10),
                "ema_fast": None if np.isnan(ema_f[i])
                else round(float(ema_f[i]), 10),
                "ema_slow": None if np.isnan(ema_s[i])
                else round(float(ema_s[i]), 10),
                "atr14": None if np.isnan(atr_v[i])
                else round(float(atr_v[i]), 10),
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
    dsl_trace = trace(dsl_sig, res_dsl, "dsl-runtime")

    # --- §61 both-touch micro-scenario: stop assumed hit first ---------
    micro_res = _engine_run(micro, fn(micro, params))
    mt = micro_res.trades.iloc[-1]
    m_atr = atr_fn(micro["high"].to_numpy(dtype=float),
                   micro["low"].to_numpy(dtype=float),
                   micro["close"].to_numpy(dtype=float), ATR_PERIOD)
    gbar = micro.iloc[35]
    micro_record = {
        "fixture": "micro_both_touch.csv",
        "entry_time": pd.Timestamp(mt["entry_time"]).isoformat(),
        "entry_fill": round(float(mt["entry_price"]), 10),
        "atr_at_entry": round(float(m_atr[33]), 10),
        "giant_bar": {"timestamp": micro.index[35].isoformat(),
                      "high": round(float(gbar["high"]), 10),
                      "low": round(float(gbar["low"]), 10)},
        "exit_reason": str(mt["exit_reason"]),
        "expected_exit_reason": "stop_loss",
        "rule": "both levels touched in one bar -> STOP assumed hit "
                "first (conservative); TP must NOT win",
    }

    exec_rows, flip_deferrals, veto_count = expected_entries(
        df, ref_sig, res_ref)

    # --- manifest + hashes ----------------------------------------------
    (out / "gold_fixture.csv").write_text(csv_text)
    (out / "micro_both_touch.csv").write_text(
        micro.to_csv(float_format="%.10f"))
    dataset_hash = _sha_bytes(csv_text.encode())
    engine_config = {"mode": MODE_NETTING, "allow_short": True,
                     "allow_signal_exit": True,
                     "sizing_mode": RISK_PERCENT_EQUITY,
                     "sl_atr": SL_ATR, "tp_atr": TP_ATR}
    manifest = {
        "gold_standard": "AEGIS-GOLD-1",
        "regeneration": ("S8-GOLD1-REGEN (2026-10-07): regenerated on the "
                         "gold2 path (PortfolioEngine, flip rule, "
                         "engine_config); NOT byte-continuous with the "
                         "2024 120-bar fixture"),
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "spec_hash": spec.spec_hash,
        "dsl_version": DSL_VERSION,
        "indicator_versions": {"EMA": "contract-v1 (indicators.ema, "
                                      "alpha=2/(n+1), SMA seed)",
                               "ATR": "contract-v1 (indicators.atr, "
                                      "Wilder, period 14)"},
        "code_version": CODE_VERSION_REF,
        # no python_version: the committed bytes must rebuild identically
        # on every CI Python (tests/test_reality_gate.py determinism)
        "git_commit": args.git_commit or _git_commit(),
        "dataset_id": "gold-fixture-h1-2024-regen",
        "dataset_hash": dataset_hash,
        "config_hash": _config_hash(),
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "timezone": TIMEZONE,
        "cost_config": COSTS,
        "risk_config": {"mode": "risk_percent_equity",
                        "risk_percent": RISK_PERCENT,
                        "equity_start": EQUITY_START},
        "broker_spec": BROKER_SPEC,
        "engine_config": engine_config,
        "seed": 0,
        "signal_timing_contract": {
            "signal_on": "closed bar (shift 1)",
            "action_at": "next bar open (EA: first tick of new bar)",
            "order_type": "market",
            "both_touch_rule": "SL assumed hit first (conservative)",
            "flip_rule": FLIP_RULE_ENTER_NEXT_BAR,
        },
        "scenario_map": {
            "no_signal": "constant warmup (EMA10 == EMA30 exactly)",
            "long_signal": "uptrend segment (Mon 2024-02-05)",
            "short_signal": "downtrend segment",
            "invalid_signal": "desired==exposure no-op + warmup NaN guard",
            "sl_hit": "vertical drop segment",
            "tp_hit": "uptrend segment (repeated TP + persistence "
                      "re-entries)",
            "simultaneous_edge": "huge-range bars (stop-first rule) + "
                                 "micro_both_touch.csv",
            "slippage": "slippage_points=1.0 on every frozen fill",
            "volume_below_minimum": "meta 0.01/0.0 weights -> DROP",
            "position_exists": "state-mode hold bars",
            "opposite_signal": "flip segment (flip_deferrals)",
        },
        "normalization_rules": {
            "csv_float_format": "%.10f",
            "json": "indent=2, sort_keys=True, trailing newline",
            "price_rounding": "10 decimals in traces; 5-decimal broker "
                              "grid in the fixture",
            "lots_rounding": "6 decimals; broker floor-to-step with the "
                             "1e-9 step-unit dust guard",
            "time": "ISO-8601 naive stamps; Monday-Friday only"},
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest_hash = _sha_bytes((out / "manifest.json").read_bytes())

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
                    "risk_vetoes": veto_count,
                    "flip_deferrals": flip_deferrals,
                    "entries": exec_rows}, indent=2, sort_keys=True)
        + "\n")

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
        "note": "Python<->DSL proven here; MQL5/MT5 legs require the "
                "owner terminal protocol (docs/MT5_ROUNDTRIP.md).",
        "trades": [{"signal_time": t["signal_time"], "side": t["side"],
                    "python": t, "dsl": d, "mt5": None,
                    "mt5_status": "PENDING_OWNER"}
                   for t, d in zip(py_trace["trades"],
                                   dsl_trace["trades"])],
    }
    (out / "reconciliation.json").write_text(
        json.dumps(recon, indent=2, sort_keys=True) + "\n")

    provenance = {
        "manifest_hash": manifest_hash,
        "fixture_hash_sha256": dataset_hash,
        "spec_hash": spec.spec_hash,
        "config_hash": _config_hash(),
        "git_commit": manifest["git_commit"],
        "builder": "tools/build_gold_standard.py",
        "test_command": TEST_COMMAND,
        "params": engine_config | {"fast": FAST, "slow": SLOW},
        "artifact_hashes": {
            name: _sha_bytes((out / name).read_bytes())
            for name in ("manifest.json", "gold_fixture.csv",
                         "micro_both_touch.csv", "python_trace.json",
                         "dsl_trace.json", "expected_execution.json",
                         "reconciliation.json")},
    }
    (out / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        "bars": len(df), "trades": len(py_trace["trades"]),
        "entries": len(exec_rows), "flip_deferrals": len(flip_deferrals),
        "signal_parity": sig_equal, "trade_parity": trade_match,
        "python_vs_dsl": recon["python_vs_dsl"],
        "manifest_hash": manifest_hash,
        "legs": sorted({t["exit_reason"] for t in py_trace["trades"]}),
        "micro_exit": micro_record["exit_reason"],
    }, indent=2))
    ok = (sig_equal and trade_match
          and micro_record["exit_reason"] == "stop_loss")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
