"""Extensible indicator universe (mission §8/§9).

Public API:
    from mql5bot.indicator_universe import ALL_KINDS, contract, compute
"""

from .contracts import CATEGORIES, IndicatorContract, IndicatorParam
from .registry import (
                       ALL_KINDS,
                       BASELINE_KINDS,
                       EXTENDED_KINDS,
                       REGISTRY,
                       compute,
                       contract,
)

__all__ = [
                       "ALL_KINDS",
                       "BASELINE_KINDS",
                       "CATEGORIES",
                       "EXTENDED_KINDS",
                       "REGISTRY",
                       "IndicatorContract",
                       "IndicatorParam",
                       "compute",
                       "contract",
]
