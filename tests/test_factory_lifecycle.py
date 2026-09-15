"""Factory lifecycle state machine tests (mission §20/§59.6/§59.7).

Every refusal is a safety property: no arbitrary status update can
promote a strategy, terminal states never resurrect, and every
accepted transition carries its evidence + actor.
"""

from __future__ import annotations

from itertools import pairwise

import pytest
from mql5bot.factory import lifecycle as lc
from mql5bot.factory.lifecycle import IllegalTransition, check_transition


def test_happy_path_promotion_ladder():
    chain = [lc.DRAFT, lc.PARSED, lc.VALIDATED, lc.BACKTESTED,
             lc.ROBUSTNESS_PASS, lc.OOS_SURVIVOR, lc.SHADOW, lc.DEMO,
             lc.LIVE_SMALL, lc.LIVE]
    for step, (cur, nxt) in enumerate(pairwise(chain), start=1):
        ev = check_transition(cur, nxt, (f"run-{step}",),
                              actor="owner")
        assert ev.kind == "promote"
        assert ev.to_state == nxt


def test_promotion_without_evidence_refused():
    with pytest.raises(IllegalTransition, match="requires evidence"):
        check_transition(lc.VALIDATED, lc.BACKTESTED, (),
                         actor="factory")


def test_promotion_without_actor_refused():
    with pytest.raises(IllegalTransition, match="actor"):
        check_transition(lc.VALIDATED, lc.BACKTESTED, ("run-1",))


def test_unknown_state_refused():
    with pytest.raises(IllegalTransition, match="unknown lifecycle"):
        check_transition("ON_THE_MOON", lc.LIVE, (), actor="owner")


def test_failure_branches():
    assert check_transition(lc.OOS_SURVIVOR, lc.REJECTED, (),
                            actor="gate:gate6").kind == "fail"
    assert check_transition(lc.SHADOW, lc.DEGRADED, (),
                            actor="monitor").kind == "fail"
    assert check_transition(lc.DEMO, lc.PAUSED, (),
                            actor="monitor").kind == "fail"
    assert check_transition(lc.LIVE, lc.DEGRADED, (),
                            actor="monitor").kind == "fail"


def test_rejected_cannot_resurrect():
    with pytest.raises(IllegalTransition, match="terminal"):
        check_transition(lc.REJECTED, lc.VALIDATED, ("run-9",),
                         actor="owner")


def test_retired_cannot_resurrect_and_evidence_is_preserved_semantics():
    with pytest.raises(IllegalTransition, match="terminal"):
        check_transition(lc.RETIRED, lc.SHADOW, (), actor="owner")
    ev = check_transition(lc.LIVE, lc.RETIRED, (), actor="owner")
    assert ev.kind == "retire"


def test_live_cannot_skip_to_paused_or_jump_backward():
    with pytest.raises(IllegalTransition):
        check_transition(lc.LIVE, lc.PAUSED, (), actor="monitor")
    with pytest.raises(IllegalTransition):
        check_transition(lc.LIVE, lc.DEMO, ("run-1",), actor="owner")


def test_recovery_requires_fresh_evidence():
    with pytest.raises(IllegalTransition, match="fresh evidence"):
        check_transition(lc.PAUSED, lc.DEMO, (), actor="owner")
    ev = check_transition(lc.PAUSED, lc.DEMO, ("obs-42",),
                          actor="owner")
    assert ev.kind == "recover"


def test_shortcut_transitions_refused():
    with pytest.raises(IllegalTransition):
        check_transition(lc.DRAFT, lc.SHADOW, ("run-1",), actor="owner")
    with pytest.raises(IllegalTransition):
        check_transition(lc.BACKTESTED, lc.SHADOW, ("run-1",),
                         actor="owner")
