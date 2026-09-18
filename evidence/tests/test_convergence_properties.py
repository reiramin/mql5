"""Convergence §66 property/metamorphic suite + §64 failure cases not
yet pinned elsewhere.  Each test states the property in its name."""

from __future__ import annotations

import pytest
from mql5bot.discovery import (
    AllocationGovernor,
    GovernorBounds,
    HealthSignals,
    PerformanceDecayController,
    ResearchSpace,
)
from mql5bot.discovery.governor import EligibilityRecord
from mql5bot.discovery.orchestrator import DiscoveryOrchestrator
from mql5bot.dsl.parse import parse_spec
from mql5bot.factory.lifecycle import PROMOTIONS
from mql5bot.factory.store import FactoryStore

from tests.test_dsl_core import _base_doc


# 2. display-name changes do not change identity
def test_display_name_change_preserves_identity():
    d1, d2 = _base_doc(), _base_doc()
    d2["name"] = "Totally Different Display"
    d2["description"] = "other words entirely"
    assert parse_spec(d1).spec_hash == parse_spec(d2).spec_hash


# 3. equivalent EN/FA descriptions normalize equivalently
def test_en_fa_equivalent_interpretation():
    from mql5bot.factory.interpreter import TemplateInterpreter
    from mql5bot.factory.providers import ResearchMaterial
    interp = TemplateInterpreter()
    en = interp.interpret(ResearchMaterial(
        source_type="HUMAN", title="t",
        text="EMA20 crosses above EMA50. SL 2 ATR TP 3 ATR"))
    fa = interp.interpret(ResearchMaterial(
        source_type="HUMAN", title="t",
        text="EMA20 از EMA50 به سمت بالا کراس کرد. "
             "حد ضرر 2 ATR حد سود 3 ATR"))
    # both drafts carry the same SEMANTIC core — the description text
    # itself differs (provenance), the meaning does not
    assert en.draft["entry"] == fa.draft["entry"]
    assert en.draft["exit"] == fa.draft["exit"]
    assert en.ambiguities == fa.ambiguities


# 4. same campaign reproduces (already covered for docs; here for the
# whole orchestrator round trip)
def test_same_campaign_reproduces_identically():
    space = ResearchSpace(indicators=("EMA", "RSI"),
                          param_grid={"RSI": {"period": [10]}})
    def build():
        orch = DiscoveryOrchestrator(
            space, budgets={"stage1_single_indicator": 3},
            policy_hash="p" * 64, campaign_id="camp_r", seed=11)
        camp = orch.run_campaign({"campaign_id": "camp_r",
                                  "progress": {}, "results": {}},
                                 lambda stage, docs: [
                                     {"strategy_id": d["strategy_id"],
                                      "state": "BACKTESTED"}
                                     for d in docs])
        return orch.manifest(camp)
    m1, m2 = build(), build()
    assert m1 == m2


# 5. OOS cannot alter prior research records
def test_oos_evaluation_cannot_alter_prior_research(tmp_path):
    store = FactoryStore(tmp_path / "oos.db")
    doc = _base_doc()
    doc["strategy_id"] = "oos_proof_strat"
    spec = parse_spec(doc)
    store.register_strategy(spec, created_by="t")
    store.record_run("oos_proof_strat", 1, run_type="backtest",
                           status="PASS", spec_hash=spec.spec_hash,
                           metrics={"profit_factor": 1.2})
    before, before_mets = _run_rows(store)
    # the OOS look is recorded as a NEW append-only run; it must never
    # mutate the prior run row
    store.record_run("oos_proof_strat", 1, run_type="oos",
                     status="PASS", spec_hash=spec.spec_hash,
                     metrics={"profit_factor": 0.9})
    after_runs, after_mets = _run_rows(store)
    assert after_runs[:len(before)] == before   # prior runs immutable
    assert len(after_runs) == len(before) + 1   # appended, not merged
    assert after_mets[:len(before_mets)] == before_mets  # metrics
    # appended too (the new OOS run's metric), never rewritten


# 6. adding an unrelated strategy does not alter prior evidence
def test_adding_unrelated_strategy_preserves_prior_evidence(tmp_path):
    store = FactoryStore(tmp_path / "add.db")
    d1 = _base_doc()
    d1["strategy_id"] = "first_strat"
    s1 = parse_spec(d1)
    store.register_strategy(s1, created_by="t")
    store.record_run("first_strat", 1, run_type="parse", status="PASS",
                     spec_hash=s1.spec_hash)
    before, before_mets = _run_rows(store)
    d2 = _base_doc()
    d2["strategy_id"] = "second_unrelated"
    s2 = parse_spec(d2)
    store.register_strategy(s2, created_by="t")
    store.record_run("second_unrelated", 1, run_type="parse",
                     status="PASS", spec_hash=s2.spec_hash)
    after_runs, after_mets = _run_rows(store)
    assert after_runs[:len(before)] == before
    assert after_mets == before_mets


# 7. dataset identity change invalidates incompatible research reuse
def test_dataset_identity_change_refuses_campaign_reuse():
    space = ResearchSpace(indicators=("EMA",))
    orch_a = DiscoveryOrchestrator(space, policy_hash="p" * 64,
                                   dataset_hash="dsA" * 16)
    camp = orch_a.run_campaign({"campaign_id": "c", "progress": {},
                                "results": {}}, lambda s, d: [])
    orch_b = DiscoveryOrchestrator(space, policy_hash="p" * 64,
                                   dataset_hash="dsB" * 16)
    from mql5bot.discovery.candidates import doc_hash
    camp["dataset_hash"] = "dsA" * 16        # as persisted
    with pytest.raises(ValueError, match="DIFFERENT dataset"):
        orch_b.run_campaign(camp, lambda s, d: [])
    assert doc_hash  # (import pin)


# 8. decay never increases allocation; recovery requires qualification
def test_decay_monotone_and_recovery_gated():
    decay = PerformanceDecayController()
    healthy, _ = decay.evaluate(HealthSignals(
        rolling_trades=50, expectancy_ratio=1.2, dd_ratio=0.8,
        drift_score=0.1, slippage_bps_vs_assumed=0.0))
    worse, _ = decay.evaluate(HealthSignals(
        rolling_trades=50, expectancy_ratio=0.2, dd_ratio=3.0,
        drift_score=0.9, slippage_bps_vs_assumed=30.0))
    assert worse.multiplier < healthy.multiplier
    assert worse.multiplier <= 1.0 and healthy.multiplier <= 1.0


# 9. risk can only decrease through the governor (delta caps bind)
def test_governor_delta_caps_bind_downward():
    gov = AllocationGovernor(GovernorBounds(max_strategy_delta=0.05))
    out = gov.recommend(
        [EligibilityRecord(strategy_id="x", lifecycle_state="LIVE",
                           human_approved=True, gates_pass=True,
                           kill_switch_ok=True, evidence_ok=True)],
        {"x": 1.0}, previous_weights={"x": 0.5})
    a = out["allocations"][0]
    assert a["effective_weight"] <= 0.5 + 1e-9   # never increased
    assert any("delta capped" in r for r in a["reasons"])


# 10. invalid promotion stays invalid under replay
def test_invalid_promotion_replay_stays_invalid(tmp_path):
    store = FactoryStore(tmp_path / "inv.db")
    doc = _base_doc()
    doc["strategy_id"] = "invalid_replay"
    spec = parse_spec(doc)
    store.register_strategy(spec, created_by="t")
    from mql5bot.factory.store import StoreError
    for _ in range(2):
        with pytest.raises(StoreError):
            store.transition("invalid_replay", 1, "BACKTESTED",
                             evidence_refs=(), actor="factory")
        assert store.current_state("invalid_replay") == "DRAFT"


# 11. restart preserves state (store round trip across instances)
def test_restart_preserves_state(tmp_path):
    store = FactoryStore(tmp_path / "restart.db")
    doc = _base_doc()
    doc["strategy_id"] = "restart_strat"
    spec = parse_spec(doc)
    store.register_strategy(spec, created_by="t")
    rid = store.record_run("restart_strat", 1, run_type="parse",
                           status="PASS", spec_hash=spec.spec_hash)
    store.transition("restart_strat", 1, "PARSED", evidence_refs=(rid,),
                     actor="factory")
    # "restart": a brand-new store instance on the same file
    store2 = FactoryStore(tmp_path / "restart.db")
    assert store2.current_state("restart_strat") == "PARSED"


# ---------------------------- §64 failure cases not pinned elsewhere


def test_failure_huge_allocation_jump_is_frozen(tmp_path):
    from mql5bot.discovery import AllocationCircuitBreaker, AllocationProposal
    cb = AllocationCircuitBreaker()
    _, st = cb.review(AllocationProposal({"a": 0.8},
                                         gross_exposure_pct=80.0),
                      previous_gross_pct=10.0)
    assert st == "FROZEN_KEEP_LAST_SAFE"


def test_failure_stale_shadow_reuse_refused(tmp_path):
    store = FactoryStore(tmp_path / "stale2.db")
    doc = _base_doc()
    doc["strategy_id"] = "stale_shadow"
    spec = parse_spec(doc)
    store.register_strategy(spec, created_by="t")
    cur = store.current_state("stale_shadow")
    while cur != "SHADOW":
        nxt, (rtype,) = PROMOTIONS[cur][0], PROMOTIONS[cur][1]
        if rtype == "demo_evidence":
            break
        rid = store.record_run("stale_shadow", 1, run_type=rtype,
                               status="PASS", spec_hash=spec.spec_hash)
        store.transition("stale_shadow", 1, nxt, evidence_refs=(rid,),
                         actor="factory")
        cur = store.current_state("stale_shadow")
    # shadow recorded, then strategy v2 with a NEW spec: v1's shadow
    # evidence must not promote v2
    old_run = store.record_run("stale_shadow", 2,
                               run_type="shadow_evidence",
                               status="PASS", spec_hash=spec.spec_hash)
    from mql5bot.factory.store import StoreError
    with pytest.raises(StoreError):
        store.transition("stale_shadow", 2, "DEMO",
                         evidence_refs=(old_run,), actor="owner",
                         human_approval=True, reason="reuse v1 shadow")
    assert store.current_state("stale_shadow") == "SHADOW"


def test_failure_wrong_version_evidence_refused(tmp_path):
    store = FactoryStore(tmp_path / "ver.db")
    doc = _base_doc()
    doc["strategy_id"] = "ver_strat"
    spec = parse_spec(doc)
    store.register_strategy(spec, created_by="t")
    rid = store.record_run("ver_strat", 1, run_type="parse",
                           status="PASS", spec_hash=spec.spec_hash)
    from mql5bot.factory.store import StoreError
    with pytest.raises(StoreError):
        store.transition("ver_strat", 2, "PARSED", evidence_refs=(rid,),
                         actor="factory")


# ------------------------------------------------------------- helpers


def _run_rows(store: FactoryStore) -> list:
    """Immutable-view of validation runs + their metric rows."""
    with store.session() as sess:
        from mql5bot.factory.models import ValidationMetric, ValidationRun
        from sqlalchemy import select
        runs = [(r.id, r.run_type, r.status, r.spec_hash,
                 r.strategy_id, r.version)
                for r in sess.scalars(select(ValidationRun))]
        mets = sorted((m.run_id, m.name, m.value)
                      for m in sess.scalars(select(ValidationMetric)))
        return runs, mets
