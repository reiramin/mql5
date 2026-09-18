"""mql5bot.data — market data loading and generation.

Three sources are supported:

* CSV files (``load_csv``)
* Synthetic regime-switching GBM data (``generate_ohlc``) — deterministic via
  seed, useful for demos and unit tests
* A live MetaTrader 5 terminal (``load_mt5``) — optional, requires the
  ``MetaTrader5`` package and a running terminal (Windows only)
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

OHLC_COLUMNS = ["open", "high", "low", "close", "volume"]

TIMEFRAMES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
    "W1": 10080,
}


def timeframe_minutes(tf: str) -> int:
    key = tf.upper()
    if key not in TIMEFRAMES:
        raise ValueError(f"unknown timeframe {tf!r}; choose from {sorted(TIMEFRAMES)}")
    return TIMEFRAMES[key]


def validate_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Return a sanitised copy with a sorted DatetimeIndex and the OHLC
    columns in canonical order."""
    df = df.copy()
    if "time" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
        df["time"] = pd.to_datetime(df["time"])
        df = df.set_index("time")
    elif isinstance(df.index, pd.DatetimeIndex):
        pass
    else:
        raise ValueError("data needs a DatetimeIndex or a 'time' column")
    df.index = pd.DatetimeIndex(df.index)
    df.index.name = "time"
    if not df.index.is_monotonic_increasing:
        # §52 data-quality firewall: out-of-order bars indicate feed
        # corruption; silently reordering could mask it
        raise ValueError("timestamps must be monotonic increasing "
                         "(refusing to silently reorder bars)")
    df = df.sort_index()
    missing = [c for c in OHLC_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    df = df[OHLC_COLUMNS].astype(float)
    df = df[~df.index.duplicated(keep="first")]
    prices = df[["open", "high", "low", "close"]]
    if not np.isfinite(prices.to_numpy()).all():
        # §52 data-quality firewall: NaN/Inf must never silently reach
        # research or execution
        raise ValueError("prices must be finite (NaN/Inf rejected)")
    if (prices <= 0).any().any():
        raise ValueError("prices must be positive")
    return df


def load_csv(path: str) -> pd.DataFrame:
    """Load OHLC data from CSV. Accepts a header row with 'time' plus
    open/high/low/close/volume columns (any order), comma or semicolon
    separated."""
    path = os.path.expanduser(path)
    sep = ","
    with open(path, "r", encoding="utf-8-sig") as fh:
        first = fh.readline().strip().lower()
    if ";" in first:
        sep = ";"
    df = pd.read_csv(path, sep=sep)
    df.columns = [c.strip().lower() for c in df.columns]
    required = {"time", "open", "high", "low", "close"}
    if not required.issubset(df.columns):
        raise ValueError(f"CSV must contain columns {sorted(required)}")
    return validate_ohlc(df)


def generate_ohlc(
    symbol: str = "EURUSD",
    timeframe: str = "H1",
    days: int = 365,
    start: str | pd.Timestamp = "2024-01-01",
    seed: int = 42,
    start_price: float = 1.10,
    annual_vol: float = 0.12,
    drift: float = 0.0,
) -> pd.DataFrame:
    """Generate synthetic OHLC bars with regime-switching volatility.

    The generator is a geometric Brownian motion with a two-state volatility
    regime chain (calm / turbulent). Output is fully reproducible for a given
    seed. Bar OHLC values are consistent (high >= max(open, close), etc.).
    """
    rng = np.random.default_rng(seed)
    minutes = timeframe_minutes(timeframe)
    bars_per_day = 1440 // minutes
    total_bars = max(days * bars_per_day, 100)
    if isinstance(start, str):
        start = pd.Timestamp(start)
    index = pd.date_range(start=start, periods=total_bars, freq=f"{minutes}min")

    # --- regime chain ----------------------------------------------------
    regimes = np.zeros(total_bars, dtype=bool)  # False=calm, True=turbulent
    i = 0
    while i < total_bars:
        turbulent = rng.random() < 0.22
        length = int(rng.integers(4, 40))  # bars in this regime
        regimes[i : i + length] = turbulent
        i += length
    vol_calm = annual_vol / np.sqrt(bars_per_day * 252)
    vol_turb = vol_calm * rng.uniform(2.0, 4.5)
    bar_vol = np.where(regimes, vol_turb, vol_calm)
    bar_drift = drift / (bars_per_day * 252)

    # --- price path ------------------------------------------------------
    returns = rng.normal(bar_drift, bar_vol, total_bars)
    close = start_price * np.exp(np.cumsum(returns))
    open_ = np.empty(total_bars)
    open_[0] = start_price
    open_[1:] = close[:-1]

    # --- intrabar ranges -------------------------------------------------
    log_range = np.abs(rng.normal(bar_vol * 0.55, bar_vol * 0.25, total_bars))
    up = close >= open_
    high = np.where(up, np.maximum(open_, close) + log_range, np.maximum(open_, close) + log_range * 0.6)
    low = np.where(up, np.minimum(open_, close) - log_range * 0.6, np.minimum(open_, close) - log_range)
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))
    low = np.maximum(low, 1e-6)

    volume = (rng.lognormal(0.0, 0.35, total_bars) * 1000 * (1 + regimes * 2)).astype(float)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )
    df.index.name = "time"
    df.attrs["symbol"] = symbol
    df.attrs["timeframe"] = timeframe
    df.attrs["seed"] = seed
    return df


def save_csv(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    df.to_csv(path, float_format="%.6f")


def load_mt5(
    symbol: str,
    timeframe: str = "H1",
    bars: int = 5000,
    utc_from: str | None = None,
):
    """Fetch bars from a running MetaTrader 5 terminal.

    Requires ``pip install MetaTrader5`` and a logged-in terminal on Windows.
    Returns a validated OHLC DataFrame.
    """
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "MetaTrader5 package not installed. Run: pip install MetaTrader5"
        ) from exc

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")

    tf_map = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
        "W1": mt5.TIMEFRAME_W1,
    }
    kwargs: dict = {"symbol": symbol, "timeframe": tf_map[timeframe.upper()], "count": bars}
    if utc_from:
        kwargs["utc_from"] = pd.Timestamp(utc_from).to_pydatetime()
    rates = mt5.copy_rates_from_pos(**kwargs)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"no data for {symbol}: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return validate_ohlc(df)


def split(df: pd.DataFrame, train_frac: float = 0.7):
    """Split into (train, test) along time, returning views of the input."""
    n = int(len(df) * train_frac)
    return df.iloc[:n], df.iloc[n:]
