"""Discovery domain — value objects and small immutable rules
(autonomous-discovery mission §3/§28/§30/§96).

Clean-architecture DOMAIN layer: no I/O, no frameworks, no engine
imports.  Invariants live on the objects, not in callers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class DomainError(ValueError):
    """Invalid value-object construction (fail fast, never coerce)."""


@dataclass(frozen=True, slots=True)
class StrategyId:
    value: str

    def __post_init__(self):
        if not _ID_RE.match(self.value):
            raise DomainError(f"invalid strategy id {self.value!r}")


@dataclass(frozen=True, slots=True)
class SpecHash:
    value: str

    def __post_init__(self):
        if not _SHA_RE.match(self.value):
            raise DomainError("spec hash must be 64 lowercase hex")


@dataclass(frozen=True, slots=True)
class DatasetHash:
    value: str

    def __post_init__(self):
        if not self.value or len(self.value) > 128:
            raise DomainError("dataset hash must be 1..128 chars")


@dataclass(frozen=True, slots=True)
class CampaignId:
    value: str

    def __post_init__(self):
        if not _ID_RE.match(self.value):
            raise DomainError(f"invalid campaign id {self.value!r}")


class EvidenceLevel(Enum):
    """Explicit research-evidence ladder (mission §30) — deliberately
    SEPARATE from both the lifecycle state and the Discovery Score."""

    E0_IDEA = "E0"
    E1_PARSED = "E1"
    E2_BACKTESTED = "E2"
    E3_OOS_ROBUST = "E3"
    E4_SHADOW = "E4"
    E5_DEMO = "E5"
    E6_LIVE_SMALL = "E6"
    E7_LIVE_PROVEN = "E7"

    @classmethod
    def from_lifecycle(cls, state: str | None) -> EvidenceLevel:
        return {
            None: cls.E0_IDEA,
            "DRAFT": cls.E0_IDEA,
            "PARSED": cls.E1_PARSED,
            "VALIDATED": cls.E1_PARSED,
            "BACKTESTED": cls.E2_BACKTESTED,
            "ROBUSTNESS_PASS": cls.E3_OOS_ROBUST,
            "OOS_SURVIVOR": cls.E3_OOS_ROBUST,
            "SHADOW": cls.E4_SHADOW,
            "DEMO": cls.E5_DEMO,
            "LIVE_SMALL": cls.E6_LIVE_SMALL,
            "LIVE": cls.E7_LIVE_PROVEN,
            "DEGRADED": cls.E4_SHADOW,
            "PAUSED": cls.E4_SHADOW,
            "RETIRED": cls.E4_SHADOW,
            "REJECTED": cls.E0_IDEA,
        }.get(state, cls.E0_IDEA)


class AutonomyLevel(Enum):
    """Automation envelope (mission §96).  Default production setting
    during this project is RESEARCH_AUTOMATION or safer; automatic
    real-money promotion stays OFF unless the configured level and the
    audited human-approval policy both allow it."""

    MANUAL = "MANUAL"
    ASSISTED = "ASSISTED"
    RESEARCH_AUTOMATION = "RESEARCH_AUTOMATION"
    SHADOW_AUTOMATION = "SHADOW_AUTOMATION"
    DEMO_AUTOMATION = "DEMO_AUTOMATION"
    LIVE_SMALL_AUTOMATION = "LIVE_SMALL_AUTOMATION"
    FULL_AUTOMATION = "FULL_AUTOMATION"

    @property
    def rank(self) -> int:
        return list(type(self)).index(self)

    def may_auto_advance_past(self, state: str) -> bool:
        """May the orchestrator auto-advance THROUGH the given state's
        exit transition?  Anything into DEMO+ needs >= DEMO_AUTOMATION
        PLUS the store's audited human-approval records; LIVE_SMALL→LIVE
        needs FULL_AUTOMATION (and still records approvals)."""
        need = {
            "DRAFT": AutonomyLevel.RESEARCH_AUTOMATION,
            "PARSED": AutonomyLevel.RESEARCH_AUTOMATION,
            "VALIDATED": AutonomyLevel.RESEARCH_AUTOMATION,
            "BACKTESTED": AutonomyLevel.RESEARCH_AUTOMATION,
            "ROBUSTNESS_PASS": AutonomyLevel.RESEARCH_AUTOMATION,
            "OOS_SURVIVOR": AutonomyLevel.SHADOW_AUTOMATION,
            "SHADOW": AutonomyLevel.DEMO_AUTOMATION,
            "DEMO": AutonomyLevel.LIVE_SMALL_AUTOMATION,
            "LIVE_SMALL": AutonomyLevel.FULL_AUTOMATION,
        }.get(state)
        return need is not None and self.rank >= need.rank


@dataclass(frozen=True, slots=True)
class AllocationWeight:
    """A Meta-layer relative weight in [0, 1.5] (existing clamp)."""

    value: float

    def __post_init__(self):
        if not 0.0 <= self.value <= 1.5:
            raise DomainError("allocation weight must be within [0, 1.5]")


@dataclass(frozen=True, slots=True)
class RiskBudget:
    """Fraction of equity authorized by the RISK engine (never by
    Meta/Factory)."""

    fraction: float

    def __post_init__(self):
        if not 0.0 <= self.fraction <= 1.0:
            raise DomainError("risk budget fraction must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class DecayBand:
    name: str
    multiplier: float
    pause: bool = False


DEFAULT_DECAY_BANDS: tuple[DecayBand, ...] = (
    DecayBand("HEALTHY", 1.00),
    DecayBand("MINOR_DEGRADATION", 0.80),
    DecayBand("MODERATE_DEGRADATION", 0.55),
    DecayBand("SEVERE_DEGRADATION", 0.25),
    DecayBand("CRITICAL", 0.00, pause=True),
)


@dataclass(frozen=True, slots=True)
class RampStep:
    factor: float
    min_live_trades: int
    max_live_dd_pct: float
    max_slippage_bps: float


DEFAULT_RAMP: tuple[RampStep, ...] = (
    RampStep(0.25, min_live_trades=0, max_live_dd_pct=4.0,
             max_slippage_bps=30.0),
    RampStep(0.40, min_live_trades=20, max_live_dd_pct=4.0,
             max_slippage_bps=30.0),
    RampStep(0.60, min_live_trades=40, max_live_dd_pct=5.0,
             max_slippage_bps=30.0),
    RampStep(0.80, min_live_trades=60, max_live_dd_pct=6.0,
             max_slippage_bps=30.0),
    RampStep(1.00, min_live_trades=100, max_live_dd_pct=8.0,
             max_slippage_bps=30.0),
)
