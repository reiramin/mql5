"""mql5bot.dsl.model — frozen parsed-spec model.

The runtime consumes THIS, never raw dicts: parsing resolves params,
collects ambiguities and pre-validates references, so evaluation is
total (no partial failures mid-run).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IndicatorDef:
    id: str
    kind: str                      # EMA/SMA/RSI/ATR/BBANDS/MACD/DONCHIAN/HIGHEST/LOWEST
    period: int = 14
    applied: str = "close"         # open/high/low/close (kinds that use it)
    shift: int = 0
    dev: float = 2.0               # BBANDS
    fast: int = 12                 # MACD
    slow: int = 26                 # MACD
    signal: int = 9                # MACD
    params: dict = field(default_factory=dict)   # registry kinds (§8/§9)


@dataclass(frozen=True)
class StopModel:
    model: str                     # atr | points | percent
    value: float


@dataclass(frozen=True)
class ExitSpec:
    sl: StopModel | None = None
    tp: StopModel | None = None
    trail_atr: float = 0.0
    breakeven_atr: float = 0.0
    time_bars: int | None = None
    reversal: bool = False


@dataclass(frozen=True)
class EntrySpec:
    mode: str                      # state | instant
    long: dict | None = None       # normalized condition trees
    short: dict | None = None
    exit_long: dict | None = None
    exit_short: dict | None = None


@dataclass(frozen=True)
class Filters:
    max_spread_points: float | None = None
    max_atr_pct: float | None = None
    cooldown_bars: int = 0
    session: tuple | None = None       # (start "HH:MM", end, tz)
    regime_forbidden: tuple = ()
    regime_allowed: tuple = ()
    regime_preferred: tuple = ()


@dataclass(frozen=True)
class MarketSpec:
    symbol: str
    timeframe: str
    session: tuple | None = None       # market-level session (informational for the EA)
    trading_days: tuple = ()           # 0=Mon..6=Sun


@dataclass(frozen=True)
class StrategySpec:
    """Immutable parsed strategy. ``document`` is the normalized dict;
    ``spec_hash``/``semantic_hash`` come from normalize.py."""

    strategy_id: str
    version: int
    document: dict
    indicators: tuple = ()             # IndicatorDef
    entry: EntrySpec | None = None
    exit: ExitSpec | None = None
    filters: Filters = field(default_factory=Filters)
    market: MarketSpec | None = None
    name: str = ""
    description: str = ""
    source: dict = field(default_factory=dict)
    hypothesis: dict = field(default_factory=dict)
    claims: tuple = ()                 # AUTHOR_CLAIM dicts (never measured)
    metadata: dict = field(default_factory=dict)
    param_decls: dict = field(default_factory=dict)
    ambiguities: tuple = ()            # {"name", "path", "range"} — block execution
    spec_hash: str = ""
    semantic_hash: str = ""
    dedup_hash: str = ""

    @property
    def executable(self) -> bool:
        """A spec with unresolved ambiguities must never run (mission
        §10: ambiguity ⇒ clarification or explicit research ranges).
        Version 0 (DRAFT) is NEVER executable regardless of content —
        drafts are placeholders that invent nothing and can neither
        run nor promote (integration gate §14/§32; store refuses to
        register non-executable specs with version != 0)."""
        return self.version > 0 and not self.ambiguities
