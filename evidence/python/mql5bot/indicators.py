"""mql5bot.indicators — vectorized technical indicators.

All functions accept 1-D ``numpy`` arrays and return arrays of the same
length (values are NaN until enough data is available). Implementations are
deliberately aligned with the MQL5 include modules so backtest results match
the live Expert Advisor behaviour as closely as possible.
"""

from __future__ import annotations

import numpy as np


def ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average (MQL5-style: alpha = 2 / (period + 1))."""
    values = np.asarray(values, dtype=float)
    period = max(int(period), 1)
    alpha = 2.0 / (period + 1.0)
    out = np.full(values.shape, np.nan, dtype=float)
    if values.size < period:
        return out
    # Seed with the simple mean of the first `period` values.
    out[period - 1] = values[:period].mean()
    for i in range(period, values.size):
        out[i] = out[i - 1] + alpha * (values[i] - out[i - 1])
    return out


def sma(values: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average."""
    values = np.asarray(values, dtype=float)
    period = max(int(period), 1)
    kernel = np.ones(period) / period
    out = np.full(values.shape, np.nan, dtype=float)
    if values.size >= period:
        out[period - 1 :] = np.convolve(values, kernel, mode="valid")
    return out


def rolling_std(values: np.ndarray, period: int, ddof: int = 0) -> np.ndarray:
    """Rolling standard deviation, NaN-padded to match the input length."""
    values = np.asarray(values, dtype=float)
    period = max(int(period), 1)
    out = np.full(values.shape, np.nan, dtype=float)
    if values.size >= period:
        out[period - 1 :] = np.std(
            np.lib.stride_tricks.sliding_window_view(values, period),
            axis=1,
            ddof=ddof,
        )
    return out


def rsi(values: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index using Wilder's smoothing (MQL5-compatible)."""
    values = np.asarray(values, dtype=float)
    period = max(int(period), 1)
    out = np.full(values.shape, np.nan, dtype=float)
    if values.size <= period:
        return out
    delta = np.diff(values)
    gain = np.where(delta > 0.0, delta, 0.0)
    loss = np.where(delta < 0.0, -delta, 0.0)
    avg_gain = np.full(values.size, np.nan)
    avg_loss = np.full(values.size, np.nan)
    avg_gain[period] = gain[:period].mean()
    avg_loss[period] = loss[:period].mean()
    for i in range(period + 1, values.size):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i - 1]) / period
    rs = avg_gain / np.maximum(avg_loss, 1e-12)
    out = 100.0 - 100.0 / (1.0 + rs)
    return out


def bollinger(
    values: np.ndarray, period: int = 20, num_dev: float = 2.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands. Returns (middle, upper, lower)."""
    mid = sma(values, period)
    sd = rolling_std(values, period, ddof=0)
    return mid, mid + num_dev * sd, mid - num_dev * sd


def atr(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14
) -> np.ndarray:
    """Average True Range (Wilder's smoothing)."""
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    period = max(int(period), 1)
    out = np.full(high.shape, np.nan, dtype=float)
    if high.size <= period:
        return out
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )
    out[period] = tr[1 : period + 1].mean()
    for i in range(period + 1, high.size):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def donchian(high: np.ndarray, low: np.ndarray, period: int = 20):
    """Donchian channel. Returns (upper, lower) where upper is the highest
    high and lower the lowest low of the *previous* `period` bars (shifted by
    one so the channel does not include the current, not-yet-closed bar)."""
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    period = max(int(period), 1)
    upper = np.full(high.shape, np.nan)
    lower = np.full(low.shape, np.nan)
    if high.size > period:
        win_high = np.lib.stride_tricks.sliding_window_view(high, period)
        win_low = np.lib.stride_tricks.sliding_window_view(low, period)
        # Channel of the previous `period` bars (excludes the current bar).
        upper[period:] = win_high.max(axis=1)[:-1]
        lower[period:] = win_low.min(axis=1)[:-1]
    return upper, lower


def macd(
    values: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD. Returns (macd_line, signal_line, histogram)."""
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    macd_line = ema_fast - ema_slow
    valid = macd_line[~np.isnan(macd_line)]
    signal_line = np.full_like(macd_line, np.nan)
    if valid.size >= signal:
        signal_line[np.isnan(macd_line) == False] = ema(
            valid, signal
        )
    return macd_line, signal_line, macd_line - signal_line


def crossover(fast: np.ndarray, slow: np.ndarray) -> np.ndarray:
    """+1 where `fast` crossed above `slow` this bar, -1 where it crossed
    below, 0 elsewhere.

    Cross contract (Reality Gate §13, DECISIONS.md 2026-09-07): an event
    requires BOTH the current and the previous sample to be valid (non-NaN)
    — a NaN predecessor suppresses the event (warmup boundary never fires),
    mirroring the EA signal engine. Events are transitions of the
    STRICT-above state (``above = fast > slow``): +1 = entering above
    (EQUAL->ABOVE fires), -1 = leaving above (ABOVE->EQUAL fires),
    below<->equal transitions fire in neither direction. Consequently
    ``crossover(a, b) == -crossover(b, a)`` holds on all tie-free inputs
    and may differ at exact-tie bars — both facts are pinned by
    tests/test_indicator_semantics.py."""
    fast = np.asarray(fast, dtype=float)
    slow = np.asarray(slow, dtype=float)
    out = np.zeros(fast.shape, dtype=int)
    above = fast > slow
    prev_above = np.roll(above, 1)
    prev_above[0] = above[0]
    valid = ~(np.isnan(fast) | np.isnan(slow))
    prev_valid = np.roll(valid, 1)
    prev_valid[0] = valid[0]
    cross_up = valid & prev_valid & above & ~prev_above
    cross_dn = valid & prev_valid & ~above & prev_above
    out[cross_up] = 1
    out[cross_dn] = -1
    return out


def crossunder(fast: np.ndarray, slow: np.ndarray) -> np.ndarray:
    """Sign-flipped crossover BY DEFINITION: +1 where `fast` left the
    strict-above state this bar (crossed below or onto `slow`), -1 where
    it entered it, else 0. Identical to ``-crossover(fast, slow)`` for all
    inputs. The DSL runtime evaluates crossings via ``crossover``
    comparisons only, so on tie-free inputs ``crossover(a,b) < 0``,
    ``crossunder(a,b) > 0`` and ``crossover(b,a) > 0`` are three spellings
    of the SAME event; exact-tie behaviour is pinned separately (see
    crossover docstring and tests/test_indicator_semantics.py)."""
    return -crossover(fast, slow)


def highest(values: np.ndarray, period: int) -> np.ndarray:
    """Rolling maximum including the current bar, NaN-padded."""
    values = np.asarray(values, dtype=float)
    period = max(int(period), 1)
    out = np.full(values.shape, np.nan)
    if values.size >= period:
        out[period - 1 :] = np.lib.stride_tricks.sliding_window_view(
            values, period
        ).max(axis=1)
    return out


def lowest(values: np.ndarray, period: int) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    period = max(int(period), 1)
    out = np.full(values.shape, np.nan)
    if values.size >= period:
        out[period - 1 :] = np.lib.stride_tricks.sliding_window_view(
            values, period
        ).min(axis=1)
    return out
