"""mql5bot.symbolspec — canonical broker symbol specification + normalisers.

Release-A seed models (see docs/IMPLEMENTATION_AUDIT.md §17 and
docs/DECISIONS.md "Python-first canonical risk/identity models"):

* :class:`SymbolSpec` mirrors the broker facts the MQL5 EA must query at
  runtime (SPEC §3.3) and that ALL risk/execution math must operate on
  instead of calling ``SymbolInfo*`` directly (SPEC §3.10). Risk code stays
  pure and unit-testable with synthetic specs (EURUSD 5-digit, USDJPY,
  XAUUSD, US30-like index, BTCUSD-like crypto, ...).
* Price/volume normalisers (tick alignment, min-stop enforcement, volume
  step) used by the sizer and, later, by the ported MQL5 ``SSymbolSpec``.
* FNV-1a magic derivation (SPEC §3.9): a strategy's Magic is a pure FNV-1a
  hash of its stable ``strategy_id`` mapped into a reserved range and kept in
  a persistent registry; Magic is NEVER derived from an array/enum index and
  never reassigned when strategies are added, removed or reloaded.

Nothing here touches account state or trade functions. Failure modes are
returned as explicit values, never silently swallowed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# FNV-1a identity (SPEC §3.9) — must stay byte-identical to the MQL5 port
# ---------------------------------------------------------------------------

FNV1A_OFFSET_BASIS: int = 2166136261  # 0x811C9DC5
FNV1A_PRIME: int = 16777619  # 0x01000193
FNV1A_MASK32: int = 0xFFFFFFFF

# Reserved magic range: [MAGIC_BASE, MAGIC_BASE + MAGIC_SPAN).
# 1 000 000 free slots; the legacy Mql5Bot default magic (20240904) lies
# above the range so old demo positions can never be mistaken for Aegis ones.
MAGIC_BASE: int = 16_777_216  # 0x1000000
MAGIC_SPAN: int = 1_048_576  # 0x100000 (2^20)
MAGIC_MAX: int = MAGIC_BASE + MAGIC_SPAN - 1


def fnv1a32(text: str) -> int:
    """FNV-1a 32-bit hash of ``text`` (UTF-8), unsigned.

    Classic vectors: ``fnv1a32("") == 0x811C9DC5``, ``fnv1a32("a") ==
    0xE40C292C``. Deterministic across processes and languages.
    """
    h = FNV1A_OFFSET_BASIS
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * FNV1A_PRIME) & FNV1A_MASK32
    return h


def derive_magic(
    strategy_id: str,
    taken: Iterable[int] = (),
    *,
    base: int = MAGIC_BASE,
    span: int = MAGIC_SPAN,
) -> int:
    """Map a stable ``strategy_id`` to a magic inside the reserved range.

    Primary slot = ``base + fnv1a32(id) % span``. If the slot is occupied by
    a DIFFERENT id (hash collision), probe deterministically to the next free
    slot. Deterministic given the same insertion set, which is what the
    persisted registry guarantees. Raises when the range is exhausted (a
    registry bug, not a trade action).
    """
    taken_set = {int(m) for m in taken}
    if not (0 < span <= MAGIC_SPAN * 16 and base >= 0):
        raise ValueError("magic range must be positive and bounded")
    first = base + fnv1a32(strategy_id) % span
    magic = first
    while magic in taken_set:
        magic += 1
        if magic >= base + span:
            magic = base  # wrap once, then give up
        if magic == first:
            raise RuntimeError(f"magic range exhausted for id {strategy_id!r}")
    return magic


class MagicRegistry:
    """Persistable ``strategy_id -> magic`` map.

    Stability contract (SPEC DoD #21): once an id has been allocated, every
    later call (even after other ids were removed and re-added, or after a
    reload from disk) returns the SAME magic. Removal never triggers
    reallocation of other ids.
    """

    def __init__(self, entries: dict[str, int] | None = None):
        self._map: dict[str, int] = dict(entries or {})

    def allocate(self, strategy_id: str) -> int:
        """Return the existing magic for ``strategy_id`` or allocate one."""
        if strategy_id in self._map:
            return self._map[strategy_id]
        magic = derive_magic(strategy_id, self._map.values())
        self._map[strategy_id] = magic
        return magic

    def get(self, strategy_id: str) -> int | None:
        return self._map.get(strategy_id)

    def ids(self) -> list[str]:
        return sorted(self._map)

    def __len__(self) -> int:
        return len(self._map)

    def to_json(self) -> str:
        return json.dumps(self._map, sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, payload: str) -> MagicRegistry:
        data = json.loads(payload)
        if not isinstance(data, dict) or not all(
            isinstance(k, str) and isinstance(v, int) for k, v in data.items()
        ):
            raise ValueError("corrupt magic registry payload")
        return cls(data)

    # -- tests ----------------------------------------------------------
    def _assert_invariants(self) -> None:
        values = list(self._map.values())
        assert len(values) == len(set(values)), "magic collision inside registry"
        for v in values:
            assert MAGIC_BASE <= v <= MAGIC_MAX, "magic outside reserved range"


# ---------------------------------------------------------------------------
# Broker symbol specification (SPEC §3.3 / §3.10)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolSpec:
    """Immutable snapshot of broker facts for one symbol/account pair.

    Field semantics mirror the MT5 properties they come from; all monetary
    values are expressed in the SYMBOL's own currency unless a field name
    says otherwise (see ``tick_value_profit/loss``), so an injected
    ``profit_to_deposit`` conversion is required by the sizer and never
    assumed to be 1.0.
    """

    name: str = "EURUSD"
    digits: int = 5
    point: float = 1e-5  # SYMBOL_POINT
    tick_size: float = 1e-5  # SYMBOL_TRADE_TICK_SIZE (price step)
    # Tick value per 1.0 lot in the PROFIT currency (SYMBOL_TRADE_TICK_VALUE_
    # PROFIT / _LOSS; use the _LOSS side for stop-loss risk math).
    tick_value_loss: float = 1.0
    # Profit-side tick value; None (default) means symmetric with the loss
    # side.  Real asymmetric specs inject both sides; the canonical engine
    # values gains with the profit side and losses with the loss side.
    tick_value_profit: float | None = None
    contract_size: float = 100_000.0  # SYMBOL_TRADE_CONTRACT_SIZE
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    volume_limit: float = 0.0  # SYMBOL_VOLUME_LIMIT; 0 = no limit
    stops_level_points: float = 0.0  # SYMBOL_TRADE_STOPS_LEVEL (points)
    freeze_level_points: float = 0.0  # SYMBOL_TRADE_FREEZE_LEVEL (points)
    currency_profit: str = "USD"
    currency_deposit: str = "USD"

    # -- derived helpers -------------------------------------------------
    def tick_value(self, side: int, move: float = 0.0) -> float:
        """Tick value per 1.0 lot for a price ``move`` of a ``side`` (+1
        long, -1 short) position.

        A favorable move (``side * move > 0``: long gains on a rise, short
        gains on a fall) is valued with :attr:`tick_value_profit` when it is
        injected, otherwise with the loss-side value (symmetric).  An
        unfavorable move always uses :attr:`tick_value_loss`, which is the
        side the stop-loss risk arithmetic uses (``loss_per_lot``).
        """
        if side * move > 0.0 and self.tick_value_profit is not None:
            return self.tick_value_profit
        return self.tick_value_loss

    def min_stop_distance(self) -> float:
        """Minimum SL/TP distance in price units (stops level, no spread)."""
        return self.stops_level_points * self.point

    def freezes_before_price(self, price: float, ref: float) -> bool:
        """True when ``price`` sits inside the freeze zone around ``ref``."""
        if self.freeze_level_points <= 0.0:
            return False
        zone = self.freeze_level_points * self.point
        return abs(price - ref) <= zone


# ---------------------------------------------------------------------------
# Normalisers — price and volume (pure)
# ---------------------------------------------------------------------------

# Volume floor dust guard, in STEP UNITS (Reality Gate §4 semantic closure,
# DECISIONS.md 2026-09-07). Must stay bitwise-identical to the MQL5
# constants in SpecNormalizeVolume (SymbolSpec.mqh) and the Meta
# re-normalisation in Mql5Bot.mq5 — both 1e-9. Derived bound: covers
# 0.5-ulp IEEE-754 division dust for volume_max/volume_step quotients up to
# ~1e7 while promoting strictly-below-grid inputs by never more than 1e-9
# of one step (representation-only; see tests/test_volume_contract.py).
VOLUME_FLOOR_DUST_EPS: float = 1e-9


def round_to_tick(price: float, spec: SymbolSpec) -> float:
    """Round a price to the symbol's tick grid.

    Uses ``tick_size`` (NOT digits): for index/crypto CFDs the tick can be a
    multiple of the printed point (e.g. tick 0.25, point 0.01), and digit
    rounding would mint prices the broker will reject.
    """
    if spec.tick_size <= 0.0:
        raise ValueError(f"{spec.name}: tick_size must be positive")
    return round(price / spec.tick_size) * spec.tick_size


def ticks_of(distance: float, spec: SymbolSpec) -> int:
    """Number of whole ticks in ``distance`` (>= 0), rounded to the nearest
    integer tick. Used for the tick-value-based loss-per-lot arithmetic so
    the risk calculation and the actual broker-level stop distance agree."""
    if spec.tick_size <= 0.0:
        raise ValueError(f"{spec.name}: tick_size must be positive")
    if distance <= 0.0:
        return 0
    return max(1, round(distance / spec.tick_size))


def enforce_min_stop(distance: float, spec: SymbolSpec) -> float:
    """Grow ``distance`` so it satisfies the broker stops level, keeping it
    on the tick grid. Never shrinks a stop below what the strategy asked for
    (SPEC DoD #10: invalid stops are never sent)."""
    minimum = spec.min_stop_distance()
    distance = max(distance, minimum)
    return round_to_tick(distance, spec)


def normalize_volume(lots: float, spec: SymbolSpec) -> float:
    """Normalise ``lots`` to the broker's volume grid.

    Floors to ``volume_step`` (never rounds UP — rounding up would exceed the
    risk budget), clamps into [volume_min, volume_max] and honours the
    broker's volume_limit when one is set. Returns 0.0 for non-positive
    input. Any positive input whose floored grid point lies below
    ``volume_min`` yields ``volume_min`` (exact mirror of the MQL5
    ``SpecNormalizeVolume`` contract); the sizing path rejects below-min
    risk budgets BEFORE reaching this function (``mql5bot.sizer`` BELOW_MIN),
    so the min-bump here is reachable only off the sizing path.

    Dust guard (Reality Gate §4, DECISIONS.md 2026-09-07): the floor uses
    ``lots/step + VOLUME_FLOOR_DUST_EPS`` with the SAME constant as the MQL5
    side (``SpecNormalizeVolume`` / Meta re-normalisation, 1e-9 step units).
    It absorbs IEEE-754 division dust only — inputs strictly below a grid
    point by MORE than 1e-9 of a step still floor down. This is
    REPRESENTATION tolerance, never EXECUTION tolerance: changing this
    constant breaks the cross-runtime volume contract and requires a
    DECISIONS.md entry.
    """
    if spec.volume_step <= 0.0 or spec.volume_min <= 0.0:
        raise ValueError(f"{spec.name}: volume min/step must be positive")
    if lots <= 0.0:
        return 0.0
    step = spec.volume_step
    floor = int(lots / step + VOLUME_FLOOR_DUST_EPS) * step
    if floor < spec.volume_min:
        return spec.volume_min
    cap = spec.volume_max
    if spec.volume_limit > 0.0:
        cap = min(cap, spec.volume_limit)
    if floor > cap:
        # floor the cap onto the step grid so the result can never exceed it
        floor = int(cap / step + VOLUME_FLOOR_DUST_EPS) * step
        if floor < spec.volume_min:
            return 0.0  # cap below the minimum: nothing tradable
    return round(floor / step) * step


def loss_per_lot(
    stop_distance: float,
    spec: SymbolSpec,
    profit_to_deposit: float = 1.0,
) -> float:
    """Stop-loss loss per 1.0 lot, in DEPOSIT currency.

    ``loss = ticks(stop_distance) * tick_value_loss * profit_to_deposit``
    where ``tick_value_loss`` is in the symbol's profit currency. The
    conversion factor is injected (queried at runtime from the profit
    currency's quote; 1.0 when profit currency == deposit currency) — never
    assumed (SPEC §3.3 lists SYMBOL_TRADE_TICK_VALUE_PROFIT/_LOSS).
    """
    if spec.tick_value_loss <= 0.0:
        raise ValueError(f"{spec.name}: tick_value_loss must be positive")
    if profit_to_deposit <= 0.0:
        raise ValueError(f"{spec.name}: profit_to_deposit must be positive")
    if stop_distance <= 0.0:
        return 0.0
    return ticks_of(stop_distance, spec) * spec.tick_value_loss * profit_to_deposit
