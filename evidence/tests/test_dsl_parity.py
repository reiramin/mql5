"""DSL parity tests (mission §16/§17) + trade-level engine parity.

Parity ladder:
1. SIGNAL parity: DSL runtime vs the compiled reference strategy —
   bar-by-bar identical desired positions on multiple frames.
2. TRADE parity: the DSL signal run through the canonical backtest
   (engine seam) vs the compiled strategy — identical trades.

The compiled implementation remains the reference until parity is
proven — and these tests keep proving it on every run.
"""

from __future__ import annotations

import pandas as pd
import pytest
from mql5bot.backtest import run_backtest
from mql5bot.data import generate_ohlc
from mql5bot.dsl import desired_positions, exit_params, parse_file
from mql5bot.strategies import STRATEGIES

EXAMPLES = __import__("pathlib").Path(__file__).resolve().parent \
    .parent / "examples" / "strategies"

# registry name → example spec
REFERENCES = {
    "ema_crossover": "ema_crossover.json",
    "rsi_reversal": "rsi_reversal.json",
    "donchian_breakout": "donchian_breakout.json",
    "bollinger_reversal": "bollinger_reversal.json",
    "macd_momentum": "macd_momentum.json",
}

FRAMES = None


def _frames():
    global FRAMES
    if FRAMES is None:
        FRAMES = {
            "fx": generate_ohlc(days=200, seed=40),
            "au": generate_ohlc(days=200, seed=41),
            "gbp": generate_ohlc(days=150, seed=42),
            "seed7": generate_ohlc(days=120, seed=7),
        }
    return FRAMES


@pytest.mark.parametrize("name", sorted(REFERENCES))
def test_signal_parity_bar_by_bar(name):
    spec = parse_file(EXAMPLES / REFERENCES[name])
    fn, defaults = STRATEGIES[name]
    for frame_name, df in _frames().items():
        ref = fn(df, dict(defaults))
        got = desired_positions(spec, df)
        assert (ref.to_numpy() == got.to_numpy()).all(), \
            f"{name} signal parity broken on {frame_name}"


@pytest.mark.parametrize("name", sorted(REFERENCES))
def test_trade_parity_through_canonical_engine(name):
    spec = parse_file(EXAMPLES / REFERENCES[name])
    _fn, defaults = STRATEGIES[name]
    df = _frames()["fx"]
    ref = run_backtest(df, name, dict(defaults))
    sig = desired_positions(spec, df)
    geo = exit_params(spec)
    dsl_params = {k: v for k, v in geo.items()
                  if k in ("sl_atr", "tp_atr", "trail_atr",
                           "breakeven_atr") and v}
    dsl = run_backtest(df, f"dsl:{spec.strategy_id}", dsl_params,
                       signal=sig)
    cols = ["side", "entry_time", "exit_time", "entry_price", "lots",
            "pnl", "exit_reason"]
    a = ref.trades[cols].reset_index(drop=True)
    b = dsl.trades[cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    pd.testing.assert_series_equal(ref.equity, dsl.equity)


def test_multilingual_series_equivalence():
    """Mission §11: the EN and FA formulations of the same idea must
    trade identically."""
    df = _frames()["fx"]
    en = parse_file(EXAMPLES / "ema_rsi_trend.json",
                    overrides={"rsi_min": 55.0})
    fa = parse_file(EXAMPLES / "ema_rsi_atr_fa.json")
    assert (desired_positions(en, df).to_numpy()
            == desired_positions(fa, df).to_numpy()).all()


def test_param_override_moves_signals_deterministically():
    df = _frames()["fx"]
    low = parse_file(EXAMPLES / "ema_rsi_trend.json",
                     overrides={"rsi_min": 50.0})
    high = parse_file(EXAMPLES / "ema_rsi_trend.json",
                      overrides={"rsi_min": 65.0})
    a = desired_positions(low, df).to_numpy()
    b = desired_positions(high, df).to_numpy()
    assert (a != b).any()                    # the override matters
    # higher RSI bar ⇒ long positions are a subset
    from mql5bot.dsl import compute_indicators
    spec = parse_file(EXAMPLES / "ema_rsi_trend.json")
    series = compute_indicators(df, spec.indicators)
    rsi = series["rsi_m"]
    long_low = set((a == 1).nonzero()[0])
    long_high = set((b == 1).nonzero()[0])
    for i in long_high - long_low:
        assert rsi[i] > 55.0                 # only mid-band adds


def test_invalid_example_is_rejected_whole():
    from mql5bot.dsl import UnknownReference
    with pytest.raises(UnknownReference):
        parse_file(EXAMPLES / "invalid_unknown_indicator.json")
