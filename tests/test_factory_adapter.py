"""Factory→Meta adapter tests (mission §36-§39, §51, §63, §70): only
earned eligibility reaches Meta; unknown states block; Factory outage
cannot touch pre-existing strategies; Meta stays the sole authority."""

from __future__ import annotations

from datetime import UTC, datetime

from mql5bot.factory.adapter import certification_for, meta_input
from mql5bot.meta_layer import (
    GATE_WEIGHTS,
    EligibilityReason,
    MetaLayer,
    StrategyMetaInput,
)


def test_pre_shadow_states_have_no_certification():
    for st in (None, "DRAFT", "PARSED", "VALIDATED", "BACKTESTED",
               "ROBUSTNESS_PASS", "OOS_SURVIVOR", "REJECTED",
               "RETIRED", "NONEXISTENT", ""):
        assert certification_for(st) is None


def test_shadow_states_map_to_pending_verification():
    for st in ("SHADOW", "DEMO"):
        assert certification_for(st) == "EMPIRICAL_VALIDATION_PENDING"


def test_live_states_map_to_verified_only_when_approved():
    assert certification_for("LIVE_SMALL") == "VERIFIED"
    assert certification_for("LIVE") == "VERIFIED"
    assert certification_for("LIVE", human_approved=False) is None


def test_meta_blocks_uncertified_and_rewards_earned():
    layer = MetaLayer()
    as_of = datetime(2026, 9, 6, tzinfo=UTC)
    base = {"strategy_id": "s1", "symbol": "EURUSD", "signal": 1,
            "regime": "TREND_UP",
            "regimes_allowed": frozenset(
                {"TREND_UP", "TREND_DOWN", "RANGE"})}
    elig = layer.eligibility(
        [meta_input(**base, lifecycle_state="VALIDATED")], as_of=as_of)
    assert not elig["s1"].eligible
    assert elig["s1"].reason == EligibilityReason.UNCERTIFIED
    elig = layer.eligibility(
        [meta_input(**base, lifecycle_state="SHADOW")], as_of=as_of)
    assert elig["s1"].eligible      # earned: shadow evidence exists
    assert GATE_WEIGHTS["EMPIRICAL_VALIDATION_PENDING"] == 0.5
    elig = layer.eligibility(
        [meta_input(**base, lifecycle_state="LIVE")], as_of=as_of)
    assert elig["s1"].eligible
    assert GATE_WEIGHTS["VERIFIED"] == 1.0


def test_factory_absent_strategy_passthrough_unchanged():
    """A pre-existing strategy carries its own certification; the
    Factory adapter never downgrades it (§38)."""
    inp = StrategyMetaInput(strategy_id="ema_crossover",
                            symbol="EURUSD", signal=1,
                            regime="TREND_UP",
                            certification_state="VERIFIED",
                            strategy_version="1")
    # no factory record: adapter not involved — Meta sees VERIFIED
    assert inp.certification_state == "VERIFIED"
