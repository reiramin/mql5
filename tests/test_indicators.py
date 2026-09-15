"""Unit tests for indicator implementations."""

import numpy as np
from mql5bot.indicators import (
    atr,
    bollinger,
    crossover,
    donchian,
    ema,
    macd,
    rsi,
    sma,
)


def test_sma_basic():
    x = np.array([1.0, 2, 3, 4, 5])
    out = sma(x, 3)
    assert np.isnan(out[0]) and np.isnan(out[1])
    assert np.isclose(out[2], 2.0)
    assert np.isclose(out[3], 3.0)
    assert np.isclose(out[4], 4.0)


def test_ema_matches_manual():
    x = np.array([1.0, 2, 3, 4, 5])
    out = ema(x, 3)
    # seed = mean(1,2,3) = 2
    assert np.isclose(out[2], 2.0)
    alpha = 2.0 / 4.0
    e3 = 2 + alpha * (4 - 2)
    e4 = e3 + alpha * (5 - e3)
    assert np.isclose(out[3], e3)
    assert np.isclose(out[4], e4)


def test_rsi_bounds_and_values():
    rng = np.random.default_rng(7)
    x = 100 + np.cumsum(rng.normal(0, 1, 500))
    out = rsi(x, 14)
    valid = out[~np.isnan(out)]
    assert valid.min() >= 0 and valid.max() <= 100
    # monotonic increasing series -> RSI near 100
    up = rsi(np.arange(50, dtype=float), 14)
    assert np.isclose(up[-1], 100.0, atol=1e-6)


def test_rsi_all_gains_and_losses():
    gains = rsi(np.linspace(1, 2, 100), 14)
    losses = rsi(np.linspace(2, 1, 100), 14)
    assert gains[-1] > 90
    assert losses[-1] < 10


def test_atr_positive():
    n = 100
    h = np.full(n, 1.10)
    l = np.full(n, 1.09)
    c = np.full(n, 1.095)
    out = atr(h, l, c, 14)
    valid = out[~np.isnan(out)]
    assert np.allclose(valid, 0.01)


def test_bollinger_symmetry():
    x = np.sin(np.linspace(0, 20, 300))
    mid, upper, lower = bollinger(x, 20, 2.0)
    valid = ~np.isnan(mid)
    assert np.allclose(upper[valid] - mid[valid], mid[valid] - lower[valid])


def test_donchian_excludes_current_bar():
    h = np.array([1.0, 2, 3, 4, 5])
    l = np.array([0.0, 0, 0, 0, 0])
    upper, _ = donchian(h, l, 3)
    # bar 3: previous 3 bars = [1,2,3] -> upper 3
    assert np.isclose(upper[3], 3.0)
    # bar 4: previous 3 bars = [2,3,4] -> upper 4 (current 5 excluded)
    assert np.isclose(upper[4], 4.0)


def test_macd_histogram_sign():
    rng = np.random.default_rng(3)
    x = np.cumsum(rng.normal(0, 1, 300)) + 100
    line, sig, hist = macd(x)
    valid = ~np.isnan(hist)
    assert np.allclose(line[valid] - sig[valid], hist[valid])


def test_crossover_events():
    fast = np.array([1.0, 2, 1, 1, 3])
    slow = np.array([2.0, 2, 2, 0, 2])
    out = crossover(fast, slow)
    # bar1: 2 > 2 false; bar2: 1>2 false; bar3: 1>0 crosses up; bar4: 3>2 stays
    assert out[3] == 1
    assert out[1] == 0 and out[2] == 0 and out[4] == 0
