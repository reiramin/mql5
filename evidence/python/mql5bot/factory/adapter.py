"""mql5bot.factory.adapter — Factory→Meta eligibility feed (mission
§36-§39, §63, §70).

READ-ONLY translation of factory lifecycle state into the EXISTING
Meta certification vocabulary.  This adapter:

- NEVER widens authority: pre-shadow strategies map to NO
  certification state (Meta's ``UNCERTIFIED`` block applies);
- never issues allocation itself — it produces
  :class:`~mql5bot.meta_layer.StrategyMetaInput` rows the existing
  Meta layer consumes through its unchanged ladder and clamps;
- strategies absent from the factory DB (e.g. the five reference
  strategies) are passed through UNCHANGED — a Factory outage cannot
  affect them (§1.14/§38);
- invalid/unknown factory states map to ``None`` (⇒ NO_NEW_TRADES for
  that strategy, never a free pass) (§1.15).
"""

from __future__ import annotations

from mql5bot.meta_layer import StrategyMetaInput

from . import lifecycle as lc

_SHADOW_PLUS = frozenset(lc.EXECUTION_STATES)
_VERIFIED_PLUS = frozenset({lc.LIVE_SMALL, lc.LIVE})
_OBSERVED_PLUS = frozenset(lc.OBSERVATION_STATES)


def certification_for(lifecycle_state: str | None,
                      *, human_approved: bool = True) -> str | None:
    """Map lifecycle state → Meta certification state.

    ``human_approved`` reflects the audited PromotionDecision chain
    (the store enforces it for DEMO/LIVE_SMALL/LIVE); an unapproved
    DEMO+ state is NOT translated into eligibility (§51)."""
    if lifecycle_state is None or lifecycle_state not in _OBSERVED_PLUS:
        return None                       # unknown ⇒ never eligible
    if lifecycle_state in _VERIFIED_PLUS and not human_approved:
        return None
    if lifecycle_state in _VERIFIED_PLUS:
        return "VERIFIED"
    return "EMPIRICAL_VALIDATION_PENDING"


def meta_input(*, strategy_id: str, symbol: str, signal: int,
               regime: str, lifecycle_state: str | None,
               strategy_version: str = "", enabled: bool = True,
               human_approved: bool = True,
               **extra) -> StrategyMetaInput:
    """Build one StrategyMetaInput from factory state (+ runtime
    signal).  Factory supplies CERTIFICATION only; the signal comes
    from the strategy runtime, never from the Factory."""
    return StrategyMetaInput(
        strategy_id=strategy_id, symbol=symbol, signal=signal,
        regime=regime,
        certification_state=certification_for(
            lifecycle_state, human_approved=human_approved),
        enabled=enabled, strategy_version=strategy_version, **extra)
