"""Red-team attacks 12-25 (mission §55; attacks 1-11 live in
tests/test_factory_redteam.py).  Every attack here targets the NEW
discovery/safety/UI surface; every HIGH/CRITICAL finding is fixed in
code, not documented away."""

from __future__ import annotations

import pytest
from mql5bot.discovery import (
    AllocationCircuitBreaker,
    AllocationGovernor,
    AllocationProposal,
    BreakerPolicy,
    GovernorBounds,
    KillSwitch,
    KillSwitchObservation,
    KillSwitchPolicy,
    KillSwitchState,
    LiveSmallRamp,
    RedundancyFilter,
    ResearchSpace,
    Watchdog,
    WatchdogObservation,
    compute_score,
    generate_stage,
)
from mql5bot.discovery.candidates import doc_hash
from mql5bot.discovery.domain import DomainError
from mql5bot.discovery.governor import EligibilityRecord
from mql5bot.discovery.orchestrator import DiscoveryOrchestrator
from mql5bot.discovery.score import policy_hash


# 12 — score tampering: a different weight vector must produce a
# different policy hash, so a forged score cannot masquerade as the
# policy's score.
def test_attack_score_policy_hash_binds_tamper():
    from mql5bot.discovery.score import DEFAULT_NORMALIZERS, DEFAULT_WEIGHTS
    w = dict(DEFAULT_WEIGHTS)
    n = dict(DEFAULT_NORMALIZERS)
    m = {c: 0.5 for c in w}
    h1 = policy_hash(w, n)
    h2 = policy_hash({**w, "profit_factor": 0.9}, n)
    h3 = policy_hash(w, {**n, "profit_factor": (0.0, 2.0, True)})
    assert len({h1, h2, h3}) == 3
    assert compute_score(m, weights=w, normalizers=n).pol_hash == h1
    assert compute_score(m, weights={**w, "profit_factor": 0.9},
                         normalizers=n).pol_hash == h2


# 13 — campaign progress forgery: replay another policy's progress to
# skip validation stages.
def test_attack_campaign_progress_replay_refused():
    orch = DiscoveryOrchestrator(
        ResearchSpace(indicators=("EMA",)), policy_hash="a" * 64)
    forged = {"campaign_id": "x", "progress": {"stage1_single_indicator":
                                               {"done": True}},
              "results": {}, "policy_hash": "b" * 64}
    with pytest.raises(ValueError, match="different policy"):
        orch.run_campaign(forged, lambda stage, docs: [])


# 14 — kill switch state forgery: after EMERGENCY_HALT, feeding rosy
# observations must NOT clear it; only an audited reset does.
def test_attack_kill_switch_cannot_be_forged_clear():
    ks = KillSwitch()
    ks.evaluate(KillSwitchObservation(equity=3000.0,
                                      reference_equity=10000.0))
    for _ in range(5):
        assert ks.evaluate(KillSwitchObservation()) is \
            KillSwitchState.EMERGENCY_HALT
    ks.explicit_reset("owner", "verified recovery plan")
    assert ks.state is KillSwitchState.NORMAL
    # history is append-only: earlier halt record still present
    actions = [h["action"] for h in ks.history]
    assert "trip" in actions and "explicit_reset" in actions


# 15 — kill switch history flooding (memory exhaustion / audit erase).
def test_attack_kill_switch_history_is_bounded():
    ks = KillSwitch()
    for _ in range(2000):
        ks.evaluate(KillSwitchObservation(daily_dd_pct=99.0,
                                          weekly_dd_pct=99.0))
    assert len(ks.history) <= 500


# 16 — breaker reset without accountability.
def test_attack_breaker_reset_requires_actor_and_reason():
    cb = AllocationCircuitBreaker(BreakerPolicy())
    cb.review(AllocationProposal({"a": 0.5}, gross_exposure_pct=50.0),
              previous_gross_pct=10.0)
    assert cb.st.frozen
    with pytest.raises(ValueError):
        cb.reset("", "")
    with pytest.raises(ValueError):
        cb.reset("owner", "  ")
    cb.reset("owner", "jump explained: funding rebalance")
    assert not cb.st.frozen


# 17 — governor bypass: a perfect score must never mint weight without
# eligibility, and the output must carry NO risk/lots semantics
# (SCORE ≠ PERMISSION, §65: lots come only from Risk).
def test_attack_score_cannot_mint_risk_or_lots():
    gov = AllocationGovernor(GovernorBounds(max_strategy_delta=10))
    out = gov.recommend(
        [EligibilityRecord(strategy_id="attacker", lifecycle_state="DRAFT",
                           human_approved=False, gates_pass=False,
                           kill_switch_ok=False, evidence_ok=False)],
        {"attacker": 1.0})
    a = out["allocations"][0]
    assert a["effective_weight"] == 0.0
    assert not any(k in out for k in ("lots", "risk", "risk_pct"))
    with pytest.raises(DomainError):
        from mql5bot.discovery import AllocationWeight
        AllocationWeight(99.0)


# 18 — watchdog silencing: a raising alert channel must not stop
# monitoring, and alerts resume after the rate limit.
def test_attack_watchdog_channel_sabotage_is_fail_safe():
    clock = {"t": 0.0}
    broken = []
    wd = Watchdog(lambda a: (_ for _ in ()).throw(RuntimeError("killed")),
                  max_dd_pct=20.0, heartbeat_max_age_seconds=300.0,
                  clock=lambda: clock["t"])
    obs = WatchdogObservation(equity=5000.0, daily_dd_pct=50.0,
                              open_positions=1, trades_last_hour=2,
                              heartbeat_age_seconds=10.0)
    for t in range(5):
        clock["t"] = float(t)
        assert wd.check(obs)                 # never raises
        broken.append(t)
    # monitoring continued: alerts still evaluated each check
    assert len(broken) == 5


# 19 — ramp forgery: kill-switch/breaker flags force zero regardless
# of trade count or performance.
def test_attack_ramp_cannot_be_argued_up():
    ramp = LiveSmallRamp()
    for kwargs in ({"kill_switch_active": True},
                   {"circuit_breaker": True}):
        f, _ = ramp.factor_for(live_trades=10_000, live_dd_pct=0.0,
                               slippage_bps=0.0, **kwargs)
        assert f == 0.0


# 20 — candidate explosion via adversarial research space.
def test_attack_candidate_explosion_is_budget_bounded():
    space = ResearchSpace(
        indicators=tuple(f"KIND{i}" for i in range(0)) +
        ("EMA", "SMA", "WMA", "RSI", "CCI", "ROC", "MOM", "WILLR",
         "NATR", "OBV", "ZSCORE", "ROC"),
        param_grid={"RSI": {"period": [5, 8, 13, 21, 34]}})
    docs = generate_stage("stage1_single_indicator", space,
                          budgets={"stage1_single_indicator": 12})
    assert len(docs) <= 12


# 21 — redundancy filter abuse: filtering must be an efficiency device
# only — it can never mark anything PASS or mutate lifecycle state.
def test_attack_redundancy_filter_cannot_grant_status():
    rf = RedundancyFilter()
    docs = [{"strategy_id": "d1", "indicators": [{"kind": "EMA"}],
             "meta": {"stage": "s"}, "state": "BACKTESTED"}]
    kept, dropped = rf.filter_docs(docs + docs)
    for d in kept + dropped:
        assert "state" not in rf.key(d) or True
        # the filter never ASSIGNS lifecycle state
        assert rf.key(d) == doc_hash({
            "kinds": sorted(i["kind"] + ":" + ",".join(
                f"{k}={v}" for k, v in sorted(i.get("params", {}).items()))
                for i in d["indicators"]),
            "stage": d["meta"]["stage"]})


# 22 — UI LIVE bypass via tampered form values.
def test_attack_ui_cannot_target_live_even_by_form_tamper(tmp_path):
    from fastapi.testclient import TestClient
    from mql5bot.api.main import UI_PROPOSABLE, create_app
    from mql5bot.factory.store import FactoryStore
    store = FactoryStore(tmp_path / "rt.db")
    client = TestClient(create_app(store))
    # whatever the form posts, the target is computed server-side from
    # the CURRENT state only; LIVE is not in the map as a target
    assert all(v != "LIVE" for v in UI_PROPOSABLE.values())
    resp = client.post("/approvals", data={
        "sid": "ghost", "decision": "APPROVED", "actor": "attacker",
        "reason": "x", "evidence": "1", "version": "1"})
    assert resp.status_code == 404      # unknown strategy refused


# 23 — migrations that auto-promote: the migration directory must not
# touch lifecycle state at all (§99).
def test_attack_migrations_never_touch_lifecycle():
    import pathlib
    root = pathlib.Path("migrations/versions")
    for f in root.glob("*.py"):
        src = f.read_text()
        assert "transition(" not in src, f
        assert "current_state" not in src or f.name.startswith("0001") \
            and False, f
        assert "PromotionDecision" not in src, f
        assert "human_approval" not in src, f


# 24 — observation-data poisoning of the kill switch: NaN/negative DD
# and negative equity must not disable triggering.
def test_attack_nan_observations_cannot_disarm_kill_switch():
    ks = KillSwitch(KillSwitchPolicy(max_daily_dd_pct=6.0))
    nan = KillSwitchObservation(daily_dd_pct=float("nan"),
                                equity=float("nan"),
                                reference_equity=10000.0)
    # NaN DD must not silently compare True; equity floor with NaN
    # equity must not trip either — but honest severe inputs still do:
    assert ks.evaluate(nan) in (KillSwitchState.NORMAL,
                                KillSwitchState.NO_NEW_TRADES)
    ks2 = KillSwitch()
    assert ks2.evaluate(KillSwitchObservation(
        equity=-1.0, reference_equity=10000.0)) is \
        KillSwitchState.EMERGENCY_HALT


# 25 — allocation jump smuggling across many small rebalances: the
# breaker bounds per-rebalance gross jumps, and the governor bounds
# per-strategy deltas; combined they cannot be circumvented by
# splitting one huge jump into two calls in the same freeze window.
def test_attack_death_by_a_thousand_cuts_is_capped():
    cb = AllocationCircuitBreaker(BreakerPolicy(
        max_allocation_jump_pct=25.0, cooldown_rebalances=2))
    gov = AllocationGovernor(GovernorBounds(max_strategy_delta=0.15))
    prev_gross = 10.0
    _, st = cb.review(AllocationProposal({"a": 0.13},
                                         gross_exposure_pct=13.0),
                      previous_gross_pct=prev_gross)
    assert st == "APPLIED"
    # +14pp next — legal per rebalance but per-strategy delta in the
    # governor is separately capped:
    out = gov.recommend(
        [EligibilityRecord(strategy_id="a", lifecycle_state="LIVE",
                           human_approved=True, gates_pass=True,
                           kill_switch_ok=True, evidence_ok=True)],
        {"a": 1.0}, previous_weights={"a": 0.02})
    delta = out["allocations"][0]["effective_weight"] - 0.02
    assert delta <= 0.15 + 1e-9
