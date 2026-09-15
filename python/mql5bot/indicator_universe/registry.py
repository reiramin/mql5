"""Indicator registry — the DECLARED universe (mission §8/§9).

Source of truth for: which kinds the DSL accepts, their parameter
ranges, outputs, warmup and documentation status.  The DSL schema
consumes this registry; adding an indicator never requires touching
DSL architecture (mission §8: extensibility without rewrites).

mql5_status:
- "parity-tested"      Python implementation pinned by tests; MQL5 port
                       exists in the repo and was digest-pinned.
- "canonical-defined"  Canonical Aegis semantics defined here and in
                       INDICATOR_UNIVERSE.md; MQL5 port pending owner
                       compile (NEVER reported as parity-proven).
"""

from __future__ import annotations

import numpy as np

from . import trend_momentum as tm
from . import volatility_volume_structure as vv
from .contracts import IndicatorContract, IndicatorParam, P, _w  # noqa: F401

BASE_PARITY = "parity-tested"


def _c(kind, category, params, outputs, warmup, fn, source,
       mql5=BASE_PARITY, notes="", requires_columns=()):
    return kind, (IndicatorContract(
        kind=kind, version=1, category=category,
        params=tuple(params), outputs=tuple(outputs), warmup=warmup,
        price_source=source, mql5_status=mql5, notes=notes,
        requires_columns=tuple(requires_columns)), fn)


REGISTRY: dict[str, tuple[IndicatorContract, object]] = dict([
    # ---- baseline kinds (existing indicators.py; parity-pinned) ----
    _c("EMA", "trend", [P("period", "int", 1, 5000, 20)],
       ("ema",), _w(20), None, "close",
       notes="EMA seeded with SMA(period); Wilder-free standard EMA."),
    _c("SMA", "trend", [P("period", "int", 1, 5000, 20)],
       ("sma",), _w(20), None, "close"),
    _c("RSI", "momentum", [P("period", "int", 1, 5000, 14)],
       ("rsi",), _w(14), None, "close",
       notes="Wilder smoothing (canonical; TradingView uses the same)."),
    _c("ATR", "volatility", [P("period", "int", 1, 5000, 14)],
       ("atr",), _w(14), None, "high_low_close",
       notes="Wilder ATR on true range."),
    _c("BBANDS", "volatility",
       [P("period", "int", 2, 5000, 20), P("dev", "float", 0.1, 10, 2.0)],
       ("mid", "upper", "lower"), _w(20), None, "close",
       notes="mid = SMA; dev in standard deviations."),
    _c("MACD", "momentum",
       [P("fast", "int", 1, 1000, 12), P("slow", "int", 2, 1000, 26),
        P("signal", "int", 1, 1000, 9)],
       ("line", "signal"), lambda p: p["slow"] + p["signal"], None,
       "close"),
    _c("DONCHIAN", "volatility", [P("period", "int", 2, 5000, 20)],
       ("upper", "lower"), _w(20), None, "high_low_close",
       notes="Upper = rolling max of highs; lower = rolling min of lows."),
    _c("HIGHEST", "structure", [P("period", "int", 1, 5000, 20)],
       ("highest",), _w(20), None, "close"),
    _c("LOWEST", "structure", [P("period", "int", 1, 5000, 20)],
       ("lowest",), _w(20), None, "close"),
    # ---- trend (new) ------------------------------------------------
    _c("WMA", "trend", [P("period", "int", 2, 5000, 20)], ("wma",),
       _w(20), tm.wma, "close"),
    _c("VWMA", "trend", [P("period", "int", 2, 5000, 20)], ("vwma",),
       _w(20), tm.vwma, "volume"),
    _c("HMA", "trend", [P("period", "int", 4, 5000, 20)], ("hma",),
       _w(20), tm.hma, "close"),
    _c("DEMA", "trend", [P("period", "int", 2, 5000, 20)], ("dema",),
       lambda p: 2 * p["period"] - 1, tm.dema, "close"),
    _c("TEMA", "trend", [P("period", "int", 2, 5000, 20)], ("tema",),
       lambda p: 3 * p["period"] - 2, tm.tema, "close"),
    _c("KAMA", "trend", [P("period", "int", 2, 2000, 10)], ("kama",),
       _w(10), tm.kama, "close"),
    _c("ZLEMA", "trend", [P("period", "int", 2, 5000, 20)], ("zlema",),
       _w(20), tm.zlema, "close"),
    _c("ALMA", "trend", [P("period", "int", 2, 5000, 20)], ("alma",),
       _w(20), tm.alma, "close",
       notes="offset=0.85 sigma=6 fixed (documented canonical)."),
    _c("TRIX", "trend", [P("period", "int", 2, 5000, 18)], ("trix",),
       lambda p: 3 * p["period"] - 2, tm.trix, "close"),
    _c("T3", "trend",
       [P("period", "int", 2, 500, 10),
        P("volume_factor", "float", 0.0, 1.0, 0.7)],
       ("t3",), lambda p: 6 * p["period"], tm.t3, "close",
       notes="Tillson T3: 6-deep EMA cascade, GD combination with "
             "volume_factor (0=simple triple EMA, 1=max smoothing)."),
    _c("ICHIMOKU", "trend",
       [P("tenkan", "int", 2, 200, 9), P("kijun", "int", 3, 500, 26),
        P("senkou", "int", 3, 1000, 52)],
       ("tenkan", "kijun", "senkou_a", "senkou_b"),
       lambda p: max(p["kijun"], p["senkou"]), tm.ichimoku,
       "high_low_close",
       notes="Unshifted components: the conventional +/-26 displacement "
             "is a plotting convention; values at i use rows <= i only."),
    _c("SUPERTREND", "trend",
       [P("period", "int", 2, 2000, 10), P("mult", "float", 0.5, 20, 3.0)],
       ("supertrend", "direction"), _w(10), tm.supertrend,
       "high_low_close",
       notes="direction: +1 up-trend, -1 down-trend."),
    _c("PSAR", "trend",
       [P("step", "float", 0.001, 1.0, 0.02),
        P("maximum", "float", 0.01, 1.0, 0.2)],
       ("psar", "direction"), lambda p: 2, tm.psar, "high_low_close",
       notes="Iterative; deterministic given the same start convention."),
    _c("AROON", "trend", [P("period", "int", 2, 5000, 14)],
       ("aroon_up", "aroon_down"), _w(14), tm.aroon, "high_low_close"),
    _c("ADX", "trend", [P("period", "int", 2, 2000, 14)],
       ("adx", "plus_di", "minus_di"), lambda p: 2 * p["period"],
       tm.adx, "high_low_close",
       notes="Wilder smoothing; bare id resolves to ADX."),
    _c("VORTEX", "trend", [P("period", "int", 2, 2000, 14)],
       ("vi_plus", "vi_minus"), _w(14), tm.vortex, "high_low_close"),
    # ---- momentum / oscillators (new) -------------------------------
    _c("STOCH", "momentum",
       [P("k_period", "int", 1, 2000, 14), P("d_period", "int", 1, 1000, 3)],
       ("k", "d"), lambda p: p["k_period"] + p["d_period"] - 1, tm.stoch,
       "high_low_close"),
    _c("STOCHRSI", "momentum",
       [P("rsi_period", "int", 2, 1000, 14),
        P("k_period", "int", 1, 1000, 14),
        P("d_period", "int", 1, 500, 3)],
       ("k", "d"),
       lambda p: p["rsi_period"] + p["k_period"] + p["d_period"],
       tm.stochrsi, "close"),
    _c("CCI", "momentum", [P("period", "int", 2, 5000, 20)], ("cci",),
       _w(20), tm.cci, "high_low_close", notes="constant 0.015 canonical."),
    _c("ROC", "momentum", [P("period", "int", 1, 5000, 12)], ("roc",),
       _w(12), tm.roc, "close"),
    _c("MOM", "momentum", [P("period", "int", 1, 5000, 10)], ("mom",),
       _w(10), tm.mom, "close"),
    _c("WILLR", "momentum", [P("period", "int", 2, 5000, 14)], ("willr",),
       _w(14), tm.willr, "high_low_close"),
    _c("CMO", "momentum", [P("period", "int", 2, 5000, 14)], ("cmo",),
       _w(14), tm.cmo, "close"),
    _c("TSI", "momentum",
       [P("long_period", "int", 2, 1000, 25),
        P("short_period", "int", 1, 500, 13)],
       ("tsi",), lambda p: p["long_period"] + p["short_period"], tm.tsi,
       "close"),
    _c("ULTOSC", "momentum",
       [P("p1", "int", 1, 500, 7), P("p2", "int", 2, 1000, 14),
        P("p3", "int", 3, 2000, 28)],
       ("ultosc",), lambda p: p["p3"], tm.ultosc, "high_low_close"),
    _c("AO", "momentum", [P("fast", "int", 1, 500, 5),
                          P("slow", "int", 2, 2000, 34)],
       ("ao",), lambda p: p["slow"], tm.ao, "high_low_close"),
    # ---- volatility (new) -------------------------------------------
    _c("NATR", "volatility", [P("period", "int", 1, 5000, 14)],
       ("natr",), _w(14), vv.natr, "high_low_close"),
    _c("KELTNER", "volatility",
       [P("period", "int", 2, 5000, 20), P("mult", "float", 0.1, 10, 2.0)],
       ("upper", "mid", "lower"), _w(20), vv.keltner, "high_low_close",
       notes="EMA basis with ATR range (canonical Aegis variant)."),
    _c("HISTVOL", "volatility", [P("period", "int", 2, 5000, 20)],
       ("histvol",), _w(20), vv.histvol, "close",
       notes="Std of log returns x100, per-bar (not annualized)."),
    _c("VOL_PERCENTILE", "volatility", [P("period", "int", 5, 5000, 50)],
       ("volpct",), _w(50), vv.vol_percentile, "close",
       notes="Percentile rank of |return| in window (0..100)."),
    _c("ROLLING_STD", "statistical", [P("period", "int", 2, 5000, 20)],
       ("rstd",), _w(20), vv.rolling_std, "close"),
    # ---- volume / flow (new) ----------------------------------------
    _c("OBV", "volume", [], ("obv",), lambda p: 1, vv.obv, "volume"),
    _c("MFI", "volume", [P("period", "int", 2, 5000, 14)], ("mfi",),
       _w(14), vv.mfi, "volume"),
    _c("CMF", "volume", [P("period", "int", 2, 5000, 20)], ("cmf",),
       _w(20), vv.cmf, "volume"),
    _c("VWAP_SESSION", "volume", [], ("vwap",), lambda p: 1,
       vv.vwap_session, "volume",
       notes="Typical-price VWAP, resets each calendar day (closed-bar)."),
    _c("VOL_OSC", "volume", [P("fast", "int", 1, 500, 5),
                             P("slow", "int", 2, 2000, 20)],
       ("vo",), lambda p: p["slow"], vv.vol_osc, "volume"),
    _c("ADL", "volume", [], ("adl",), lambda p: 1, vv.adl, "volume"),
    _c("CHAIKIN", "volume", [P("fast", "int", 1, 500, 3),
                             P("slow", "int", 2, 2000, 10)],
       ("chaikin",), lambda p: p["slow"], vv.chaikin_osc, "volume"),
    # ---- price / structure (new) ------------------------------------
    _c("RANGE", "structure", [P("period", "int", 1, 5000, 20)],
       ("range",), _w(20), vv.range_hl, "high_low_close"),
    _c("RETURNS", "statistical", [], ("ret",), lambda p: 2, vv.returns,
       "close"),
    _c("LOG_RETURNS", "statistical", [], ("logret",), lambda p: 2,
       vv.log_returns, "close"),
    _c("SWING_HIGH", "structure",
       [P("left", "int", 1, 500, 3), P("right", "int", 1, 500, 3)],
       ("level", "age"), lambda p: p["left"] + p["right"], vv.swing_high,
       "high_low_close",
       notes="Pivot confirmed `right` bars later; level emitted at the "
             "confirmation index (pivot_time < confirmation_time, §77)."),
    _c("SWING_LOW", "structure",
       [P("left", "int", 1, 500, 3), P("right", "int", 1, 500, 3)],
       ("level", "age"), lambda p: p["left"] + p["right"], vv.swing_low,
       "high_low_close", notes="See SWING_HIGH (§77)."),
    _c("FLOOR_PIVOTS", "structure", [P("period", "int", 2, 5000, 20)],
       ("pp", "r1", "s1"), _w(20), vv.floor_pivots, "high_low_close",
       notes="Values from the PREVIOUS completed window only."),
    _c("BREAKOUT_DIST", "structure", [P("period", "int", 2, 5000, 20)],
       ("up", "down"), _w(20), vv.breakout_dist, "high_low_close",
       notes="Distance in channel widths vs PREVIOUS window (shift 1)."),
    _c("CHANNEL_SLOPE", "statistical", [P("period", "int", 3, 5000, 20)],
       ("slope",), _w(20), vv.channel_slope, "close",
       notes="OLS slope normalized by window x-variance."),
    # ---- candle primitives (new) ------------------------------------
    _c("DOJI", "candle", [P("max_body_ratio", "float", 0.01, 0.5, 0.1)],
       ("doji",), lambda p: 1, vv.doji, "ohlcv",
       notes="1.0 when body <= ratio * range, else 0.0."),
    _c("INSIDE_BAR", "candle", [], ("inside",), lambda p: 2,
       vv.inside_bar, "high_low", notes="1.0 on inside bars."),
    _c("ENGULFING", "candle", [], ("engulf",), lambda p: 2, vv.engulfing,
       "open_close", notes="+1 bullish engulf, -1 bearish engulf."),
    _c("PIN_BAR", "candle", [P("wick_ratio", "float", 1.0, 10, 2.0)],
       ("pin",), lambda p: 1, vv.pin_bar, "ohlcv",
       notes="+1 hammer-like, -1 shooting-star-like."),
    _c("GAP", "candle", [], ("gap",), lambda p: 2, vv.gap, "open_close",
       notes="Gap % between open and previous close."),
    # ---- statistical (new) ------------------------------------------
    _c("ROLLING_MEDIAN", "statistical", [P("period", "int", 2, 5000, 20)],
       ("median",), _w(20), vv.rolling_median, "close"),
    _c("ROLLING_QUANTILE", "statistical",
       [P("period", "int", 3, 5000, 20), P("q", "float", 0.0, 100, 0.25)],
       ("quantile",), _w(20), vv.rolling_quantile, "close"),
    _c("ZSCORE", "statistical", [P("period", "int", 3, 5000, 20)],
       ("z",), _w(20), vv.zscore, "close"),
    _c("ROLLING_SKEW", "statistical", [P("period", "int", 4, 5000, 20)],
       ("skew",), _w(20), vv.rolling_skew, "close"),
    _c("ROLLING_KURT", "statistical", [P("period", "int", 5, 5000, 20)],
       ("kurt",), _w(20), vv.rolling_kurt, "close"),
    _c("AUTOCORR", "statistical",
       [P("period", "int", 3, 5000, 20), P("lag", "int", 1, 1000, 1)],
       ("ac",), lambda p: p["period"] + p["lag"], vv.autocorr, "close"),
    _c("BETA", "statistical", [P("period", "int", 5, 5000, 60)],
       ("beta",), lambda p: p["period"] + 1, vv.beta, "close",
       notes="Rolling beta vs 'benchmark_close' column (required, "
             "bar-aligned). Raises on missing benchmark.",
       requires_columns=("benchmark_close",)),
    # ---- multi-timeframe (new; closed HTF bars only) ------------------
    _c("MTF_EMA", "mtf", [P("period", "int", 1, 5000, 20),
                          P("mtf", "int", 2, 1000, 24)],
       ("mtf",), lambda p: 2 * p["mtf"] + p["period"], vv.mtf_ema,
       "close",
       notes="HTF value known only when the aggregated bar CLOSES."),
    _c("MTF_SMA", "mtf", [P("period", "int", 1, 5000, 20),
                          P("mtf", "int", 2, 1000, 24)],
       ("mtf",), lambda p: p["mtf"] + p["period"], vv.mtf_sma, "close"),
    _c("MTF_RSI", "mtf", [P("period", "int", 2, 5000, 14),
                          P("mtf", "int", 2, 1000, 24)],
       ("mtf",), lambda p: p["mtf"] + p["period"], vv.mtf_rsi, "close"),
    _c("MTF_ATR", "mtf", [P("period", "int", 1, 5000, 14),
                          P("mtf", "int", 2, 1000, 24)],
       ("mtf",), lambda p: p["mtf"] + p["period"], vv.mtf_atr,
       "high_low_close"),
])

# the 9 baseline kinds keep their hand-written runtime path (parity!)
BASELINE_KINDS = {"EMA", "SMA", "RSI", "ATR", "BBANDS", "MACD",
                  "DONCHIAN", "HIGHEST", "LOWEST"}
EXTENDED_KINDS = frozenset(
    k for k, (_, fn) in REGISTRY.items() if fn is not None)
ALL_KINDS = frozenset(REGISTRY)


def contract(kind: str) -> IndicatorContract:
    try:
        return REGISTRY[kind][0]
    except KeyError:
        raise KeyError(
            f"unsupported indicator {kind!r}; supported: "
            f"{sorted(ALL_KINDS)}") from None



def compute(kind: str, df, params: dict) -> dict[str, np.ndarray]:
    fn = REGISTRY[kind][1]
    return fn(df, params)
