"""Allocation governor — evidence → weight → Meta → Risk → lots
(mission §40/§65-§67/§78/§79).

Hard separations enforced in code:

- discovery SCORE ranks candidates; it NEVER sizes orders (lots come
  only from the Risk engine after Meta weights, §65).
- the governor's recommendation is a RECOMMENDATION; the effective
  allocation equals recommendation × decay multiplier × ramp factor ×
  safety overrides (kill switch ⇒ 0 new trades; circuit breaker ⇒
  last-safe), bounded by the circuit-breaker policy (§79).
- 0% gross exposure is a legitimate outcome (§40) and heat ≠ gross.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .domain import AllocationWeight
from .safety import KillSwitchState


@dataclass
class GovernorBounds:
    max_daily_abs_change_pct: float = 15.0
    max_strategy_delta: float = 0.20
    max_gross_exposure_delta_pct: float = 20.0
    max_risk_delta: float = 0.05

    def validate(self) -> None:
        if any(v <= 0 for v in (self.max_daily_abs_change_pct,
                                self.max_gross_exposure_delta_pct,
                                self.max_risk_delta)):
            raise ValueError("governor bounds must be positive")


@dataclass
class EligibilityRecord:
    """What makes a strategy ELIGIBLE for allocation at all (§66).
    Score is NOT among these — eligibility is gates + lifecycle."""

    strategy_id: str
    lifecycle_state: str          # must be a live-carrying state
    human_approved: bool
    gates_pass: bool              # Gate-1/robustness/OOS all PASS
    kill_switch_ok: bool
    evidence_ok: bool             # stage-adequate evidence bound to spec

    def eligible(self) -> tuple[bool, str]:
        if self.lifecycle_state not in ("SHADOW", "DEMO", "LIVE_SMALL",
                                        "LIVE"):
            return False, (f"lifecycle {self.lifecycle_state} carries no "
                           "live allocation")
        if not self.human_approved:
            return False, "missing structured human approval"
        if not self.gates_pass:
            return False, "qualification gates not PASS"
        if not self.kill_switch_ok:
            return False, "kill switch not NORMAL"
        if not self.evidence_ok:
            return False, "evidence missing or unbound"
        return True, "eligible"


@dataclass
class AllocationDecisionRecord:
    """§78: the five distinct notions kept apart."""
    strategy_id: str
    score: float                                  # research attractiveness
    eligible: bool                                # gates+lifecycle+approval
    recommendation: float                         # governor's weight proposal
    approved: bool                                # human/circuit outcome
    effective_weight: float                       # after decay×ramp×safety
    decay_multiplier: float = 1.0
    ramp_factor: float = 1.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"strategy_id": self.strategy_id, "score": self.score,
                "eligible": self.eligible,
                "recommendation": self.recommendation,
                "approved": self.approved,
                "effective_weight": self.effective_weight,
                "decay_multiplier": self.decay_multiplier,
                "ramp_factor": self.ramp_factor,
                "reasons": self.reasons}


class AllocationGovernor:
    def __init__(self, bounds: GovernorBounds | None = None,
                 *, target_gross_min_pct: float = 10.0,
                 target_gross_max_pct: float = 20.0,
                 allow_zero_exposure: bool = True):
        self.bounds = bounds or GovernorBounds()
        self.bounds.validate()
        if target_gross_min_pct < 0 or \
                target_gross_max_pct < target_gross_min_pct:
            raise ValueError("invalid gross target band")
        self.target_gross_min_pct = target_gross_min_pct
        self.target_gross_max_pct = target_gross_max_pct
        self.allow_zero_exposure = allow_zero_exposure

    def recommend(self, entries: list[EligibilityRecord],
                  scores: dict[str, float],
                  *, decay_mult: dict[str, float] | None = None,
                  ramp: dict[str, float] | None = None,
                  kill_switch_state: KillSwitchState = KillSwitchState.NORMAL,
                  previous_weights: dict[str, float] | None = None
                  ) -> dict:
        """Returns {allocations: [...], gross_pct, status, reasons}."""
        previous = previous_weights or {}
        decay_mult = decay_mult or {}
        ramp = ramp or {}
        if kill_switch_state is not KillSwitchState.NORMAL:
            return {"allocations": [], "gross_pct": 0.0,
                    "status": "KILL_SWITCH",
                    "reasons": [(f"kill switch "
                                 f"{kill_switch_state.value}: "
                                 "no new trades")]}

        # decay/ramp are DEMOTE-ONLY multipliers by contract (decay bands and
        # ramp steps are all in [0, 1]). Clamp defensively so a hostile or
        # buggy caller cannot pass a multiplier > 1 and inflate exposure
        # above the gross band — Meta/governor may only REDUCE.
        def _demote(d: dict[str, float], sid: str) -> float:
            v = d.get(sid, 1.0)
            if not math.isfinite(v):
                return 0.0  # non-finite → most conservative
            return min(1.0, max(0.0, v))

        raw: dict[str, float] = {}
        records: list[AllocationDecisionRecord] = []
        for e in entries:
            ok, why = e.eligible()
            dm = _demote(decay_mult, e.strategy_id)
            rf = _demote(ramp, e.strategy_id)
            rec = 0.0
            if ok:
                base = max(0.0, scores.get(e.strategy_id, 0.0))
                rec = base * dm * rf
            raw[e.strategy_id] = rec
            records.append(AllocationDecisionRecord(
                strategy_id=e.strategy_id, score=scores.get(
                    e.strategy_id, 0.0),
                eligible=ok, recommendation=rec, approved=ok,
                effective_weight=rec,
                decay_multiplier=dm,
                ramp_factor=rf,
                reasons=[] if ok else [why]))
        # normalize into the gross target band, THEN apply decay×ramp —
        # safety/degradation multipliers scale the FINAL allocation and
        # are never renormalized away (§33/§29)
        total = sum(raw.values())
        gross_target = self.target_gross_max_pct / 100.0
        allocs = []
        for r in records:
            w = (raw[r.strategy_id] / total) * gross_target \
                if total > 0 else 0.0
            w *= r.decay_multiplier * r.ramp_factor
            # a single strategy can never carry more than the whole gross
            # target band (reduce-only ceiling; the [0,1.5] domain type stays
            # a loose backstop above this tighter cap).
            aw = AllocationWeight(round(min(w, gross_target), 6))
            r.effective_weight = aw.value
            allocs.append(r)
        gross = round(sum(r.effective_weight for r in allocs) * 100, 4)
        reasons = []
        if total == 0 and self.allow_zero_exposure:
            reasons.append("no eligible candidate → 0% exposure "
                           "(legitimate, §40)")
        # §79: bound per-strategy and gross deltas vs previous
        for r in allocs:
            # An ineligible strategy (failed gate / lifecycle demotion /
            # missing evidence / kill switch) is a HARD zero and must never
            # be smoothed back up by the symmetric delta cap — mirrors the
            # zero-reason exemption in meta_layer._apply_modes. Without this
            # a strategy that just failed its gate would keep
            # ``prev - max_strategy_delta`` of allocation (§66/§78).
            if not r.eligible:
                r.effective_weight = 0.0
                continue
            prev = previous.get(r.strategy_id, 0.0)
            if abs(r.effective_weight - prev) > \
                    self.bounds.max_strategy_delta:
                capped = prev + (self.bounds.max_strategy_delta
                                 if r.effective_weight > prev
                                 else -self.bounds.max_strategy_delta)
                r.reasons.append(
                    f"delta capped {prev:.3f}→{capped:.3f} "
                    f"(≤{self.bounds.max_strategy_delta}/rebalance)")
                r.effective_weight = round(max(0.0, capped), 6)
        return {"allocations": [r.to_dict() for r in allocs],
                "gross_pct": gross, "status": "OK", "reasons": reasons}
