"""mql5bot — a full-stack algorithmic trading system for MetaTrader 5.

Python side: strategy library, rigorous backtest engine, optimiser,
reporting, and tooling that mirrors the MQL5 Expert Advisor in
``../mql5``.
"""

from __future__ import annotations

from . import backtest, data, indicators, metrics, optimizer, report, strategies
from .backtest import BacktestResult, run_backtest
from .data import generate_ohlc, load_csv, load_mt5
from .metrics import compute_metrics
from .optimizer import grid_search, walk_forward
from .report import build_report_html, save_report_html
from .strategies import (
    STRATEGIES,
    default_params,
    get_strategy,
    list_strategies,
    signal,
)

__version__ = "1.0.0"

__all__ = [
    "STRATEGIES",
    "BacktestResult",
    "backtest",
    "build_report_html",
    "compute_metrics",
    "data",
    "default_params",
    "generate_ohlc",
    "get_strategy",
    "grid_search",
    "indicators",
    "list_strategies",
    "load_csv",
    "load_mt5",
    "metrics",
    "optimizer",
    "report",
    "run_backtest",
    "save_report_html",
    "signal",
    "strategies",
    "walk_forward",
]
