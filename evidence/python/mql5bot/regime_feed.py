"""mql5bot.regime_feed — causal, deterministic regime snapshots for Meta
decisions (meta-realism mission, Phase 7).

Seven labels (contract): TREND_UP, TREND_DOWN, RANGE, HIGH_VOL, LOW_VOL,
TRANSITION, UNKNOWN.

Causality: a snapshot at ``as_of`` consumes bars STRICTLY BEFORE
``as_of`` (the decision bar's own open/close never influence the label —
same exclusivity as the as-of statistics).  The label is a pure function
of the price series prefix: same prefix ⇒ same label (pinned).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

REGIME_VERSION = "asof-1.1"

LABELS = ("TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL", "LOW_VOL",
          "TRANSITION", "UNKNOWN")

TREND_WINDOW = 20
VOL_WINDOW = 60
VOL_Q = 0.8
TREND_BAND = 0.02
TRADING_DAYS = 252


@dataclass(frozen=True)
class RegimeSnapshot:
    label: str
    as_of: pd.Timestamp
    regime_version: str = REGIME_VERSION
    regime_as_of: str = ""       # ISO timestamp of the snapshot itself
    detail: str = ""

    def journal(self) -> dict:
        return {"regime": self.label, "regime_version": self.regime_version,
                "regime_as_of": self.regime_as_of or str(self.as_of)}


def _trend(close: pd.Series) -> pd.Series:
    return close.pct_change(TREND_WINDOW)


def _vol(close: pd.Series) -> pd.Series:
    rets = close.pct_change()
    return rets.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)


def regime_snapshot(close: pd.Series, as_of: pd.Timestamp, *,
                    hi_thr: float | None = None,
                    lo_thr: float | None = None) -> RegimeSnapshot:
    """Label for ``as_of`` from bars with ``index < as_of``.

    ``hi_thr``/``lo_thr`` allow a caller to pin the expanding volatility
    quantiles for determinism tests; by default they are computed from
    the trailing (pre-``as_of``) window itself — still causal, since the
    quantiles only use past bars.
    """
    ts = pd.Timestamp(as_of)
    if close.index.tz is not None and ts.tzinfo is None:
        ts = ts.tz_localize(close.index.tz)
    past = close.loc[close.index < ts]
    if len(past) < VOL_WINDOW + 2:
        return RegimeSnapshot("UNKNOWN", ts,
                              regime_as_of=str(ts),
                              detail=f"insufficient history ({len(past)})")
    trend = float(_trend(past).iloc[-1])
    vol = _vol(past)
    v_now = float(vol.iloc[-1])
    hi = float(vol.expanding(min_periods=VOL_WINDOW).quantile(VOL_Q)
               .iloc[-1]) if hi_thr is None else hi_thr
    lo = float(vol.expanding(min_periods=VOL_WINDOW).quantile(1.0 - VOL_Q)
               .iloc[-1]) if lo_thr is None else lo_thr

    # TRANSITION: a SUSTAINED regime flip — the trend sign flipped across
    # the trend window, or the vol regime bucket (window-half medians,
    # noise-resistant) changed inside the vol window.
    t_series = _trend(past).dropna()
    transition = False
    if len(t_series) >= 2:
        last_w = t_series.iloc[-TREND_WINDOW:]
        if (last_w > 0).any() and (last_w < 0).any() \
                and last_w.iloc[0] * trend < 0:
            transition = True
        v_w = vol.dropna().iloc[-VOL_WINDOW:]
        if len(v_w) >= 4:
            half = len(v_w) // 2

            def bucket(seg):
                m = float(seg.median())
                return 1 if m > hi else (-1 if m < lo else 0)
            if bucket(v_w.iloc[:half]) != bucket(v_w.iloc[half:]) \
                    and bucket(v_w.iloc[half:]) != 0:
                transition = True

    if not np.isfinite(v_now) or v_now <= 0.0:
        label = "UNKNOWN"
    elif hi > lo and v_now >= hi:
        label = "HIGH_VOL"
    elif hi > lo and v_now <= lo:
        label = "LOW_VOL"
    elif transition:
        label = "TRANSITION"
    elif trend > TREND_BAND:
        label = "TREND_UP"
    elif trend < -TREND_BAND:
        label = "TREND_DOWN"
    else:
        label = "RANGE"
    return RegimeSnapshot(label, ts, regime_as_of=str(ts),
                          detail=f"trend={trend:.5f} vol={v_now:.6f}")


def regime_series(close: pd.Series) -> pd.Series:
    """Whole-series labels (each bar labelled from its own past only)."""
    out = {}
    for ts in close.index:
        out[ts] = regime_snapshot(close, ts).label
    return pd.Series(out, name="regime")
