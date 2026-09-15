"""Safety governance — independent controls (mission §41-§45/§79-§81).

Three DELIBERATELY boring, small components:

- :class:`KillSwitch` — account/execution safety.  States
  NORMAL / NO_NEW_TRADES / EMERGENCY_HALT.  Sits OUTSIDE strategy,
  factory, discovery score, Meta and LLM; it overrides every one of
  them (§43).  State persists; EMERGENCY_HALT requires an explicit
  audited reset.  CLOSE_ALL behavior is policy-driven (§42) and
  defaults to keep-managing (never indiscriminate liquidation).

- :class:`AllocationCircuitBreaker` — decision-behavior anomaly guard
  (§41/§79/§80): abnormal allocation jumps, strategy-count collapse or
  candidate explosions FREEZE new allocation and keep the last safe
  allocation.  NOT the kill switch; never closes anything.

- :class:`Watchdog` — a minimal external monitor (§44/§45): no
  strategy logic, no LLM, no allocation authority; observes
  heartbeat/equity/drawdown/positions and emits rate-limited alerts
  through an injected channel.  Designed to run in its own process so
  a Factory crash cannot silence it (§81).

All three are deterministic and persist their state transitions.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

# ------------------------------------------------------------ kill switch


class KillSwitchState(str, Enum):
    NORMAL = "NORMAL"
    NO_NEW_TRADES = "NO_NEW_TRADES"
    EMERGENCY_HALT = "EMERGENCY_HALT"


@dataclass
class KillSwitchPolicy:
    max_daily_dd_pct: float = 6.0
    max_weekly_dd_pct: float = 12.0
    max_total_dd_pct: float = 25.0
    max_trade_rate_per_hour: int = 60
    max_execution_failure_rate: float = 0.5
    max_stale_heartbeat_seconds: float = 300.0
    equity_floor_pct: float = 50.0        # of reference equity
    close_all_on_emergency: bool = False  # §42: policy-driven

    def validate(self) -> None:
        vals = [self.max_daily_dd_pct, self.max_weekly_dd_pct,
                self.max_total_dd_pct, self.equity_floor_pct]
        if any(v <= 0 or v > 100 for v in vals) or \
                self.max_trade_rate_per_hour < 1 or \
                not 0 < self.max_execution_failure_rate <= 1:
            raise ValueError("kill-switch thresholds out of range")


@dataclass
class KillSwitchObservation:
    daily_dd_pct: float = 0.0
    weekly_dd_pct: float = 0.0
    total_dd_pct: float = 0.0
    trades_last_hour: int = 0
    execution_failure_rate: float = 0.0
    heartbeat_age_seconds: float = 0.0
    equity: float = 0.0
    reference_equity: float = 0.0
    impossible_position_state: bool = False
    broker_connected: bool = True
    exposure_breach: bool = False


class KillSwitch:
    """Independent authority.  ``evaluate`` is PURE given (observation,
    current state); persistence is the caller's ``state_sink``."""

    def __init__(self, policy: KillSwitchPolicy | None = None,
                 state_sink: Callable[[dict], None] | None = None):
        self.policy = policy or KillSwitchPolicy()
        self.policy.validate()
        self._sink = state_sink
        self.state = KillSwitchState.NORMAL
        self.reason = ""
        self.history: list[dict] = []

    def _record(self, action: str, obs: KillSwitchObservation | None,
                reason: str, actor: str = "system") -> None:
        entry = {"action": action, "state": self.state.value,
                 "reason": reason, "actor": actor,
                 "ts": time.time(),
                 "daily_dd": obs.daily_dd_pct if obs else None}
        self.history.append(entry)
        if len(self.history) > 500:      # bounded, append-only window
            del self.history[:len(self.history) - 500]
        if self._sink is not None:
            self._sink({"state": self.state.value, "reason": self.reason,
                        "history": self.history[-100:]})

    def trips(self, obs: KillSwitchObservation) -> list[str]:
        p = self.policy
        out = []
        if obs.daily_dd_pct >= p.max_daily_dd_pct:
            out.append(f"daily DD {obs.daily_dd_pct:.1f}% >= "
                       f"{p.max_daily_dd_pct}%")
        if obs.weekly_dd_pct >= p.max_weekly_dd_pct:
            out.append(f"weekly DD {obs.weekly_dd_pct:.1f}%")
        if obs.total_dd_pct >= p.max_total_dd_pct:
            out.append(f"total DD {obs.total_dd_pct:.1f}%")
        if obs.trades_last_hour > p.max_trade_rate_per_hour:
            out.append(f"trade rate {obs.trades_last_hour}/h")
        if obs.execution_failure_rate >= p.max_execution_failure_rate:
            out.append("execution failure rate")
        if obs.heartbeat_age_seconds > p.max_stale_heartbeat_seconds:
            out.append("stale heartbeat")
        if p.equity_floor_pct > 0 and obs.reference_equity > 0 and \
                obs.equity < obs.reference_equity * p.equity_floor_pct / 100:
            out.append("equity below floor")
        if obs.impossible_position_state:
            out.append("impossible position state")
        if not obs.broker_connected:
            out.append("broker disconnected")
        if obs.exposure_breach:
            out.append("exposure breach")
        return out

    def evaluate(self, obs: KillSwitchObservation) -> KillSwitchState:
        if self.state is KillSwitchState.EMERGENCY_HALT:
            return self.state               # only explicit_reset leaves
        trips = self.trips(obs)
        if trips:
            severe = ("equity below floor" in trips
                      or "impossible position state" in trips
                      or "total DD" in " ".join(trips))
            self.state = (KillSwitchState.EMERGENCY_HALT if severe
                          else KillSwitchState.NO_NEW_TRADES)
            self.reason = "; ".join(trips)
            self._record("trip", obs, self.reason)
        else:
            if self.state is not KillSwitchState.NORMAL:
                # NO_NEW_TRADES clears when the trigger is gone; the
                # EMERGENCY_HALT path never reaches this branch
                self.state = KillSwitchState.NORMAL
                self.reason = ""
                self._record("clear", obs, "all triggers cleared")
        return self.state

    def explicit_reset(self, actor: str, reason: str) -> KillSwitchState:
        """§42: severe states require an EXPLICIT, audited reset."""
        prev = self.state
        self.state = KillSwitchState.NORMAL
        self.reason = ""
        self._record("explicit_reset", None, f"{prev.value} → NORMAL by "
                     f"{actor}: {reason}", actor=actor)
        return self.state

    def may_open_new_trades(self) -> bool:
        return self.state is KillSwitchState.NORMAL

    @property
    def close_all_requested(self) -> bool:
        return (self.state is KillSwitchState.EMERGENCY_HALT
                and self.policy.close_all_on_emergency)


# ------------------------------------------------------ circuit breaker


@dataclass
class BreakerPolicy:
    max_allocation_jump_pct: float = 25.0
    max_strategy_count_drop: int = 2
    max_candidate_explosion: int = 200
    cooldown_rebalances: int = 3

    def validate(self) -> None:
        if self.max_allocation_jump_pct <= 0 or \
                self.max_strategy_count_drop < 1 or \
                self.cooldown_rebalances < 1:
            raise ValueError("circuit-breaker bounds must be positive")


@dataclass
class AllocationProposal:
    """Proposed NEXT allocation snapshot (weights in [0, 1])."""

    weights: dict[str, float]
    gross_exposure_pct: float = 0.0

    def count(self) -> int:
        return len(self.weights)


@dataclass
class CircuitBreakerStateData:
    frozen: bool = False
    cooldown_left: int = 0
    last_safe: dict = field(default_factory=dict)
    last_reason: str = ""


class AllocationCircuitBreaker:
    """§41/§80: freezes NEW allocation on decision anomalies while the
    kill switch guards the ACCOUNT.  On anomaly: keep last safe
    allocation, alert, require human review."""

    def __init__(self, policy: BreakerPolicy | None = None):
        self.policy = policy or BreakerPolicy()
        self.policy.validate()
        self.st = CircuitBreakerStateData()

    def review(self, proposal: AllocationProposal, *,
               previous_gross_pct: float, candidate_count: int = 0
               ) -> tuple[dict, str]:
        """Returns (effective_weights, status) — status in
        APPLIED | FROZEN_KEEP_LAST_SAFE."""
        p = self.policy
        if self.st.cooldown_left > 0:
            self.st.cooldown_left -= 1
            return dict(self.st.last_safe), "FROZEN_KEEP_LAST_SAFE"
        anomalies = []
        jump = abs(proposal.gross_exposure_pct - previous_gross_pct)
        if jump > p.max_allocation_jump_pct:
            anomalies.append(
                f"gross allocation jump {jump:.1f}pp exceeds "
                f"{p.max_allocation_jump_pct}pp")
        if candidate_count > p.max_candidate_explosion:
            anomalies.append(f"candidate explosion ({candidate_count})")
        prev_count = len(self.st.last_safe)
        if prev_count and prev_count - proposal.count() >= \
                p.max_strategy_count_drop:
            anomalies.append(
                f"strategy count collapse {prev_count}→"
                f"{proposal.count()}")
        for sid, w in proposal.weights.items():
            prev = self.st.last_safe.get(sid, 0.0)
            if abs(w - prev) > 0.75:
                anomalies.append(f"per-strategy jump {sid} "
                                 f"{prev:.2f}→{w:.2f}")
        if anomalies:
            self.st.frozen = True
            self.st.cooldown_left = p.cooldown_rebalances
            self.st.last_reason = "; ".join(anomalies)
            return dict(self.st.last_safe), "FROZEN_KEEP_LAST_SAFE"
        self.st.frozen = False
        self.st.last_reason = ""
        self.st.last_safe = dict(proposal.weights)
        return dict(proposal.weights), "APPLIED"

    def reset(self, actor: str, reason: str) -> None:
        if not actor.strip() or not reason.strip():
            raise ValueError("breaker reset requires actor + reason")
        self.st.frozen = False
        self.st.cooldown_left = 0
        self.st.last_reason = f"reset by {actor}: {reason}"


# -------------------------------------------------------------- watchdog


@dataclass
class WatchdogObservation:
    equity: float
    daily_dd_pct: float
    open_positions: int
    trades_last_hour: int
    heartbeat_age_seconds: float
    emergency_state: str = "NORMAL"       # kill-switch view, if provided


class Watchdog:
    """Minimal external monitor (§44/§45).  No strategy logic, no LLM,
    no allocation authority.  ``channel`` receives alert dicts; the
    default channel logs.  Rate-limited per alert kind."""

    def __init__(self,
                 channel: Callable[[dict], None] | None = None,
                 *, heartbeat_max_age_seconds: float = 300.0,
                 max_dd_pct: float = 20.0,
                 alert_rate_limit_seconds: float = 300.0,
                 clock: Callable[[], float] = time.time):
        self.channel = channel or (lambda alert: print(
            "WATCHDOG:", json.dumps(alert, sort_keys=True)))
        self.heartbeat_max_age = heartbeat_max_age_seconds
        self.max_dd_pct = max_dd_pct
        self.rate_limit = alert_rate_limit_seconds
        self._clock = clock
        self._last_alert: dict[str, float] = {}
        self._channel_errors: list[dict] = []

    def check(self, obs: WatchdogObservation) -> list[str]:
        alerts = []
        if obs.daily_dd_pct >= self.max_dd_pct:
            alerts.append(f"daily DD {obs.daily_dd_pct:.1f}%")
        if obs.heartbeat_age_seconds > self.heartbeat_max_age:
            alerts.append(f"heartbeat stale "
                          f"{obs.heartbeat_age_seconds:.0f}s")
        if obs.emergency_state != "NORMAL":
            alerts.append(f"engine state {obs.emergency_state}")
        if obs.open_positions < 0:
            alerts.append("impossible position count")
        now = self._clock()
        for kind in alerts:
            if now - self._last_alert.get(kind, 0.0) >= self.rate_limit:
                self._last_alert[kind] = now
                try:
                    self.channel({"watchdog_alert": kind, "ts": now,
                                  "equity": obs.equity,
                                  "open_positions": obs.open_positions})
                except Exception as exc:            # noqa: BLE001
                    # fail-safe (§45): a broken alert channel must
                    # never stop the watchdog from monitoring; keep a
                    # local breadcrumb of the delivery failure
                    self._channel_errors.append(
                        {"kind": kind, "error": repr(exc), "ts": now})
        return alerts
