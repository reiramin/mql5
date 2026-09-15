"""Performance decay controller and live-small ramp (mission §33-§36).

Decay (§35) uses MULTIPLE signals — rolling expectancy ratio, live-vs-
backtest drawdown ratio, drift score, execution quality — never
consecutive losses alone.  One isolated loss cannot demote (a minimum
rolling-trade count guards the band decision).  Recovery (§36) always
routes through requalification: PAUSED → REQUALIFICATION → SHADOW;
recent improvement alone never revives a failed strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from .domain import DEFAULT_DECAY_BANDS, DEFAULT_RAMP, DecayBand, RampStep


@dataclass(frozen=True)
class HealthSignals:
    """Recent live evidence vs backtest expectation."""

    rolling_trades: int
    expectancy_ratio: float          # live expectancy / backtest expectancy
    dd_ratio: float                  # live DD% / backtest DD%
    drift_score: float               # [0, 1] from drift_feed
    slippage_bps_vs_assumed: float   # realized minus assumed
    regime_mismatch: bool = False
    risk_breach: bool = False        # hard risk-control breach


class PerformanceDecayController:
    def __init__(self, bands: tuple[DecayBand, ...] = DEFAULT_DECAY_BANDS,
                 *, min_expectancy_ratio: float = 0.5,
                 max_dd_ratio: float = 2.0, max_drift_score: float = 0.6,
                 min_rolling_trades: int = 10):
        if not bands or bands[0].name != "HEALTHY":
            raise ValueError("decay bands must start HEALTHY")
        mults = [b.multiplier for b in bands]
        if mults != sorted(mults, reverse=True) or any(
                not 0.0 <= m <= 1.0 for m in mults):
            raise ValueError("decay multipliers must descend within [0,1]")
        self.bands = bands
        self.min_expectancy_ratio = min_expectancy_ratio
        self.max_dd_ratio = max_dd_ratio
        self.max_drift_score = max_drift_score
        self.min_rolling_trades = min_rolling_trades

    def evaluate(self, s: HealthSignals) -> tuple[DecayBand, str]:
        """Returns (band, reason).  Deterministic; worst-signal-wins."""
        if s.risk_breach:
            return self.bands[-1], "risk-control breach (hard evidence)"
        if s.rolling_trades < self.min_rolling_trades:
            # §35: one isolated loss (or a tiny sample) NEVER demotes
            return self.bands[0], (f"insufficient rolling trades "
                                   f"({s.rolling_trades} < "
                                   f"{self.min_rolling_trades})")
        reasons = []
        penalties = 0
        if s.expectancy_ratio < self.min_expectancy_ratio:
            penalties += 2
            reasons.append(f"expectancy ratio {s.expectancy_ratio:.2f} "
                           f"< {self.min_expectancy_ratio}")
        if s.dd_ratio > self.max_dd_ratio:
            penalties += 2
            reasons.append(f"DD ratio {s.dd_ratio:.2f} > "
                           f"{self.max_dd_ratio}")
        if s.drift_score > self.max_drift_score:
            penalties += 1
            reasons.append(f"drift {s.drift_score:.2f} > "
                           f"{self.max_drift_score}")
        if s.slippage_bps_vs_assumed > 10.0:
            penalties += 1
            reasons.append(f"slippage +{s.slippage_bps_vs_assumed:.1f}bps "
                           "vs assumption")
        if s.regime_mismatch:
            penalties += 1
            reasons.append("regime mismatch")
        idx = min(penalties, len(self.bands) - 1)
        if idx == 0:
            return self.bands[0], "healthy"
        return self.bands[idx], "; ".join(reasons)


class RequalificationGate:
    """§36: PAUSED strategies return through requalification, never by
    a lucky recent streak."""

    def __init__(self, *, min_shadow_trades: int = 30,
                 min_shadow_days: int = 14, min_score: float = 0.55):
        self.min_shadow_trades = min_shadow_trades
        self.min_shadow_days = min_shadow_days
        self.min_score = min_score

    def may_requalify(self, *, shadow_trades: int, shadow_days: int,
                      shadow_score: float, rejected_before: bool = False
                      ) -> tuple[bool, str]:
        if rejected_before:
            return False, ("previously REJECTED candidates need a NEW "
                           "version + full validation, not revival")
        if shadow_trades < self.min_shadow_trades:
            return False, (f"shadow trades {shadow_trades} < "
                           f"{self.min_shadow_trades}")
        if shadow_days < self.min_shadow_days:
            return False, (f"shadow days {shadow_days} < "
                           f"{self.min_shadow_days}")
        if shadow_score < self.min_score:
            return False, (f"shadow score {shadow_score:.3f} < "
                           f"{self.min_score}")
        return True, "requalification evidence complete"


class LiveSmallRamp:
    """§33/§34: progressive, evidence-gated, REVERSIBLE sizing."""

    def __init__(self, steps: tuple[RampStep, ...] = DEFAULT_RAMP):
        if not steps or steps[0].factor <= 0 or \
                steps[-1].factor != 1.0 or \
                any(b.factor <= a.factor for a, b in pairwise(steps)):
            raise ValueError("ramp must start >0, ascend, end at 1.0")
        self.steps = steps

    def factor_for(self, *, live_trades: int, live_dd_pct: float,
                   slippage_bps: float, degraded: bool = False,
                   circuit_breaker: bool = False,
                   kill_switch_active: bool = False) -> tuple[float, str]:
        """Worst-case wins: any safety flag or threshold violation
        scales DOWN (reversibility, §34)."""
        if kill_switch_active:
            return 0.0, "kill switch active"
        if circuit_breaker:
            return 0.0, "allocation circuit breaker frozen"
        factor, why = 0.0, "no ramp step qualified"
        for step in self.steps:
            if live_trades >= step.min_live_trades and \
                    live_dd_pct <= step.max_live_dd_pct and \
                    slippage_bps <= step.max_slippage_bps:
                factor, why = step.factor, (
                    f"step {step.factor}x qualifies "
                    f"(trades {live_trades}, dd {live_dd_pct:.1f}%, "
                    f"slip {slippage_bps:.0f}bps)")
        if degraded:
            factor = round(factor * 0.5, 4)
            why += " | degraded: halved (reversible)"
        return factor, why
