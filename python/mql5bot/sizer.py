"""mql5bot.sizer — canonical risk engine sizing (SPEC §8.C) on injected specs.

Pure, deterministic position sizing. Every broker fact arrives through a
:class:`~mql5bot.symbolspec.SymbolSpec` and every account fact through
arguments — nothing reads live terminal state, so the exact same arithmetic
is unit-testable on synthetic broker specs and portable 1:1 into the MQL5
port that wraps ``OrderCalcMargin``.

Sizing modes (SPEC §8.C):

* ``fixed_lot`` — caller-controlled lot size; risk money is reported, not
  enforced.
* ``risk_percent_equity`` (default) — risk a % of current equity.
* ``risk_percent_balance`` — risk a % of current balance.
* ``fixed_money`` — risk a fixed amount of deposit currency.
* ``kelly_fraction`` — budget = equity * min(kelly(win_rate, payoff), cap);
  cap defaults to 0.25 and the mode is OFF by default (SPEC §8.C /
  DECISIONS.md). A non-positive Kelly means no measurable edge -> no trade.

Conservative rules hard-coded here (documented in DECISIONS.md):

1. Volume is floored to the broker step — rounding up would exceed the risk
   budget.
2. If the floored size lands below ``volume_min`` the order is REJECTED:
   forcing ``volume_min`` would overshoot the risk budget. (A future
   ``allow_min_overshoot`` flag may lift this per strategy, never per trade
   silently.)
3. If the raw size exceeds ``volume_max`` / ``volume_limit`` it is clamped
   DOWN and flagged ``clamped_to_max`` (risk only shrinks).
4. When an injected margin calculator says the required margin exceeds the
   injected free margin, volume is reduced step by step; if even
   ``volume_min`` does not fit, the order is REJECTED with
   ``margin_rejected``.
5. Stop distance of 0 / unset stop -> ``missing_stop`` rejection. Aegis never
   opens a position without a stop (SPEC §3.2).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .symbolspec import SymbolSpec, enforce_min_stop, loss_per_lot, normalize_volume

# Sizing modes --------------------------------------------------------------
FIXED_LOT = "fixed_lot"
RISK_PERCENT_EQUITY = "risk_percent_equity"  # SPEC default
RISK_PERCENT_BALANCE = "risk_percent_balance"
FIXED_MONEY = "fixed_money"
KELLY_FRACTION = "kelly_fraction"

SIZING_MODES = (
    FIXED_LOT,
    RISK_PERCENT_EQUITY,
    RISK_PERCENT_BALANCE,
    FIXED_MONEY,
    KELLY_FRACTION,
)

KELLY_DEFAULT_CAP = 0.25  # SPEC §8.C: capped Kelly, conservative
KELLY_DEFAULT_OFF = True  # SPEC §8.C: off by default

# Result reasons ------------------------------------------------------------
OK = "ok"
MISSING_STOP = "missing_stop"
NO_EDGE = "no_edge"  # Kelly <= 0
BELOW_MIN = "below_min_volume"  # risk budget cannot fit the broker minimum
CLAMPED_TO_MAX = "clamped_to_max"
MARGIN_REDUCED = "margin_reduced"
MARGIN_REJECTED = "margin_rejected"
INVALID_ARGS = "invalid_args"


@dataclass(frozen=True)
class SizingResult:
    """Outcome of one sizing request. ``rejected`` is True whenever the
    engine must NOT send an order."""

    lots: float = 0.0
    reason: str = INVALID_ARGS
    risk_money_budget: float = 0.0  # what the caller wanted to risk (deposit ccy)
    risk_money_actual: float = 0.0  # real loss at the stop with `lots`
    loss_per_lot_ccy: float = 0.0  # loss per 1.0 lot at the stop (deposit ccy)

    @property
    def rejected(self) -> bool:
        return self.reason not in (OK, MARGIN_REDUCED, CLAMPED_TO_MAX)


def kelly_fraction(win_rate: float, payoff_ratio: float) -> float:
    """Full Kelly fraction of equity: ``w - (1-w)/b`` (b = avg win / avg
    loss, positive). <= 0 means no edge."""
    if not 0.0 < win_rate < 1.0 or payoff_ratio <= 0.0:
        return 0.0
    return win_rate - (1.0 - win_rate) / payoff_ratio


def size_position(
    spec: SymbolSpec,
    *,
    mode: str = RISK_PERCENT_EQUITY,
    equity: float = 0.0,
    balance: float = 0.0,
    stop_distance: float = 0.0,
    value: float = 0.0,
    profit_to_deposit: float = 1.0,
    max_lots: float = 0.0,
    kelly_cap: float = KELLY_DEFAULT_CAP,
    kelly_enabled: bool = not KELLY_DEFAULT_OFF,
    win_rate: float = 0.0,
    payoff_ratio: float = 0.0,
    margin_calc: Callable[[float], float] | None = None,
    free_margin: float | None = None,
) -> SizingResult:
    """Compute the position size for one order.

    Args:
        spec: injected broker specification (SPEC §3.10).
        mode: one of :data:`SIZING_MODES`.
        equity/balance: current account equity / balance (deposit currency).
        stop_distance: intended SL distance from entry, in price units,
            BEFORE broker min-stop enforcement (we enforce here: the risk
            arithmetic must match the stop that will actually be sent).
        value: lot size (fixed_lot) or fixed risk money (fixed_money).
        profit_to_deposit: conversion profit currency -> deposit currency.
        max_lots: strategy/EA-level cap on top of ``spec.volume_max``.
        kelly_cap/kelly_enabled: kelly mode guard rails.
        win_rate/payoff_ratio: inputs for kelly mode.
        margin_calc: injected broker margin function volume -> required
            margin in deposit currency (MQL5: wrapper around
            ``OrderCalcMargin``). None disables the margin check.
        free_margin: account free margin (deposit currency); required when
            ``margin_calc`` is given.

    Returns: a :class:`SizingResult`; check ``rejected`` before trading.
    """
    # -- argument validation --------------------------------------------
    if mode not in SIZING_MODES:
        return SizingResult(reason=INVALID_ARGS)
    if equity < 0.0 or balance < 0.0 or free_margin is not None and free_margin < 0.0:
        return SizingResult(reason=INVALID_ARGS)
    if mode == KELLY_FRACTION and not kelly_enabled:
        return SizingResult(reason=INVALID_ARGS)  # off by default (SPEC §8.C)
    if max_lots <= 0.0:
        max_lots = spec.volume_max

    # -- stop -------------------------------------------------------------
    if stop_distance <= 0.0:
        return SizingResult(reason=MISSING_STOP)  # rule 5 / SPEC §3.2
    distance = enforce_min_stop(stop_distance, spec)
    loss_pl = loss_per_lot(distance, spec, profit_to_deposit)
    if loss_pl <= 0.0:
        return SizingResult(reason=MISSING_STOP)

    # -- budget -----------------------------------------------------------
    if mode == FIXED_LOT:
        lots_raw = value
        budget = lots_raw * loss_pl
    elif mode == FIXED_MONEY:
        budget = value
        lots_raw = budget / loss_pl
    elif mode == RISK_PERCENT_BALANCE:
        budget = balance * value / 100.0
        lots_raw = budget / loss_pl
    elif mode == KELLY_FRACTION:
        k = kelly_fraction(win_rate, payoff_ratio)
        if k <= 0.0:
            return SizingResult(reason=NO_EDGE)
        budget = equity * min(k, kelly_cap)
        lots_raw = budget / loss_pl
    else:  # risk_percent_equity (default)
        budget = equity * value / 100.0
        lots_raw = budget / loss_pl

    if budget <= 0.0 or lots_raw <= 0.0:
        return SizingResult(reason=INVALID_ARGS)

    # -- volume normalisation --------------------------------------------
    reason = OK
    effective_cap = min(max_lots, spec.volume_max)
    if spec.volume_limit > 0.0:
        effective_cap = min(effective_cap, spec.volume_limit)

    # raw size below broker minimum -> forcing min would overshoot risk
    if lots_raw < spec.volume_min:
        return SizingResult(
            lots=0.0, reason=BELOW_MIN, risk_money_budget=budget,
            risk_money_actual=0.0, loss_per_lot_ccy=loss_pl,
        )
    if effective_cap < spec.volume_min - 1e-12:
        # strategy/broker cap below the tradable minimum: nothing to send
        return SizingResult(
            lots=0.0, reason=BELOW_MIN, risk_money_budget=budget,
            risk_money_actual=0.0, loss_per_lot_ccy=loss_pl,
        )
    if lots_raw > effective_cap:
        lots = normalize_volume(effective_cap, spec)
        reason = CLAMPED_TO_MAX  # risk only shrinks; never overshoots
    else:
        lots = normalize_volume(lots_raw, spec)
    if lots <= 0.0:  # e.g. cap grid below the minimum: nothing tradable
        return SizingResult(reason=INVALID_ARGS)

    # -- margin check (injected broker function) -------------------------
    # Broker margin is monotonic in volume, so step down from the requested
    # size until the free-margin constraint holds; if even volume_min does
    # not fit, reject. Bounded loop: at most lots/step iterations.
    if margin_calc is not None:
        if free_margin is None:
            return SizingResult(reason=INVALID_ARGS)
        step = spec.volume_step
        s = round(lots / step)
        best: float | None = None
        while s >= 1:
            v = round(s * step, 12)
            if v < spec.volume_min - 1e-12:
                break
            if margin_calc(v) <= free_margin + 1e-12:
                best = v
                break
            s -= 1
        if best is None:
            return SizingResult(
                lots=0.0, reason=MARGIN_REJECTED, risk_money_budget=budget,
                risk_money_actual=0.0, loss_per_lot_ccy=loss_pl,
            )
        if best < lots - 1e-12:
            lots = best
            if reason == OK:
                reason = MARGIN_REDUCED

    actual = lots * loss_pl
    return SizingResult(
        lots=lots, reason=reason, risk_money_budget=budget,
        risk_money_actual=actual, loss_per_lot_ccy=loss_pl,
    )
