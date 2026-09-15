"""mql5bot.engine — canonical portfolio backtest engine (Phases 1/4/5).

This is the deterministic multi-position engine: multi-symbol,
multi-strategy, simultaneous positions with netting or hedging semantics.
The legacy single-position ``mql5bot.backtest`` remains the research work
horse for strategy screens; this engine is the canonical portfolio core.

CANONICAL RULES
===============

Risk (Phase 1)
  * Position sizing ALWAYS goes through ``mql5bot.sizer.size_position``
    with an injected :class:`~mql5bot.symbolspec.SymbolSpec`; there is NO
    ``risk / (stop_distance * contract_size)`` formula anywhere in this
    module (guarded by tests).  Stop distances are enforced to the broker
    stops level and the tick grid before sizing.
  * PnL valuation is tick-based: unfavourable moves use
    ``tick_value_loss``, favourable moves the profit-side tick value (the
    loss-side value when the spec is symmetric), and the profit -> deposit
    conversion is applied per leg.  The price-continuous convention of the
    legacy engine is exactly recovered when
    ``tick_value == tick_size * contract_size`` and conversion is 1.0.

Costs (Phase 2)
  * Every fill is priced by ``mql5bot.costs`` — fixed or per-bar variable
    spread (bar open is the mid), adverse slippage on every fill,
    per-side (or per-round-trip) commission with an optional
    per-execution minimum, swap charged at server-day boundaries (per 1.0
    lot per server day), optional gap rejection and deterministic
    per-bar reject masks.  All charges are explicit in trade rows and
    cash flow; nothing is hidden in formulas.
  * Stop-loss / take-profit fills follow the costs module conventions
    (stop first when a bar touches both — conservative; gap-through fills
    at the open; stop fills carry adverse slippage, TP fills do not).
    Manual exits (limits, signals, offsets, end of data) cross the spread
    via ``exit_fill``.  Books opened at a bar's open are also resolved
    intrabar on that same bar.
  * Trade rows report net ``pnl`` (all charges deducted) plus two ledger
    columns: ``fees`` (entry + exit commission shares plus the allocated
    swap) and ``costs`` (``fees`` + the tick-valued spread/slippage drag
    of both executions against the raw quote levels — gap-through fills
    count their gap, favourable limit fills can reduce it).  Costs are
    signed so per-window/per-strategy cost accounting is possible without
    replaying fills.

Positions (Phase 4)
  * One trading line per (symbol, strategy).  Instruments must share a
    single aligned DatetimeIndex; unaligned frames raise (no silent
    resampling).  Duplicate (symbol, strategy) lines are rejected.
  * Exposure controls are explicit: max total positions, per-strategy max
    positions, per-symbol notional share of equity, correlation-group
    notional cap, profit-currency exposure cap and portfolio heat (gross
    notional / equity).  They are evaluated on the *post-action* exposure
    and rejections are recorded as events, never silent.
  * Per-strategy risk overrides (sizing mode, value, max lots, max open
    positions) layer on the run defaults.

Netting / hedging (Phase 5)
  * ``netting``: one book per symbol.  A same-side desired from a
    strategy with no open leg merges into the book — the leg keeps its own
    entry (attribution) while the book SL/TP becomes the lots-weighted
    average of the legs' levels (a netting account holds one SL/TP).  An
    opposite-side desired offsets legs FIFO at the open; any remainder
    opens as a fresh book.
  * ``hedging``: independent books per (symbol, strategy); opposite
    positions on one symbol coexist up to the exposure caps.
  * ``allow_signal_exit`` (default on): a strategy whose desired position
    flips or goes flat closes its own legs at the market.  In netting its
    own leg volume is closed first; other strategies' legs are only
    touched when its new opposite exposure offsets them FIFO.

Timing / lookahead
  * Signals are desired positions computed from closed bars and act at
    the NEXT bar's open.  Trailing/breakeven/partial updates use the
    previous bar's close and ATR — a bar's own close never influences its
    intrabar stop resolution.  Level updates skip the bar a book was
    opened on; entries and scale-outs are filled at the bar's open.
  * Per-bar order: (1) day rollover on the first bar of a new server day
    (swap charged on carried books, day-start equity snapshotted at the
    prior close, daily-loss lock lifted); (2) risk checks at the OPEN on
    the equity known from the previous close — a daily-loss or
    max-drawdown breach force-closes every book at the open fill
    (daily-loss first, drawdown second on the post-close basis) and
    blocks new trades until the next day reset / forever; (3) open-gap
    exits, then book reconciliation against the previous bar's desired
    signal at the open (signal exits, FIFO offsets, merges, entries —
    sized on the prior-close equity); (4) intrabar stop/TP resolution and
    max-bars for every open book; (5) end-of-bar equity = cash + close
    marks.

Daily resets (Phase 3)
  * Server-time day boundaries come from :class:`mql5bot.dayclock.DayClock`
    (configurable reset hour/minute, DST-safe).  Swap is charged at the
    boundary and the daily-loss limit snapshots day-start equity with EA
    semantics: one ``max_daily_loss_pct`` breach halts NEW trades until
    the next server-day reset.  Known simplification: swap is charged per
    day boundary present in the data (broker weekend/triple-swap
    schedules belong to the TRUTH side of the research loop).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import strategies
from .costs import (
    REASON_DAILY_LOSS_LIMIT,
    REASON_END_OF_DATA,
    REASON_GAP_SKIPPED,
    REASON_MAX_BARS,
    REASON_MAX_DRAWDOWN,
    REASON_MERGE_OFFSET,
    REASON_NO_VALID_STOP,
    REASON_REJECTED,
    REASON_SIGNAL_EXIT,
    REASON_STOP_LOSS,
    REASON_TAKE_PROFIT,
    CostConfig,
    commission_cash,
    entry_fill,
    exit_fill,
    gap_blocks,
    stop_fill,
    swap_charge,
    tp_fill,
)
from .dayclock import DayClock, server_day_ids
from .indicators import atr as atr_indicator
from .sizer import RISK_PERCENT_EQUITY, SIZING_MODES, size_position
from .specs import synthetic_profit_to_deposit, synthetic_spec
from .symbolspec import SymbolSpec, enforce_min_stop, round_to_tick

MODE_NETTING = "netting"
MODE_HEDGING = "hedging"

REASON_PARTIAL_EXIT = "partial_exit"  # scale-out at partial_atr (engine-only)

EXIT_REASONS = (
    REASON_STOP_LOSS,
    REASON_TAKE_PROFIT,
    REASON_MAX_BARS,
    REASON_DAILY_LOSS_LIMIT,
    REASON_MAX_DRAWDOWN,
    REASON_END_OF_DATA,
    REASON_SIGNAL_EXIT,
    REASON_MERGE_OFFSET,
    REASON_PARTIAL_EXIT,
)


# ---------------------------------------------------------------------------
# Public configuration objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Instrument:
    """One (symbol, strategy) trading line with its broker/cost context.

    ``df`` must carry a DatetimeIndex aligned with every other instrument
    of the run.  ``spec`` defaults to the canonical synthetic fixture for
    ``symbol`` and ``profit_to_deposit`` to its fixture conversion — live
    research must inject real broker specs/conversions instead.
    """

    symbol: str
    strategy: str
    df: pd.DataFrame
    costs: CostConfig | None = None
    spec: SymbolSpec | None = None
    profit_to_deposit: float | None = None
    corr_group: str = ""
    margin_calc: object | None = None  # Callable[[float], float] | None
    params: dict | None = None  # run-wide signal params (over registry defaults)
    # Precomputed desired-position series (DSL runtime parity seam): when
    # set it IS the signal — the registry lookup is skipped and
    # ``schedule`` is inapplicable (a DSL spec is already the resolved
    # semantics).  Values must be in {-1, 0, +1} on the frame's index.
    signal: pd.Series | None = None
    schedule: tuple[tuple[int, dict], ...] = ()  # (start_index, params)
    # Meta allocation seam (contract 1.1.1 §5.2): (effective_from, weight)
    # step function.  At every entry the Risk-Engine-approved lots are
    # scaled reduce-only by the weight effective at the bar's open, then
    # floored to the volume grid and DROPPED below the broker minimum —
    # exactly the MQL5 EA seam.  Weights are clamped to [0, 1].
    allocation_schedule: tuple[tuple[pd.Timestamp, float], ...] = ()

    def resolved_spec(self) -> SymbolSpec:
        if self.spec is not None:
            return self.spec
        return synthetic_spec(self.symbol)

    def resolved_conversion(self) -> float:
        if self.profit_to_deposit is not None:
            return self.profit_to_deposit
        return synthetic_profit_to_deposit(self.symbol)

    def resolved_costs(self) -> CostConfig:
        if self.costs is not None:
            return self.costs
        return CostConfig(symbol=self.symbol)


@dataclass
class StrategyRisk:
    """Per-strategy risk overrides (defaults live on RunConfig)."""

    mode: str | None = None  # one of mql5bot.sizer.SIZING_MODES
    value: float | None = None  # % equity / fixed money / fixed lots
    max_lots: float | None = None
    max_open_positions: int | None = None


@dataclass
class RunConfig:
    """Portfolio run configuration — every limit is explicit."""

    initial_capital: float = 10_000.0
    mode: str = MODE_NETTING
    allow_short: bool = True
    # sizing defaults
    sizing_mode: str = RISK_PERCENT_EQUITY
    risk_value: float = 1.0  # % of equity in the default risk mode
    max_lots: float = 100.0
    strategy_risk: dict[str, StrategyRisk] = field(default_factory=dict)
    # exposure caps (notional in deposit currency)
    max_total_positions: int = 10
    per_symbol_max_notional_share: float = float("inf")
    portfolio_heat_max: float = float("inf")
    corr_group_max_notional_share: dict[str, float] = field(default_factory=dict)
    currency_max_notional_share: dict[str, float] = field(default_factory=dict)
    # exits
    trail_atr: float = 0.0
    breakeven_atr: float = 0.0
    breakeven_offset_points: float = 0.0
    partial_atr: float = 0.0
    partial_fraction: float = 0.5
    max_bars: int = 0
    allow_signal_exit: bool = True
    # risk stops
    max_daily_loss_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    # fold-isolation support (CPCV): bars [0, warmup_bars) compute signals
    # (indicator history) but open NO positions — state stays at its
    # initial values until ``warmup_bars``.  Used by fold-isolated
    # cross-validation so a scored span's state derives only from data
    # allowed by the fold (see docs/CV_STATE_CONTRACT.md).
    warmup_bars: int = 0
    clock: DayClock = field(default_factory=DayClock)

    def validate(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be > 0")
        if self.mode not in (MODE_NETTING, MODE_HEDGING):
            raise ValueError(f"mode must be netting|hedging, got {self.mode!r}")
        if self.sizing_mode not in SIZING_MODES:
            raise ValueError(f"sizing_mode must be one of {SIZING_MODES}")
        if not 0.0 < self.partial_fraction < 1.0:
            raise ValueError("partial_fraction must be in (0, 1)")
        if self.max_total_positions < 1:
            raise ValueError("max_total_positions must be >= 1")
        if self.portfolio_heat_max <= 0 or self.per_symbol_max_notional_share <= 0:
            raise ValueError("notional caps must be > 0")
        if any(v <= 0 for v in self.corr_group_max_notional_share.values()):
            raise ValueError("corr-group notional caps must be > 0")
        if any(v <= 0 for v in self.currency_max_notional_share.values()):
            raise ValueError("currency notional caps must be > 0")
        if self.warmup_bars < 0:
            raise ValueError("warmup_bars must be >= 0")
        self.clock.validate()


@dataclass
class EngineResult:
    """Portfolio run result: trade rows, equity/notional curves, events."""

    config: dict = field(default_factory=dict)
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    equity: pd.Series = field(default_factory=pd.Series)
    notional: pd.Series = field(default_factory=pd.Series)
    events: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        eq = self.equity
        step = max(1, math.ceil(len(eq) / 1500))
        eq_ds = eq.iloc[::step]
        return {
            "config": self.config,
            "metrics": {k: _jsonable(v) for k, v in self.metrics.items()},
            "equity": {
                "time": [str(t) for t in eq_ds.index],
                "value": [float(v) for v in eq_ds.values],
            },
            "notional": {
                "time": [str(t) for t in eq_ds.index],
                "value": [float(v) for v in self.notional.iloc[::step].values],
            },
            "trades": self.trades.to_dict(orient="records"),
            "events": [_jsonable(e) for e in self.events],
        }


# ---------------------------------------------------------------------------
# Internal bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class _Leg:
    """One strategy's share of a book, with its own entry (attribution)."""

    strategy: str
    lots: float
    entry_price: float
    entry_index: int
    entry_fee: float = 0.0  # commission charged at open (deposit ccy)
    swap_fee: float = 0.0  # swap share allocated so far (deposit ccy)


@dataclass
class _Book:
    """One broker position: a netting book (>=1 legs) or a hedging leg."""

    ins: int
    symbol: str
    side: int
    lots: float
    entry_price: float  # lots-weighted average entry (book thresholds)
    entry_index: int
    sl: float
    tp: float
    legs: list[_Leg] = field(default_factory=list)
    bars_held: int = 0
    partial_done: bool = False
    be_done: bool = False


class _Line:
    """Precomputed state for one instrument: data, spec, costs, signal."""

    def __init__(self, ins: Instrument, n: int):
        self.ins = ins
        self.spec = ins.resolved_spec()
        self.conv = ins.resolved_conversion()
        self.costs = ins.resolved_costs()
        self.df = ins.df
        self.o = ins.df["open"].to_numpy(dtype=float)
        self.h = ins.df["high"].to_numpy(dtype=float)
        self.l = ins.df["low"].to_numpy(dtype=float)
        self.c = ins.df["close"].to_numpy(dtype=float)
        self.atr = np.asarray(atr_indicator(self.h, self.l, self.c, 14), dtype=float)
        self.desired = self._desired_series(n)
        self.point = self.spec.point
        self.alloc_ts = np.asarray(
            [pd.Timestamp(t).value for t, _ in ins.allocation_schedule],
            dtype=np.int64)
        self.alloc_w = np.asarray(
            [float(w) for _, w in ins.allocation_schedule], dtype=float)

    def scale_at(self, bar: int) -> float:
        """Meta allocation weight effective at ``bar``'s open (1.0 when no
        schedule; clamped to [0, 1]; the latest entry with
        ``effective_from <= bar open`` applies)."""
        if len(self.alloc_ts) == 0:
            return 1.0
        idx = int(np.searchsorted(self.alloc_ts,
                                  self.df.index[bar].value,
                                  side="right")) - 1
        if idx < 0:
            return 1.0
        return float(min(1.0, max(0.0, self.alloc_w[idx])))

    def params_at(self, bar: int) -> dict:
        """Strategy parameters effective at ``bar`` (frozen per segment)."""
        if self.ins.signal is not None:
            # precomputed-signal line (DSL runtime parity seam): the
            # params dict IS the effective set; no registry defaults
            merged = dict(self.ins.params or {})
        else:
            merged = strategies.default_params(self.ins.strategy)
            if self.ins.params:
                merged.update(self.ins.params)
        for start, params in sorted(self.ins.schedule):
            if bar >= start:
                merged.update(params or {})
        return merged

    def _desired_series(self, n: int) -> np.ndarray:
        ins = self.ins
        if ins.signal is not None:
            sig = ins.signal
            if len(sig) != n:
                raise ValueError(
                    f"precomputed signal length {len(sig)} != frame "
                    f"length {n}")
            return np.asarray(sig.to_numpy(), dtype=int).copy()
        out = strategies.signal(ins.df, ins.strategy,
                                ins.params or None).to_numpy(
                                    dtype=int, copy=True)
        if not ins.schedule:
            return out
        # walk-forward schedule: params (and so the signal) freeze per
        # segment from each start index on; bars before the first schedule
        # start keep the base-strategy signal.
        for start, params in sorted(ins.schedule):
            seg = dict(ins.params) if ins.params else {}
            seg.update(params or {})
            sig = strategies.signal(ins.df, ins.strategy,
                                    seg).to_numpy(dtype=int, copy=True)
            out[start:] = sig[start:]
        return out


# ---------------------------------------------------------------------------
# Pure valuation helpers
# ---------------------------------------------------------------------------


def leg_cash(
    side: int,
    lots: float,
    entry: float,
    price: float,
    spec: SymbolSpec,
    conv: float,
) -> float:
    """Realised/unrealised cash of one leg moved from ``entry`` to ``price``
    (deposit currency).  Tick-valued: whole ticks x per-tick value x lots.
    A favourable move (``side * (price - entry) > 0``) is valued with the
    profit-side tick value when the spec injects one."""
    move = side * (price - entry)
    ticks = round(abs(price - entry) / spec.tick_size)
    if move == 0.0 or ticks <= 0 or lots == 0.0:
        # sub-tick residuals (incl. float noise on equal prices) are not
        # tradable moves and generate no PnL (tick-quantised valuation)
        return 0.0
    value = spec.tick_value(side, price - entry)
    return math.copysign(1.0, move) * ticks * value * conv * lots


def _notional_deposit(lots: float, price: float, spec: SymbolSpec,
                      conv: float) -> float:
    return abs(lots) * spec.contract_size * price * conv


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
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

TRADE_COLUMNS = [
    "symbol", "strategy", "side", "entry_time", "exit_time",
    "entry_price", "exit_price", "lots", "bars_held",
    "pnl", "pnl_pct", "fees", "costs", "exit_reason",
]


class PortfolioEngine:
    """Deterministic portfolio backtester (module docstring = contract)."""

    def __init__(self, config: RunConfig | None = None):
        self.cfg = config or RunConfig()
        self.cfg.validate()

    # -- public API -------------------------------------------------------
    def run(self, instruments: list[Instrument]) -> EngineResult:
        cfg = self.cfg
        if not instruments:
            raise ValueError("at least one instrument required")
        self._validate_instruments(instruments)
        n = len(instruments[0].df.index)
        index = instruments[0].df.index
        lines = [_Line(ins, n) for ins in instruments]

        cash = float(cfg.initial_capital)
        equity = np.empty(n)
        notional = np.empty(n)
        books: list[_Book] = []
        trades: list[dict] = []
        events: list[dict] = []
        peak = float(cfg.initial_capital)
        basis = float(cfg.initial_capital)  # equity reference for checks/sizing
        day_halted = False
        dd_halted = False
        day_start_equity = float(cfg.initial_capital)
        day_ids = server_day_ids(index, cfg.clock)

        def charge(fee: float) -> None:
            """Subtract an execution fee from cash (mutates the closure)."""
            nonlocal cash
            cash -= fee

        def event(bar: int, etype: str, code: str = "", **extra) -> None:
            row: dict = {"bar": int(bar), "time": str(index[bar]), "type": etype}
            if code:
                row["code"] = code
            for k, v in extra.items():
                row[k] = _jsonable(v)
            events.append(row)

        def line_of(book_or_symbol) -> _Line:
            if isinstance(book_or_symbol, _Book):
                return lines[book_or_symbol.ins]
            for ln in lines:
                if ln.ins.symbol == book_or_symbol:
                    return ln
            raise KeyError(book_or_symbol)  # pragma: no cover

        def fill_entry(ln: _Line, bar: int, side: int) -> float:
            # tick-rounded: executions sit on the broker's price grid
            return round_to_tick(entry_fill(ln.o[bar], side,
                                            ln.costs.spread_at(bar),
                                            ln.costs.slippage_points,
                                            ln.point), ln.spec)

        def fill_exit(ln: _Line, bar: int, side: int, price: float) -> float:
            return round_to_tick(exit_fill(price, side,
                                           ln.costs.spread_at(bar),
                                           ln.costs.slippage_points,
                                           ln.point), ln.spec)

        # -- PnL / accounting ---------------------------------------------
        def mark_books(bar: int) -> float:
            total = cash
            for b in books:
                ln = lines[b.ins]
                for leg in b.legs:
                    total += leg_cash(b.side, leg.lots, leg.entry_price,
                                      ln.c[bar], ln.spec, ln.conv)
            return total

        def book_notional(b: _Book, price: float) -> float:
            ln = lines[b.ins]
            return _notional_deposit(b.lots, price, ln.spec, ln.conv)

        def _row(bar: int, b: _Book, leg: _Leg, take: float, fill: float,
                 reason: str, entry_fee_share: float, swap_share: float,
                 fee_share: float, quote: float) -> dict:
            ln = lines[b.ins]
            pnl = leg_cash(b.side, take, leg.entry_price, fill, ln.spec, ln.conv)
            pnl_net = pnl - entry_fee_share - swap_share - fee_share
            # execution costs vs the raw quote levels, tick-valued:
            # entries fill at open +/- surcharge; stops fill worse by
            # slippage (gap fills at the open), TPs fill at the level.
            cost_entry = leg_cash(b.side, take, ln.o[leg.entry_index],
                                  leg.entry_price, ln.spec, ln.conv)
            cost_exit = leg_cash(b.side, take, fill, quote,
                                 ln.spec, ln.conv)
            fees = entry_fee_share + swap_share + fee_share
            return {
                "symbol": b.symbol,
                "strategy": leg.strategy,
                "side": "long" if b.side > 0 else "short",
                "entry_time": str(index[leg.entry_index]),
                "exit_time": str(index[bar]),
                "entry_price": round(float(leg.entry_price), 8),
                "exit_price": round(float(fill), 8),
                "lots": round(float(take), 12),
                "bars_held": int(bar - leg.entry_index),
                "pnl": round(float(pnl_net), 8),
                "pnl_pct": round(float(pnl_net) / cfg.initial_capital * 100.0, 8),
                "fees": round(float(fees), 8),
                "costs": round(float(fees + cost_entry + cost_exit), 8),
                "exit_reason": reason,
            }

        def close_slices(book: _Book, volume: float, fill: float, reason: str,
                         bar: int, exit_fee: float, quote: float) -> None:
            """Close ``volume`` lots of ``book`` FIFO across its legs,
            emitting one trade row per leg slice.  Realised PnL lands in
            cash; ``exit_fee`` (this execution's exit commission) is split
            across slices pro-rata; entry/swap fees follow the volume."""
            nonlocal cash
            ln = lines[book.ins]
            realized = 0.0
            remaining = float(volume)
            for leg in list(book.legs):
                if remaining <= 1e-12:
                    break
                take = min(leg.lots, remaining)
                share = take / leg.lots if leg.lots > 0 else 0.0
                e_fee = leg.entry_fee * share
                s_fee = leg.swap_fee * share
                fee = exit_fee * (take / volume) if volume > 0 else 0.0
                pnl = leg_cash(book.side, take, leg.entry_price, fill,
                               ln.spec, ln.conv)
                realized += pnl
                trades.append(_row(bar, book, leg, take, fill, reason,
                                   e_fee, s_fee, fee, quote))
                if take >= leg.lots - 1e-12:
                    book.legs.remove(leg)
                else:
                    leg.lots -= take
                    leg.entry_fee -= e_fee
                    leg.swap_fee -= s_fee
                remaining -= take
            book.lots -= volume
            cash += realized  # realised PnL (signed); fees are charged below
            charge(exit_fee)
            if book.lots <= 1e-12 and book in books:
                books.remove(book)

        def close_whole_book(book: _Book, bar: int, reason: str,
                             fill: float, quote: float) -> None:
            """Close the entire book at an already-computed fill price."""
            ln = lines[book.ins]
            close_slices(book, book.lots, fill, reason, bar,
                         commission_cash(book.lots, ln.costs), quote)

        def close_strategy_legs(book: _Book, strategy: str, bar: int,
                                reason: str, quote: float | None = None) -> float:
            """Close every leg of ``strategy`` in ``book`` at the bar's
            open-based exit price.  Returns the closed volume."""
            nonlocal cash
            ln = lines[book.ins]
            targets = [leg for leg in book.legs if leg.strategy == strategy]
            if not targets:
                return 0.0
            volume = sum(leg.lots for leg in targets)
            if quote is None:
                quote = ln.o[bar]
            fill = fill_exit(ln, bar, book.side, quote)
            fee = commission_cash(volume, ln.costs)
            realized = sum(leg_cash(book.side, leg.lots, leg.entry_price,
                                    fill, ln.spec, ln.conv) for leg in targets)
            for leg in targets:
                share = leg.lots / volume if volume > 0 else 0.0
                trades.append(_row(bar, book, leg, leg.lots, fill, reason,
                                   leg.entry_fee, leg.swap_fee, fee * share,
                                   quote))
                book.legs.remove(leg)
            book.lots -= volume
            cash += realized  # realised PnL (signed); fees are charged below
            charge(fee)
            if book.lots <= 1e-12 and book in books:
                books.remove(book)
            return volume

        # -- sizing --------------------------------------------------------
        def size_lots(ln: _Line, side: int, equity_ref: float,
                      bar: int) -> tuple[float, str]:
            """Canonical sizing via mql5bot.sizer.  Returns ``(lots, reason)``
            with ``lots == 0.0`` when the order must not trade."""
            a = ln.atr[bar - 1] if bar >= 1 else np.nan
            if not np.isfinite(a) or a <= 0.0:
                return 0.0, REASON_NO_VALID_STOP
            params = ln.params_at(bar)
            sl_dist = float(params.get("sl_atr", 2.0)) * a
            if sl_dist <= 0.0:
                return 0.0, REASON_NO_VALID_STOP
            srisk = cfg.strategy_risk.get(ln.ins.strategy)
            mode = (srisk.mode if srisk is not None and srisk.mode
                    else cfg.sizing_mode)
            value = (srisk.value if srisk is not None
                     and srisk.value is not None else cfg.risk_value)
            cap = cfg.max_lots
            if srisk is not None and srisk.max_lots is not None:
                cap = min(cap, srisk.max_lots)
            margin = ln.ins.margin_calc if callable(ln.ins.margin_calc) else None
            result = size_position(
                ln.spec,
                mode=mode,
                equity=equity_ref,
                balance=equity_ref,
                stop_distance=sl_dist,
                value=value,
                profit_to_deposit=ln.conv,
                max_lots=cap,
                margin_calc=margin,
                free_margin=equity_ref if margin is not None else None,
            )
            return (result.lots if not result.rejected else 0.0), result.reason

        def fresh_levels(ln: _Line, bar: int, side: int,
                         entry_price: float) -> tuple[float, float]:
            """(sl, tp) absolute prices for a fresh order, tick-rounded and
            stops-level enforced (same enforcement the sizer used)."""
            params = ln.params_at(bar)
            a = ln.atr[bar - 1]
            sl_dist = enforce_min_stop(float(params.get("sl_atr", 2.0)) * a,
                                       ln.spec)
            tp_dist = enforce_min_stop(float(params.get("tp_atr", 4.0)) * a,
                                       ln.spec)
            return (round_to_tick(entry_price - side * sl_dist, ln.spec),
                    round_to_tick(entry_price + side * tp_dist, ln.spec))

        # -- exposure caps --------------------------------------------------
        def symbol_books(symbol: str) -> list[_Book]:
            return [b for b in books if b.symbol == symbol]

        def caps_allow(bar: int, symbol: str, strategy: str, lots: float,
                       equity_ref: float, *, adds_book: bool) -> tuple[bool, str]:
            """Exposure caps evaluated on the post-action portfolio: the
            books that exist at the call (offsets must already be closed)
            plus the ``lots`` being added."""
            ln = line_of(symbol)
            price = ln.o[bar]  # decisions at the open use the open price
            delta = _notional_deposit(lots, price, ln.spec, ln.conv)
            if delta <= 1e-12:
                return True, ""  # nothing added: no cap headroom needed
            if adds_book and len(books) >= cfg.max_total_positions:
                return False, "max_total_positions"
            srisk = cfg.strategy_risk.get(strategy)
            if (adds_book and srisk is not None
                    and srisk.max_open_positions is not None):
                open_for = sum(
                    1 for b in books
                    if any(leg.strategy == strategy for leg in b.legs))
                if open_for >= srisk.max_open_positions:
                    return False, "max_strategy_positions"
            if (sum(book_notional(b, price) for b in symbol_books(symbol)) + delta
                    > cfg.per_symbol_max_notional_share * equity_ref):
                return False, "per_symbol_notional"
            g = ln.ins.corr_group
            if g in cfg.corr_group_max_notional_share:
                group_notional = sum(
                    book_notional(b, price) for b in books
                    if lines[b.ins].ins.corr_group == g)
                if (group_notional + delta
                        > cfg.corr_group_max_notional_share[g] * equity_ref):
                    return False, "corr_group_notional"
            ccy = ln.spec.currency_profit
            if ccy in cfg.currency_max_notional_share:
                ccy_notional = sum(
                    book_notional(b, price) for b in books
                    if lines[b.ins].spec.currency_profit == ccy)
                if (ccy_notional + delta
                        > cfg.currency_max_notional_share[ccy] * equity_ref):
                    return False, "currency_notional"
            heat = sum(book_notional(b, price) for b in books)
            if heat + delta > cfg.portfolio_heat_max * equity_ref:
                return False, "portfolio_heat"
            return True, ""

        # -- opening --------------------------------------------------------
        def open_order(ln: _Line, bar: int, side: int, lots: float,
                       equity_ref: float,
                       meta_weight: float = 1.0) -> bool:
            """Open, merge into, or offset against the symbol's book."""
            if bar >= 1 and gap_blocks(ln.o[bar], ln.c[bar - 1], ln.costs):
                event(bar, "reject", REASON_GAP_SKIPPED, symbol=ln.ins.symbol,
                      strategy=ln.ins.strategy, lots=lots)
                return False
            if ln.costs.rejects(bar):
                event(bar, "reject", REASON_REJECTED, symbol=ln.ins.symbol,
                      strategy=ln.ins.strategy, lots=lots)
                return False
            fill = fill_entry(ln, bar, side)
            sl, tp = fresh_levels(ln, bar, side, fill)
            existing = symbol_books(ln.ins.symbol)
            book = existing[0] if cfg.mode == MODE_NETTING and existing else None

            if book is not None and book.side != side:
                # opposite side: FIFO offset; remainder opens a fresh book
                vol = min(book.lots, lots)
                fill_x = fill_exit(ln, bar, book.side, ln.o[bar])
                close_slices(book, vol, fill_x, REASON_MERGE_OFFSET, bar,
                             commission_cash(vol, ln.costs), ln.o[bar])
                remainder = lots - vol
                event(bar, "offset", code=REASON_MERGE_OFFSET,
                      symbol=ln.ins.symbol, strategy=ln.ins.strategy,
                      lots=vol)
                if remainder <= 1e-12:
                    return True
                # the offset already closed; caps evaluate the remainder as
                # the book it leaves behind (post-action exposure)
                ok, code = caps_allow(bar, ln.ins.symbol, ln.ins.strategy,
                                      remainder, equity_ref, adds_book=True)
                if not ok:
                    event(bar, "reject", code, symbol=ln.ins.symbol,
                          strategy=ln.ins.strategy, lots=remainder)
                    return False
                new_book = _Book(ins=lines.index(ln), symbol=ln.ins.symbol,
                                 side=side, lots=remainder, entry_price=fill,
                                 entry_index=bar, sl=sl, tp=tp)
                fee = commission_cash(remainder, ln.costs)
                new_book.legs.append(_Leg(strategy=ln.ins.strategy,
                                          lots=remainder, entry_price=fill,
                                          entry_index=bar, entry_fee=fee))
                books.append(new_book)
                charge(fee)
                event(bar, "open", symbol=ln.ins.symbol,
                      strategy=ln.ins.strategy, lots=remainder, side=side,
                      meta_weight=meta_weight)
                return True

            if book is not None:
                # same side: merge into the netting book
                ok, code = caps_allow(bar, ln.ins.symbol, ln.ins.strategy,
                                      lots, equity_ref, adds_book=False)
                if not ok:
                    event(bar, "reject", code, symbol=ln.ins.symbol,
                          strategy=ln.ins.strategy, lots=lots)
                    return False
                old = book.lots
                new = old + lots
                fee = commission_cash(lots, ln.costs)
                leg = _Leg(strategy=ln.ins.strategy, lots=lots,
                           entry_price=fill, entry_index=bar, entry_fee=fee)
                book.sl = (old * book.sl + lots * sl) / new
                book.tp = (old * book.tp + lots * tp) / new
                book.entry_price = (old * book.entry_price + lots * fill) / new
                book.lots = new
                book.legs.append(leg)
                charge(fee)
                event(bar, "merge", symbol=ln.ins.symbol,
                      strategy=ln.ins.strategy, lots=lots,
                      sl=book.sl, tp=book.tp, meta_weight=meta_weight)
                return True

            # fresh book (hedging, or first exposure on the symbol)
            ok, code = caps_allow(bar, ln.ins.symbol, ln.ins.strategy, lots,
                                  equity_ref, adds_book=True)
            if not ok:
                event(bar, "reject", code, symbol=ln.ins.symbol,
                      strategy=ln.ins.strategy, lots=lots)
                return False
            new_book = _Book(ins=lines.index(ln), symbol=ln.ins.symbol,
                             side=side, lots=lots, entry_price=fill,
                             entry_index=bar, sl=sl, tp=tp)
            fee = commission_cash(lots, ln.costs)
            new_book.legs.append(_Leg(strategy=ln.ins.strategy, lots=lots,
                                      entry_price=fill, entry_index=bar,
                                      entry_fee=fee))
            books.append(new_book)
            charge(fee)
            event(bar, "open", symbol=ln.ins.symbol,
                  strategy=ln.ins.strategy, lots=lots, side=side,
                  meta_weight=meta_weight)
            return True

        # -- reconciliation (entries / flips / offsets at the open) ---------
        def reconcile(bar: int) -> None:
            nonlocal basis
            if basis <= 0.0:
                return
            for ln in lines:
                side = int(ln.desired[bar - 1])
                if side < 0 and not cfg.allow_short:
                    side = 0
                my_books = [
                    b for b in books if b.symbol == ln.ins.symbol
                    and any(leg.strategy == ln.ins.strategy for leg in b.legs)
                ]
                if my_books:
                    held_side = my_books[0].side
                    if side == held_side:
                        continue  # desired direction already open
                    if not cfg.allow_signal_exit:
                        continue  # hands-off: only SL/TP/max-bars exits
                    for b in list(my_books):
                        close_strategy_legs(b, ln.ins.strategy, bar,
                                            REASON_SIGNAL_EXIT)
                    if side == 0:
                        continue  # went flat
                elif side == 0:
                    continue
                lots, reason = size_lots(ln, side, basis, bar)
                if lots <= 0.0:
                    if reason != REASON_NO_VALID_STOP:
                        # warm-up (no ATR yet) is silent, like the legacy loop
                        event(bar, "reject", reason, symbol=ln.ins.symbol,
                              strategy=ln.ins.strategy)
                    continue
                # Meta allocation seam (contract 1.1.1 §5.2 / ML-9): the
                # Risk Engine approved `lots`; the allocation weight may
                # only shrink it.  EA parity (Mql5Bot.mq5): floor the
                # scaled size to the broker step and DROP it entirely when
                # below the broker minimum — normalize_volume's min-bump
                # is a RISK-ENGINE sizing behavior and is deliberately NOT
                # used here (bumping would exceed the meta decision).
                weight = ln.scale_at(bar)
                if weight < 1.0:
                    step = ln.spec.volume_step if ln.spec.volume_step > 0 \
                        else 0.01
                    scaled = math.floor(lots * weight / step + 1e-9) * step
                    if scaled < ln.spec.volume_min or scaled > lots + 1e-12:
                        event(bar, "reject", "meta_scale_dropped",
                              symbol=ln.ins.symbol,
                              strategy=ln.ins.strategy, lots=lots)
                        continue
                    lots = scaled
                open_order(ln, bar, side, lots, basis, meta_weight=weight)

        # -- per-book manage (intrabar exits, trail/be/partial, max-bars) ----
        def manage(bar: int) -> None:
            for b in list(books):  # noqa: PERF101 (snapshot: closers mutate)
                ln = lines[b.ins]
                b.bars_held += 1
                # level updates (trail/breakeven/partial) use the PREVIOUS
                # close and ATR and only apply to carried books; a book
                # opened at this bar's open is first managed next bar.
                a = ln.atr[bar - 1] if bar >= 1 else np.nan
                if (b.entry_index < bar and np.isfinite(a) and a > 0.0):
                    prev_c = ln.c[bar - 1]
                    if cfg.trail_atr > 0.0:
                        if b.side > 0:
                            b.sl = max(b.sl, prev_c - cfg.trail_atr * a)
                        else:
                            b.sl = min(b.sl, prev_c + cfg.trail_atr * a)
                    if (cfg.breakeven_atr > 0.0 and not b.be_done
                            and b.side * (prev_c - b.entry_price)
                            >= cfg.breakeven_atr * a):
                        b.sl = round_to_tick(
                            b.entry_price + b.side
                            * cfg.breakeven_offset_points * ln.point,
                            ln.spec)
                        b.be_done = True
                    if (cfg.partial_atr > 0.0 and not b.partial_done
                            and b.side * (prev_c - b.entry_price)
                            >= cfg.partial_atr * a):
                        vol = b.lots * cfg.partial_fraction
                        # scale-out acts at this bar's open, then the
                        # remainder is resolved intrabar with a breakeven SL
                        fill = fill_exit(ln, bar, b.side, ln.o[bar])
                        close_slices(b, vol, fill, REASON_PARTIAL_EXIT,
                                     bar, commission_cash(vol, ln.costs),
                                     ln.o[bar])
                        if b in books:
                            b.sl = round_to_tick(b.entry_price, ln.spec)
                            b.partial_done = True
                if b not in books:
                    continue
                # intrabar stop first (conservative), then take-profit
                hit_sl, fill_sl = stop_fill(ln.o[bar], ln.l[bar], ln.h[bar],
                                            b.side, b.sl, ln.costs, ln.point)
                if hit_sl:
                    close_whole_book(b, bar, REASON_STOP_LOSS, fill_sl, b.sl)
                    continue
                hit_tp, fill_tp = tp_fill(ln.o[bar], ln.l[bar], ln.h[bar],
                                          b.side, b.tp, ln.costs, ln.point)
                if hit_tp:
                    close_whole_book(b, bar, REASON_TAKE_PROFIT, fill_tp, b.tp)
                    continue
                if cfg.max_bars > 0 and b.bars_held >= cfg.max_bars:
                    close_whole_book(b, bar, REASON_MAX_BARS,
                                     fill_exit(ln, bar, b.side, ln.c[bar]),
                                     ln.c[bar])

        # -- open-gap exits (fill at the open BEFORE open-level actions) -----
        def open_gap_exits(bar: int) -> None:
            """Close any carried book whose stop/TP was gapped through at the
            bar's open (conservative: stop first when both could fill)."""
            for b in list(books):  # noqa: PERF101 (snapshot: closers mutate)
                if b.entry_index >= bar:
                    continue  # opened at this bar's open: not "carried"
                ln = lines[b.ins]
                if b.side > 0:
                    if ln.o[bar] <= b.sl:
                        close_whole_book(b, bar, REASON_STOP_LOSS, ln.o[bar],
                                         b.sl)
                    elif ln.o[bar] >= b.tp:
                        close_whole_book(b, bar, REASON_TAKE_PROFIT, ln.o[bar],
                                         b.tp)
                else:
                    if ln.o[bar] >= b.sl:
                        close_whole_book(b, bar, REASON_STOP_LOSS, ln.o[bar],
                                         b.sl)
                    elif ln.o[bar] <= b.tp:
                        close_whole_book(b, bar, REASON_TAKE_PROFIT, ln.o[bar],
                                         b.tp)

        # -- day rollover ----------------------------------------------------
        def rollover(bar: int) -> None:
            nonlocal day_halted, day_start_equity, basis
            if int(day_ids[bar]) == int(day_ids[bar - 1]):
                return
            # swap accrues at the boundary on carried books
            for b in books:
                ln = lines[b.ins]
                total = swap_charge(b.side, b.lots, ln.costs, 1)
                if total > 0.0:
                    charge(total)
                    for leg in b.legs:
                        leg.swap_fee += total * leg.lots / b.lots
            # day-start equity = prior close, net of that day's swap (EA
            # semantics: the snapshot is the equity carried into the day)
            basis = mark_books(bar - 1)
            day_start_equity = basis
            day_halted = False
            if cfg.max_daily_loss_pct > 0.0:
                event(bar, "day_reset", code="",
                      day_id=int(day_ids[bar]), day_start_equity=basis)

        # -- main loop --------------------------------------------------------
        for i in range(n):
            if i >= 1:
                rollover(i)  # swap + day-start snapshot + lift the day lock
                # Risk checks act at the OPEN of bar i on the equity known
                # from the previous close (no same-bar lookahead); a breach
                # force-closes everything at the open fill.  Daily-loss is
                # evaluated first, drawdown second on the post-close basis.
                lim = cfg.max_daily_loss_pct
                if (lim > 0.0 and not day_halted
                        and basis <= day_start_equity * (1.0 - lim / 100.0)):
                    for b in list(books):  # noqa: PERF101 (snapshot: closers mutate)
                        ln = lines[b.ins]
                        close_whole_book(b, i, REASON_DAILY_LOSS_LIMIT,
                                         fill_exit(ln, i, b.side, ln.o[i]),
                                         ln.o[i])
                    day_halted = True
                    basis = mark_books(i)
                    event(i, "halt", REASON_DAILY_LOSS_LIMIT, equity=basis)
                dd_lim = cfg.max_drawdown_pct
                if (dd_lim > 0.0 and not dd_halted
                        and basis <= peak * (1.0 - dd_lim / 100.0)):
                    for b in list(books):  # noqa: PERF101 (snapshot: closers mutate)
                        ln = lines[b.ins]
                        close_whole_book(b, i, REASON_MAX_DRAWDOWN,
                                         fill_exit(ln, i, b.side, ln.o[i]),
                                         ln.o[i])
                    dd_halted = True
                    basis = mark_books(i)
                    event(i, "halt", REASON_MAX_DRAWDOWN, equity=basis)

            if i >= max(1, cfg.warmup_bars) and not day_halted and not dd_halted:
                open_gap_exits(i)  # carried books first (fills at the open)
                reconcile(i)  # flips / offsets / merges / entries at the open
                manage(i)  # intrabar stops, max-bars, level updates

            equity[i] = mark_books(i)
            peak = max(peak, float(equity[i]))
            basis = float(equity[i])
            notional[i] = sum(book_notional(b, lines[b.ins].c[i]) for b in books)

        # close anything still open at the final close
        if books:
            last = n - 1
            for b in list(books):  # noqa: PERF101 (snapshot: closers mutate)
                ln = lines[b.ins]
                close_whole_book(b, last, REASON_END_OF_DATA,
                                 fill_exit(ln, last, b.side, ln.c[last]),
                                 ln.c[last])
            equity[last] = mark_books(last)
            notional[last] = 0.0

        from .metrics import compute_metrics

        trades_df = pd.DataFrame(trades, columns=TRADE_COLUMNS)
        equity_series = pd.Series(equity, index=index, name="equity")
        notional_series = pd.Series(notional, index=index, name="notional")
        metrics = compute_metrics(equity_series, trades_df,
                                  periods_per_year=_periods_per_year(index))
        config = {
            "mode": cfg.mode,
            "initial_capital": cfg.initial_capital,
            "sizing_mode": cfg.sizing_mode,
            "risk_value": cfg.risk_value,
            "max_lots": cfg.max_lots,
            "max_total_positions": cfg.max_total_positions,
            "allow_short": cfg.allow_short,
            "warmup_bars": int(cfg.warmup_bars),
            "instruments": [
                {"symbol": ins.symbol, "strategy": ins.strategy,
                 "corr_group": ins.corr_group}
                for ins in instruments
            ],
            "bars": int(n),
        }
        return EngineResult(config=config, trades=trades_df,
                            equity=equity_series, notional=notional_series,
                            events=events, metrics=metrics)

    # -- validation helpers --------------------------------------------------
    def _validate_instruments(self, instruments: list[Instrument]) -> None:
        first_index = instruments[0].df.index
        seen: set[tuple[str, str]] = set()
        for ins in instruments:
            if not isinstance(ins.df.index, pd.DatetimeIndex):
                raise TypeError(
                    f"{ins.symbol}::{ins.strategy}: index must be a DatetimeIndex")
            if not ins.df.index.equals(first_index):
                raise ValueError(
                    f"instrument {ins.symbol}::{ins.strategy} index is not "
                    "aligned with the other instruments (one shared "
                    "DatetimeIndex is required; align/resample first)")
            for col in ("open", "high", "low", "close"):
                if col not in ins.df.columns:
                    raise ValueError(
                        f"{ins.symbol}::{ins.strategy}: missing column {col!r}")
            key = (ins.symbol, ins.strategy)
            if key in seen:
                raise ValueError(f"duplicate (symbol, strategy) line: {key}")
            seen.add(key)
            ins.resolved_costs().validate(len(ins.df))
            if ins.schedule:
                self._validate_schedule(ins)

    def _validate_schedule(self, ins: Instrument) -> None:
        n = len(ins.df)
        starts = sorted(s for s, _ in ins.schedule)
        if not starts or starts[0] < 1 or starts[-1] >= n:
            raise ValueError("schedule start indexes must lie inside the frame")
        if len(starts) != len(set(starts)):
            raise ValueError("schedule start indexes must be unique")
