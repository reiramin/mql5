"""mql5bot.fast_engine — FAST screening engine (performance & selection
hardening, Phase C).

FAST is a NumPy-array re-implementation of the canonical engine's
ORCHESTRATION for the single-(symbol, strategy) netting screening case.
It deliberately reuses the canonical pure math (``mql5bot.sizer``,
``mql5bot.costs``, ``mql5bot.symbolspec`` rounding, the engine's own
``leg_cash`` valuation helper) so that **no accounting or sizing formula
is duplicated** — the single-owner rule of the canonical engine stays
intact.  Only the per-bar bookkeeping loop is re-written on plain
NumPy arrays/scalars (no pandas per-bar work), which is what makes
screening cheap.

``run_fast`` mirrors :func:`mql5bot.backtest.run_backtest`'s signature
parameter-for-parameter and returns the same
:class:`~mql5bot.backtest.BacktestResult` shape, so it is a drop-in for
grid / walk-forward / screening sweeps: every kwargs combination valid on
the TRUTH wrapper is valid here, and results are schema-identical.

Scope (everything else raises ``NotImplementedError`` — loud, never
silent):

* one instrument, netting mode (as built by the wrapper);
* market entries; fixed spread, slippage, commission; gap rejection;
* zero swap rates (swap accrual is a dayclock feature of the TRUTH path);
* legacy ``allow_signal_exit=False`` (flips never close) or engine-style
  ``allow_signal_exit=True`` signal exits — both mirror the engine;
* SL / TP / gap-through / max-bars / partial scale-out / breakeven /
  trailing exits; daily-loss and max-drawdown halts with the engine's
  exact timing (prior-close equity, act at the open; permanent);
* fold-isolation ``warmup_bars`` (entries blocked on ``[0, warmup)``
  — the CPCV primitive);
* no walk-forward schedule (WFA freeze is TRUTH-path), no margin
  calculator, no exposure caps, no per-strategy risk map.

IMPLEMENTATION SCOPE — measured, honestly stated (see
``docs/BENCHMARK_FAST.md``):

* **Array-based (NumPy, no per-bar pandas)**: OHLC extraction, the
  desired-signal series, ATR(14), spread/reject series (constant arrays
  in fixed-cost mode), server-day ids, equity/notional curves, and the
  timestamp strings (vectorised strftime when the index is
  whole-second; exact per-element conversion otherwise).
* **Python loops that REMAIN**: the per-bar event loop itself (risk
  checks, reconciliation, fills, position management) — one Python
  iteration per bar, per open trade and per trade row.  Fill/valuation
  helpers (``costs``, ``leg_cash``, ``size_position``, symbol rounding)
  are called per event, not vectorised: they are the single-owner
  accounting formulas shared with the TRUTH engine.
* **Numba is NOT used** (no JIT, no C extension): FAST is pure
  Python + NumPy.  Its speed comes from staying out of pandas per bar,
  hoisting per-book constants and a per-book ``leg_cash`` value cache
  that is fed by ``leg_cash`` itself (identical keys are bit-identical).
* Measured profile (30k bars): the per-bar loop, per-event fills and
  per-trade rows dominate; ``compute_metrics`` (pandas, shared with the
  TRUTH path) is a known non-FAST-specific cost and is intentionally
  left alone.

TRUTH ENGINE: ``mql5bot.engine.PortfolioEngine`` (and the real MT5
Strategy Tester via ``mt5tester.py``) remain the ONLY certification path.
FAST results are screening signals only — never final, never a profit
claim.  Equivalence with ``run_backtest`` on the supported subset is
pinned by ``tests/test_fast_engine.py`` on random fixtures.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import _TRADE_COLUMNS, BacktestResult
from .costs import (
    REASON_DAILY_LOSS_LIMIT,
    REASON_END_OF_DATA,
    REASON_MAX_BARS,
    REASON_MAX_DRAWDOWN,
    REASON_SIGNAL_EXIT,
    REASON_STOP_LOSS,
    REASON_TAKE_PROFIT,
    CostConfig,
    commission_cash,
    entry_fill,
    exit_fill,
    gap_blocks,
    stop_fill,
    tp_fill,
)
from .dayclock import DayClock, server_day_ids
from .engine import REASON_PARTIAL_EXIT, TRADE_COLUMNS, _periods_per_year, leg_cash
from .indicators import atr as atr_indicator
from .sizer import size_position
from .strategies import default_params
from .strategies import signal as strategy_signal
from .symbolspec import SymbolSpec, enforce_min_stop, round_to_tick


def run_fast(
    df,
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
    allow_signal_exit: bool = False,
    schedule: tuple = (),
) -> BacktestResult:
    """FAST single-line screening run — drop-in for
    :func:`mql5bot.backtest.run_backtest` (identical signature and result
    shape; screening results may be ranked, never certified)."""
    # validation identical to the canonical wrapper (legacy contract)
    if risk_percent <= 0:
        raise ValueError("risk_percent must be > 0")
    if not 0.0 < partial_fraction < 1.0:
        raise ValueError("partial_fraction must be in (0, 1)")
    if spread_points < 0 or slippage_points < 0 or commission_per_lot < 0:
        raise ValueError("costs must be >= 0")
    if warmup_bars < 0:
        raise ValueError("warmup_bars must be >= 0")
    if schedule:
        raise NotImplementedError(
            "FAST has no walk-forward schedule support (WFA param freeze "
            "is TRUTH-path — use mql5bot.backtest.run_backtest)")

    merged = default_params(strategy_name)  # KeyError: unknown strategy
    if params:
        merged.update(params)
    sl_atr_mult = float(merged.get("sl_atr", 2.0))  # hoisted: per-entry
    tp_atr_mult = float(merged.get("tp_atr", 4.0))  # dict lookups are a
    # measured hot-path cost on trade-dense sweeps

    # ---- explicit broker context (wrapper-identical) --------------------
    spec = SymbolSpec(
        name="BACKTEST",
        digits=max(1, round(-np.log10(point))) if point > 0 else 1,
        point=point,
        tick_size=point,
        # symmetric tick value: one tick of one lot moves point*contract
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
    cost_cfg = CostConfig(
        symbol=spec.name,
        spread_points=spread_points,
        slippage_points=slippage_points,
        commission_per_lot=commission_per_lot,
    )

    index = df.index
    n = len(df)
    if n < 4:
        raise ValueError("need at least 4 bars")
    # Timestamp formatting is a measured hot path on large frames: use the
    # vectorised strftime when the whole index is whole-second (the
    # produced strings are identical to str(t)); fall back to the exact
    # per-element conversion otherwise.
    if bool((index.nanosecond != 0).any()) \
            or bool((index.microsecond != 0).any()):
        times = [str(t) for t in index]
    else:
        times = list(index.strftime("%Y-%m-%d %H:%M:%S"))
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)

    desired = np.asarray(strategy_signal(df, strategy_name, merged),
                         dtype=int)

    # ---- precomputed arrays ----------------------------------------------
    atr = np.asarray(atr_indicator(h, l, c, 14), dtype=float)
    # spread/reject series: fixed-mode configs are constant arrays
    # (identical to spread_at/rejects per bar — single source stays
    # costs.py, which validated the config)
    if cost_cfg.spread_mode == "variable":
        spreads = np.asarray([cost_cfg.spread_at(i) for i in range(n)],
                             dtype=float)
    else:
        spreads = np.full(n, float(cost_cfg.spread_points), dtype=float)
    if cost_cfg.reject_mask is not None:
        rejects = np.asarray([cost_cfg.rejects(i) for i in range(n)],
                             dtype=bool)
    else:
        rejects = np.zeros(n, dtype=bool)
    day_ids = np.asarray(server_day_ids(index, DayClock())) \
        if max_daily_loss_pct > 0.0 else None

    # ---- state -----------------------------------------------------------
    cash = float(initial_capital)
    equity = np.empty(n)
    notional = np.empty(n)
    trades: list[dict] = []
    peak = float(initial_capital)
    basis = float(initial_capital)
    day_halted = dd_halted = False
    day_start_equity = float(initial_capital)

    # ---- single netting book state ----------------------------------------
    lots = 0.0
    side = 0
    entry_price = 0.0
    entry_index = -1
    entry_fee = 0.0
    sl = 0.0
    tp = 0.0
    bars_held = 0
    partial_done = False
    be_done = False

    def fill_exit_at(bar: int, book_side: int, price: float) -> float:
        return round_to_tick(exit_fill(price, book_side, spreads[bar],
                                       cost_cfg.slippage_points, spec.point),
                             spec)

    def add_row(bar: int, take: float, fill: float, reason: str,
                entry_fee_share: float, exit_fee_share: float,
                quote: float) -> None:
        """One trade row; mirrors the engine's ``_row`` exactly."""
        pnl = leg_cash(side, take, entry_price, fill, spec, 1.0)
        pnl_net = pnl - entry_fee_share - exit_fee_share
        cost_entry = leg_cash(side, take, o[entry_index], entry_price,
                              spec, 1.0)
        cost_exit = leg_cash(side, take, fill, quote, spec, 1.0)
        fees = entry_fee_share + exit_fee_share
        trades.append({
            "symbol": "BACKTEST",
            "strategy": strategy_name,
            "side": "long" if side > 0 else "short",
            "entry_time": times[entry_index],
            "exit_time": times[bar],
            "entry_price": round(float(entry_price), 8),
            "exit_price": round(float(fill), 8),
            "lots": round(float(take), 12),
            "bars_held": int(bar - entry_index),
            "pnl": round(float(pnl_net), 8),
            "pnl_pct": round(float(pnl_net) / initial_capital * 100.0, 8),
            "fees": round(float(fees), 8),
            "costs": round(float(fees + cost_entry + cost_exit), 8),
            "exit_reason": reason,
        })

    def close_book(bar: int, fill: float, reason: str, quote: float,
                   vol: float | None = None) -> None:
        """Close ``vol`` (default: the whole book) at ``fill``, engine
        FIFO/leg accounting for the single leg: realised PnL enters cash,
        entry fee share follows the volume, exit fee charged once."""
        nonlocal lots, side, entry_price, entry_index, entry_fee, cash
        nonlocal bars_held, partial_done, be_done, sl, tp
        take = lots if vol is None else min(lots, float(vol))
        exit_fee = commission_cash(take, cost_cfg)
        pnl = leg_cash(side, take, entry_price, fill, spec, 1.0)
        e_share = entry_fee * (take / lots) if lots > 0.0 else 0.0
        cash += pnl - exit_fee
        add_row(bar, take, fill, reason, e_share, exit_fee, quote)
        entry_fee -= e_share
        lots -= take
        if lots <= 1e-12:
            lots = 0.0
            side = 0
            entry_price = 0.0
            entry_index = -1
            entry_fee = 0.0
            sl = tp = 0.0
            bars_held = 0
            partial_done = be_done = False

    def open_book(bar: int, want_side: int, vol: float) -> None:
        nonlocal lots, side, entry_price, entry_index, entry_fee, sl, tp
        nonlocal bars_held, partial_done, be_done, cash
        fill = round_to_tick(entry_fill(o[bar], want_side, spreads[bar],
                                        cost_cfg.slippage_points, spec.point),
                             spec)
        a = atr[bar - 1]
        sl_dist = enforce_min_stop(sl_atr_mult * a, spec)
        tp_dist = enforce_min_stop(tp_atr_mult * a, spec)
        fee = commission_cash(vol, cost_cfg)
        lots, side = vol, want_side
        entry_price, entry_index = fill, bar
        entry_fee = fee
        sl = round_to_tick(entry_price - side * sl_dist, spec)
        tp = round_to_tick(entry_price + side * tp_dist, spec)
        bars_held = 0
        partial_done = be_done = False
        cash -= fee  # entry fee charged at the open

    def mark(bar: int) -> float:
        # deliberately left as the single-owner leg_cash call: a per-book
        # value cache was tried and measured (docs/BENCHMARK_FAST.md) —
        # no engine-level speedup above environment noise, so the extra
        # invalidation complexity was rejected.
        if lots > 0.0 and side != 0:
            return cash + leg_cash(side, lots, entry_price, c[bar], spec, 1.0)
        return cash

    # ---- main bar loop (plain arrays; mirrors the TRUTH loop exactly) ----
    for i in range(n):
        if i >= 1:
            # rollover: a new server day resets the daily-loss snapshot
            if day_ids is not None and int(day_ids[i]) != int(day_ids[i - 1]):
                basis = mark(i - 1)
                day_start_equity = basis
                day_halted = False
            # risk checks act at the open on prior-close equity
            lim = max_daily_loss_pct
            if (lim > 0.0 and not day_halted
                    and basis <= day_start_equity * (1.0 - lim / 100.0)):
                if lots > 0.0:
                    fill = fill_exit_at(i, side, o[i])
                    close_book(i, fill, REASON_DAILY_LOSS_LIMIT, o[i])
                day_halted = True
                basis = cash
            dd_lim = max_drawdown_pct
            if (dd_lim > 0.0 and not dd_halted
                    and basis <= peak * (1.0 - dd_lim / 100.0)):
                if lots > 0.0:
                    fill = fill_exit_at(i, side, o[i])
                    close_book(i, fill, REASON_MAX_DRAWDOWN, o[i])
                dd_halted = True
                basis = cash

        if i >= max(1, warmup_bars) and not day_halted and not dd_halted:
            # open-gap exits of a carried book first (fill at the open)
            if lots > 0.0 and entry_index < i:
                if side > 0 and o[i] <= sl:
                    close_book(i, o[i], REASON_STOP_LOSS, sl)
                elif side > 0 and o[i] >= tp:
                    close_book(i, o[i], REASON_TAKE_PROFIT, tp)
                elif side < 0 and o[i] >= sl:
                    close_book(i, o[i], REASON_STOP_LOSS, sl)
                elif side < 0 and o[i] <= tp:
                    close_book(i, o[i], REASON_TAKE_PROFIT, tp)

            # reconcile (engine-ordered, single line):
            if basis > 0.0:
                want = int(desired[i - 1])
                if want < 0 and not allow_short:
                    want = 0
                if lots > 0.0 and allow_signal_exit and want != side:
                    # flip or go-flat: close own legs at the open
                    fill = fill_exit_at(i, side, o[i])
                    close_book(i, fill, REASON_SIGNAL_EXIT, o[i])
                    # legacy allow_signal_exit=False: hands-off while holding
                if lots == 0.0 and want != 0:
                    a = atr[i - 1]
                    valid = np.isfinite(a) and a > 0.0
                    sl_dist = sl_atr_mult * a if valid else 0.0
                    if sl_dist > 0.0:
                        res = size_position(
                            spec, mode="risk_percent_equity",
                            equity=basis, balance=basis,
                            stop_distance=sl_dist, value=risk_percent,
                            profit_to_deposit=1.0,
                            max_lots=max_lots, margin_calc=None,
                            free_margin=None)
                        passable = res.lots > 0.0 and not res.rejected \
                            and (i < 1 or not gap_blocks(o[i], c[i - 1],
                                                         cost_cfg)) \
                            and not rejects[i]
                        if passable:
                            open_book(i, want, res.lots)

            # manage: held bars, level updates, intrabar exits
            if lots > 0.0:
                bars_held += 1
                a = atr[i - 1] if i >= 1 else np.nan
                if entry_index < i and np.isfinite(a) and a > 0.0:
                    prev_c = c[i - 1]
                    if trail_atr > 0.0:
                        if side > 0:
                            sl = max(sl, prev_c - trail_atr * a)
                        else:
                            sl = min(sl, prev_c + trail_atr * a)
                    if (breakeven_atr > 0.0 and not be_done
                            and side * (prev_c - entry_price)
                            >= breakeven_atr * a):
                        sl = round_to_tick(
                            entry_price + side
                            * breakeven_offset_points * spec.point, spec)
                        be_done = True
                    if (partial_atr > 0.0 and not partial_done
                            and side * (prev_c - entry_price)
                            >= partial_atr * a):
                        fill = fill_exit_at(i, side, o[i])
                        close_book(i, fill, REASON_PARTIAL_EXIT, o[i],
                                   lots * partial_fraction)
                        if lots > 0.0:
                            sl = round_to_tick(entry_price, spec)
                            partial_done = True
                if lots > 0.0:
                    hit_sl, fill_sl = stop_fill(o[i], l[i], h[i], side, sl,
                                                cost_cfg, spec.point)
                    if hit_sl:
                        close_book(i, fill_sl, REASON_STOP_LOSS, sl)
                    else:
                        hit_tp, fill_tp = tp_fill(o[i], l[i], h[i], side, tp,
                                                  cost_cfg, spec.point)
                        if hit_tp:
                            close_book(i, fill_tp, REASON_TAKE_PROFIT, tp)
                        elif max_bars > 0 and bars_held >= max_bars:
                            fill = fill_exit_at(i, side, c[i])
                            close_book(i, fill, REASON_MAX_BARS, c[i])

        equity[i] = mark(i)
        peak = max(peak, float(equity[i]))
        basis = float(equity[i])
        notional[i] = (abs(lots) * spec.contract_size * c[i]
                       if lots > 0.0 else 0.0)

    # close anything still open at the final close (TRUTH-identical)
    if lots > 0.0:
        last = n - 1
        fill = fill_exit_at(last, side, c[last])
        close_book(last, fill, REASON_END_OF_DATA, c[last])
        equity[last] = mark(last)
        notional[last] = 0.0

    from .metrics import compute_metrics

    trades_df = pd.DataFrame(trades, columns=TRADE_COLUMNS)
    trades_df = trades_df[_TRADE_COLUMNS]
    equity_s = pd.Series(equity, index=index, name="equity")
    metrics = compute_metrics(
        equity_s, trades_df,
        periods_per_year=_periods_per_year(index))
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
            "engine": "fast",
        }
    return BacktestResult(
        strategy=strategy_name,
        params=merged,
        config=config,
        trades=trades_df,
        equity=equity_s,
        metrics=metrics,
    )
