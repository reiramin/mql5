#!/usr/bin/env python3
"""Build the AEGIS GOLD #2 RECONSTRUCTED execution-parity artifacts.

GOLD_2_RECONSTRUCTED_NEW_PROVENANCE — this is NOT "the original Gold
#2" and no continuity with the historical seven-trade artifact is
claimed or implied.  Everything here is a fresh reconstruction with new
provenance (final-closure mission §7–§13).

Determinism: the fixture is constructed from explicit piecewise segments
(no RNG); every artifact is written with a stable serialization and
carries the SHA-256 of its inputs.  Expected values are NEVER
hand-typed: they are produced by running the canonical Python reference
(``mql5bot.gold2_reference``) and the DSL runtime
(``examples/strategies/gold2_multifactor.json``) over the fixture
through the SAME canonical portfolio engine (``mql5bot.engine``) with an
explicit, recorded configuration.

Engine contract for this artifact (recorded in provenance): netting
mode, allow_signal_exit=True (a flat/opposite desired closes the book —
the session flattening therefore really closes positions at 16:00),
risk_percent_equity sizing on the PREVIOUS closed bar's ATR, market
entries at next bar open, SL-first both-touch rule.

Outputs (artifacts/gold_2/):
    manifest.json             frozen identity + provenance + hashes
    gold2_fixture.csv         deterministic M1 OHLCV fixture
    python_trace.json         canonical Python per-bar reference trace
    dsl_trace.json            DSL-runtime per-bar trace
    expected_execution.json   sizing / risk-veto / meta expectations
    reconciliation.json       PYTHON_DSL_MQL5_SOURCE_PARITY record
    provenance.json           provenance incl. distance_to_boundary

Run:  python tools/build_gold2_standard.py [--out artifacts/gold_2]
      [--git-commit <pin>]   # pin the recorded commit when verifying a
                             # frozen identity (Gold #1 precedent)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

import numpy as np
import pandas as pd
from mql5bot.costs import CostConfig
from mql5bot.dsl import desired_positions, parse_file
from mql5bot.engine import MODE_NETTING, Instrument, PortfolioEngine, RunConfig
from mql5bot.gold2_reference import (
    CHANNEL,
    FAST,
    GOLD2_LABEL,
    GOLD2_STRATEGY_ID,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_PERIOD,
    SLOW,
    boundary_distances,
    gold2_multifactor,
)
from mql5bot.indicators import atr as atr_fn
from mql5bot.indicators import ema as ema_fn
from mql5bot.indicators import rsi as rsi_fn
from mql5bot.sizer import RISK_PERCENT_EQUITY, size_position
from mql5bot.symbolspec import SymbolSpec

GOLD2_DIR = REPO / "artifacts" / "gold_2"
GOLD2_SPEC = REPO / "examples" / "strategies" / "gold2_multifactor.json"

DSL_VERSION = "1.0"
STRATEGY_VERSION = 1
SYMBOL = "EURUSD"
TIMEFRAME = "M1"
TIMEZONE = ("UTC (naive stamps; broker server-time mapping is an "
            "owner-env reconciliation item)")
SESSION = {"start": "08:00", "end": "16:00",
           "semantics": "start-inclusive, end-exclusive; bars outside "
                        "are flattened (filters only ever flatten); the "
                        "flattening closes open books via signal_exit "
                        "under this artifact's engine configuration"}
RISK_PERCENT = 1.0
EQUITY_START = 10_000.0
SL_ATR = 2.0
TP_ATR = 3.0
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
CODE_VERSION_REF = "python/mql5bot@gold-2-reconstructed"
META_WEIGHTS = (1.0, 0.5, 0.1, 0.0)
# Meta allocation step function (contract 1.1.1 §5.2 / engine seam).
# One weight per trading day so the fixture exercises the full weight
# ladder {1.0, 0.5, 0.1, 0.0} deterministically: Day1 full, Day2 half,
# Day3 tenth, Day4 zero (zero => every approved size is dropped below
# the broker minimum => reduce-only meta can suppress all entries).
META_SCHEDULE = (
    (pd.Timestamp("2024-01-01 00:00:00"), 1.0),
    (pd.Timestamp("2024-01-02 00:00:00"), 0.5),
    (pd.Timestamp("2024-01-03 00:00:00"), 0.1),
    (pd.Timestamp("2024-01-04 00:00:00"), 0.0),
)
TEST_COMMAND = (".venv/bin/python -m pytest tests/test_gold2_standard.py "
                "-q")


# ---------------------------------------------------------------- fixture
def _bars(closes: list[float], t0: pd.Timestamp) -> pd.DataFrame:
    n = len(closes)
    o = [closes[0]] + closes[:-1]
    h = [max(a, b) for a, b in zip(o, closes)]
    lo = [min(a, b) for a, b in zip(o, closes)]
    idx = pd.date_range(t0, periods=n, freq="min")
    return pd.DataFrame({"open": o, "high": h, "low": lo,
                         "close": closes,
                         "volume": [1000.0] * n}, index=idx)


AMP = 5e-4          # healthy-tape zig-zag amplitude (per-bar move 1e-3,
                    # ATR ~ 1e-3, RSI ~ 50, tops/bottoms repeat exactly)


def build_fixture() -> pd.DataFrame:
    """Four synthetic trading days (M1, 24h), 5760 bars.  No RNG.

    Scene grammar (engine config: allow_signal_exit=True; SL = 2*ATR,
    TP = 3*ATR, ATR = Wilder(14) of the bar BEFORE entry):

    * ``zig`` / ``qz``: zero-drift zig-zags.  Tops and bottoms repeat
      EXACTLY (no breakout fires), RSI ~ 50, and per-bar travel keeps
      Wilder ATR healthy so later entries keep wide SL/TP bands.
    * entry rides ``zz``: zig-zag amp around drift +-1.5e-5; every other
      bar breaks the rolling channel by exactly the drift (state
      persists); worst-case adverse travel amp + n*drift stays inside
      SL, favorable travel inside TP.
    * type-F scene: ride + short qz + gentle 3-bar flip (+-2e-4/bar).
      The flip burns the residual EMA8-EMA21 gap (drift-scale, small),
      fires the opposite breakout, and stays inside the outgoing book's
      SL budget -> the outgoing book exits as signal_exit and the new
      side enters one bar later (direct long<->short transition).
    * crash: ONE bar (default -3e-3).  Exceeds every SL budget
      (stop_loss), crosses the gate inside the bar, new side enters
      AFTER the crash.  Post-crash scenes use qz(25) so the crash bar
      leaves the 20-bar channel window, then a 2-bar +-3e-4 flip.
    * spike: +2.8e-3 / +1.5e-3 bar => take_profit; the following crash
      closes the documented post-TP re-entry at stop_loss.
    * cumulative drift of any held position is kept below its TP
      distance; long same-direction holds are short (<= ~60 bars).

    Meta allocation (Instrument.allocation_schedule) steps down one
    weight per day: 1.0 / 0.5 / 0.1 / 0.0.
    """
    start = pd.Timestamp("2024-01-01 00:00:00")   # a Monday
    frames: list[pd.DataFrame] = []
    price = 1.10000

    def day(closes: list[float]):
        nonlocal price
        if len(closes) != 1440:
            raise AssertionError(f"day needs 1440 bars, got {len(closes)}")
        t0 = start + pd.Timedelta(days=len(frames))
        frames.append(_bars(closes, t0))
        price = closes[-1]

    seg: list[float] = []

    def zig(n: int, amp: float = AMP, end_up: bool = True) -> None:
        """Zero-drift zig-zag around the current price; phase chosen so
        the LAST bar is an up step (end_up) or a down step."""
        p0 = seg[-1] if seg else price
        base = p0 - amp
        last_up = (n - 1) % 2 == 1
        flip_phase = last_up != end_up
        for k in range(n):
            up = (k % 2 == 1) != flip_phase
            seg.append(base + (amp if up else -amp))

    def qz(n: int, amp: float = AMP) -> None:
        zig(n, amp, end_up=True)

    def ramp(step: float, n: int) -> None:
        p0 = seg[-1] if seg else price
        seg.extend(p0 + step * (k + 1) for k in range(n))

    def zz(drift: float, n: int = 12, amp: float = 2e-4) -> None:
        p = seg[-1] if seg else price
        for k in range(n):
            p = p + drift + (amp if k % 2 else -amp)
            seg.append(p)

    def flip(sign: float, step: float = 2e-4, bars: int = 3) -> None:
        ramp(sign * step, bars)

    def crash(sign: float, mag: float = 3e-3) -> None:
        ramp(sign * mag, 1)

    def clock() -> str:
        m = len(seg) % 1440
        return f"{m // 60:02d}:{m % 60:02d}"

    def pad_day() -> None:
        need = 1440 - len(seg)
        if need < 0:
            raise AssertionError(f"day overflow: {len(seg)} bars")
        if need:
            seg.extend([seg[-1]] * need)

    # ------------------------------- DAY 1 (Mon) -- meta weight 1.0 -----
    zig(420)                          # 00:00-06:59 warmup healthy tape
    zig(45)                           # 07:00-07:44 primer, ends at a top
    ramp(6e-5, 15)                    # 07:45-07:59 pre-open ramp: breakout
    #   fires OUTSIDE session = session-VETO cluster; state +1 carried
    # 08:00 session opens: LONG #1 enters (first-valid-minute entry)
    zz(+1.5e-5)                       # 08:00-08:11
    crash(-1.0)                       # 08:12 SL on LONG #1; gate flips;
    #   SHORT #2 enters AFTER the crash (long->short transition)
    qz(25, 2.5e-4)                    # crash bar leaves channel
    flip(+1.0, 3e-4, 2)               # SHORT #2 signal_exit -> LONG #3
    # chained type-F scenes (each: ride + qz + flip): every scene is one
    #   signal_exit exit + one entry
    for _ in range(2):                # LONG #3, SHORT #4
        zz(+1.5e-5)
        qz(15, 2e-4)
        flip(-1.0)
        zz(-1.5e-5)
        qz(15, 2e-4)
        flip(+1.0)
    zz(+1.5e-5)                       # LONG #5 ride
    qz(20, 2e-4)                      # EMA gap decays to drift-scale so
    ramp(2.8e-3, 1)                   #   the crash flips the gate;
    #   take_profit on LONG #5
    crash(-1.0, 4e-3)                 # closes post-TP re-entry (SL); flips
    #   -> SHORT #6 enters after the crash
    qz(25, 2.5e-4)
    flip(+1.0, 3e-4, 2)               # SHORT #6 signal_exit -> LONG #7
    for _ in range(3):                # chained type-F scenes
        zz(+1.5e-5)
        qz(15, 2e-4)
        flip(-1.0)
        zz(-1.5e-5)
        qz(15, 2e-4)
        flip(+1.0)
    zz(+1.5e-5, 20)                   # wind toward the boundary scene
    qz(12, 2e-4)
    flip(-1.0, 1.5e-4, 3)             # -> SHORT #16 (boundary hold book;
    #   small flip keeps delta shallow so the snap can flip the gate)
    need = 953 - (len(seg) % 1440)    # hold until the boundary scene at
    if need < 0 or need > 55:         #   ~15:53 (short hold: favorable
        raise AssertionError(f"day-1 boundary scene misaligned: "
                             f"clock={len(seg) % 1440} need={need}")
    zz(-6e-6, need, 3e-4)             #   travel stays far below TP);
    #   fires on the held side are no-ops
    ramp(-1.5e-4, 2)                  # dip (state already -1); snap
    ramp(2e-4, 4)                     #   fires breakout_up in the LAST
    #   VALID MINUTES -> SHORT signal_exit, LONG #17 enters near 15:58,
    #   then the 16:00 flatten closes it (session-boundary entry + exit)
    pad_day()
    day(seg)
    seg = []

    # ------------------------------- DAY 2 (Tue) -- meta weight 0.5 -----
    zig(455)                          # 00:00-07:34 healthy tape
    p0 = seg[-1]
    for k in range(20):               # 07:35-07:54 +-700-pip whipsaws:
        p0 = p0 + (0.0700 if k % 2 == 0 else -0.0700)
        seg.append(p0)                #   ATR ~ 0.08 pre-open
    ramp(-5e-4, 3)                    # 07:55-07:57 breakdown fires while
    #   ATR huge -> Risk BELOW_MIN rejections at the open; ATR decays on
    #   the tape: risk passes but Meta 0.5 floor-DROPs; when ATR decays
    #   to ~2.5e-3 the half size clears the volume grid -> SHORT #1 SENDs
    qz(22, 3.5e-4)                    # Risk -> Meta ladder plays out
    qz(20, 3.5e-4)                    # crash-scale bars leave channel
    flip(+1.0, 3e-4, 2)               # SHORT #1 signal_exit -> LONG #2
    for _ in range(6):                # chained type-F scenes
        zz(+1.5e-5)
        qz(15, 2e-4)
        flip(-1.0)
        zz(-1.5e-5)
        qz(15, 2e-4)
        flip(+1.0)
    zz(+1.5e-5)
    qz(15, 2e-4)
    flip(-1.0)
    zz(-1.5e-5)
    qz(15, 2e-4)
    flip(+1.0)                        # one more scene pair -> ~15:15
    zz(+1.5e-5)                       # final LONG ride
    need = 960 - (len(seg) % 1440)    # hold (drift stays below the TP
    if need < 0 or need > 80:         #   distance) -> 16:00 flatten
        raise AssertionError("day-2 final hold misaligned")
    zz(+1.5e-5, need, 2e-4)
    pad_day()
    day(seg)
    seg = []

    # ------------------------------- DAY 3 (Wed) -- meta weight 0.1 -----
    zig(420)                          # 00:00-06:59 healthy tape
    ramp(4e-5, 30)                    # 07:00-07:29 pre-open ramp up:
    #   breakout fires VETOED; trend_up established
    ramp(-1.5e-4, 10)                 # 07:30-07:39 V down: RSI < 30
    ramp(1.3e-4, 20)                  # 07:40-07:59 snap: escape-up edge
    #   PRE-OPEN (RSI 30-margin record); breakout on the snap also fires
    #   -> session-VETOED fire, state +1 carried to the open
    # 08:00 LONG #1 enters (escape-scene entry); small ATR regime
    zz(+1e-5, 10, 1e-4)
    qz(20, 5e-5)                      # EMA gap decays toward drift-scale
    ramp(1.5e-3, 1)                   # take_profit on LONG #1
    crash(-1.0, 5e-3)                 # closes post-TP re-entry; flips;
    #   SHORT #2 attempts while ATR > 5e-4: Meta 0.1 floor-DROP events,
    #   then SEND (scaled to a tenth, 0.01) once ATR decays
    qz(25, 1e-4)                      # ladder + crash bar leaves channel
    flip(+1.0, 1.5e-4, 2)             # SHORT #2 signal_exit -> LONG #3
    for _ in range(8):                # small-regime type-F scenes
        zz(+1e-5, 10, 1e-4)
        qz(10, 5e-5)
        flip(-1.0, 1e-4)
        zz(-1e-5, 10, 1e-4)
        qz(10, 5e-5)
        flip(+1.0, 1e-4)
    zz(+1e-5, 10, 1e-4)               # one more scene, cut short: the
    qz(10, 5e-5)                      #   SHORT book is still open when
    flip(-1.0, 1e-4)                  #   the session flattens
    zz(-1e-5, 10, 1e-4)
    qz(10, 5e-5)
    pad_day()
    day(seg)
    seg = []

    # ------------------------------- DAY 4 (Thu) -- meta weight 0.0 -----
    zig(420, end_up=False)            # 00:00-06:59 healthy tape
    ramp(-4e-5, 50)                   # 07:00-07:49 downtrend: pre-open
    #   breakdown fires VETOED; trend_dn established
    ramp(6e-5, 25)                    # 07:50-08:14 rally: RSI > 70;
    #   breakout fires (pre-open VETOED, in-session attempts DROPPED by
    #   Meta weight 0.0 -> signal present, zero positions all day)
    ramp(-1.2e-4, 8)                  # 08:15-08:22 fade phase 1
    ramp(-4e-6, 20)                   # 08:23-08:42 fade phase 2 (slow):
    #   RSI crosses 70 downward with trend_dn -> escape-down fire (RSI
    #   70-margin record) -> SHORT attempt DROPPED
    ramp(-8e-5, 15)                   # 08:39-08:53 extend: RSI < 30
    ramp(2.5e-4, 6)                   # 08:54-08:59 snap: RSI crosses 30
    #   upward while trend_dn still -> escape-up edge fires but the
    #   trend gate blocks it: AND-gate veto (edge recorded, no state)
    ramp(2.5e-4, 12)                  # gate flips up, breakout fires ->
    #   LONG attempt DROPPED
    qz(30)                            # healthy tape
    ramp(1.5e-5, 25)                  # ramp (state +1 held; attempts
    p0 = seg[-1]                      #   DROPPED)
    seg.append(p0 + 1e-5)             # ONE-TICK breakout: close =
    #   channel top + 1 tick while trend_up (distance_to_boundary =
    #   1 tick; entry attempt DROPPED)
    ramp(1.5e-5, 25)                  # ramp on
    zig(60)                           # wind down
    pad_day()
    day(seg)
    seg = []

    df = pd.concat(frames)
    df.index.name = "time"
    for col in ("open", "high", "low", "close"):
        df[col] = np.round(df[col].to_numpy(dtype=float), 5)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


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
    ins = Instrument(symbol=SYMBOL, strategy=GOLD2_STRATEGY_ID, df=df,
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
             # every remaining trace-affecting run input (semantic
             # dependency audit, mission §3): defaults pinned here so a
             # future change cannot silently leave the hash unchanged
             "warmup_bars": 0,
             "clock": "DayClock default (midnight server-day roll)",
             "geometry": {"sl_atr": SL_ATR, "tp_atr": TP_ATR,
                          "atr_period": ATR_PERIOD},
             "strategy": {"fast": FAST, "slow": SLOW,
                          "rsi_period": RSI_PERIOD,
                          "rsi_oversold": RSI_OVERSOLD,
                          "rsi_overbought": RSI_OVERBOUGHT,
                          "channel": CHANNEL, "session": SESSION},
             "meta_schedule": [[str(ts), w] for ts, w in META_SCHEDULE]}
    return _sha_bytes(json.dumps(canon, sort_keys=True).encode())


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(GOLD2_DIR))
    ap.add_argument("--git-commit", default=None)
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    df = build_fixture()
    csv_text = df.to_csv(float_format="%.10f")

    spec = parse_file(GOLD2_SPEC)
    ref_sig = gold2_multifactor(df)
    dsl_sig = desired_positions(spec, df)
    raw_dsl = desired_positions(spec, df, apply_filters=False)
    sig_equal = bool((ref_sig.to_numpy() == dsl_sig.to_numpy()).all())

    res_ref = _engine_run(df, ref_sig)
    res_dsl = _engine_run(df, dsl_sig)
    trade_match = res_ref.trades.equals(res_dsl.trades)

    # ------------- scenario scan ----------------------------------------
    bd = boundary_distances(df)
    esc_up = ((bd["rsi_prev"] < RSI_OVERSOLD)
              & (bd["rsi"] >= RSI_OVERSOLD))
    esc_dn = ((bd["rsi_prev"] > RSI_OVERBOUGHT)
              & (bd["rsi"] <= RSI_OVERBOUGHT))
    brk_up = np.zeros(len(df), dtype=bool)
    brk_dn = np.zeros(len(df), dtype=bool)
    for i in range(1, len(df)):
        if not np.isnan(bd["hh_prev"][i]):
            brk_up[i] = bd["close"][i] > bd["hh_prev"][i]
        if not np.isnan(bd["ll_prev"][i]):
            brk_dn[i] = bd["close"][i] < bd["ll_prev"][i]
    in_s = bd["in_session"]

    fires = []       # (bar, kind, in_session) for pre-filter edges
    raw = raw_dsl.to_numpy()
    for i in range(1, len(df)):
        if raw[i] == raw[i - 1]:
            continue
        if raw[i] == 0:
            continue
        kind = []
        if esc_up[i]:
            kind.append("rsi_escape_up")
        if esc_dn[i]:
            kind.append("rsi_escape_down")
        if brk_up[i]:
            kind.append("breakout_up")
        if brk_dn[i]:
            kind.append("breakout_down")
        fires.append({"bar": i, "time": df.index[i].isoformat(),
                      "side": "long" if raw[i] == 1 else "short",
                      "kinds": sorted(kind), "in_session": bool(in_s[i]),
                      "rsi": None if np.isnan(bd["rsi"][i])
                      else round(float(bd["rsi"][i]), 6),
                      "rsi_to_oversold": None if np.isnan(bd["rsi"][i])
                      else round(float(bd["rsi"][i] - RSI_OVERSOLD), 6),
                      "rsi_to_overbought": None if np.isnan(bd["rsi"][i])
                      else round(float(RSI_OVERBOUGHT - bd["rsi"][i]), 6),
                      "minutes_to_session_start":
                          int(bd["minutes_to_session_start"][i]),
                      "minutes_to_session_end":
                          int(bd["minutes_to_session_end"][i])})

    if args.report_only:
        trs = [{"entry": str(t["entry_time"]), "side": t["side"],
                "lots": round(float(t["lots"]), 4),
                "exit": str(t["exit_time"]), "reason": t["exit_reason"]}
               for _, t in res_ref.trades.iterrows()]
        escs = [{"t": df.index[i].isoformat(),
                 "kind": "esc_up" if esc_up[i] else "esc_dn",
                 "rsi": round(float(bd["rsi"][i]), 4),
                 "in_session": bool(in_s[i])}
                for i in np.where(esc_up | esc_dn)[0]]
        brks = [{"t": df.index[i].isoformat(),
                 "side": "up" if brk_up[i] else "dn",
                 "ticks": round(float((bd["close"][i] - bd["hh_prev"][i])
                                      if brk_up[i] else
                                      (bd["ll_prev"][i] - bd["close"][i])
                                      ) / 1e-5, 2),
                 "in_session": bool(in_s[i])}
                for i in np.where(brk_up | brk_dn)[0]]
        print(json.dumps({
            "bars": len(df), "trades": len(res_ref.trades),
            "signal_parity": sig_equal, "trade_parity": trade_match,
            "exit_reasons": sorted(set(res_ref.trades["exit_reason"])),
            "sides": res_ref.trades["side"].value_counts().to_dict(),
            "equity_end": round(float(res_ref.equity.iloc[-1]), 2),
            "trade_rows": trs, "escapes": escs[:60],
            "breakouts": brks[:60],
            "vetoed_fires": [f for f in fires if not f["in_session"]][:30],
        }, indent=1, default=str))
        return 0

    # ------------- traces -------------------------------------------------
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    ema_f = ema_fn(close, FAST)
    ema_s = ema_fn(close, SLOW)
    rsi_v = rsi_fn(close, RSI_PERIOD)
    atr_v = atr_fn(high, low, close, ATR_PERIOD)

    def trace(sig_series: pd.Series, res, label: str) -> dict:
        bars = []
        for i, (ts, row) in enumerate(df.iterrows()):
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
                "rsi14": None if np.isnan(rsi_v[i])
                else round(float(rsi_v[i]), 10),
                "atr14": None if np.isnan(atr_v[i])
                else round(float(atr_v[i]), 10),
                "desired_position": int(sig_series.iloc[i]),
            })
        tr = []
        for _, t in res.trades.iterrows():
            tr.append({
                "strategy_id": GOLD2_STRATEGY_ID,
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

    # ------------- expected execution (sizer + risk veto + meta) ---------
    # The engine's sizing reference ``basis`` is the CURRENT equity at
    # the previous close: it is re-marked at the end of EVERY bar
    # (engine.py: ``basis = float(equity[i])``).  An entry triggered by
    # the signal on bar i is therefore sized on ``equity[i]`` — the
    # signal bar's closing equity.  Recompute with exactly that series
    # (never hand-typed).
    spec_obj = SymbolSpec(**BROKER_SPEC)
    s = ref_sig.to_numpy()
    eq = res_ref.equity
    basis_at = eq.to_numpy()
    exec_rows = []
    veto_count = 0

    def build_row(i: int, entry_kind: str) -> dict:
        """Sizing expectation for an entry whose signal sits on bar i.

        The engine enters at bar i+1 and sizes on atr[(i+1) - 1] =
        atr[i] (engine.py size_lots) against basis = equity[i] (the
        signal bar's closing equity), exactly as the engine passes it.
        """
        side = "long" if s[i] == 1 else "short"
        a_sig = atr_v[i]
        dist = SL_ATR * float(a_sig) if np.isfinite(a_sig) else None
        r = (size_position(spec_obj, mode="risk_percent_equity",
                           equity=float(basis_at[i]), stop_distance=dist,
                           value=RISK_PERCENT) if dist else None)
        return {"i": i, "side": side, "dist": dist, "r": r,
                "entry_kind": entry_kind}

    for i in range(1, len(df)):
        if s[i] == 0 or s[i] == s[i - 1]:
            continue
        pre = build_row(i, "signal_transition")
        i, side, dist, r = pre["i"], pre["side"], pre["dist"], pre["r"]
        kinds = []
        if esc_up[i]:
            kinds.append("rsi_escape_up")
        if esc_dn[i]:
            kinds.append("rsi_escape_down")
        if brk_up[i]:
            kinds.append("breakout_up")
        if brk_dn[i]:
            kinds.append("breakout_down")
        row = {
            "signal_time": df.index[i].isoformat(),
            "side": side,
            "entry_kind": "signal_transition",
            "fire_kinds": sorted(kinds),
            "distance_to_boundary": {
                "rsi_to_oversold": None if np.isnan(bd["rsi"][i])
                else round(float(bd["rsi"][i] - RSI_OVERSOLD), 6),
                "rsi_to_overbought": None if np.isnan(bd["rsi"][i])
                else round(float(RSI_OVERBOUGHT - bd["rsi"][i]), 6),
                "rsi_prev_to_oversold": None if np.isnan(bd["rsi_prev"][i])
                else round(float(bd["rsi_prev"][i] - RSI_OVERSOLD), 6),
                "rsi_prev_to_overbought": None
                if np.isnan(bd["rsi_prev"][i])
                else round(float(RSI_OVERBOUGHT - bd["rsi_prev"][i]), 6),
                "minutes_to_session_start":
                    int(bd["minutes_to_session_start"][i]),
                "minutes_to_session_end":
                    int(bd["minutes_to_session_end"][i]),
                "price_margin_ticks_vs_channel":
                    None if (np.isnan(bd["hh_prev"][i])
                             and np.isnan(bd["ll_prev"][i]))
                    else round(float(
                        (bd["close"][i] - bd["hh_prev"][i])
                        if not np.isnan(bd["hh_prev"][i])
                        and bd["close"][i] > bd["hh_prev"][i]
                        else (bd["ll_prev"][i] - bd["close"][i])
                        if not np.isnan(bd["ll_prev"][i])
                        and bd["close"][i] < bd["ll_prev"][i]
                        else 0.0) / 1e-5, 4),
            },
            "atr_signal_bar": None if np.isnan(atr_v[i])
            else round(float(atr_v[i]), 10),
            "stop_distance": None if dist is None else round(dist, 10),
            "sizing_basis": round(float(basis_at[i]), 6),
            "risk": (None if r is None else
                     {"approved_lots": round(float(r.lots), 6),
                      "reason": r.reason,
                      "rejected": bool(r.rejected)}),
            "meta": {},
        }
        if r is not None and not r.rejected and r.lots > 0:
            for w in META_WEIGHTS:
                lots = float(r.lots) * w
                final = np.floor(lots / BROKER_SPEC["volume_step"]
                                 + 1e-9) * BROKER_SPEC["volume_step"]
                if final < BROKER_SPEC["volume_min"] or final > float(
                        r.lots) + 1e-12:
                    row["meta"][str(w)] = {"final_lots": 0.0,
                                           "action": "DROP"}
                else:
                    row["meta"][str(w)] = {"final_lots": round(final, 6),
                                           "action": "SEND"}
            below_w = round(BROKER_SPEC["volume_min"] / float(r.lots)
                            / 2.0, 6)
            lots_b = float(r.lots) * below_w
            final_b = np.floor(lots_b / BROKER_SPEC["volume_step"]
                               + 1e-9) * BROKER_SPEC["volume_step"]
            row["meta"]["below_min"] = {
                "weight": below_w,
                "final_lots": round(final_b, 6),
                "action": "DROP" if final_b < BROKER_SPEC["volume_min"]
                else "SEND"}
        elif r is not None and r.rejected:
            veto_count += 1
        exec_rows.append(row)

    # Persistence re-entries: desired stayed on the same non-zero side
    # while the previous book was stopped out — the engine re-enters at
    # the next bar (closed-bar contract: the signal still says "be in").
    # Recompute their sizing expectations with the same canonical path.
    tr_df = res_ref.trades
    for _, t in tr_df.iterrows():
        j = df.index.get_loc(pd.Timestamp(t["entry_time"]))
        i = j - 1                                  # signal bar
        if i < 1 or s[i] == 0 or s[i] != s[i - 1]:
            continue                               # covered above
        pre = build_row(i, "persistence_reentry")
        row = {
            "signal_time": df.index[i].isoformat(),
            "side": pre["side"],
            "entry_kind": pre["entry_kind"],
            "fire_kinds": [],
            "distance_to_boundary": {},
            "atr_signal_bar": None if np.isnan(atr_v[i])
            else round(float(atr_v[i]), 10),
            "stop_distance": None if pre["dist"] is None
            else round(pre["dist"], 10),
            "sizing_basis": round(float(basis_at[i]), 6),
            "risk": (None if pre["r"] is None else
                     {"approved_lots": round(float(pre["r"].lots), 6),
                      "reason": pre["r"].reason,
                      "rejected": bool(pre["r"].rejected)}),
            "meta": {},
        }
        r = pre["r"]
        if r is not None and not r.rejected and r.lots > 0:
            for w in META_WEIGHTS:
                lots = float(r.lots) * w
                final = np.floor(lots / BROKER_SPEC["volume_step"]
                                 + 1e-9) * BROKER_SPEC["volume_step"]
                if final < BROKER_SPEC["volume_min"] or final > float(
                        r.lots) + 1e-12:
                    row["meta"][str(w)] = {"final_lots": 0.0,
                                           "action": "DROP"}
                else:
                    row["meta"][str(w)] = {"final_lots": round(final, 6),
                                           "action": "SEND"}
        exec_rows.append(row)
    exec_rows.sort(key=lambda r: r["signal_time"])
    for r in exec_rows:
        r.pop("i", None)

    # ------------- manifest + provenance ---------------------------------
    (out / "gold2_fixture.csv").write_text(csv_text)
    fixture_hash = _sha_bytes(csv_text.encode())
    manifest = {
        "gold_standard": "AEGIS-GOLD-2",
        "provenance_label": GOLD2_LABEL,
        "continuity_disclaimer": (
            "Reconstruction with NEW provenance. This is NOT the "
            "original Gold #2 artifact; no claim is made that the "
            "historical seven trades reproduce. All expected values "
            "were generated by executing the canonical Python reference "
            "and the DSL runtime over the deterministic fixture "
            "(never hand-typed)."),
        "strategy_id": GOLD2_STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "spec_hash": spec.spec_hash,
        "dsl_version": DSL_VERSION,
        "indicator_versions": {
            "EMA": "contract-v1 (indicators.ema, alpha=2/(n+1), SMA seed)",
            "RSI": "contract-v1 (indicators.rsi, Wilder, period 14)",
            "ATR": "contract-v1 (indicators.atr, Wilder, period 14)",
            "HIGHEST/LOWEST": "contract-v1 (rolling window, shift 1 = "
                              "previous 20 closed bars)"},
        "code_version": CODE_VERSION_REF,
        "git_commit": args.git_commit or _git_commit(),
        "python_version": platform.python_version(),
        "dataset_id": "gold2-fixture-m1-2024",
        "dataset_hash": fixture_hash,
        "config_hash": _config_hash(),
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "timezone": TIMEZONE,
        "session": SESSION,
        "cost_config": COSTS,
        "risk_config": {"mode": "risk_percent_equity",
                        "risk_percent": RISK_PERCENT,
                        "equity_start": EQUITY_START},
        "broker_spec": BROKER_SPEC,
        "engine_config": {"mode": MODE_NETTING, "allow_short": True,
                          "allow_signal_exit": True,
                          "sizing_mode": RISK_PERCENT_EQUITY,
                          "sl_atr": SL_ATR, "tp_atr": TP_ATR},
        "seed": 0,
        "signal_timing_contract": {
            "signal_on": "closed bar (shift 1)",
            "action_at": "next bar open (EA: first tick of new bar)",
            "order_type": "market",
            "both_touch_rule": "SL assumed hit first (conservative)",
            "flip_rule": "close opposite (signal_exit); enter next bar",
            "session_rule": "bars outside [08:00, 16:00) flattened; the "
                            "flatten closes open books (signal_exit)"},
        "normalization_rules": {
            "csv_float_format": "%.10f",
            "json": "indent=2, sort_keys=True, trailing newline",
            "price_rounding": "10 decimals in traces; 5-decimal broker "
                              "grid in the fixture",
            "lots_rounding": "6 decimals; broker floor-to-step with the "
                             "1e-9 step-unit dust guard",
            "time": "ISO-8601 naive stamps"},
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest_hash = _sha_bytes((out / "manifest.json").read_bytes())

    (out / "python_trace.json").write_text(
        json.dumps({"manifest_hash": manifest_hash,
                    "signal_timing": manifest["signal_timing_contract"],
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
                    "entries": exec_rows}, indent=2, sort_keys=True)
        + "\n")

    recon = {
        "manifest_hash": manifest_hash,
        "parity_class": "PYTHON_DSL_MQL5_SOURCE_PARITY",
        "parity_disclaimer": (
            "This record proves Python<->DSL trace parity and pins the "
            "MQL5 source-level contracts. It is NOT MT5 runtime parity: "
            "no MetaTrader 5 terminal, Strategy Tester, or broker "
            "environment exists in this sandbox; those legs remain "
            "PENDING_OWNER per the canonical owner protocol."),
        "fields": ["signal_time", "strategy_id", "symbol", "side",
                   "risk_approved", "meta_weight", "requested_lots",
                   "broker_normalized_lots", "fill_volume", "entry_price",
                   "sl", "tp", "position_identifier", "exit_time",
                   "exit_price", "realized_pnl"],
        "python_vs_dsl": "MATCHED" if (sig_equal and trade_match)
                         else "MISMATCH",
        "python_vs_mql5_source": "SOURCE_PARITY",
        "mql5_source_contracts": [
            "closed-bar signals (shift 1), act at next bar open",
            "market orders; single OrderSend path",
            ("RSI zone-escape rule = SignalEngine.EvaluateRsiReversal "
             "(PROVEN_EXACT closure, DECISIONS.md 2026-09-07)"),
            ("session flatten = filters only ever flatten (strategies "
             "propose, filters veto)"),
            "SL-first both-touch rule",
            ("risk sizing floor-to-step with the 1e-9 dust guard; "
             "below-minimum REJECTED in both runtimes"),
            "meta allocation reduce-only, floor-to-step, DROP below min",
        ],
        "python_vs_mt5_tester": "PENDING_OWNER",
        "note": "Python<->DSL proven here; MQL5/MT5 legs require the "
                "owner terminal protocol (docs/MT5_ROUNDTRIP.md "
                "canonical TEN-step sequence).",
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
        "provenance_label": GOLD2_LABEL,
        "fixture_hash_sha256": fixture_hash,
        "spec_hash": spec.spec_hash,
        "config_hash": _config_hash(),
        "git_commit": manifest["git_commit"],
        "python_version": platform.python_version(),
        "builder": "tools/build_gold2_standard.py",
        "test_command": TEST_COMMAND,
        "params": manifest["engine_config"] | {"fast": FAST, "slow": SLOW,
                                               "rsi_period": RSI_PERIOD,
                                               "rsi_oversold": RSI_OVERSOLD,
                                               "rsi_overbought":
                                                   RSI_OVERBOUGHT,
                                               "channel": CHANNEL,
                                               "session": SESSION},
        "artifact_hashes": {
            name: _sha_bytes((out / name).read_bytes())
            for name in ("manifest.json", "gold2_fixture.csv",
                         "python_trace.json", "dsl_trace.json",
                         "expected_execution.json", "reconciliation.json")
        },
        "distance_to_boundary": [
            {"signal_time": r["signal_time"], "side": r["side"],
             "entry_kind": r["entry_kind"], "fire_kinds": r["fire_kinds"],
             **r["distance_to_boundary"]} for r in exec_rows],
        # full pre-filter fire scan (computed, never typed): records
        # every raw-signal edge, whether the session filter vetoed it,
        # and the boundary geometry at that bar (mission §13/§18)
        "signal_fires": [{**f, "vetoed_by_session": not f["in_session"]}
                         for f in fires],
        # every RSI zone-escape EDGE (including no-op edges where the
        # state machine was already positioned) with its boundary
        # distances — the +-0.5/+-1/+-2 margin record (mission §12)
        "rsi_escape_edges": [
            {"time": df.index[i].isoformat(),
             "kind": "escape_up" if esc_up[i] else "escape_down",
             "in_session": bool(in_s[i]),
             "rsi": round(float(bd["rsi"][i]), 6),
             "rsi_prev": round(float(bd["rsi_prev"][i]), 6),
             "distance_to_boundary": {
                 "rsi_to_oversold": round(float(bd["rsi"][i]
                                                - RSI_OVERSOLD), 6),
                 "rsi_to_overbought": round(float(RSI_OVERBOUGHT
                                                  - bd["rsi"][i]), 6),
                 "rsi_prev_to_oversold": round(float(bd["rsi_prev"][i]
                                                     - RSI_OVERSOLD), 6),
                 "rsi_prev_to_overbought": round(float(RSI_OVERBOUGHT
                                                       - bd["rsi_prev"][i]),
                                                 6)}}
            for i in np.where(esc_up | esc_dn)[0]],
        "normalization_rules": manifest["normalization_rules"],
        "continuity_disclaimer": manifest["continuity_disclaimer"],
    }
    (out / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        "label": GOLD2_LABEL,
        "bars": len(df), "trades": len(res_ref.trades),
        "signal_parity": sig_equal, "trade_parity": trade_match,
        "python_vs_dsl": recon["python_vs_dsl"],
        "risk_vetoes": veto_count,
        "manifest_hash": manifest_hash,
        "legs": sorted(set(res_ref.trades["exit_reason"])),
    }, indent=2))
    return 0 if (sig_equal and trade_match) else 1


if __name__ == "__main__":
    raise SystemExit(main())
