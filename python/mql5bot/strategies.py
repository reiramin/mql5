"""mql5bot.strategies — signal generators.

Each strategy maps an OHLC frame to a *desired position* series in
{-1, 0, +1} computed strictly from closed bars. The backtest engine acts on
the desired position one bar later (at the next bar's open), which makes
lookahead bias impossible by construction.

The default parameters, entry logic and SL/TP placement match the
corresponding MQL5 modules under ``mql5/Include/Mql5Bot/Strategies/``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import (
    bollinger,
    donchian,
    ema,
    macd,
    rsi,
)

# --------------------------------------------------------------------------
# Strategies
# --------------------------------------------------------------------------


def ema_crossover(df: pd.DataFrame, p: dict | None = None) -> pd.Series:
    """Trend following: hold long while fast EMA > slow EMA, short while below."""
    p = _params(p, fast=10, slow=30, sl_atr=2.5, tp_atr=4.0)
    f = ema(df["close"].to_numpy(), int(p["fast"]))
    s = ema(df["close"].to_numpy(), int(p["slow"]))
    desired = np.zeros(len(df), dtype=int)
    valid = ~(np.isnan(f) | np.isnan(s))
    desired[valid & (f > s)] = 1
    desired[valid & (f < s)] = -1
    return pd.Series(desired, index=df.index, name="ema_crossover")


def rsi_zone_escape_state(r: np.ndarray, oversold: float,
                          overbought: float) -> np.ndarray:
    """Pure zone-escape state machine — EXACT mirror of the EA's
    ``EvaluateRsiReversal`` semantics (Reality Gate §4 closure,
    DECISIONS.md 2026-09-07 final; classification PROVEN_EXACT):

    * zones are STRICT: oversold = r < oversold, overbought = r >
      overbought; exact ties (r == line) are OUTSIDE the zone;
    * escape from oversold   = (r_prev < os) and (r >= os)  -> dir +1;
    * escape from overbought = (r_prev > ob) and (r <= ob)  -> dir -1;
    * the escaped direction is CARRIED (EA ``m_state``): it persists
      through later bars;
    * the OUTPUT direction is the carried state gated by the CURRENT
      zone: neutral band (os <= r <= ob, inclusive) -> carried value;
      inside an extreme zone -> 0 (stand aside) while the carried state
      is preserved for the next neutral bar (EA: sig.direction = 0 but
      m_state.emaDir keeps the escape);
    * NaN on either sample -> invalid (EA returns an invalid signal, no
      action; here output 0). On RSI this only occurs during warmup,
      where no position exists, so observable behaviour is identical."""
    r = np.asarray(r, dtype=float)
    out = np.zeros(len(r), dtype=int)
    carried = 0  # EA m_state.emaDir
    for i in range(1, len(r)):
        rp, rc = r[i - 1], r[i]
        if np.isnan(rp) or np.isnan(rc):
            continue  # EA: invalid signal; output stays 0
        if (rp < oversold) and (rc >= oversold):
            carried = 1
        elif (rp > overbought) and (rc <= overbought):
            carried = -1
        if oversold <= rc <= overbought:
            out[i] = carried
        # else: inside an extreme zone -> output 0, carried preserved
    return out


def rsi_reversal(df: pd.DataFrame, p: dict | None = None) -> pd.Series:
    """Mean reversion: long when RSI escapes out of oversold, short when
    it escapes out of overbought. Hold through the neutral band; stand
    aside at the extremes. Zone membership and escape semantics are the
    EA's (SignalEngine.EvaluateRsiReversal), mirrored exactly —
    PROVEN_EXACT over the full (prev, cur) tie-inclusive truth table
    (tests/test_indicator_semantics.py)."""
    p = _params(p, period=14, oversold=30.0, overbought=70.0, sl_atr=2.0, tp_atr=3.0)
    r = rsi(df["close"].to_numpy(), int(p["period"]))
    desired = rsi_zone_escape_state(r, float(p["oversold"]),
                                    float(p["overbought"]))
    return pd.Series(desired, index=df.index, name="rsi_reversal")


def donchian_breakout(df: pd.DataFrame, p: dict | None = None) -> pd.Series:
    """Breakout: long when close exceeds the previous N-bar high, short when
    it falls below the previous N-bar low. The position persists until the
    opposite side breaks (a classic turtle channel)."""
    p = _params(p, period=20, sl_atr=2.0, tp_atr=5.0)
    upper, lower = donchian(
        df["high"].to_numpy(), df["low"].to_numpy(), int(p["period"])
    )
    close = df["close"].to_numpy()
    desired = np.zeros(len(df), dtype=int)
    state = 0
    for i in range(len(df)):
        if np.isnan(upper[i]):
            desired[i] = 0
            continue
        if close[i] > upper[i]:
            state = 1
        elif close[i] < lower[i]:
            state = -1
        desired[i] = state
    return pd.Series(desired, index=df.index, name="donchian_breakout")


def bollinger_reversal(df: pd.DataFrame, p: dict | None = None) -> pd.Series:
    """Mean reversion: fade extremes. Long when the close closes below the
    lower Bollinger band, short when it closes above the upper band. Flat
    while the close is inside the bands."""
    p = _params(p, period=20, dev=2.0, sl_atr=2.5, tp_atr=3.5)
    mid, upper, lower = bollinger(
        df["close"].to_numpy(), int(p["period"]), float(p["dev"])
    )
    close = df["close"].to_numpy()
    desired = np.zeros(len(df), dtype=int)
    valid = ~(np.isnan(mid))
    desired[valid & (close < lower)] = 1
    desired[valid & (close > upper)] = -1
    return pd.Series(desired, index=df.index, name="bollinger_reversal")


def macd_momentum(df: pd.DataFrame, p: dict | None = None) -> pd.Series:
    """Momentum: long while MACD line > signal line, short while below."""
    p = _params(p, fast=12, slow=26, signal=9, sl_atr=2.5, tp_atr=4.0)
    line, sig, _hist = macd(
        df["close"].to_numpy(), int(p["fast"]), int(p["slow"]), int(p["signal"])
    )
    desired = np.zeros(len(df), dtype=int)
    valid = ~(np.isnan(line) | np.isnan(sig))
    desired[valid & (line > sig)] = 1
    desired[valid & (line < sig)] = -1
    return pd.Series(desired, index=df.index, name="macd_momentum")


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

STRATEGIES = {
    "ema_crossover": (ema_crossover, {"fast": 10, "slow": 30, "sl_atr": 2.5, "tp_atr": 4.0}),
    "rsi_reversal": (
        rsi_reversal,
        {"period": 14, "oversold": 30.0, "overbought": 70.0,
         "sl_atr": 2.0, "tp_atr": 3.0},
    ),
    "donchian_breakout": (
        donchian_breakout,
        {"period": 20, "sl_atr": 2.0, "tp_atr": 5.0},
    ),
    "bollinger_reversal": (
        bollinger_reversal,
        {"period": 20, "dev": 2.0, "sl_atr": 2.5, "tp_atr": 3.5},
    ),
    "macd_momentum": (
        macd_momentum,
        {"fast": 12, "slow": 26, "signal": 9, "sl_atr": 2.5, "tp_atr": 4.0},
    ),
}

_DESCRIPTIONS = {
    "ema_crossover": "Trend — hold with fast/slow EMA alignment",
    "rsi_reversal": "Mean reversion — buy RSI escapes from oversold, sell from overbought",
    "donchian_breakout": "Breakout — turtle channel on prior N-bar high/low",
    "bollinger_reversal": "Mean reversion — fade closes outside Bollinger bands",
    "macd_momentum": "Momentum — hold with MACD/signal alignment",
}

# Declared strategy versions (research-versioning seed, plan Phase 17 will
# formalise the bump policy): bump the entry whenever the strategy's
# behaviour changes; anything not declared here reports "undeclared".
STRATEGY_VERSIONS = {name: "1.0.0" for name in STRATEGIES}


def list_strategies() -> list[dict]:
    out = []
    for name, (fn, defaults) in STRATEGIES.items():
        out.append(
            {
                "name": name,
                "description": _DESCRIPTIONS[name],
                "defaults": defaults,
                "family": fn.__doc__.strip().splitlines()[0] if fn.__doc__ else "",
                "version": STRATEGY_VERSIONS.get(name, "undeclared"),
            }
        )
    return out


def get_strategy(name: str):
    if name not in STRATEGIES:
        raise KeyError(
            f"unknown strategy {name!r}; available: {sorted(STRATEGIES)}"
        )
    return STRATEGIES[name][0]


def default_params(name: str) -> dict:
    if name not in STRATEGIES:
        raise KeyError(f"unknown strategy {name!r}")
    return dict(STRATEGIES[name][1])


def signal(df: pd.DataFrame, name: str, params: dict | None = None) -> pd.Series:
    """Convenience wrapper: desired-position series for a strategy."""
    fn = get_strategy(name)
    merged = default_params(name)
    if params:
        merged.update(params)
    return fn(df, merged)


def _params(p: dict | None, **defaults) -> dict:
    merged = dict(defaults)
    if p:
        merged.update(p)
    return merged
