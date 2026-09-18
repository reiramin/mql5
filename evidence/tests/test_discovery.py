"""Discovery domain tests (mission §3-§5, §27-§30, §33-§41, §63-§66,
§79-§81): score transparency, safety independence, staged resumable
campaigns, allocation separations."""

from __future__ import annotations

import pytest
from mql5bot.discovery import (
    COMPONENTS,
    AllocationCircuitBreaker,
    AllocationGovernor,
    AllocationProposal,
    AutonomyLevel,
    BreakerPolicy,
    CampaignId,
    ConcentrationLimits,
    EvidenceLevel,
    GovernorBounds,
    HealthSignals,
    KillSwitch,
    KillSwitchObservation,
    KillSwitchPolicy,
    KillSwitchState,
    LiveSmallRamp,
    PerformanceDecayController,
    RedundancyFilter,
    RequalificationGate,
    ResearchSpace,
    SpecHash,
    StrategyId,
    Watchdog,
    WatchdogObservation,
    build_portfolio,
    compute_score,
)
from mql5bot.discovery.candidates import doc_hash, generate_stage
from mql5bot.discovery.domain import DomainError
from mql5bot.discovery.orchestrator import DiscoveryOrchestrator
from mql5bot.factory.models import DiscoveryCampaign
from mql5bot.factory.store import FactoryStore

# ------------------------------------------------------------- domain


def test_value_objects_accept_and_reject():
    assert StrategyId("ema_trend_v1").value == "ema_trend_v1"
    with pytest.raises(DomainError):
        StrategyId("Bad-Id")
    with pytest.raises(DomainError):
        SpecHash("abc")
    with pytest.raises(DomainError):
        CampaignId("no")
    from mql5bot.discovery import DatasetHash
    DatasetHash("ds-123")
    with pytest.raises(DomainError):
        from mql5bot.discovery import DatasetHash as DH
        DH("")


def test_evidence_level_maps_lifecycle_separately():
    assert EvidenceLevel.from_lifecycle("OOS_SURVIVOR") is \
        EvidenceLevel.E3_OOS_ROBUST
    assert EvidenceLevel.from_lifecycle("LIVE") is \
        EvidenceLevel.E7_LIVE_PROVEN
    assert EvidenceLevel.from_lifecycle("BOGUS") is EvidenceLevel.E0_IDEA


def test_autonomy_ladder_blocks_low_levels_from_live_transitions():
    assert not AutonomyLevel.RESEARCH_AUTOMATION.may_auto_advance_past(
        "OOS_SURVIVOR")
    assert AutonomyLevel.RESEARCH_AUTOMATION.may_auto_advance_past(
        "VALIDATED")
    assert AutonomyLevel.DEMO_AUTOMATION.may_auto_advance_past("SHADOW")
    assert not AutonomyLevel.LIVE_SMALL_AUTOMATION.may_auto_advance_past(
        "LIVE_SMALL")           # LIVE_SMALL→LIVE needs FULL_AUTOMATION
    assert AutonomyLevel.FULL_AUTOMATION.may_auto_advance_past(
        "LIVE_SMALL")
    assert not AutonomyLevel.MANUAL.may_auto_advance_past("DRAFT")


# -------------------------------------------------------------- score


def _full_measurements() -> dict:
    return {
        "oos_survival": 1.0, "profit_factor": 1.5,
        "drawdown_quality": 12.0, "expectancy": 100.0,
        "trade_count_confidence": 500.0, "parameter_robustness": 0.7,
        "wfa_survival": 0.8, "cpcv_pbo_evidence": 0.2,
        "monte_carlo_stability": 0.6, "cost_robustness": 0.7,
        "regime_stability": 0.5, "drift_health": 0.9,
        "execution_realism": 0.8, "portfolio_diversification": 0.6,
        "shadow_evidence": 0.4, "live_evidence": 0.0,
    }


def test_score_sums_weights_and_exposes_rows():
    sc = compute_score(_full_measurements())
    assert len(sc.rows) == len(COMPONENTS) == 16
    assert 0.0 < sc.score <= 1.0
    # normalized rows are weighted means → sum(norm*w)/sum(w)
    tw = sum(r.weight for r in sc.rows)
    expect = sum(r.normalized * r.weight for r in sc.rows) / tw
    assert abs(sc.score - expect) < 1e-4
    assert sc.pol_hash and len(sc.pol_hash) == 64


def test_score_missing_evidence_is_unavailable_not_zero_quality():
    m = _full_measurements()
    m["live_evidence"] = None
    sc = compute_score(m)
    assert "live_evidence" in sc.unavailable
    row = next(r for r in sc.rows if r.component == "live_evidence")
    assert not row.available and row.contribution == 0.0
    assert "MISSING EVIDENCE" in sc.explain()


def test_score_policy_hash_binds_weights():
    a = compute_score(_full_measurements())
    w = {r.component: r.weight * 1.01 for r in a.rows}
    b = compute_score(_full_measurements(), weights={
        r.component: r.weight for r in a.rows} | {"profit_factor": 0.2})
    assert b.pol_hash != a.pol_hash
    assert w["profit_factor"] >= 0


# -------------------------------------------------------- kill switch


def _obs(**kw) -> KillSwitchObservation:
    d = {"daily_dd_pct": 1.0, "weekly_dd_pct": 2.0, "total_dd_pct": 5.0,
         "trades_last_hour": 3, "execution_failure_rate": 0.0,
         "heartbeat_age_seconds": 5.0, "equity": 10000.0,
         "reference_equity": 10000.0, "broker_connected": True}
    d.update(kw)
    return KillSwitchObservation(**d)


def test_kill_switch_normal_and_persisted_transitions():
    persisted: list[dict] = []
    ks = KillSwitch(state_sink=persisted.append)
    assert ks.evaluate(_obs()) is KillSwitchState.NORMAL
    assert ks.evaluate(_obs(daily_dd_pct=7.0)) is \
        KillSwitchState.NO_NEW_TRADES
    assert not ks.may_open_new_trades()
    assert persisted and persisted[-1]["state"] == "NO_NEW_TRADES"
    # trigger gone → clears (no_new_trades is auto-clearing)
    ks.evaluate(_obs())
    assert ks.may_open_new_trades()


def test_kill_switch_severe_requires_explicit_reset():
    ks = KillSwitch()
    ks.evaluate(_obs(equity=4000.0, reference_equity=10000.0,
                     total_dd_pct=30.0))
    assert ks.state is KillSwitchState.EMERGENCY_HALT
    # further observations do NOT clear it
    ks.evaluate(_obs())
    assert ks.state is KillSwitchState.EMERGENCY_HALT
    ks.explicit_reset("owner", " reviewed drawdown; resume manual")
    assert ks.state is KillSwitchState.NORMAL
    assert any(h["action"] == "explicit_reset" for h in ks.history)


def test_kill_switch_close_all_is_policy_driven():
    ks = KillSwitch(policy=KillSwitchPolicy(close_all_on_emergency=False))
    ks.evaluate(_obs(equity=4000.0, reference_equity=10000.0))
    assert not ks.close_all_requested
    ks2 = KillSwitch(policy=KillSwitchPolicy(close_all_on_emergency=True))
    ks2.evaluate(_obs(equity=4000.0, reference_equity=10000.0))
    assert ks2.close_all_requested


def test_kill_switch_detects_operational_anomalies():
    ks = KillSwitch()
    assert ks.evaluate(_obs(trades_last_hour=100)) is \
        KillSwitchState.NO_NEW_TRADES
    ks2 = KillSwitch()
    assert ks2.evaluate(_obs(heartbeat_age_seconds=1000)) is \
        KillSwitchState.NO_NEW_TRADES
    ks3 = KillSwitch()
    assert ks3.evaluate(_obs(impossible_position_state=True)) is \
        KillSwitchState.EMERGENCY_HALT
    with pytest.raises(ValueError):
        KillSwitch(policy=KillSwitchPolicy(max_daily_dd_pct=0))


# ---------------------------------------------------- circuit breaker


def test_circuit_breaker_freezes_on_allocation_jump():
    cb = AllocationCircuitBreaker(BreakerPolicy(
        max_allocation_jump_pct=25.0))
    normal = AllocationProposal({"a": 0.1, "b": 0.05},
                                gross_exposure_pct=15.0)
    w, status = cb.review(normal, previous_gross_pct=15.0)
    assert status == "APPLIED" and cb.st.last_safe == {"a": 0.1, "b": 0.05}
    # 40pp jump → freeze, keep last safe
    crazy = AllocationProposal({"a": 0.5, "b": 0.2},
                               gross_exposure_pct=55.0)
    w, status = cb.review(crazy, previous_gross_pct=15.0)
    assert status == "FROZEN_KEEP_LAST_SAFE"
    assert w == {"a": 0.1, "b": 0.05} and cb.st.frozen
    # cooldown: even sane proposals stay frozen
    _, status2 = cb.review(normal, previous_gross_pct=15.0)
    assert status2 == "FROZEN_KEEP_LAST_SAFE"
    cb.reset("owner", "reviewed jump cause")
    _, status3 = cb.review(normal, previous_gross_pct=15.0)
    assert status3 == "APPLIED"


def test_circuit_breaker_flags_strategy_count_collapse():
    cb = AllocationCircuitBreaker(BreakerPolicy(max_strategy_count_drop=2))
    cb.st.last_safe = {f"s{i}": 0.05 for i in range(5)}
    _, status = cb.review(
        AllocationProposal({"s1": 0.1}, gross_exposure_pct=10.0),
        previous_gross_pct=25.0)
    assert status == "FROZEN_KEEP_LAST_SAFE"


# ----------------------------------------------------------- watchdog


def test_watchdog_alerts_and_rate_limits():
    alerts: list[dict] = []
    clock = {"t": 1000.0}
    wd = Watchdog(alerts.append, max_dd_pct=20.0,
                  heartbeat_max_age_seconds=300.0,
                  alert_rate_limit_seconds=300.0,
                  clock=lambda: clock["t"])
    obs = WatchdogObservation(equity=9000.0, daily_dd_pct=25.0,
                              open_positions=2, trades_last_hour=5,
                              heartbeat_age_seconds=600.0)
    got = wd.check(obs)
    assert any("daily DD" in g for g in got)
    assert any("heartbeat" in g for g in got)
    n = len(alerts)
    clock["t"] += 10                      # within rate limit → silent
    assert wd.check(obs) == got and len(alerts) == n
    clock["t"] += 400                     # after limit → alerts again
    wd.check(obs)
    assert len(alerts) > n


# ------------------------------------------------------- decay / ramp


def test_decay_single_loss_never_demotes():
    d = PerformanceDecayController()
    band, why = d.evaluate(HealthSignals(
        rolling_trades=1, expectancy_ratio=0.0, dd_ratio=9.0,
        drift_score=1.0, slippage_bps_vs_assumed=50.0))
    assert band.name == "HEALTHY" and "insufficient rolling trades" in why


def test_decay_multi_signal_demotion_and_risk_breach():
    d = PerformanceDecayController()
    band, _ = d.evaluate(HealthSignals(
        rolling_trades=50, expectancy_ratio=0.4, dd_ratio=0.9,
        drift_score=0.2, slippage_bps_vs_assumed=0.0))
    assert band.name == "MODERATE_DEGRADATION"
    band_s, _ = d.evaluate(HealthSignals(
        rolling_trades=50, expectancy_ratio=0.4, dd_ratio=2.5,
        drift_score=0.7, slippage_bps_vs_assumed=15.0))
    assert band_s.name in ("SEVERE_DEGRADATION", "CRITICAL")
    band2, why2 = d.evaluate(HealthSignals(
        rolling_trades=50, expectancy_ratio=1.2, dd_ratio=0.8,
        drift_score=0.1, slippage_bps_vs_assumed=0.0, risk_breach=True))
    assert band2.name == "CRITICAL" and "risk-control breach" in why2
    band3, _ = d.evaluate(HealthSignals(
        rolling_trades=50, expectancy_ratio=1.2, dd_ratio=0.8,
        drift_score=0.1, slippage_bps_vs_assumed=0.0))
    assert band3.name == "HEALTHY"


def test_decay_band_validation():
    from mql5bot.discovery.domain import DecayBand
    with pytest.raises(ValueError):
        PerformanceDecayController(bands=(
            DecayBand("BAD", 0.5), DecayBand("HEALTHY", 1.0)))
    with pytest.raises(ValueError):
        PerformanceDecayController(bands=(
            DecayBand("HEALTHY", 0.5), DecayBand("WORSE", 0.9)))


def test_requalification_requires_full_shadow_evidence():
    rq = RequalificationGate()
    ok, why = rq.may_requalify(shadow_trades=5, shadow_days=2,
                               shadow_score=0.9)
    assert not ok and "shadow trades" in why
    ok2, _ = rq.may_requalify(shadow_trades=40, shadow_days=20,
                              shadow_score=0.8)
    assert ok2
    ok3, why3 = rq.may_requalify(shadow_trades=40, shadow_days=20,
                                 shadow_score=0.8, rejected_before=True)
    assert not ok3 and "NEW version" in why3


def test_ramp_progressive_and_reversible():
    r = LiveSmallRamp()
    f0, _ = r.factor_for(live_trades=0, live_dd_pct=0.0, slippage_bps=0.0)
    assert f0 == 0.25
    f1, _ = r.factor_for(live_trades=120, live_dd_pct=2.0,
                         slippage_bps=5.0)
    assert f1 == 1.0
    # degradation halves (reversible) — never jumps to full
    f2, why = r.factor_for(live_trades=120, live_dd_pct=2.0,
                           slippage_bps=5.0, degraded=True)
    assert f2 == 0.5 and "halved" in why
    # dd breach scales down
    f3, _ = r.factor_for(live_trades=120, live_dd_pct=9.0,
                         slippage_bps=5.0)
    assert f3 < 1.0
    assert r.factor_for(live_trades=10, live_dd_pct=1.0,
                        slippage_bps=1.0, kill_switch_active=True)[0] == 0.0
    assert r.factor_for(live_trades=10, live_dd_pct=1.0,
                        slippage_bps=1.0, circuit_breaker=True)[0] == 0.0


# ----------------------------------------------------------- governor


def _elig(sid: str, state: str = "LIVE_SMALL",
          approved: bool = True) -> object:
    from mql5bot.discovery import EligibilityRecord
    return EligibilityRecord(strategy_id=sid, lifecycle_state=state,
                             human_approved=approved, gates_pass=True,
                             kill_switch_ok=True, evidence_ok=True)


def test_governor_scores_rank_but_only_eligible_get_weight():
    g = AllocationGovernor(GovernorBounds(max_strategy_delta=10.0))
    entries = [_elig("strong"), _elig("weak"),
               _elig("backtest_only", state="BACKTESTED")]
    out = g.recommend(entries,
                      {"strong": 0.9, "weak": 0.6, "backtest_only": 0.99})
    amap = {a["strategy_id"]: a for a in out["allocations"]}
    assert amap["strong"]["effective_weight"] > \
        amap["weak"]["effective_weight"]
    assert amap["backtest_only"]["effective_weight"] == 0.0
    assert "lifecycle BACKTESTED carries no live allocation" in \
        amap["backtest_only"]["reasons"]
    # SCORE ≠ PERMISSION: highest score with no approval gets zero
    out2 = g.recommend([_elig("unapproved", approved=False)],
                       {"unapproved": 0.999})
    assert out2["allocations"][0]["effective_weight"] == 0.0


def test_governor_kill_switch_overrides_everything():
    g = AllocationGovernor()
    out = g.recommend([_elig("a")], {"a": 0.9},
                      kill_switch_state=KillSwitchState.EMERGENCY_HALT)
    assert out["allocations"] == [] and out["status"] == "KILL_SWITCH"
    assert out["gross_pct"] == 0.0


def test_governor_delta_caps_and_zero_exposure_legitimate():
    g = AllocationGovernor(GovernorBounds(max_strategy_delta=0.10))
    out = g.recommend([_elig("a")], {"a": 1.0},
                      previous_weights={"a": 0.05})
    a = out["allocations"][0]
    assert a["effective_weight"] == pytest.approx(0.15)
    assert any("delta capped" in r for r in a["reasons"])
    g0 = AllocationGovernor()
    out0 = g0.recommend([_elig("x", state="PAUSED")], {"x": 0.9})
    assert out0["gross_pct"] == 0.0 and out0["status"] == "OK"
    assert any("0% exposure" in r for r in out0["reasons"])


# ----------------------------------------------------------- portfolio


def _cand(sid, score, symbol="EURUSD", returns=None, weight=1.0):
    import numpy as np
    rng = np.random.default_rng(abs(hash(sid)) % (2**32))
    if returns is None:
        returns = tuple(float(x) for x in rng.normal(0.0005, 0.004, 300))
    return {"strategy_id": sid, "score": score, "symbol": symbol,
            "direction": "long", "asset_class": "fx", "weight": weight,
            "returns": returns}


def test_portfolio_correlation_penalty_excludes_clones():
    rets = tuple(float(x) for x in
                 __import__("numpy").random.default_rng(7)
                 .normal(0.0005, 0.004, 300))
    cands = [_cand("alpha", 0.80, returns=rets),
             _cand("alpha_clone", 0.79, returns=rets)]
    pf = build_portfolio(cands, min_score=0.4)
    ids = [p["strategy_id"] for p in pf["positions"]]
    assert "alpha" in ids and "alpha_clone" not in ids
    reasons = dict(pf["excluded"]).get("alpha_clone", "")
    assert ("redundant" in reasons or "correlation penalty" in reasons
            or "per-symbol cap" in reasons)


def test_portfolio_respects_caps_and_zero_exposure():
    cands = [_cand(f"s{i}", 0.9) for i in range(10)]
    limits = ConcentrationLimits(max_positions_cap=None) if False else \
        ConcentrationLimits()
    pf = build_portfolio(cands, limits=limits, min_score=0.5,
                         max_positions=8)
    assert len(pf["positions"]) <= 8
    sym = {}
    for p in pf["positions"]:
        sym[p["strategy_id"]] = p["scaled_weight"]
    assert sum(sym.values()) * 100 <= 20.0 + 1e-6      # gross target 15%
    empty = build_portfolio([_cand("low", 0.2)], min_score=0.5)
    assert empty["zero_exposure"] and empty["gross_exposure_pct"] == 0.0


def test_portfolio_heat_is_not_gross():
    pf = build_portfolio([_cand("a", 0.9), _cand("b", 0.7)])
    assert pf["gross_exposure_pct"] == 15.0     # target band, not sum-100
    assert 0 < pf["portfolio_heat"] < pf["gross_exposure_pct"]


def test_marginal_contribution_reports_deltas():
    base_c = [_cand("a", 0.9), _cand("b", 0.7)]
    clone = _cand("c", 0.85, returns=base_c[0]["returns"])
    diverse = _cand("d", 0.85)
    from mql5bot.discovery.portfolio import marginal_contribution
    m1 = marginal_contribution(base_c, clone)
    m2 = marginal_contribution(base_c, diverse)
    assert not m1["admitted"]
    assert m2["admitted"] and "delta_heat" in m2


# --------------------------------------------------- staged campaigns


def _space() -> ResearchSpace:
    return ResearchSpace(
        indicators=("EMA", "RSI", "ATR", "SUPERTREND", "KELTNER",
                    "ADX"),
        param_grid={"RSI": {"period": [10, 14]},
                    "SUPERTREND": {"period": [10], "mult": [3.0]}})


def test_generate_stage_is_deterministic_and_budget_bounded():
    sp = _space()
    a = generate_stage("stage1_single_indicator", sp,
                       budgets={"stage1_single_indicator": 7})
    b = generate_stage("stage1_single_indicator", sp,
                       budgets={"stage1_single_indicator": 7})
    assert [doc_hash(d) for d in a] == [doc_hash(d) for d in b]
    assert len(a) == 7


def test_research_space_rejects_unknown_kind_and_param():
    with pytest.raises(ValueError):
        ResearchSpace(indicators=("NOT_A_KIND",)).validate()
    with pytest.raises(ValueError):
        ResearchSpace(indicators=("RSI",),
                      param_grid={"RSI": {"bogus": [1]}}).validate()


def test_redundancy_filter_drops_structural_and_series_duplicates():
    import numpy as np
    rf = RedundancyFilter(threshold=0.95)
    d1 = generate_stage("stage1_single_indicator", _space(),
                        budgets={"stage1_single_indicator": 5})
    kept, dropped = rf.filter_docs(d1 + d1[:2])
    assert len(kept) == len(d1) and len(dropped) == 2
    series = np.sin(np.linspace(0, 10, 500))
    docs = [{"strategy_id": "x", "indicators": [{"kind": "EMA"}],
             "meta": {"stage": "s"}},]
    noisy = series + np.random.default_rng(1).normal(0, 1e-6, 500)
    docs2 = docs + [{"strategy_id": "y",
                     "indicators": [{"kind": "EMA"}],
                     "meta": {"stage": "s2"}}]
    k2, d2 = rf.filter_docs(docs2, series_fn=lambda doc: [
        series if doc["strategy_id"] == "x" else noisy])
    assert len(k2) == 1 and len(d2) == 1


def _fake_pipeline(states_by_stage: dict):
    calls = {"n": 0, "stages": []}

    def run_stage(stage, docs):
        calls["n"] += 1
        calls["stages"].append(stage)
        out = []
        for i, d in enumerate(docs):
            st = states_by_stage.get(stage, "OOS_SURVIVOR") \
                if i == 0 else "BACKTESTED"
            out.append({"strategy_id": d["strategy_id"], "state": st,
                        "score_hint": 0.7})
        return out

    return run_stage, calls


def test_orchestrator_resumes_without_rerunning_completed_stages():
    orch = DiscoveryOrchestrator(_space(),
                                 budgets={"stage1_single_indicator": 4,
                                          "stage2_two_factor": 4},
                                 policy_hash="p" * 64)
    run, calls = _fake_pipeline({})
    camp = {"campaign_id": "camp_test", "progress": {}, "results": {}}
    out = orch.run_campaign(dict(camp), run)
    assert out["status"] == "DONE"
    assert calls["n"] == 5          # all stages have generators
    # resume: completed stages are NOT re-executed
    run2, calls2 = _fake_pipeline({})
    out2 = orch.run_campaign(dict(out), run2)
    assert calls2["n"] == 0 and out2["status"] == "DONE"
    assert out2["progress"]["stage1_single_indicator"]["done"]
    assert out2["manifest_hash"]


def test_orchestrator_rank_includes_only_stage_eligible():
    orch = DiscoveryOrchestrator(_space(),
                                 budgets={"stage1_single_indicator": 3})
    run, _ = _fake_pipeline({"stage1_single_indicator": "OOS_SURVIVOR"})
    camp = orch.run_campaign({"campaign_id": "c", "progress": {},
                              "results": {}}, run)
    ranked = orch.rank_candidates(camp, lambda item: compute_score(
        _full_measurements()))
    assert ranked and ranked[0]["state"] == "OOS_SURVIVOR"
    assert all(r["score"] >= ranked[-1]["score"] for r in ranked)


def test_campaign_persists_via_orm(tmp_path):
    store = FactoryStore(tmp_path / "camp.db")
    with store.session() as sess:
        row = DiscoveryCampaign(
            campaign_id="camp_2026_09", name="first", stage="stage1",
            status="RUNNING", budget={"stage1": 12},
            progress={"stage1_single_indicator": {"done": True}},
            manifest={"stages": 2}, manifest_hash="a" * 64,
            policy_hash="b" * 64, dataset_hash="ds1")
        sess.add(row)
        sess.commit()
    with store.session() as sess:
        got = sess.query(DiscoveryCampaign).filter_by(
            campaign_id="camp_2026_09").one()
        assert got.status == "RUNNING"
        assert got.progress["stage1_single_indicator"]["done"] is True
        assert got.manifest_hash == "a" * 64
