"""mql5bot.factory.lifecycle — the evidence-gated strategy state machine.

States (mission §20)::

    DRAFT → PARSED → VALIDATED → BACKTESTED → ROBUSTNESS_PASS
          → OOS_SURVIVOR → SHADOW → DEMO → LIVE_SMALL → LIVE

Failure branches::

    DRAFT/VALIDATED/BACKTESTED/ROBUSTNESS_PASS/OOS_SURVIVOR → REJECTED
    SHADOW → DEGRADED          DEMO/LIVE_SMALL → PAUSED
    LIVE → DEGRADED            DEGRADED → RETIRED   PAUSED → (resume)

Hard rules:

- a transition WITHOUT its required evidence raises — no arbitrary
  database status update can promote a strategy (mission §20);
- every accepted transition appends an immutable event
  (``lifecycle_events`` in the store — the state machine itself is
  pure and returns the event);
- terminal states (REJECTED, RETIRED) never resurrect;
- REJECTED/DEGRADED/PAUSED preserve all evidence (mission §1.18/§1.19).
"""

from __future__ import annotations

from dataclasses import dataclass

DRAFT = "DRAFT"
PARSED = "PARSED"
VALIDATED = "VALIDATED"
BACKTESTED = "BACKTESTED"
ROBUSTNESS_PASS = "ROBUSTNESS_PASS"
OOS_SURVIVOR = "OOS_SURVIVOR"
SHADOW = "SHADOW"
DEMO = "DEMO"
LIVE_SMALL = "LIVE_SMALL"
LIVE = "LIVE"
REJECTED = "REJECTED"
DEGRADED = "DEGRADED"
PAUSED = "PAUSED"
RETIRED = "RETIRED"

RESEARCH_STATES = (DRAFT, PARSED, VALIDATED, BACKTESTED, ROBUSTNESS_PASS,
                   OOS_SURVIVOR)
EXECUTION_STATES = (SHADOW, DEMO, LIVE_SMALL, LIVE)
OBSERVATION_STATES = (SHADOW, DEMO, LIVE_SMALL, LIVE, DEGRADED, PAUSED)
TERMINAL_STATES = (REJECTED, RETIRED)
ALL_STATES = frozenset(RESEARCH_STATES + EXECUTION_STATES +
                       (REJECTED, DEGRADED, PAUSED, RETIRED))

# Forward ladder: state → the single next promotion state.  Every
# promotion requires the evidence kinds listed; the store refuses
# duplicates of the same evidence (mission §40: re-running validation
# creates a NEW run record, it never mutates prior evidence).
PROMOTIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    DRAFT: (PARSED, ("parse",)),
    PARSED: (VALIDATED, ("schema",)),
    VALIDATED: (BACKTESTED, ("backtest",)),
    BACKTESTED: (ROBUSTNESS_PASS, ("robustness",)),
    ROBUSTNESS_PASS: (OOS_SURVIVOR, ("oos",)),
    OOS_SURVIVOR: (SHADOW, ("shadow_entry",)),
    SHADOW: (DEMO, ("shadow_evidence",)),
    DEMO: (LIVE_SMALL, ("demo_evidence",)),
    LIVE_SMALL: (LIVE, ("live_small_evidence",)),
}

# Failure branches: state → allowed failure destinations.  (Mission
# §20 lists DRAFT/VALIDATED/BACKTESTED/ROBUSTNESS_PASS/OOS_SURVIVOR →
# REJECTED; PARSED → REJECTED is added as a safety SUPERSET — a spec
# that fails schema evidence must be rejectable.  No failure branch
# ever leads forward.)
FAILURES: dict[str, tuple[str, ...]] = {
    DRAFT: (REJECTED,),
    PARSED: (REJECTED,),
    VALIDATED: (REJECTED,),
    BACKTESTED: (REJECTED,),
    ROBUSTNESS_PASS: (REJECTED,),
    OOS_SURVIVOR: (REJECTED,),
    SHADOW: (DEGRADED,),
    DEMO: (PAUSED,),
    LIVE_SMALL: (PAUSED,),
    LIVE: (DEGRADED,),
}

# Recovery branches (observation continues; authority does not grow).
RECOVERIES: dict[str, tuple[str, ...]] = {
    PAUSED: (DEMO, LIVE_SMALL),
    DEGRADED: (SHADOW,),        # re-enter observation at shadow at most
}

# Retirement: anything observed may retire; RETIRED is terminal.
RETIRE_FROM = frozenset(OBSERVATION_STATES)


class IllegalTransition(Exception):
    """A state change that the machine forbids (with the reason)."""


@dataclass(frozen=True)
class Transition:
    """One accepted lifecycle event (append-only payload)."""

    strategy_id: str
    version: int
    from_state: str
    to_state: str
    kind: str                     # promote | fail | recover | retire
    evidence_refs: tuple          # ids of validation_runs / artifacts
    actor: str                    # who/what decided (owner | factory | gate:<name>)
    reason: str
    gate_version: str = ""


def normalize_state(state: str) -> str:
    s = str(state).upper()
    if s not in ALL_STATES:
        raise IllegalTransition(f"unknown lifecycle state {state!r}; "
                                f"known: {sorted(ALL_STATES)}")
    return s


def check_transition(current: str, target: str,
                     evidence_refs: tuple = (), *,
                     actor: str = "") -> Transition:
    """Validate a proposed transition and return its event payload.

    Raises :class:`IllegalTransition` when the machine forbids the
    move or the evidence is missing — the store must treat that as a
    hard refusal (no silent promotion, mission §41)."""
    cur = normalize_state(current)
    tgt = normalize_state(target)
    if not actor:
        raise IllegalTransition("every transition records an actor "
                                "(owner | factory | gate:<name>)")

    if cur in TERMINAL_STATES:
        raise IllegalTransition(
            f"{cur} is terminal: historical evidence is preserved and "
            "the strategy can never resurrect (mission §1.19)")

    if cur == tgt:
        raise IllegalTransition(f"self-transition {cur} is a no-op")

    if tgt == RETIRED:
        if cur in RETIRE_FROM:
            return Transition(
                strategy_id="", version=0, from_state=cur,
                to_state=RETIRED, kind="retire",
                evidence_refs=tuple(evidence_refs), actor=actor,
                reason="retirement preserves all historical evidence")
        raise IllegalTransition(
            f"{cur} cannot retire directly (must pass through an "
            "observed state)")

    if tgt in PROMOTIONS.get(cur, ("",))[0:1] or \
            (cur in PROMOTIONS and PROMOTIONS[cur][0] == tgt):
        required = PROMOTIONS[cur][1]
        if len(evidence_refs) < 1:
            raise IllegalTransition(
                f"{cur} → {tgt} requires evidence "
                f"({', '.join(required)}); arbitrary status updates "
                "cannot promote (mission §20)")
        return Transition(
            strategy_id="", version=0, from_state=cur, to_state=tgt,
            kind="promote", evidence_refs=tuple(evidence_refs),
            actor=actor, reason="promotion gate passed")

    if tgt in FAILURES.get(cur, ()):
        return Transition(
            strategy_id="", version=0, from_state=cur, to_state=tgt,
            kind="fail", evidence_refs=tuple(evidence_refs),
            actor=actor, reason="failure branch")

    if cur in RECOVERIES and tgt in RECOVERIES[cur]:
        if not evidence_refs:
            raise IllegalTransition(
                f"recovery {cur} → {tgt} requires fresh evidence")
        return Transition(
            strategy_id="", version=0, from_state=cur, to_state=tgt,
            kind="recover", evidence_refs=tuple(evidence_refs),
            actor=actor, reason="recovered with fresh evidence")

    raise IllegalTransition(
        f"transition {cur} → {tgt} is not in the state machine "
        "(promotion ladder, failure branches, recovery or retirement)")


def can_promote(current: str) -> bool:
    return current in PROMOTIONS


def required_evidence(current: str, target: str) -> tuple[str, ...]:
    """Evidence run kinds the store must see for cur→tgt (§15: promotion
    depends on the configured gate evidence, never on scores/claims)."""
    if current in PROMOTIONS and PROMOTIONS[current][0] == target:
        return PROMOTIONS[current][1]
    return ()
