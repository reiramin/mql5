"""Tests for data loading and generation."""


import pandas as pd
import pytest
from mql5bot.data import (
    generate_ohlc,
    load_csv,
    save_csv,
    split,
    timeframe_minutes,
    validate_ohlc,
)


def test_generate_ohlc_shape_and_ohlc_consistency():
    df = generate_ohlc(symbol="EURUSD", timeframe="H1", days=30, seed=1)
    assert len(df) == 30 * 24
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert (df["high"] >= df[["open", "close"]].max(axis=1)).all()
    assert (df["low"] <= df[["open", "close"]].min(axis=1)).all()
    assert (df[["open", "high", "low", "close"]] > 0).all().all()


def test_generate_ohlc_reproducible():
    a = generate_ohlc(days=10, seed=7)
    b = generate_ohlc(days=10, seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_generate_ohlc_different_timeframes():
    m15 = generate_ohlc(timeframe="M15", days=10, seed=3)
    d1 = generate_ohlc(timeframe="D1", days=10, seed=3)
    assert len(m15) == 10 * 96
    assert len(d1) == 100  # generator enforces a 100-bar minimum


def test_timeframe_minutes():
    assert timeframe_minutes("H1") == 60
    assert timeframe_minutes("m5") == 5
    with pytest.raises(ValueError):
        timeframe_minutes("nope")


def test_csv_roundtrip(tmp_path):
    df = generate_ohlc(days=5, seed=9)
    path = tmp_path / "data.csv"
    save_csv(df, str(path))
    loaded = load_csv(str(path))
    pd.testing.assert_frame_equal(
        loaded, df, check_exact=False, rtol=1e-4, check_freq=False
    )


def test_csv_semicolon_and_column_order(tmp_path):
    df = generate_ohlc(days=3, seed=2)
    shuffled = df.reset_index()[["close", "volume", "time", "low", "open", "high"]]
    path = tmp_path / "semi.csv"
    shuffled.to_csv(path, sep=";")
    loaded = load_csv(str(path))
    assert list(loaded.columns) == ["open", "high", "low", "close", "volume"]
    assert loaded.index.equals(df.index)


def test_validate_rejects_bad_input():
    good = generate_ohlc(days=2, seed=1)
    validate_ohlc(good)
    bad = good.copy()
    bad["close"] = -1.0
    with pytest.raises(ValueError):
        validate_ohlc(bad)
    with pytest.raises(ValueError):
        validate_ohlc(good.drop(columns=["close"]))


def test_split():
    df = generate_ohlc(days=10, seed=4)
    train, test = split(df, 0.7)
    assert len(train) + len(test) == len(df)
    assert train.index[-1] < test.index[0]
