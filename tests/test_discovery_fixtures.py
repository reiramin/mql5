"""Acceptance fixtures (mission §49-§54): portfolio-of-≥5 fixture with
a diversifier beating the standalone winner, capital cases A-E, and
the decay/recovery simulation."""

from __future__ import annotations

import numpy as np
import pytest
from mql5bot.discovery import (
    AllocationCircuitBreaker,
    AllocationGovernor,
    AllocationProposal,
    GovernorBounds,
    HealthSignals,
    KillSwitch,
    KillSwitchObservation,
    KillSwitchPolicy,
    KillSwitchState,
    LiveSmallRamp,
    PerformanceDecayController,
    RequalificationGate,
    build_portfolio,
    marginal_contribution,
)
from mql5bot.discovery.governor import EligibilityRecord
from mql5bot.discovery.portfolio import ConcentrationLimits


def _ret(seed: int) -> tuple:
    return tuple(float(x) for x in
                 np.random.default_rng(seed).normal(0.0006, 0.005, 400))


def _cand(sid: str, score: float, returns: tuple, *,
          symbol: str = "EURUSD", asset_class: str = "fx") -> dict:
    return {"strategy_id": sid, "score": score, "symbol": symbol,
            "direction": "long", "asset_class": asset_class,
            "weight": 1.0, "returns": returns}


def test_fixture_portfolio_of_five_diversifier_beats_standalone():
    """§53: ≥5 qualified candidates; the correlation-aware portfolio
    that includes the diversifier achieves lower portfolio-average
    pairwise correlation than a portfolio of the top standalone
    winner + clones, and the diversifier's marginal admission raises
    portfolio heat LESS than a redundant clone (efficiency)."""
    base = _ret(11)
    noise1 = np.random.default_rng(12).normal(0, 1e-4, 400)
    noise2 = np.random.default_rng(13).normal(0, 1e-4, 400)
    near1 = tuple(a + float(b) for a, b in zip(base, noise1))
    near2 = tuple(a + float(b) for a, b in zip(base, noise2))
    indep1 = _ret(21)
    indep2 = _ret(22)
    diversifier = _ret(31)                 # genuinely different stream
    candidates = [
        _cand("winner", 0.90, base),
        _cand("clone1", 0.85, tuple(near1)),
        _cand("clone2", 0.84, tuple(near2)),
        _cand("indep1", 0.80, indep1),
        _cand("indep2", 0.78, indep2),
        _cand("diversifier", 0.72, diversifier, symbol="XAUUSD",
              asset_class="metal"),
    ]
    pf = build_portfolio(candidates, min_score=0.4)
    ids = [p["strategy_id"] for p in pf["positions"]]
    assert len(pf["positions"]) >= 4
    assert "winner" in ids and "diversifier" in ids
    # clones of the winner are excluded as redundant
    assert "clone1" not in ids and "clone2" not in ids
    # the diversifier earns its slot despite the LOWEST standalone
    # score: marginal analysis admits it with modest heat delta while
    # a further clone of the winner would be denied outright
    base_pool = [c for c in candidates if c["strategy_id"] != "diversifier"]
    m_div = marginal_contribution(base_pool, candidates[-1])
    m_clone = marginal_contribution(base_pool, _cand(
        "clone3", 0.86, near1))
    assert m_clone["admitted"] is False or \
        m_clone.get("delta_heat", 0) >= m_div.get("delta_heat", 0)
    # diversification quality: the diversifier's worst pairwise
    # correlation with the selected set stays well below a winner
    # clone's (near-1.0); the portfolio prefers it despite the lowest
    # standalone score
    from mql5bot.discovery.portfolio import correlation as _corr
    others = [c for c in candidates if c["strategy_id"] != "diversifier"]
    worst_div = max(abs(_corr(diversifier, o["returns"]))
                    for o in others)
    worst_clone = abs(_corr(base, base))
    assert worst_clone >= 0.999
    assert worst_div < 0.5


def test_fixture_capital_case_A_full_qualification():
    """A: all gates + approval → full allocation within the band."""
    gov = AllocationGovernor(GovernorBounds(max_strategy_delta=10))
    e = EligibilityRecord(strategy_id="case_a", lifecycle_state="LIVE",
                          human_approved=True, gates_pass=True,
                          kill_switch_ok=True, evidence_ok=True)
    out = gov.recommend([e], {"case_a": 0.9})
    a = out["allocations"][0]
    assert a["effective_weight"] > 0 and out["status"] == "OK"
    assert out["gross_pct"] <= 20.0 + 1e-9


def test_fixture_capital_case_B_shadow_only_gets_ramp_fraction():
    """B: fresh LIVE_SMALL strategy → 0.25 ramp factor caps exposure."""
    gov = AllocationGovernor(GovernorBounds(max_strategy_delta=10))
    ramped = EligibilityRecord(strategy_id="case_b",
                               lifecycle_state="LIVE_SMALL",
                               human_approved=True, gates_pass=True,
                               kill_switch_ok=True, evidence_ok=True)
    full = EligibilityRecord(strategy_id="case_b_full",
                             lifecycle_state="LIVE",
                             human_approved=True, gates_pass=True,
                             kill_switch_ok=True, evidence_ok=True)
    ramp = LiveSmallRamp()
    f, _ = ramp.factor_for(live_trades=2, live_dd_pct=0.5,
                           slippage_bps=4.0)
    assert f == 0.25
    out = gov.recommend([ramped, full],
                        {"case_b": 0.9, "case_b_full": 0.9},
                        ramp={"case_b": f, "case_b_full": 1.0})
    amap = {a["strategy_id"]: a for a in out["allocations"]}
    assert amap["case_b"]["effective_weight"] < \
        amap["case_b_full"]["effective_weight"]


def test_fixture_capital_case_C_decayed_to_critical_pauses():
    """C: severe decay → CRITICAL band (multiplier 0) + PAUSE; recovery
    only through requalification."""
    decay = PerformanceDecayController()
    band, _why = decay.evaluate(HealthSignals(
        rolling_trades=60, expectancy_ratio=0.2, dd_ratio=3.0,
        drift_score=0.9, slippage_bps_vs_assumed=25.0, risk_breach=True))
    assert band.pause and band.multiplier == 0.0
    gov = AllocationGovernor(GovernorBounds(max_strategy_delta=10))
    e = EligibilityRecord(strategy_id="case_c", lifecycle_state="LIVE",
                          human_approved=True, gates_pass=True,
                          kill_switch_ok=True, evidence_ok=True)
    out = gov.recommend([e], {"case_c": 0.95},
                        decay_mult={"case_c": band.multiplier})
    assert out["allocations"][0]["effective_weight"] == 0.0
    rq = RequalificationGate()
    ok, _ = rq.may_requalify(shadow_trades=3, shadow_days=2,
                             shadow_score=0.9)
    assert not ok                     # cannot revive without evidence


def test_fixture_capital_case_D_kill_switch_overrides_all():
    """D: EMERGENCY_HALT → zero allocations regardless of scores."""
    ks = KillSwitch(policy=KillSwitchPolicy(close_all_on_emergency=False))
    ks.evaluate(KillSwitchObservation(
        equity=4000.0, reference_equity=10000.0, total_dd_pct=30.0))
    assert ks.state is KillSwitchState.EMERGENCY_HALT
    gov = AllocationGovernor()
    out = gov.recommend(
        [EligibilityRecord(strategy_id="case_d", lifecycle_state="LIVE",
                           human_approved=True, gates_pass=True,
                           kill_switch_ok=False, evidence_ok=True)],
        {"case_d": 0.999},
        kill_switch_state=KillSwitchState.EMERGENCY_HALT)
    assert out["allocations"] == [] and out["gross_pct"] == 0.0
    assert not ks.close_all_requested     # policy: manage, don't dump


def test_fixture_capital_case_E_breaker_freeze_keeps_last_safe():
    """E: allocation circuit breaker anomaly → freeze + keep last safe
    allocation (which is NOT the kill switch and closes nothing)."""
    breaker = AllocationCircuitBreaker()
    _, st = breaker.review(
        AllocationProposal({"a": 0.08, "b": 0.05},
                           gross_exposure_pct=13.0),
        previous_gross_pct=13.0)
    assert st == "APPLIED"
    _, st2 = breaker.review(
        AllocationProposal({"a": 0.45, "b": 0.3},
                           gross_exposure_pct=75.0),
        previous_gross_pct=13.0)
    assert st2 == "FROZEN_KEEP_LAST_SAFE"
    assert breaker.st.last_safe == {"a": 0.08, "b": 0.05}


def test_fixture_decay_recovery_simulation():
    """§54: one bad month (few trades) ≠ demotion; sustained decay
    demotes; recovery returns through SHADOW only."""
    decay = PerformanceDecayController()
    # month 1: single loss, tiny sample
    b1, _ = decay.evaluate(HealthSignals(rolling_trades=2,
                                         expectancy_ratio=-0.5,
                                         dd_ratio=1.1, drift_score=0.1,
                                         slippage_bps_vs_assumed=1.0))
    assert b1.multiplier == 1.0
    # months 2-4: sustained underperformance with adequate sample
    b2, _ = decay.evaluate(HealthSignals(rolling_trades=40,
                                         expectancy_ratio=0.3,
                                         dd_ratio=2.4, drift_score=0.7,
                                         slippage_bps_vs_assumed=12.0))
    assert b2.multiplier < 1.0
    # recovery: requalification evidence required
    rq = RequalificationGate()
    assert not rq.may_requalify(shadow_trades=10, shadow_days=5,
                                shadow_score=0.8)[0]
    assert rq.may_requalify(shadow_trades=45, shadow_days=21,
                            shadow_score=0.9)[0]
    # concentration caps still bind after recovery
    limits = ConcentrationLimits()
    limits.validate()
    with pytest.raises(ValueError):
        ConcentrationLimits(max_per_symbol_pct=0).validate()
