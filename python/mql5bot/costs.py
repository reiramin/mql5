"""mql5bot.costs — explicit, configurable execution cost model (Phase 2).

Every cost the canonical engine charges is declared here — nothing is
hidden inside an arbitrary formula:

* bid/ask spread — fixed ``spread_points`` or a per-bar variable spread
  series (engine passes the bar's spread in points);
* slippage — adverse, in points, applied at every fill (entry, exit,
  stop, take-profit);
* commission — per lot per side (or per round trip), plus an optional
  minimum per execution, in deposit currency;
* swap — per 1.0 lot per server day, long and short separately, in
  deposit currency (charged by the engine at daily reset boundaries);
* gap — an entry bar whose ``|open/prev_close - 1|`` exceeds
  ``max_gap_fraction`` is skipped (gap rejection is *optional*: the
  default is no limit, which models a broker that always fills);
* rejected execution — an optional deterministic per-bar reject mask
  (e.g. from a seeded RNG or a "session-open degradation" schedule);
  rejected entries leave no trade and are recorded;
* stop/TP fills — canonical worst-case conventions documented below;
* pending orders — optional stop-pending entries with offset/expiry.

The four deterministic research profiles (:data:`COST_PROFILES`, built by
:func:`cost_profile`) turn the model into named gates — ``ZERO`` (cost-free),
``BASE``, ``STRESSED`` and ``SEVERE`` — with strictly escalating rates, so a
strategy's cost resilience is testable as a monotone ladder.

Fill conventions (documented, conservative):

1. Bar ``open`` is treated as the mid price.  A buy fills at
   ``open + spread/2 + slippage``; a sell at ``open - spread/2 - slippage``
   — a round trip therefore pays the full spread plus slippage on both
   legs (same convention the legacy engine used, now explicit).
2. Stop loss: if the bar opens beyond the stop (gap), the fill is the
   open (worse than the stop); otherwise the fill is the stop price minus
   adverse slippage (buy stop loss fills at ``sl - slippage``).
3. Take profit: if the bar opens beyond the TP (gap), the fill is the
   open; otherwise the fill is the TP price (no adverse slippage — a
   limit order cannot slip against the trader; the gap rule keeps the
   model honest when the market jumps over the level).
4. Pending stop entry: trigger when high >= trigger (buy stop) or low <=
   trigger (sell stop) intrabar; fill at the trigger price plus adverse
   slippage; a bar that opens beyond the trigger fills at the open.
   Pending orders expire after ``pending_expire_bars`` bars.
5. A position whose SL/TP sits inside the broker freeze zone around the
   current price cannot be placed/modified — the engine records the
   event instead of silently trading around the rule (conservative).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

# fill/order modes
ENTRY_MARKET = "market"
ENTRY_PENDING_STOP = "pending_stop"
ENTRY_MODES = (ENTRY_MARKET, ENTRY_PENDING_STOP)

# reasons recorded by the engine (canonical vocabulary)
REASON_STOP_LOSS = "stop_loss"
REASON_TAKE_PROFIT = "take_profit"
REASON_MAX_BARS = "max_bars"
REASON_DAILY_LOSS_LIMIT = "daily_loss_limit"
REASON_MAX_DRAWDOWN = "max_drawdown"
REASON_END_OF_DATA = "end_of_data"
REASON_SIGNAL_EXIT = "signal_exit"  # desired flips opposite (netting close)
REASON_PENDING_EXPIRED = "pending_expired"
REASON_GAP_SKIPPED = "gap_skipped"
REASON_REJECTED = "rejected_execution"
REASON_NO_VALID_STOP = "no_valid_stop"
REASON_MERGE_OFFSET = "merge_offset"  # netting opposite-side offset close


@dataclass(frozen=True)
class CostConfig:
    """Execution cost settings for one symbol in one run.

    ``spread_points`` is used when ``spread_series`` is None.  When
    ``spread_series`` is provided it must have one value per bar (points);
    variable-spread modelling is then explicit and per bar.
    ``reject_mask`` (optional, one bool per bar) makes rejected execution
    deterministic for a given run configuration.
    """

    symbol: str = "EURUSD"
    # spread ----------------------------------------------------------
    spread_mode: str = "fixed"  # 'fixed' | 'variable'
    spread_points: float = 1.0
    spread_series: Sequence[float] | None = None
    # slippage / commission ------------------------------------------
    slippage_points: float = 0.0
    commission_per_lot: float = 0.0  # deposit ccy per 1.0 lot per side
    commission_min: float = 0.0  # deposit ccy per execution, when > 0
    commission_per_round_trip: bool = False  # charge half at entry+exit
    # swap (deposit ccy per 1.0 lot per server day) -------------------
    swap_long_per_lot_day: float = 0.0
    swap_short_per_lot_day: float = 0.0
    # gap / rejection ------------------------------------------------
    max_gap_fraction: float = math.inf  # 0.01 = skip >1% gaps
    reject_mask: Sequence[bool] | None = None
    # pending orders --------------------------------------------------
    entry_mode: str = ENTRY_MARKET
    pending_offset_points: float = 0.0
    pending_expire_bars: int = 0  # 0 = no expiry

    def validate(self, n_bars: int | None = None) -> None:
        if self.spread_mode not in ("fixed", "variable"):
            raise ValueError(f"spread_mode must be fixed|variable, got {self.spread_mode!r}")
        if self.spread_points < 0 or self.slippage_points < 0:
            raise ValueError("spread and slippage must be >= 0")
        if self.commission_per_lot < 0 or self.commission_min < 0:
            raise ValueError("commission must be >= 0")
        if self.max_gap_fraction <= 0:
            raise ValueError("max_gap_fraction must be > 0 (use inf to disable)")
        if self.entry_mode not in ENTRY_MODES:
            raise ValueError(f"entry_mode must be one of {ENTRY_MODES}")
        if self.pending_offset_points < 0 or self.pending_expire_bars < 0:
            raise ValueError("pending offset/expiry must be >= 0")
        if self.spread_mode == "variable":
            if self.spread_series is None:
                raise ValueError("variable spread mode requires spread_series")
            if n_bars is not None and len(self.spread_series) != n_bars:
                raise ValueError(
                    f"spread_series length {len(self.spread_series)} != bars {n_bars}")
        if (
            self.reject_mask is not None
            and n_bars is not None
            and len(self.reject_mask) != n_bars
        ):
            raise ValueError(
                f"reject_mask length {len(self.reject_mask)} != bars {n_bars}")

    def spread_at(self, bar: int) -> float:
        """Spread in points for bar ``bar`` (fixed or variable)."""
        if self.spread_mode == "variable":
            assert self.spread_series is not None
            return float(self.spread_series[bar])
        return self.spread_points

    def rejects(self, bar: int) -> bool:
        return bool(self.reject_mask is not None and self.reject_mask[bar])


# ---------------------------------------------------------------------------
# Deterministic cost profiles (research gate ZERO / BASE / STRESSED / SEVERE)
# ---------------------------------------------------------------------------

COST_PROFILES = ("ZERO", "BASE", "STRESSED", "SEVERE", "EXTREME")
"""The five canonical research profiles, in strictly harsher order.

``ZERO`` is a fully cost-free execution model (deterministic zero trading
costs); ``BASE`` models a clean retail execution; ``STRESSED`` and
``SEVERE`` escalate spread, slippage, commission, swap and gap sensitivity.
Every rate in a later profile is >= (harsher or equal to) the previous one
field-by-field, so on an identical trade path the profiles produce
monotonically harsher outcomes.  ``EXTREME`` is the crisis envelope
(crisis spreads and slippage, wide gaps): it is an OBSERVATION scenario
for degradation measurement, never an expected steady state.  Profiles
never inject a reject mask — rejection is a per-run scenario knob, not
a profile property.
"""

_PROFILE_DEFAULTS: dict[str, dict] = {
    "ZERO": {
        "spread_points": 0.0,
        "slippage_points": 0.0,
        "commission_per_lot": 0.0,
        "commission_min": 0.0,
        "swap_long_per_lot_day": 0.0,
        "swap_short_per_lot_day": 0.0,
        "max_gap_fraction": math.inf,
    },
    "BASE": {
        "spread_points": 1.0,
        "slippage_points": 0.25,
        "commission_per_lot": 3.5,  # $3.50/1.0 lot/side (~$7 round trip)
        "commission_min": 0.0,
        "swap_long_per_lot_day": 0.5,
        "swap_short_per_lot_day": 0.5,
        "max_gap_fraction": math.inf,
    },
    "STRESSED": {
        "spread_points": 2.5,
        "slippage_points": 1.0,
        "commission_per_lot": 7.0,
        "commission_min": 1.0,
        "swap_long_per_lot_day": 1.5,
        "swap_short_per_lot_day": 2.0,
        "max_gap_fraction": 0.05,  # 5% overnight gaps skip the entry
    },
    "SEVERE": {
        "spread_points": 5.0,
        "slippage_points": 2.5,
        "commission_per_lot": 14.0,
        "commission_min": 2.0,
        "swap_long_per_lot_day": 4.0,
        "swap_short_per_lot_day": 5.0,
        "max_gap_fraction": 0.01,  # 1% overnight gaps skip the entry
    },
    "EXTREME": {
        "spread_points": 12.0,     # crisis spread envelope
        "slippage_points": 6.0,
        "commission_per_lot": 28.0,   # crisis-tier routing cost
        "commission_min": 4.0,
        "swap_long_per_lot_day": 4.0,
        "swap_short_per_lot_day": 5.0,
        "max_gap_fraction": 0.005,  # 0.5% overnight gaps skip the entry
    },
}


#: Field-level view of the canonical profile ladder (tests and docs pin
#: the field-by-field escalation against this mapping).
PROFILE_DEFAULTS: dict[str, dict] = {k: dict(v)
                                     for k, v in _PROFILE_DEFAULTS.items()}


def cost_profile(profile: str, *, symbol: str = "EURUSD", **overrides) -> CostConfig:
    """Return the named deterministic :class:`CostConfig` preset.

    ``profile`` is case-insensitive and must be one of :data:`COST_PROFILES`.
    ``symbol`` labels the config (broker specs stay authoritative for live
    numbers; these fixtures are for research stress gates).  ``overrides``
    may tune individual fields for a specific run.
    """
    key = str(profile).upper()
    if key not in COST_PROFILES:
        raise ValueError(
            f"unknown cost profile {profile!r}; use one of {COST_PROFILES}"
        )
    return replace(CostConfig(symbol=symbol, **_PROFILE_DEFAULTS[key]), **overrides)


# ---------------------------------------------------------------------------
# pure helpers (all deterministic; engine calls these and records reasons)
# ---------------------------------------------------------------------------


def spread_price(spread_points: float, point: float) -> float:
    """Spread in price units for a point-based spread."""
    return spread_points * point


def entry_fill(
    bar_open: float,
    side: int,
    spread_points: float,
    slippage_points: float,
    point: float,
) -> float:
    """Mid-price convention: buy pays +spread/2 +slippage, sell the mirror."""
    surcharge = (spread_points / 2.0 + slippage_points) * point
    return bar_open + side * surcharge


def exit_fill(
    price: float,
    side: int,
    spread_points: float,
    slippage_points: float,
    point: float,
) -> float:
    """Exit at ``price`` (stop/tp/close): adverse half-spread + slippage."""
    surcharge = (spread_points / 2.0 + slippage_points) * point
    return price - side * surcharge


def commission_cash(lots: float, cfg: CostConfig) -> float:
    """Commission for ONE execution of ``lots`` (deposit ccy).

    Per side when ``commission_per_round_trip`` is False (the default:
    entry pays it, exit pays it again).  In round-trip mode each leg pays
    half, so a full round trip always pays ``per_lot * lots`` exactly once
    per side pair (half at entry + half at exit).
    """
    if cfg.commission_per_lot <= 0.0:
        return 0.0
    per_lot = cfg.commission_per_lot
    if cfg.commission_per_round_trip:
        per_lot /= 2.0
    cash = per_lot * lots
    if cfg.commission_min > 0.0:
        cash = max(cash, cfg.commission_min)
    return cash


def swap_charge(
    side: int,
    lots: float,
    cfg: CostConfig,
    days_held: int = 1,
) -> float:
    """Swap cost for ``days_held`` server days (deposit ccy, >= 0).

    The configured rates are costs per 1.0 lot per server day (positive
    values); the engine subtracts this charge from PnL.  A zero rate means
    no swap is modelled for that side.
    """
    rate = cfg.swap_long_per_lot_day if side > 0 else cfg.swap_short_per_lot_day
    return rate * lots * days_held


def gap_blocks(bar_open: float, prev_close: float, cfg: CostConfig) -> bool:
    """True when the bar-to-bar gap exceeds the configured limit."""
    if math.isinf(cfg.max_gap_fraction) or prev_close <= 0.0:
        return False
    return abs(bar_open / prev_close - 1.0) > cfg.max_gap_fraction


def stop_fill(
    bar_open: float,
    bar_low: float,
    bar_high: float,
    side: int,
    stop_price: float,
    cfg: CostConfig,
    point: float,
) -> tuple[bool, float]:
    """Intrabar stop-loss fill (conservative worst case).

    Returns ``(hit, fill_price)``.  Gap-through fills at the open (worse);
    otherwise the fill is ``stop_price`` minus adverse slippage.
    """
    touched = (side > 0 and bar_low <= stop_price) or (
        side < 0 and bar_high >= stop_price)
    if not touched:
        return False, 0.0
    gap_over = (side > 0 and bar_open <= stop_price) or (
        side < 0 and bar_open >= stop_price)
    if gap_over:
        return True, bar_open
    slip = cfg.slippage_points * point
    return True, stop_price - side * slip


def tp_fill(
    bar_open: float,
    bar_low: float,
    bar_high: float,
    side: int,
    tp_price: float,
    cfg: CostConfig,
    point: float,
) -> tuple[bool, float]:
    """Intrabar take-profit fill.

    Returns ``(hit, fill_price)``.  Gap-through fills at the open;
    otherwise the fill is the TP price (no adverse slippage).
    """
    touched = (side > 0 and bar_high >= tp_price) or (
        side < 0 and bar_low <= tp_price)
    if not touched:
        return False, 0.0
    gap_over = (side > 0 and bar_open >= tp_price) or (
        side < 0 and bar_open <= tp_price)
    if gap_over:
        return True, bar_open
    return True, tp_price


def pending_trigger_fill(
    bar_open: float,
    bar_low: float,
    bar_high: float,
    side: int,
    trigger: float,
    cfg: CostConfig,
    point: float,
) -> tuple[bool, float]:
    """Stop-pending entry fill: trigger intrabar, fill at trigger (or the
    open when the bar opens beyond it), plus adverse slippage."""
    touched = (side > 0 and bar_high >= trigger) or (
        side < 0 and bar_low <= trigger)
    if not touched:
        return False, 0.0
    gap_over = (side > 0 and bar_open >= trigger) or (
        side < 0 and bar_open <= trigger)
    base = bar_open if gap_over else trigger
    slip = cfg.slippage_points * point
    return True, base + side * slip
