"""mql5bot.indicator_universe — the extensible indicator registry.

Mission §8/§9: the DSL is NOT restricted to a handful of hardcoded
indicators.  This package declares the universe as DATA (contracts)
plus deterministic, causal, closed-bar compute functions.

Contract (mission §9) — every indicator declares:
    kind            stable DSL token
    version         semantic version of the DEFINITION
    category        trend|momentum|volatility|volume|structure|candle|
                    statistical|mtf
    params          typed parameters with valid ranges (+ defaults)
    outputs         named outputs; PRIMARY FIRST (bare id → primary)
    warmup          bars required before the first defined value
    price_source    which frame columns it consumes
    determinism     always True here (pure functions, no clocks)
    causality       closed-bar guarantee text
    mql5_status     parity-tested | canonical-defined (owner compile)
    notes           platform-difference documentation (§10)

Canonical Aegis semantics (mission §10):
- all values are computed from CLOSED bars only;
- a value at index i uses rows <= i and is NaN during warmup;
- Wilder smoothing for RSI/ATR/ADX-family (as in ``indicators.py``);
- EMA seeds with SMA of the first ``period`` values;
- comparisons against other platforms must be documented here, never
  silently approximated.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

CATEGORIES = {"trend", "momentum", "volatility", "volume", "structure",
              "candle", "statistical", "mtf"}


@dataclass(frozen=True)
class IndicatorParam:
    name: str
    type: str                    # "int" | "float"
    minimum: float
    maximum: float
    default: float | None = None

    def check(self, value) -> str | None:
        """Return an error string when invalid (never repair)."""
        if self.type == "int":
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or float(value) != int(value):
                return f"{self.name} must be an integer"
        elif not isinstance(value, (int, float)):
            return f"{self.name} must be numeric"
        if not self.minimum <= value <= self.maximum:
            return (f"{self.name} must be in "
                    f"[{self.minimum:g}, {self.maximum:g}]")
        return None


@dataclass(frozen=True)
class IndicatorContract:
    kind: str
    version: int
    category: str
    params: tuple[IndicatorParam, ...]
    outputs: tuple[str, ...]              # PRIMARY FIRST
    warmup: Callable[[dict], int]
    price_source: str                     # close|high_low_close|ohlcv|volume
    determinism: bool = True
    causality: str = "closed-bar: value at i uses rows <= i only"
    mql5_status: str = "canonical-defined"
    notes: str = ""
    requires_columns: tuple[str, ...] = ()   # extra df columns (e.g. benchmark)

    def param_map(self) -> dict[str, IndicatorParam]:
        return {p.name: p for p in self.params}

    def validate(self, given: dict) -> list[str]:
        errors = []
        for p in self.params:
            if p.name in given:
                err = p.check(given[p.name])
                if err:
                    errors.append(err)
            elif p.default is None:
                errors.append(f"{p.name} is required")
        return errors

    def resolve(self, given: dict) -> dict:
        out = {}
        for p in self.params:
            if p.name in given:
                v = given[p.name]
                out[p.name] = int(v) if p.type == "int" else float(v)
            else:
                out[p.name] = p.default
        return out


def _w(period: int):
    return lambda p: int(p.get("period", period))


def P(name, type, lo, hi, default=None):
    return IndicatorParam(name, type, lo, hi, default)
