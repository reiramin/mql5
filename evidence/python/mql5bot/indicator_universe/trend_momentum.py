"""Indicator universe — trend & momentum computes (mission §8).

Every function is a PURE, DETERMINISTIC, CAUSAL closed-bar transform:
value at index i uses rows <= i only, NaN during warmup.  No clocks,
no random, no global state.  These are the canonical Aegis semantics
(§10); platform differences are documented in the registry notes,
never silently approximated.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators import atr as _atr
from ..indicators import ema as _ema
from ..indicators import rsi as _rsi
from ..indicators import sma as _sma


def _col(df, name):
    return df[name].to_numpy(dtype=float)


def _ema_robust(x, period):
    """EMA that tolerates a leading NaN band (composed indicators feed
    the output of one smoother into the next)."""
    x = np.asarray(x, dtype=float)
    finite = np.flatnonzero(np.isfinite(x))
    out = np.full(len(x), np.nan)
    if len(finite) == 0:
        return out
    f = int(finite[0])
    out[f:] = _ema(x[f:], period)
    return out


def _nan_head(arr, k):
    out = np.array(arr, dtype=float)
    k = min(int(k), len(out))
    out[:k] = np.nan
    return out


# ------------------------------------------------------------- trend


def wma(df, p):
    x = _col(df, "close")
    n, w = len(x), p["period"]
    out = np.full(n, np.nan)
    denom = w * (w + 1) / 2.0
    for i in range(w - 1, n):
        win = x[i - w + 1:i + 1]
        out[i] = float(np.dot(np.arange(1, w + 1), win) / denom)
    return {"wma": out}


def vwma(df, p):
    c, v = _col(df, "close"), _col(df, "volume")
    w = p["period"]
    num = pd.Series(c * v).rolling(w).sum().to_numpy()
    den = pd.Series(v).rolling(w).sum().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"vwma": num / den}


def hma(df, p):
    x = _col(df, "close")
    w = max(2, int(p["period"]))
    half = _wma_arr(x, max(2, w // 2))
    full = _wma_arr(x, w)
    raw = 2 * half - full
    out = np.full(len(x), np.nan)
    rw = max(2, int(np.sqrt(w)))
    s = pd.Series(raw).rolling(rw).apply(
        lambda win: np.dot(np.arange(1, rw + 1), win)
        / (rw * (rw + 1) / 2), raw=True)
    out[:] = s.to_numpy()
    return {"hma": out}


def _wma_arr(x, w):
    out = np.full(len(x), np.nan)
    denom = w * (w + 1) / 2.0
    for i in range(w - 1, len(x)):
        out[i] = float(np.dot(np.arange(1, w + 1),
                              x[i - w + 1:i + 1]) / denom)
    return out


def dema(df, p):
    x = _col(df, "close")
    e1 = _ema_robust(x, p["period"])
    e2 = _ema_robust(e1, p["period"])
    return {"dema": 2 * e1 - e2}


def tema(df, p):
    x = _col(df, "close")
    e1 = _ema_robust(x, p["period"])
    e2 = _ema_robust(e1, p["period"])
    e3 = _ema_robust(e2, p["period"])
    return {"tema": 3 * e1 - 3 * e2 + e3}


def kama(df, p):
    x = _col(df, "close")
    w, n = p["period"], len(x)
    out = np.full(n, np.nan)
    if n <= w:
        return {"kama": out}
    change = np.abs(x[w] - x[0])
    vol = np.sum(np.abs(np.diff(x[:w + 1])))
    sc_const = (2.0 / (30.0 + 1.0))
    k = x[w]
    out[w] = k
    for i in range(w + 1, n):
        change = abs(x[i] - x[i - w])
        vol = np.sum(np.abs(np.diff(x[i - w:i + 1])))
        er = change / vol if vol > 0 else 0.0
        sc = (er * (2.0 / (2.0 + 1.0) - sc_const) + sc_const) ** 2
        k = k + sc * (x[i] - k)
        out[i] = k
    return {"kama": out}


def zlema(df, p):
    x = _col(df, "close")
    lag = max(1, p["period"] // 2)
    z = x.copy()
    z[lag:] = x[lag:] + (x[lag:] - x[:-lag])
    return {"zlema": _ema(z, p["period"])}


def alma(df, p):
    x = _col(df, "close")
    w = p["period"]
    m = 0.85 * (w - 1)
    s = w / 6.0
    i = np.arange(w)
    weights = np.exp(-((i - m) ** 2) / (2 * s * s))
    weights /= weights.sum()
    out = np.full(len(x), np.nan)
    for j in range(w - 1, len(x)):
        out[j] = float(np.dot(weights, x[j - w + 1:j + 1]))
    return {"alma": out}


def t3(df, p):
    """Tillson T3: six-deep EMA cascade with volume factor v (0..1).
    GD-combination coefficients per Tillson's book (causal — EMAs only
    use rows <= i)."""
    x = _col(df, "close")
    n, v = p["period"], p["volume_factor"]
    e1 = _ema_robust(x, n)
    e2 = _ema_robust(e1, n)
    e3 = _ema_robust(e2, n)
    e4 = _ema_robust(e3, n)
    e5 = _ema_robust(e4, n)
    e6 = _ema_robust(e5, n)
    c1 = -(v ** 3)
    c2 = 3 * v * v + 3 * v ** 3
    c3 = -6 * v * v - 3 * v - 3 * v ** 3
    c4 = 1 + 3 * v + v ** 3 + 3 * v * v
    out = (c1 * np.where(np.isfinite(e6), e6, 0.0)
           + c2 * np.where(np.isfinite(e5), e5, 0.0)
           + c3 * np.where(np.isfinite(e4), e4, 0.0)
           + c4 * np.where(np.isfinite(e3), e3, 0.0))
    # the GD combination is only defined once the WHOLE cascade is warm
    first = np.flatnonzero(np.isfinite(e6))
    if len(first):
        out[:int(first[0])] = np.nan
    return {"t3": out}


def ichimoku(df, p):
    """Ichimoku components, UNSHIFTED (the standard +/-26 bar forward/
    backward displacements are plotting conventions).  Every value at
    bar i is computed from rows <= i only, so the contract stays
    causal.  senkou_b uses the longer `senkou` window mid-price."""
    h, l = _col(df, "high"), _col(df, "low")
    mid = lambda w: (pd.Series(h).rolling(w).max().to_numpy()
                     + pd.Series(l).rolling(w).min().to_numpy()) / 2.0
    tenkan = mid(p["tenkan"])
    kijun = mid(p["kijun"])
    senkou_a = (tenkan + kijun) / 2.0
    senkou_b = mid(p["senkou"])
    return {"tenkan": tenkan, "kijun": kijun, "senkou_a": senkou_a,
            "senkou_b": senkou_b}


def trix(df, p):
    x = _col(df, "close")
    e1 = _ema_robust(x, p["period"])
    e2 = _ema_robust(e1, p["period"])
    e3 = _ema_robust(e2, p["period"])
    out = np.full(len(x), np.nan)
    out[1:] = 100.0 * (e3[1:] - e3[:-1]) / np.where(
        np.abs(e3[:-1]) > 0, np.abs(e3[:-1]), np.nan)
    return {"trix": out}


def supertrend(df, p):
    h, l, c = _col(df, "high"), _col(df, "low"), _col(df, "close")
    mult, n = p["mult"], len(c)
    a = _atr(h, l, c, p["period"])
    hl2 = (h + l) / 2.0
    ub, lb = hl2 + mult * a, hl2 - mult * a
    st = np.full(n, np.nan)
    direction = np.zeros(n)
    fub, flb = ub.copy(), lb.copy()
    for i in range(1, n):
        if np.isnan(ub[i]) or np.isnan(fub[i - 1]):
            continue
        fub[i] = ub[i] if (ub[i] < fub[i - 1]
                           or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1]
                           or c[i - 1] < flb[i - 1]) else flb[i - 1]
        if np.isnan(st[i - 1]):
            direction[i] = -1 if c[i] < fub[i] else 1
        elif st[i - 1] == fub[i - 1]:
            direction[i] = -1 if c[i] <= fub[i] else 1
        else:
            direction[i] = 1 if c[i] >= flb[i] else -1
        st[i] = flb[i] if direction[i] == 1 else fub[i]
    return {"supertrend": st, "direction": direction}


def psar(df, p):
    h, l = _col(df, "high"), _col(df, "low")
    step, mx = p["step"], p["maximum"]
    n = len(h)
    out = np.full(n, np.nan)
    direction = np.ones(n)
    if n < 2:
        return {"psar": out, "direction": direction}
    bull, af, ep = True, step, h[1]
    sar = l[0]
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if bull:
            sar = min(sar, l[i - 1], l[i - 2] if i >= 2 else l[i - 1])
            if l[i] < sar:                     # flip
                bull, sar, ep, af = False, ep, l[i], step
            elif h[i] > ep:
                ep, af = h[i], min(mx, af + step)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i >= 2 else h[i - 1])
            if h[i] > sar:
                bull, sar, ep, af = True, ep, h[i], step
            elif l[i] < ep:
                ep, af = l[i], min(mx, af + step)
        out[i] = sar
        direction[i] = 1 if bull else -1
    return {"psar": out, "direction": direction}


def aroon(df, p):
    h, l = _col(df, "high"), _col(df, "low")
    w = p["period"]
    n = len(h)
    up = np.full(n, np.nan)
    down = np.full(n, np.nan)
    for i in range(w, n):
        hw = h[i - w:i + 1]
        lw = l[i - w:i + 1]
        up[i] = 100.0 * w / max(1, w - int(np.argmax(hw)))
        down[i] = 100.0 * w / max(1, w - int(np.argmin(lw)))
    return {"aroon_up": up, "aroon_down": down}


def adx(df, p):
    h, l, c = _col(df, "high"), _col(df, "low"), _col(df, "close")
    w = p["period"]
    n = len(h)
    tr = np.maximum(h[1:] - l[1:], np.maximum(
        np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    up = h[1:] - h[:-1]
    dn = l[:-1] - l[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)

    def wilder(x):
        out = np.full(n - 1, np.nan)
        if len(x) < w:
            return out
        out[w - 1] = x[:w].sum()
        for i in range(w, len(x)):
            out[i] = out[i - 1] - out[i - 1] / w + x[i]
        return out

    atr_s = wilder(tr)
    pdi_s = wilder(plus_dm)
    mdi_s = wilder(minus_dm)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi = 100.0 * pdi_s / atr_s
        mdi = 100.0 * mdi_s / atr_s
        dx = 100.0 * np.abs(pdi - mdi) / (pdi + mdi)
    adx_arr = np.full(n, np.nan)
    valid = ~np.isnan(dx)
    idx = np.flatnonzero(valid)
    if len(idx) >= w:
        start = idx[w - 1]
        seg = dx[idx[:w]]
        adx_seg = np.full(n - 1, np.nan)
        adx_seg[start] = seg.mean()
        for i in range(start + 1, n - 1):
            adx_seg[i] = (adx_seg[i - 1] * (w - 1) + dx[i]) / w
        adx_arr[1:] = adx_seg
    plus = np.full(n, np.nan)
    minus = np.full(n, np.nan)
    plus[1:] = pdi
    minus[1:] = mdi
    return {"adx": adx_arr, "plus_di": plus, "minus_di": minus}


def vortex(df, p):
    h, l, c = _col(df, "high"), _col(df, "low"), _col(df, "close")
    w = p["period"]
    tr = np.maximum(h[1:] - l[1:], np.maximum(
        np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    vmp = np.abs(h[1:] - l[:-1])
    vmn = np.abs(l[1:] - h[:-1])
    n = len(h)
    vip = np.full(n, np.nan)
    vim = np.full(n, np.nan)
    str_tr = pd.Series(tr).rolling(w).sum().to_numpy()
    s_p = pd.Series(vmp).rolling(w).sum().to_numpy()
    s_m = pd.Series(vmn).rolling(w).sum().to_numpy()
    vip[1:] = s_p / str_tr
    vim[1:] = s_m / str_tr
    return {"vi_plus": vip, "vi_minus": vim}


# ---------------------------------------------------------- momentum


def stoch(df, p):
    h, l, c = _col(df, "high"), _col(df, "low"), _col(df, "close")
    w, d = p["k_period"], p["d_period"]
    hh = pd.Series(h).rolling(w).max().to_numpy()
    ll = pd.Series(l).rolling(w).min().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        k = 100.0 * (c - ll) / (hh - ll)
    k_s = pd.Series(k).rolling(d).mean().to_numpy()
    return {"k": k, "d": k_s}


def stochrsi(df, p):
    r = _rsi(_col(df, "close"), p["rsi_period"])
    w, d = p["k_period"], p["d_period"]
    s = pd.Series(r)
    hh = s.rolling(w).max().to_numpy()
    ll = s.rolling(w).min().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        k = 100.0 * (r - ll) / (hh - ll)
    return {"k": k, "d": pd.Series(k).rolling(d).mean().to_numpy()}


def cci(df, p):
    h, l, c = _col(df, "high"), _col(df, "low"), _col(df, "close")
    tp = (h + l + c) / 3.0
    w = p["period"]
    sma_tp = pd.Series(tp).rolling(w).mean().to_numpy()
    mad = pd.Series(tp).rolling(w).apply(
        lambda win: np.mean(np.abs(win - win.mean())), raw=True).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"cci": (tp - sma_tp) / (0.015 * mad)}


def roc(df, p):
    x = _col(df, "close")
    w = p["period"]
    out = np.full(len(x), np.nan)
    out[w:] = 100.0 * (x[w:] - x[:-w]) / np.where(
        np.abs(x[:-w]) > 0, np.abs(x[:-w]), np.nan)
    return {"roc": out}


def mom(df, p):
    x = _col(df, "close")
    w = p["period"]
    out = np.full(len(x), np.nan)
    out[w:] = x[w:] - x[:-w]
    return {"mom": out}


def willr(df, p):
    h, l, c = _col(df, "high"), _col(df, "low"), _col(df, "close")
    w = p["period"]
    hh = pd.Series(h).rolling(w).max().to_numpy()
    ll = pd.Series(l).rolling(w).min().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"willr": -100.0 * (hh - c) / (hh - ll)}


def cmo(df, p):
    x = _col(df, "close")
    w = p["period"]
    diff = np.diff(x, prepend=x[0])
    up = pd.Series(np.where(diff > 0, diff, 0.0)).rolling(w).sum().to_numpy()
    dn = pd.Series(np.where(diff < 0, -diff, 0.0)).rolling(w).sum().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"cmo": 100.0 * (up - dn) / (up + dn)}


def tsi(df, p):
    x = _col(df, "close")
    m = np.diff(x, prepend=x[0])
    long_w, short_w = p["long_period"], p["short_period"]
    num = pd.Series(m).ewm(span=long_w, adjust=False).mean() \
        .ewm(span=short_w, adjust=False).mean().to_numpy()
    den = pd.Series(np.abs(m)).ewm(span=long_w, adjust=False).mean() \
        .ewm(span=short_w, adjust=False).mean().to_numpy()
    out = np.full(len(x), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[1:] = 100.0 * num[1:] / den[1:]
    return {"tsi": out}


def ultosc(df, p):
    h, l, c = _col(df, "high"), _col(df, "low"), _col(df, "close")
    n = len(c)
    cp = np.concatenate([[c[0]], c[:-1]])
    bp = c - np.minimum(l, cp)
    tr = np.maximum(h, cp) - np.minimum(l, cp)
    w1, w2, w3 = p["p1"], p["p2"], p["p3"]
    out = np.zeros(n)

    def roll(x, w):
        return pd.Series(x).rolling(w).sum().to_numpy()

    for w, k in ((w1, 4.0), (w2, 2.0), (w3, 1.0)):
        b, t = roll(bp, w), roll(tr, w)
        with np.errstate(invalid="ignore", divide="ignore"):
            out = out + k * (b / t)
    return {"ultosc": out / 7.0}


def ao(df, p):
    h, l = _col(df, "high"), _col(df, "low")
    mp = (h + l) / 2.0
    fast, slow = p.get("fast", 5), p.get("slow", 34)
    return {"ao": _sma(mp, fast) - _sma(mp, slow)}
