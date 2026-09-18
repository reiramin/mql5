"""mql5bot.backtest — legacy single-symbol research entry point (canonical wrapper).

This module is now a THIN CANONICAL WRAPPER around the portfolio engine
(:mod:`mql5bot.engine`) for the single-symbol, single-strategy research
case.  The legacy bespoke loop (direct ``risk / (stop_distance *
contract_size)`` sizing, hand-rolled fills, calendar-day resets) is GONE:
every position is sized by :func:`mql5bot.sizer.size_position` on an
injected :class:`~mql5bot.symbolspec.SymbolSpec`, every fill and cost is
priced by :mod:`mql5bot.costs`, and day boundaries come from
:class:`~mql5bot.dayclock.DayClock` — the exact same code paths the
portfolio engine and (eventually) the MQL5 EA use.

Behaviour mapping (legacy semantics preserved where they are the research
contract, canonical semantics where the legacy module was arbitrary):

* Signals are desired positions computed from closed bars and act at the
  NEXT bar's open — lookahead is impossible (unchanged).
* Entry fills at the open adjusted for half the spread plus slippage;
  market exits (flips, halts, max-bars, end-of-data, partial scale-outs)
  adjust the same way, so a round trip ending at a market exit pays the
  full spread plus slippage on both legs plus commission (unchanged; all
  charged through ``mql5bot.costs``).
* Stop loss / take profit resolve intrabar from the bar's high/low; when a
  bar touches both levels the stop is assumed hit first (conservative,
  unchanged).  Canonical fill conventions apply: gap-through fills at the
  open, stops carry explicit slippage, TPs do not slip.
* Risk sizing uses ``risk_percent`` of the previous close's equity over
  the (tick-rounded, stops-level-enforced) stop distance — now via the
  canonical sizer, which floors volume to the broker step and REJECTS
  orders whose risk-adequate size is below ``volume_min`` instead of the
  legacy clamp-up that overshot the risk budget.
* Signal flips never close a position (legacy ``allow_signal_exit=False``
  semantics — the canonical engine's default of exiting on flips is for
  portfolio strategies that opt in).
* Daily reset follows server time via the default midnight ``DayClock``
  (calendar-day equivalent for naive hourly data); the daily-loss limit
  and drawdown kill switch fire at the bar OPEN on the previous close's
  equity (no same-bar lookahead) and fill at that open.

Result rows follow the engine's canonical trade vocabulary; the legacy
column set is preserved so existing consumers (optimizer, CLI, metrics)
keep working unchanged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import strategies
from .costs import CostConfig
from .engine import Instrument, PortfolioEngine, RunConfig
from .symbolspec import SymbolSpec

# ---------------------------------------------------------------------------
# Result container (legacy shape, unchanged)
# ---------------------------------------------------------------------------


@dataclass
class BacktestResult:
    strategy: str
    params: dict
    config: dict
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    equity: pd.Series = field(default_factory=pd.Series)
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """JSON-serialisable summary (equity downsampled to <= 1500 points)."""
        eq = self.equity
        step = max(1, math.ceil(len(eq) / 1500))
        eq_ds = eq.iloc[::step]
        return {
            "strategy": self.strategy,
            "params": self.params,
            "config": self.config,
            "metrics": {k: _jsonable(v) for k, v in self.metrics.items()},
            "equity": {
                "time": [str(t) for t in eq_ds.index],
                "value": [float(v) for v in eq_ds.values],
            },
            "trades": self.trades.to_dict(orient="records"),
        }


# ---------------------------------------------------------------------------
# Legacy single-symbol API — canonical engine under the hood
# ---------------------------------------------------------------------------

# Legacy column set, extended with the engine's ledger columns ("fees" and
# "costs" — see mql5bot.engine) so downstream consumers can account for
# per-window/per-strategy costs without replaying fills.  The original
# columns keep their names and order; the extras are appended before
# "exit_reason".
_TRADE_COLUMNS = [
    "entry_time", "exit_time", "side", "entry_price", "exit_price",
    "lots", "bars_held", "pnl", "pnl_pct", "fees", "costs", "exit_reason",
]


def run_backtest(
    df: pd.DataFrame,
    strategy_name: str,
    params: dict | None = None,
    *,
    initial_capital: float = 10_000.0,
    risk_percent: float = 1.0,
    max_lots: float = 100.0,
    allow_short: bool = True,
    spread_points: float = 1.0,
    slippage_points: float = 0.0,
    commission_per_lot: float = 7.0,
    commission_min: float = 0.0,
    swap_long_per_lot_day: float = 0.0,
    swap_short_per_lot_day: float = 0.0,
    max_gap_fraction: float = math.inf,
    point: float = 1e-5,
    contract_size: float = 100_000.0,
    trail_atr: float = 0.0,
    breakeven_atr: float = 0.0,
    breakeven_offset_points: float = 0.0,
    partial_atr: float = 0.0,
    partial_fraction: float = 0.5,
    max_bars: int = 0,
    max_daily_loss_pct: float = 0.0,
    max_drawdown_pct: float = 0.0,
    warmup_bars: int = 0,
    schedule: tuple[tuple[int, dict], ...] = (),
    signal: pd.Series | None = None,
) -> BacktestResult:
    """Run the single-symbol backtest on the canonical portfolio engine.

    The legacy numeric parameters (``point``, ``contract_size``,
    ``spread_points`` ...) are injected into the canonical models as an
    explicit broker :class:`SymbolSpec` and :class:`CostConfig`, so the
    wrapper needs no risk arithmetic of its own.  ``schedule`` (optional)
    carries walk-forward segment starts (engine convention: the params
    apply to the signal from that index on — pass ``oos_start - 1`` for
    entries from the OOS bar's open) and freezes the parameters per
    segment over the single continuous run.  ``warmup_bars`` blocks
    entries on bars ``[0, warmup_bars)`` (indicator warm-up only: the
    engine state stays at its initial values) — the fold-isolation
    primitive used by purged cross-validation.  Returns the historical
    :class:`BacktestResult` shape.
    """
    # ---------------- validation (legacy contract, unchanged) ------------
    if risk_percent <= 0:
        raise ValueError("risk_percent must be > 0")
    if not 0.0 < partial_fraction < 1.0:
        raise ValueError("partial_fraction must be in (0, 1)")
    if spread_points < 0 or slippage_points < 0 or commission_per_lot < 0 \
            or commission_min < 0:
        raise ValueError("costs must be >= 0")
    if max_gap_fraction <= 0:
        raise ValueError("max_gap_fraction must be > 0 (inf disables)")
    if warmup_bars < 0:
        raise ValueError("warmup_bars must be >= 0")

    if signal is not None:
        # DSL runtime parity seam: the precomputed series IS the
        # signal; registry defaults are inapplicable (an arbitrary
        # line label is allowed for attribution).
        merged = dict(params or {})
    else:
        merged = strategies.default_params(strategy_name)  # KeyError: unknown
        if params:
            merged.update(params)

    # ---- explicit broker context derived from the legacy parameters ------
    spec = SymbolSpec(
        name="BACKTEST",
        digits=max(1, round(-math.log10(point))) if point > 0 else 1,
        point=point,
        tick_size=point,
        # symmetric tick value: one tick of one lot moves point*contract
        # deposit currency (the EURUSD-style identity the legacy tests used)
        tick_value_loss=point * contract_size,
        contract_size=contract_size,
        volume_min=0.01,
        volume_max=max(max_lots, 0.01),
        volume_step=0.01,
        volume_limit=0.0,
        stops_level_points=0.0,
        freeze_level_points=0.0,
        currency_profit="USD",
        currency_deposit="USD",
    )
    costs = CostConfig(
        symbol=spec.name,
        spread_points=spread_points,
        slippage_points=slippage_points,
        commission_per_lot=commission_per_lot,
        commission_min=commission_min,
        swap_long_per_lot_day=swap_long_per_lot_day,
        swap_short_per_lot_day=swap_short_per_lot_day,
        max_gap_fraction=max_gap_fraction,
    )
    cfg = RunConfig(
        initial_capital=initial_capital,
        mode="netting",
        allow_short=allow_short,
        sizing_mode="risk_percent_equity",
        risk_value=risk_percent,
        max_lots=max_lots,
        trail_atr=trail_atr,
        breakeven_atr=breakeven_atr,
        breakeven_offset_points=breakeven_offset_points,
        partial_atr=partial_atr,
        partial_fraction=partial_fraction,
        max_bars=max_bars,
        max_daily_loss_pct=max_daily_loss_pct,
        max_drawdown_pct=max_drawdown_pct,
        warmup_bars=max(0, int(warmup_bars)),
        allow_signal_exit=False,  # legacy: flips never close a position
    )
    ins = Instrument(
        symbol=spec.name,
        strategy=strategy_name,
        df=df,
        costs=costs,
        spec=spec,
        profit_to_deposit=1.0,  # research contract: deposit-currency account
        params=merged,
        schedule=schedule,
        signal=signal,
    )
    result = PortfolioEngine(cfg).run([ins])

    # ---- map the canonical result onto the legacy container ---------------
    trades = result.trades[_TRADE_COLUMNS]
    equity = result.equity
    n = len(df)

    from .metrics import compute_metrics

    metrics = compute_metrics(
        equity,
        trades,
        periods_per_year=_periods_per_year(df.index),
    )
    config = {
        "initial_capital": initial_capital,
        "risk_percent": risk_percent,
        "max_lots": max_lots,
        "allow_short": allow_short,
        "spread_points": spread_points,
        "slippage_points": slippage_points,
        "commission_per_lot": commission_per_lot,
        "trail_atr": trail_atr,
        "breakeven_atr": breakeven_atr,
        "partial_atr": partial_atr,
        "max_bars": max_bars,
        "max_daily_loss_pct": max_daily_loss_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "warmup_bars": int(warmup_bars),
        "bars": int(n),
    }
    return BacktestResult(
        strategy=strategy_name,
        params=merged,
        config=config,
        trades=trades,
        equity=equity,
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _periods_per_year(index: pd.DatetimeIndex) -> float:
    """Approximate bars per year from the median bar spacing."""
    if len(index) < 2:
        return 252.0
    delta = index.to_series().diff().dt.total_seconds().median()
    if pd.isna(delta) or delta <= 0:
        return 252.0
    return 365.25 * 24 * 3600 / delta


def _jsonable(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value
