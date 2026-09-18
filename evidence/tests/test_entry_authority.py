"""Convergence §32/§36/§39/§57/§65/§71-§73: entry-chain authority
proofs, approval-record enrichment, concurrency/duplicate attacks."""

from __future__ import annotations

import pytest
from mql5bot.discovery.entry_chain import ChainContext, EntryRequest, govern_entry
from mql5bot.discovery.safety import KillSwitchState
from mql5bot.dsl.parse import parse_spec
from mql5bot.factory.lifecycle import PROMOTIONS
from mql5bot.factory.store import FactoryStore, StoreError

from tests.test_dsl_core import _base_doc


def _req(**kw) -> EntryRequest:
    d = {"origin": "strategy", "strategy_id": "strat_a", "symbol":
         "EURUSD", "side": "long", "requested_risk": 0.005}
    d.update(kw)
    return EntryRequest(**d)


def _ctx(**kw) -> ChainContext:
    d = {"market_data_ok": True, "lifecycle_state": "LIVE_SMALL",
         "human_approved": True, "gates_pass": True, "evidence_ok": True,
         "regime_allowed": True, "score": 0.6, "meta_weight": 0.10,
         "portfolio_ok": True, "risk_approved_risk": 0.005,
         "risk_budget": 0.01, "breaker_frozen": False,
         "kill_switch_state": "NORMAL"}
    d.update(kw)
    return ChainContext(**d)


# ------------------------------------------------ §36 authority proofs


def test_llm_ml_community_factory_never_trade():
    for origin in ("llm", "ml", "community", "factory", "interpreter",
                   "optimizer"):
        d = govern_entry(_req(origin=origin), _ctx())
        assert not d.allowed
        assert d.veto_owner == "origin-authority"
        assert d.trace[0]["layer"] == "origin"


def test_meta_says_trade_but_kill_switch_blocks():
    d = govern_entry(_req(), _ctx(kill_switch_state="NO_NEW_TRADES"))
    assert not d.allowed and d.veto_owner == "kill-switch"
    d2 = govern_entry(_req(),
                      _ctx(kill_switch_state=KillSwitchState.EMERGENCY_HALT
                           .value))
    assert not d2.allowed and d2.veto_owner == "kill-switch"


def test_risk_says_yes_but_kill_switch_still_blocks():
    d = govern_entry(_req(), _ctx(risk_approved_risk=0.009,
                                  kill_switch_state="EMERGENCY_HALT"))
    assert not d.allowed and d.veto_owner == "kill-switch"


def test_no_layer_removes_a_lower_veto():
    # breaker frozen blocks even with everything else perfect
    d = govern_entry(_req(), _ctx(breaker_frozen=True))
    assert not d.allowed and d.veto_owner == "circuit-breaker"
    # kill switch blocks even when breaker is clear
    d2 = govern_entry(_req(), _ctx(kill_switch_state="EMERGENCY_HALT"))
    assert not d2.allowed and d2.veto_owner == "kill-switch"
    # order in trace follows §57
    layers = [t["layer"] for t in d2.trace]
    assert layers.index("risk") < layers.index("kill_switch")


def test_risk_can_only_decrease_through_meta():
    """§39: approved risk is min(risk, Meta×budget) — a Risk number
    above Meta's share is clamped DOWN, never up."""
    d = govern_entry(_req(), _ctx(risk_approved_risk=0.05,
                                  meta_weight=0.1, risk_budget=0.01))
    assert d.allowed
    assert d.approved_risk <= 0.1 * 0.01 + 1e-12


def test_high_score_cannot_jump_the_chain():
    d = govern_entry(_req(), _ctx(score=0.999, gates_pass=False))
    assert not d.allowed and d.veto_owner == "lifecycle"


# ------------------------------------------- §32 approval record fields


def _seed(store: FactoryStore, sid: str, to: str = "SHADOW"):
    doc = _base_doc()
    doc["strategy_id"] = sid
    spec = parse_spec(doc)
    store.register_strategy(spec, created_by="test")
    cur = store.current_state(sid)
    while cur != to:
        nxt, (rtype,) = PROMOTIONS[cur][0], PROMOTIONS[cur][1]
        if rtype == "demo_evidence":
            break
        rid = store.record_run(sid, 1, run_type=rtype, status="PASS",
                               spec_hash=spec.spec_hash)
        store.transition(sid, 1, nxt, evidence_refs=(rid,),
                         actor="factory")
        cur = store.current_state(sid)
    return spec


def test_approval_record_binds_evidence_hash_and_policy_version(tmp_path):
    store = FactoryStore(tmp_path / "a.db")
    spec = _seed(store, "auth_evid_strat")
    rid = store.record_run("auth_evid_strat", 1,
                           run_type="shadow_evidence", status="PASS",
                           spec_hash=spec.spec_hash)
    store.transition("auth_evid_strat", 1, "DEMO", evidence_refs=(rid,),
                     actor="owner", human_approval=True,
                     reason="shadow reviewed",
                     policy_version="discovery-defaults-1.0")
    with store.session() as sess:
        from mql5bot.factory.models import PromotionDecision
        from sqlalchemy import select
        row = sess.scalars(select(PromotionDecision).where(
            PromotionDecision.strategy_id == "auth_evid_strat")).all()[-1]
    assert row.policy_version == "discovery-defaults-1.0"
    assert len(row.evidence_hash) == 64
    import hashlib

    from mql5bot.factory.models import ValidationRun
    with store.session() as sess:
        vr = sess.get(ValidationRun, int(rid))
        expect = hashlib.sha256(
            f"{vr.id}|{vr.run_type}|{vr.status}|{vr.spec_hash}".encode()
        ).hexdigest()
    assert row.evidence_hash == expect


# ------------------------------------- §65 attacks 26-30 / §72 / §73


def test_attack_duplicate_campaign_id_refused_by_db(tmp_path):
    from mql5bot.factory.models import DiscoveryCampaign
    store = FactoryStore(tmp_path / "b.db")
    with store.session() as sess:
        sess.add(DiscoveryCampaign(campaign_id="camp_dup", name="n",
                                   stage="s1", status="RUNNING"))
        sess.commit()
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError), store.session() as sess:
        sess.add(DiscoveryCampaign(campaign_id="camp_dup", name="n2",
                                   stage="s1", status="RUNNING"))
        sess.commit()


def test_attack_concurrent_promotion_second_refused(tmp_path):
    """§73: two promotion requests for the same transition — exactly
    one wins; the loser gets a refusal, never a duplicate event."""
    store = FactoryStore(tmp_path / "c.db")
    spec = _seed(store, "race_strat")
    rid = store.record_run("race_strat", 1, run_type="shadow_evidence",
                           status="PASS", spec_hash=spec.spec_hash)
    store.transition("race_strat", 1, "DEMO", evidence_refs=(rid,),
                     actor="owner", human_approval=True, reason="first")
    with pytest.raises(StoreError):
        store.transition("race_strat", 1, "DEMO", evidence_refs=(rid,),
                         actor="owner", human_approval=True,
                         reason="second")
    with store.session() as sess:
        from mql5bot.factory.models import LifecycleEvent
        from sqlalchemy import func, select
        n = sess.scalar(select(func.count()).select_from(LifecycleEvent)
                        .where(LifecycleEvent.strategy_id == "race_strat",
                               LifecycleEvent.to_state == "DEMO"))
    assert n == 1


def test_attack_forged_human_approval_by_machine_role(tmp_path):
    """§65#21: llm:/factory:/ml: actors can never self-approve into a
    human-gated state."""
    store = FactoryStore(tmp_path / "d.db")
    spec = _seed(store, "forge_strat")
    rid = store.record_run("forge_strat", 1, run_type="shadow_evidence",
                           status="PASS", spec_hash=spec.spec_hash)
    for actor in ("llm:gpt", "factory:pipeline", "ml:drift",
                  "optimizer:grid"):
        with pytest.raises(StoreError, match="not a human role"):
            store.transition("forge_strat", 1, "DEMO",
                             evidence_refs=(rid,), actor=actor,
                             human_approval=True, reason="self-approve")
    assert store.current_state("forge_strat") == "SHADOW"


def test_attack_stale_shadow_result_is_not_evidence(tmp_path):
    """§65#28: shadow evidence recorded under an OLD spec_hash must not
    promote the current version."""
    store = FactoryStore(tmp_path / "e.db")
    _seed(store, "stale_strat")
    stale = store.record_run("stale_strat", 1, run_type="shadow_evidence",
                             status="PASS", spec_hash="0" * 64)
    with pytest.raises(StoreError, match="requires PASS"):
        store.transition("stale_strat", 1, "DEMO", evidence_refs=(stale,),
                         actor="owner", human_approval=True, reason="x")


def test_migration_0003_upgrade_downgrade(tmp_path):
    """§71: the enrichment migration is reversible; lifecycle data is
    never touched by migrations (§99)."""
    import os
    import subprocess
    import sys
    db = str(tmp_path / "mig.db")
    env = dict(os.environ, AEGIS_FACTORY_DB=db)
    for args in (("upgrade", "head"), ("downgrade", "0001"),
                 ("upgrade", "head")):
        subprocess.run([sys.executable, "-m", "alembic", *args],
                       check=True, env=env, capture_output=True)
    import sqlite3
    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute(
        "PRAGMA table_info(promotion_decisions)")}
    con.close()
    assert {"evidence_hash", "policy_version"} <= cols
