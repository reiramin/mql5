"""AEGIS autonomous discovery: domain, score, staging, governance."""

from .candidates import STAGES, RedundancyFilter, ResearchSpace, generate_stage
from .domain import (
                     AllocationWeight,
                     AutonomyLevel,
                     CampaignId,
                     DatasetHash,
                     DecayBand,
                     DomainError,
                     EvidenceLevel,
                     RampStep,
                     RiskBudget,
                     SpecHash,
                     StrategyId,
)
from .governance import (
                     HealthSignals,
                     LiveSmallRamp,
                     PerformanceDecayController,
                     RequalificationGate,
)
from .governor import (
                     AllocationDecisionRecord,
                     AllocationGovernor,
                     EligibilityRecord,
                     GovernorBounds,
)
from .orchestrator import DiscoveryOrchestrator, StageResult
from .portfolio import ConcentrationLimits, build_portfolio, marginal_contribution
from .safety import (
                     AllocationCircuitBreaker,
                     AllocationProposal,
                     BreakerPolicy,
                     KillSwitch,
                     KillSwitchObservation,
                     KillSwitchPolicy,
                     KillSwitchState,
                     Watchdog,
                     WatchdogObservation,
)
from .score import COMPONENTS, SCORE_VERSION, DiscoveryScore, compute_score

__all__ = [
                     "COMPONENTS",
                     "SCORE_VERSION",
                     "STAGES",
                     "AllocationCircuitBreaker",
                     "AllocationDecisionRecord",
                     "AllocationGovernor",
                     "AllocationProposal",
                     "AllocationWeight",
                     "AutonomyLevel",
                     "BreakerPolicy",
                     "CampaignId",
                     "ConcentrationLimits",
                     "DatasetHash",
                     "DecayBand",
                     "DiscoveryOrchestrator",
                     "DiscoveryScore",
                     "DomainError",
                     "EligibilityRecord",
                     "EvidenceLevel",
                     "GovernorBounds",
                     "HealthSignals",
                     "KillSwitch",
                     "KillSwitchObservation",
                     "KillSwitchPolicy",
                     "KillSwitchState",
                     "LiveSmallRamp",
                     "PerformanceDecayController",
                     "RampStep",
                     "RedundancyFilter",
                     "RequalificationGate",
                     "ResearchSpace",
                     "RiskBudget",
                     "SpecHash",
                     "StageResult",
                     "StrategyId",
                     "Watchdog",
                     "WatchdogObservation",
                     "build_portfolio",
                     "compute_score",
                     "generate_stage",
                     "marginal_contribution",
]
