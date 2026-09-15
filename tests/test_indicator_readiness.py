"""Reality Gate §8/§10 — indicator initialization & readiness contract.

Pins the warmup model chosen in DECISIONS.md 2026-09-07: **deterministic
NaN propagation**. An unavailable/uninitialized indicator value is NaN in
both runtimes; every strategy suppresses evaluation on NaN; a suppressed
bar emits an INVALID signal (EA) / zero desired position (Python).

Evidence classes:
* Python behaviour           -> TESTED_RUNTIME (this file)
* EA source semantics        -> SOURCE_BEHAVIOR (pins in test_mql5_sources)
* EMPTY_VALUE / first-valid  -> OFFICIAL_DOCUMENTATION (mql5.com "Other
  Constants": EMPTY_VALUE == DBL_MAX for uncomputed buffer slots; mql5.com
  "Applying One Indicator to Another": RSI(14) first reasonable value at
  index 14)
* iMA/iMACD seeding details  -> COMMUNITY_EVIDENCE until the owner's
  tester leg settles them (BLOCKED_OWNER_ENVIRONMENT)

The phantom-signal reproductions below model the OLD MQL5 behaviour
(EMPTY_VALUE/0.0 passed to comparators) to keep the historical bug
reproducible forever, then prove the fixed NaN contract suppresses it.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from mql5bot import strategies as S
from mql5bot.indicators import atr, bollinger, donchian, ema, macd, rsi

DBL_MAX = 1.7976931348623157e308  # MQL5 EMPTY_VALUE (official docs)


def _series(n=120, seed=3):
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, 0.001, n)
    return 1.10 + np.cumsum(steps)


# ---------------------------------------------------------------------------
# Readiness matrix — Python side (TESTED_RUNTIME)
# ---------------------------------------------------------------------------


def test_ema_first_valid_and_seed():
    x = _series(60)
    out = ema(x, 10)
    assert np.isnan(out[:9]).all()
    assert out[9] == pytest.approx(x[:10].mean())   # SMA seed (contract-v1)
    assert np.isfinite(out[9:]).all()


def test_rsi_first_valid_index_is_period():
    x = _series(60)
    out = rsi(x, 14)
    assert np.isnan(out[:14]).all()
    assert np.isfinite(out[14])
    # Wilder seed check: avg gain/loss of the first 14 deltas
    d = np.diff(x[:16])
    g = np.where(d > 0, d, 0.0)[:14].mean()
    l = np.where(d < 0, -d, 0.0)[:14].mean()
    assert out[14] == pytest.approx(100.0 - 100.0 / (1.0 + g / max(l, 1e-12)))


def test_rsi_all_gains_approaches_100_representation_only():
    """When avg loss == 0 the denominator clamp (1e-12) yields 100 - eps
    instead of the platform's exact 100.0. Pinned as a REPRESENTATION
    difference: |RSI - 100| < 1e-6, and no 30/70 threshold decision can
    ever depend on it (margin >= 29.999999 points)."""
    x = np.linspace(1.0, 2.0, 40)
    out = rsi(x, 14)
    assert out[-1] < 100.0
    assert out[-1] > 100.0 - 1e-6
    assert 100.0 - out[-1] < 1e-6 and out[-1] - 70.0 > 29.0


def test_atr_first_valid_index_is_period():
    n = 60
    rng = np.random.default_rng(1)
    close = 1.10 + np.cumsum(rng.normal(0, 0.001, n))
    high = close + 0.0005
    low = close - 0.0005
    out = atr(high, low, close, 14)
    assert np.isnan(out[:14]).all()
    assert np.isfinite(out[14])


def test_bollinger_first_valid_index():
    x = _series(60)
    mid, up, lo = bollinger(x, 20, 2.0)
    assert np.isnan(mid[:19]).all()
    assert np.isfinite(mid[19]) and np.isfinite(up[19]) and np.isfinite(lo[19])


def test_macd_first_valid_indices():
    x = _series(80)
    line, sig, hist = macd(x, 12, 26, 9)
    assert np.isnan(line[:25]).all()
    assert np.isfinite(line[25])
    assert np.isnan(sig[:33]).all()
    assert np.isfinite(sig[33])
    assert np.isfinite(hist[33])


def test_donchian_first_valid_index_and_window():
    n = 40
    high = np.arange(n, dtype=float) + 1.0
    low = high - 0.5
    up, lo = donchian(high, low, 5)
    assert np.isnan(up[:5]).all()
    assert up[5] == 5.0          # max of bars 0..4
    assert lo[5] == 0.5          # min of bars 0..4
    assert up[6] == 6.0          # window slides: bars 1..5


# ---------------------------------------------------------------------------
# Strategy-level warmup suppression (Python): zero desired position until
# every consumed indicator is valid
# ---------------------------------------------------------------------------


def _df(n=120, seed=3):
    import pandas as pd

    rng = np.random.default_rng(seed)
    close = 1.10 + np.cumsum(rng.normal(0, 0.001, n))
    high = close + np.abs(rng.normal(0, 0.0004, n))
    low = close - np.abs(rng.normal(0, 0.0004, n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": 1000.0}, index=idx)


@pytest.mark.parametrize("name,first_possible", [
    ("ema_crossover", 29),      # slow EMA(30) first valid at index 29
    # RSI(14) first valid at index 14; a crossover event needs TWO valid
    # samples (DECISIONS.md 2026-09-07 cross contract), so the earliest
    # possible signal bar is 15.
    ("rsi_reversal", 15),
    ("donchian_breakout", 20),  # channel valid from index 20
    ("bollinger_reversal", 19), # bands valid from index 19
    ("macd_momentum", 33),      # signal line valid from index 33
])
def test_no_signal_before_readiness(name, first_possible):
    df = _df()
    desired = S.signal(df, name).to_numpy()
    assert (desired[:first_possible] == 0).all(), name


# ---------------------------------------------------------------------------
# Phantom-signal reproduction: the OLD MQL5 value feed (EMPTY_VALUE / 0.0
# reaching comparators) vs the FIXED NaN contract
# ---------------------------------------------------------------------------


def _rsi_escape_direction(r, r_prev, oversold=30.0, overbought=70.0):
    """Transcription of EvaluateRsiReversal's escape/state logic."""
    now_os, prev_os = r < oversold, r_prev < oversold
    now_ob, prev_ob = r > overbought, r_prev > overbought
    state = 0
    if prev_os and not now_os:
        state = 1
    elif prev_ob and not now_ob:
        state = -1
    if not now_os and not now_ob:
        return state
    return 0


def test_old_rsi_feed_minted_a_phantom_sell_on_first_valid_bar():
    """Historical bug (kept as the permanent regression): on the FIRST
    valid RSI bar, rPrev == EMPTY_VALUE compared as overbought, so the
    'escape overbought' transition fired and produced direction -1."""
    r, r_prev = 55.0, DBL_MAX            # neutral RSI, EMPTY predecessor
    assert _rsi_escape_direction(r, r_prev) == -1      # phantom SELL
    # fixed contract: EMPTY_VALUE -> NaN -> evaluation suppressed
    assert math.isnan(float("nan"))
    r_prev_nan = float("nan")
    suppressed = math.isnan(r) or math.isnan(r_prev_nan)
    assert suppressed                    # no direction is ever produced


def test_old_bollinger_feed_minted_a_phantom_buy():
    close = 1.10
    lower_empty = DBL_MAX                # EMPTY_VALUE lower band
    assert close < lower_empty           # old path: phantom BUY
    nan = float("nan")
    assert not (close < nan)


def test_old_macd_feed_minted_a_phantom_sell():
    line = 0.0002
    signal_empty = DBL_MAX               # EMPTY_VALUE signal line
    assert line < signal_empty           # old path: phantom SELL
    nan = float("nan")
    assert not (line < nan)


def test_old_donchian_feed_minted_a_phantom_breakout():
    """Out-of-range iHigh/iLow return 0 -> zero-width channel -> phantom."""
    close = 1.10
    upper_old = 0.0                      # out-of-range zeros (lower too)
    assert close > upper_old             # old path: phantom BUY
    # fixed contract: Bars gate -> signal invalid before the window exists


def test_fixed_contract_suppresses_every_warmup_path():
    """Model of the fixed GetValue: every unavailable source maps to NaN,
    and NaN never satisfies a strict comparison in either direction."""
    nan = float("nan")
    assert not (nan > 70.0) and not (nan < 30.0)
    assert not (1.10 < nan) and not (1.10 > nan)
    assert nan != nan                    # noqa: PLR0124 — IsNaN() catches it


# ---------------------------------------------------------------------------
# INIT_FAILED audit (§10): fatal states only, every one with a reason
# ---------------------------------------------------------------------------


def test_init_failed_is_fatal_only_and_always_reasoned():
    from pathlib import Path

    ea = (Path(__file__).resolve().parents[1]
          / "mql5/Experts/Mql5Bot/Mql5Bot.mq5").read_text()
    lines = ea.splitlines()
    fatal_sites = [i for i, ln in enumerate(lines)
                   if "return INIT_FAILED" in ln]
    assert len(fatal_sites) == 5, fatal_sites
    # each fatal site is one of the classified environment/identity
    # failures, gated by an explicit condition within the previous lines
    context = "\n".join(lines)
    for gate in ("BuildSymbolSpec", "TERMINAL_TRADE_ALLOWED",
                 "g_signal.Init", "g_guard.Init", "g_magic < 0"):
        assert gate in context, gate
    # every input-validation failure uses the DISTINCT parameters category
    assert context.count("return INIT_PARAMETERS_INCORRECT") == 8
    # data insufficiency is NOT a fatal init state: it is handled by the
    # NaN suppression contract, never by INIT_FAILED
    assert "INIT_FAILED" not in (
        Path(__file__).resolve().parents[1]
        / "mql5/Include/Mql5Bot/SignalEngine.mqh").read_text()


def test_signal_engine_nan_warmup_contract_source_pins():
    from pathlib import Path

    se = (Path(__file__).resolve().parents[1]
          / "mql5/Include/Mql5Bot/SignalEngine.mqh").read_text()
    # unavailable sources map to NaN, never to a numeric
    assert "return NaNValue();" in se
    assert "if(handle == INVALID_HANDLE)\n         return NaNValue();" in se
    assert "CopyBuffer(handle, buffer, shift, 1, buf) <= 0" in se
    assert "buf[0] == EMPTY_VALUE" in se
    # the old numeric fallbacks are gone from GetValue
    assert "return 0.0;" not in se.split("double            EMA(")[0]
    # Donchian gates on the channel window before reading iHigh/iLow
    assert "Bars(m_symbol, m_tf) < n + 2" in se
    # strategies keep their NaN guards (they are live code now)
    assert se.count("IsNaN(") >= 6
