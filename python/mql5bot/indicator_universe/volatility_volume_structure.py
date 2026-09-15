"""Indicator universe — volatility, volume, structure, candle,
statistical and multi-timeframe computes (mission §8/§77).

Pure, deterministic, causal, closed-bar transforms; NaN during warmup.
Pivot semantics (§77): a swing/pivot value carries `pivot_time` (the
extremum bar) and is only DEFINED from `confirmation_time` =
pivot_time + confirmation bars onward — the emitted series places the
value at the confirmation index so `signal_time >= confirmation_time`
holds structurally.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators import atr as _atr
from ..indicators import ema as _ema
from ..indicators import rolling_std as _rolling_std
from ..indicators import sma as _sma
from .trend_momentum import _col


def natr(df, p):
    h, l, c = _col(df, "high"), _col(df, "low"), _col(df, "close")
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"natr": 100.0 * _atr(h, l, c, p["period"]) / c}


def keltner(df, p):
    h, l, c = _col(df, "high"), _col(df, "low"), _col(df, "close")
    mid = _ema(c, p["period"])
    a = _atr(h, l, c, p["period"])
    rng = p["mult"] * a
    return {"upper": mid + rng, "mid": mid, "lower": mid - rng}


def histvol(df, p):
    c = _col(df, "close")
    lr = np.full(len(c), np.nan)
    lr[1:] = np.log(c[1:] / c[:-1])
    out = pd.Series(lr).rolling(p["period"]).std().to_numpy() * 100.0
    return {"histvol": out}


def vol_percentile(df, p):
    c = _col(df, "close")
    lr = np.full(len(c), np.nan)
    lr[1:] = np.log(c[1:] / c[:-1])
    s = pd.Series(np.abs(lr))
    out = s.rolling(p["period"]).rank(pct=True).to_numpy() * 100.0
    return {"volpct": out}


def rolling_std(df, p):
    x = _col(df, "close")
    return {"rstd": _rolling_std(x, p["period"])}


def obv(df, p):
    c, v = _col(df, "close"), _col(df, "volume")
    sign = np.sign(np.diff(c, prepend=c[0]))
    return {"obv": np.cumsum(sign * v)}


def mfi(df, p):
    h, l, c, v = (_col(df, "high"), _col(df, "low"), _col(df, "close"),
                  _col(df, "volume"))
    tp = (h + l + c) / 3.0
    raw = tp * v
    diff = np.diff(tp, prepend=tp[0])
    pos = pd.Series(np.where(diff > 0, raw, 0.0)).rolling(
        p["period"]).sum().to_numpy()
    neg = pd.Series(np.where(diff < 0, raw, 0.0)).rolling(
        p["period"]).sum().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"mfi": 100.0 - 100.0 / (1.0 + pos / neg)}


def cmf(df, p):
    h, l, c, v = (_col(df, "high"), _col(df, "low"), _col(df, "close"),
                  _col(df, "volume"))
    rng = h - l
    with np.errstate(invalid="ignore", divide="ignore"):
        mfv = np.where(rng > 0, ((c - l) - (h - c)) / rng * v, 0.0)
    num = pd.Series(mfv).rolling(p["period"]).sum().to_numpy()
    den = pd.Series(v).rolling(p["period"]).sum().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"cmf": num / den}


def vwap_session(df, p):
    """Session-anchored VWAP of the TYPICAL price (canonical closed-bar
    semantics: bar's typical price × bar volume; resets at each new
    calendar day / session start).  Causal: uses rows <= i only."""
    h, l, c, v = (_col(df, "high"), _col(df, "low"), _col(df, "close"),
                  _col(df, "volume"))
    tp = (h + l + c) / 3.0
    days = pd.Series(df.index.normalize())
    new_day = (days != days.shift(1)).to_numpy()
    out = np.full(len(c), np.nan)
    cum_pv = cum_v = 0.0
    for i in range(len(c)):
        if new_day[i] or i == 0:
            cum_pv = cum_v = 0.0
        cum_pv += tp[i] * v[i]
        cum_v += v[i]
        out[i] = cum_pv / cum_v if cum_v > 0 else np.nan
    return {"vwap": out}


def vol_osc(df, p):
    v = _col(df, "volume")
    fast = _sma(v, p["fast"])
    slow = _sma(v, p["slow"])
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"vo": 100.0 * (fast - slow) / slow}


def adl(df, p):
    h, l, c, v = (_col(df, "high"), _col(df, "low"), _col(df, "close"),
                  _col(df, "volume"))
    rng = h - l
    with np.errstate(invalid="ignore", divide="ignore"):
        mfv = np.where(rng > 0, ((c - l) - (h - c)) / rng * v, 0.0)
    return {"adl": np.cumsum(mfv)}


def chaikin_osc(df, p):
    from .trend_momentum import _ema_robust
    ad = adl(df, p)["adl"]
    return {"chaikin": _ema_robust(ad, p["fast"])
            - _ema_robust(ad, p["slow"])}


# --------------------------------------------------------- structure


def range_hl(df, p):
    h, l = _col(df, "high"), _col(df, "low")
    w = p["period"]
    return {"range": (pd.Series(h).rolling(w).max()
                      - pd.Series(l).rolling(w).min()).to_numpy()}


def returns(df, p):
    c = _col(df, "close")
    out = np.full(len(c), np.nan)
    out[1:] = 100.0 * (c[1:] - c[:-1]) / np.where(
        np.abs(c[:-1]) > 0, np.abs(c[:-1]), np.nan)
    return {"ret": out}


def log_returns(df, p):
    c = _col(df, "close")
    out = np.full(len(c), np.nan)
    out[1:] = 100.0 * np.log(c[1:] / c[:-1])
    return {"logret": out}


def swing_high(df, p):
    """Confirmed swing high (§77): bar i is a pivot when its high is
    the maximum of [i-left, i+right]; the LEVEL is emitted at the
    confirmation index i+right (pivot_time < confirmation_time)."""
    h = _col(df, "high")
    left, right = p["left"], p["right"]
    n = len(h)
    level = np.full(n, np.nan)
    age = np.full(n, np.nan)
    for i in range(left, n - right):
        win = h[i - left:i + right + 1]
        if h[i] >= win.max() and int(np.argmax(win)) == left:
            level[i + right] = h[i]
            age[i + right] = float(right)
    return {"level": level, "age": age}


def swing_low(df, p):
    l = _col(df, "low")
    left, right = p["left"], p["right"]
    n = len(l)
    level = np.full(n, np.nan)
    age = np.full(n, np.nan)
    for i in range(left, n - right):
        win = l[i - left:i + right + 1]
        if l[i] <= win.min() and int(np.argmin(win)) == left:
            level[i + right] = l[i]
            age[i + right] = float(right)
    return {"level": level, "age": age}


def floor_pivots(df, p):
    """Classic floor pivots from the PREVIOUS completed p-bar window
    (causal: window k's values exist from the close of window k)."""
    h, l, c = _col(df, "high"), _col(df, "low"), _col(df, "close")
    w = p["period"]
    n = len(c)
    pp = np.full(n, np.nan)
    r1 = np.full(n, np.nan)
    s1 = np.full(n, np.nan)
    for end in range(w - 1, n):
        seg_h = h[end - w + 1:end + 1]
        seg_l = l[end - w + 1:end + 1]
        seg_c = c[end]
        pivot = (seg_h.max() + seg_l.min() + seg_c) / 3.0
        # emitted from the NEXT bar onward (previous window's close)
        if end + 1 < n:
            pp[end + 1] = pivot
            r1[end + 1] = 2 * pivot - seg_l.min()
            s1[end + 1] = 2 * pivot - seg_h.max()
    return {"pp": pp, "r1": r1, "s1": s1}


def breakout_dist(df, p):
    """Distance of close from the previous p-bar channel (previous bars
    only — shift(1) on the rolling extremes; never the current bar)."""
    h, l, c = _col(df, "high"), _col(df, "low"), _col(df, "close")
    w = p["period"]
    hh = pd.Series(h).rolling(w).max().shift(1).to_numpy()
    ll = pd.Series(l).rolling(w).min().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        rng = np.where(np.abs(hh - ll) > 0, hh - ll, np.nan)
        up = (c - hh) / rng
        dn = (c - ll) / rng
    return {"up": up, "down": dn}


def channel_slope(df, p):
    """Closed-form OLS slope of close over a p-bar window (x local
    0..w-1): slope = cov(x,y)/var(x); var_x = w(w^2-1)/12.  Causal:
    window ends at the current CLOSED bar."""
    c = _col(df, "close")
    w = p["period"]
    n = len(c)
    out = np.full(n, np.nan)
    if n < w:
        return {"slope": out}
    cs = np.cumsum(np.insert(c, 0, 0.0))
    g = np.arange(n, dtype=float)
    gcs = np.cumsum(np.insert(g * c, 0, 0.0))
    var_x = w * (w * w - 1.0) / 12.0
    mean_x = (w - 1) / 2.0
    for i in range(w - 1, n):
        j = i - w + 1
        sum_y = cs[i + 1] - cs[j]
        sum_gy = gcs[i + 1] - gcs[j]
        sum_xy = sum_gy - j * sum_y          # x local = g - j
        cov = sum_xy - mean_x * sum_y
        out[i] = cov / (w * var_x)
    return {"slope": out}


# ------------------------------------------------------------ candle


def doji(df, p):
    o, h, l, c = (_col(df, "open"), _col(df, "high"), _col(df, "low"),
                  _col(df, "close"))
    body = np.abs(c - o)
    rng = h - l
    with np.errstate(invalid="ignore", divide="ignore"):
        val = np.where(rng > 0, (body <= p["max_body_ratio"] * rng)
                       .astype(float), 0.0)
    return {"doji": val}


def inside_bar(df, p):
    h, l = _col(df, "high"), _col(df, "low")
    out = np.zeros(len(h))
    out[1:] = ((h[1:] < h[:-1]) & (l[1:] > l[:-1])).astype(float)
    return {"inside": out}


def engulfing(df, p):
    o, c = _col(df, "open"), _col(df, "close")
    n = len(c)
    out = np.zeros(n)
    for i in range(1, n):
        if c[i] > o[i] and c[i - 1] < o[i - 1] \
                and c[i] >= o[i - 1] and o[i] <= c[i - 1]:
            out[i] = 1.0
        elif c[i] < o[i] and c[i - 1] > o[i - 1] \
                and c[i] <= o[i - 1] and o[i] >= c[i - 1]:
            out[i] = -1.0
    return {"engulf": out}


def pin_bar(df, p):
    o, h, l, c = (_col(df, "open"), _col(df, "high"), _col(df, "low"),
                  _col(df, "close"))
    body = np.abs(c - o)
    lower = np.minimum(c, o) - l
    upper = h - np.maximum(c, o)
    rng = h - l
    out = np.zeros(len(c))
    with np.errstate(invalid="ignore", divide="ignore"):
        hammer = (lower >= p["wick_ratio"] * body) & (upper <= body) \
            & (rng > 0)
        shooter = (upper >= p["wick_ratio"] * body) & (lower <= body) \
            & (rng > 0)
    out[hammer] = 1.0
    out[shooter] = -1.0
    return {"pin": out}


def gap(df, p):
    o, c = _col(df, "open"), _col(df, "close")
    out = np.full(len(c), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[1:] = 100.0 * (o[1:] - c[:-1]) / np.where(
            np.abs(c[:-1]) > 0, np.abs(c[:-1]), np.nan)
    return {"gap": out}


# ------------------------------------------------------- statistical


def rolling_median(df, p):
    s = pd.Series(_col(df, "close"))
    return {"median": s.rolling(p["period"]).median().to_numpy()}


def rolling_quantile(df, p):
    s = pd.Series(_col(df, "close"))
    q = p["q"] if p["q"] <= 1.0 else p["q"] / 100.0
    return {"quantile": s.rolling(p["period"]).quantile(q).to_numpy()}


def zscore(df, p):
    s = pd.Series(_col(df, "close"))
    mean = s.rolling(p["period"]).mean()
    std = s.rolling(p["period"]).std()
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"z": ((s - mean) / std).to_numpy()}


def rolling_skew(df, p):
    s = pd.Series(_col(df, "close"))
    return {"skew": s.rolling(p["period"]).skew().to_numpy()}


def rolling_kurt(df, p):
    s = pd.Series(_col(df, "close"))
    return {"kurt": s.rolling(p["period"]).kurt().to_numpy()}


def autocorr(df, p):
    s = pd.Series(_col(df, "close"))
    lag = p["lag"]
    return {"ac": s.rolling(p["period"]).corr(s.shift(lag)).to_numpy()}


def beta(df, p):
    """Rolling OLS beta of the symbol's close-to-close returns against
    an aligned benchmark carried in the frame as 'benchmark_close'
    (required column; raises if absent).  Both series must stay
    aligned bar-by-bar; the window is causal."""
    if "benchmark_close" not in df.columns:
        raise ValueError(
            "BETA requires an aligned 'benchmark_close' column")
    r = pd.Series(_col(df, "close")).pct_change()
    b = pd.Series(df["benchmark_close"].to_numpy(dtype=float)).pct_change()
    cov = r.rolling(p["period"]).cov(b)
    var = b.rolling(p["period"]).var()
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"beta": (cov / var).to_numpy()}


def lrslope(df, p):
    return channel_slope(df, p)


# ---------------------------------------------------------------- MTF


def _aggregate(df, n_bars):
    """Aggregate CLOSED base bars into non-overlapping higher-timeframe
    bars (first open, max high, min low, last close, summed volume)."""
    n = len(df)
    k = n // n_bars                       # complete HTF bars only
    o = _col(df, "open")[:k * n_bars].reshape(k, n_bars)
    h = _col(df, "high")[:k * n_bars].reshape(k, n_bars)
    l = _col(df, "low")[:k * n_bars].reshape(k, n_bars)
    c = _col(df, "close")[:k * n_bars].reshape(k, n_bars)
    v = _col(df, "volume")[:k * n_bars].reshape(k, n_bars)
    return (o[:, 0], h.max(axis=1), l.min(axis=1), c[:, -1], v.sum(axis=1))


def _mtf_value(df, p, fn):
    """HTF indicator value is known only when the HTF bar CLOSES: the
    k-th aggregated bar's value becomes available at base index
    (k+1)*mtf_bars - 1 and is carried forward (causal, closed bars)."""
    m = p["mtf"]
    n = len(df)
    (o, h, l, c, v) = _aggregate(df, m)
    ht = pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                       "volume": v})
    vals = fn(ht)                          # length k
    out = np.full(n, np.nan)
    for k_i in range(len(vals)):
        idx = (k_i + 1) * m - 1            # HTF close on the base frame
        if idx < n:
            out[idx:] = vals[k_i]
    return out


def mtf_ema(df, p):
    def fn(ht):
        return _ema(_col(ht, "close"), p["period"])
    return {"mtf": _mtf_value(df, p, fn)}


def mtf_sma(df, p):
    def fn(ht):
        return _sma(_col(ht, "close"), p["period"])
    return {"mtf": _mtf_value(df, p, fn)}


def mtf_rsi(df, p):
    def fn(ht):
        from ..indicators import rsi
        return rsi(_col(ht, "close"), p["period"])
    return {"mtf": _mtf_value(df, p, fn)}


def mtf_atr(df, p):
    def fn(ht):
        return _atr(_col(ht, "high"), _col(ht, "low"),
                    _col(ht, "close"), p["period"])
    return {"mtf": _mtf_value(df, p, fn)}
