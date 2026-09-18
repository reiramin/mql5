"""mql5bot.gold2_reference — Gold #2 reconstructed reference strategy.

GOLD_2_RECONSTRUCTED_NEW_PROVENANCE.  This module is the Python-side
reference implementation of the Gold #2 multi-factor strategy
(``examples/strategies/gold2_multifactor.json``).  It is deliberately
written as a plain, reviewable transcription of the DSL spec so that the
Python↔DSL trace parity recorded in ``artifacts/gold_2/`` is a real
two-implementation check, not a shared-code tautology.

Provenance honesty rules (mission §7–§13):

* This is NOT "the original Gold #2".  The historical Gold #2 artifact
  was lost; what exists here is a RECONSTRUCTION with NEW provenance.
  No claim is made that the historical seven trades reproduce.
* Expected values are never hand-typed: they are produced by running
  this reference (and the DSL runtime) over the deterministic fixture
  via ``tools/build_gold2_standard.py``.

Signal contract (all closed-bar, causal; act at next bar open):

* trend gate      ema_fast(8) > ema_slow(21)  (up) / <  (down)
* RSI trigger     zone-escape exactly as the EA's
                  ``EvaluateRsiReversal`` (PROVEN_EXACT closure,
                  DECISIONS.md 2026-09-07): long escape = prev RSI < 30
                  strictly, now >= 30; short escape = prev RSI > 70
                  strictly, now <= 70.
* breakout branch close above the 20-bar high of the PREVIOUS 20 closed
                  bars (long) / below the 20-bar low (short).
* entry           AND(trend gate, OR(RSI escape, breakout))
* signal exit     long: ema_fast < ema_slow; short: ema_fast > ema_slow
* session filter  [08:00, 16:00) — start-inclusive, end-exclusive;
                  bars outside are FLAT (filters only ever flatten).
* geometry        ATR(14) SL 2.0 / TP 3.0 (recorded in the DSL spec).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import ema, highest, lowest, rsi

GOLD2_STRATEGY_ID = "gold2_multifactor"
GOLD2_LABEL = "GOLD_2_RECONSTRUCTED_NEW_PROVENANCE"

# --- parameters (mirrored exactly in the DSL spec) ----------------------
FAST = 8
SLOW = 21
RSI_PERIOD = 14
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
CHANNEL = 20
SESSION_START_MIN = 8 * 60          # 08:00 inclusive
SESSION_END_MIN = 16 * 60           # 16:00 exclusive


def _session_mask(idx: pd.DatetimeIndex) -> np.ndarray:
    """[08:00, 16:00) — same semantics as dsl.runtime._apply_filters:
    minutes >= start and minutes < end."""
    minutes = idx.hour.to_numpy() * 60 + idx.minute.to_numpy()
    return (minutes >= SESSION_START_MIN) & (minutes < SESSION_END_MIN)


def gold2_multifactor(df: pd.DataFrame, p: dict | None = None) -> pd.Series:
    """Desired-position series in {-1, 0, +1} — Gold #2 reference.

    ``p`` is accepted for registry-shape compatibility; the parameters
    are frozen constants of the reconstruction (any override raises).
    """
    if p:
        unknown = set(p) - {"fast", "slow", "rsi_period", "channel"}
        if unknown:
            raise ValueError(f"gold2 parameters are frozen: {unknown}")
        if (p.get("fast", FAST), p.get("slow", SLOW),
                p.get("rsi_period", RSI_PERIOD),
                p.get("channel", CHANNEL)) != (FAST, SLOW, RSI_PERIOD,
                                               CHANNEL):
            raise ValueError("gold2 parameters are frozen constants of "
                             "the reconstruction and may not change")

    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(df)

    ema_f = ema(close, FAST)
    ema_s = ema(close, SLOW)
    r = rsi(close, RSI_PERIOD)
    r_prev = np.full(n, np.nan)
    r_prev[1:] = r[:-1]                      # shift-1 closed bar
    hh = highest(high, CHANNEL)              # includes current bar…
    ll = lowest(low, CHANNEL)
    hh_prev = np.full(n, np.nan)             # …so shift 1 excludes it
    ll_prev = np.full(n, np.nan)
    hh_prev[1:] = hh[:-1]
    ll_prev[1:] = ll[:-1]

    trend_up = ema_f > ema_s                 # NaN-safe: False on NaN
    trend_dn = ema_f < ema_s
    esc_up = (r_prev < RSI_OVERSOLD) & (r >= RSI_OVERSOLD)
    esc_dn = (r_prev > RSI_OVERBOUGHT) & (r <= RSI_OVERBOUGHT)
    brk_up = close > hh_prev
    brk_dn = close < ll_prev

    long_fire = trend_up & (esc_up | brk_up)
    short_fire = trend_dn & (esc_dn | brk_dn)
    exit_long = ema_f < ema_s
    exit_short = ema_f > ema_s

    desired = np.zeros(n, dtype=int)
    state = 0
    for i in range(n):
        if long_fire[i]:
            state = 1
        elif short_fire[i]:
            state = -1
        elif (state == 1 and exit_long[i]) or (state == -1
                                               and exit_short[i]):
            state = 0
        desired[i] = state

    desired[~_session_mask(df.index)] = 0    # filters only ever flatten
    return pd.Series(desired, index=df.index, name=GOLD2_STRATEGY_ID)


def boundary_distances(df: pd.DataFrame) -> dict:
    """Per-bar boundary geometry used by the provenance record.

    Everything is COMPUTED from the fixture + canonical indicators —
    nothing is hand-typed (mission §12)."""
    close = df["close"].to_numpy(dtype=float)
    r = rsi(close, RSI_PERIOD)
    r_prev = np.full(len(df), np.nan)
    r_prev[1:] = r[:-1]
    hh = highest(df["high"].to_numpy(dtype=float), CHANNEL)
    ll = lowest(df["low"].to_numpy(dtype=float), CHANNEL)
    hh_prev = np.full(len(df), np.nan)
    ll_prev = np.full(len(df), np.nan)
    hh_prev[1:] = hh[:-1]
    ll_prev[1:] = ll[:-1]
    minutes = df.index.hour.to_numpy() * 60 + df.index.minute.to_numpy()
    to_start = minutes - SESSION_START_MIN
    to_end = SESSION_END_MIN - minutes
    return {
        "rsi": r, "rsi_prev": r_prev,
        "hh_prev": hh_prev, "ll_prev": ll_prev,
        "close": close,
        "minutes_to_session_start": to_start,   # negative = before open
        "minutes_to_session_end": to_end,       # negative = after close
        "in_session": _session_mask(df.index),
    }
