"""Factory store tests: idempotency, immutability, evidence-gated
lifecycle, human approval boundary, restart equivalence (mission
§19/§39/§40/§41/§51/§59.6/§59.7)."""

from __future__ import annotations

import json

import pytest
from mql5bot.dsl import parse_spec
from mql5bot.factory import lifecycle as lc
from mql5bot.factory.store import FactoryStore, StoreError

from tests.test_dsl_core import _base_doc


@pytest.fixture()
def store(tmp_path):
    return FactoryStore(tmp_path / "factory.db")


@pytest.fixture()
def spec():
    return parse_spec(_base_doc())


def _register_executable(store, spec, **kw):
    return store.register_strategy(spec, created_by="test", **kw)


def test_register_is_idempotent_by_spec_hash(store, spec):
    id1, created1 = _register_executable(store, spec)
    id2, created2 = _register_executable(store, spec)
    assert created1 and not created2
    assert id1 == id2


def test_same_id_version_different_spec_refused(store, spec):
    _register_executable(store, spec)
    doc2 = _base_doc()
    doc2["indicators"][0]["period"] = 15          # different logic
    spec2 = parse_spec(doc2)
    with pytest.raises(StoreError, match="immutable"):
        _register_executable(store, spec2)


def test_version_must_increase(store, spec):
    _register_executable(store, spec)
    doc2 = _base_doc()
    doc2["indicators"][0]["period"] = 15
    doc2["version"] = 1                            # same version number
    spec2 = parse_spec(doc2)
    with pytest.raises(StoreError, match="immutable"):
        _register_executable(store, spec2)
    doc2["version"] = 2
    spec3 = parse_spec(doc2)
    _, created = _register_executable(store, spec3, parent=(
        spec.strategy_id, spec.version))
    assert created


def test_evidence_gated_promotion(store, spec):
    _register_executable(store, spec)
    sid = spec.strategy_id
    with pytest.raises(StoreError, match="requires evidence"):
        store.transition(sid, 1, lc.PARSED, actor="factory")
    # arbitrary target refused even with evidence
    from mql5bot.factory.store import StoreError as _SE
    with pytest.raises(_SE):
        store.transition(sid, 1, lc.LIVE, evidence_refs=("1",),
                         actor="owner", human_approval=True)


def test_missing_evidence_row_blocks_promotion(store, spec):
    _register_executable(store, spec)
    with pytest.raises(StoreError, match="requires PASS"):
        store.transition(spec.strategy_id, 1, lc.PARSED,
                         evidence_refs=(999,), actor="factory")


def test_full_ladder_with_real_evidence_and_human_gate(store, spec):
    _register_executable(store, spec)
    sid = spec.strategy_id
    run_id = store.record_run(sid, 1, run_type="parse",
                              status="PASS", spec_hash=spec.spec_hash)
    store.transition(sid, 1, lc.PARSED, evidence_refs=(run_id,),
                     actor="factory", gate_version="gates-1.0.0")
    assert store.current_state(sid) == lc.PARSED
    # type adequacy is STORE-ENFORCED (gate §15): a wrong-type PASS run
    # is refused even though it binds the same strategy/version
    wrong = store.record_run(sid, 1, run_type="backtest", status="PASS",
                             spec_hash=spec.spec_hash)
    import pytest as _pytest
    from mql5bot.factory.store import StoreError as _SE
    with _pytest.raises(_SE, match="requires PASS"):
        store.transition(sid, 1, lc.VALIDATED, evidence_refs=(wrong,),
                         actor="factory")
    run2 = store.record_run(sid, 1, run_type="schema", status="PASS",
                            spec_hash=spec.spec_hash)
    store.transition(sid, 1, lc.VALIDATED, evidence_refs=(run2,),
                     actor="factory")
    assert store.current_state(sid) == lc.VALIDATED
    # Human approval boundary: SHADOW → DEMO without approval refused
    for _ in range(4):              # VALIDATED → … → SHADOW
        cur = store.current_state(sid)
        nxt, (rtype,) = lc.PROMOTIONS[cur][0], lc.PROMOTIONS[cur][1]
        rid = store.record_run(sid, 1, run_type=rtype,
                               status="PASS", spec_hash=spec.spec_hash)
        store.transition(sid, 1, nxt, evidence_refs=(rid,),
                         actor="factory")
    assert store.current_state(sid) == lc.SHADOW
    rid = store.record_run(sid, 1, run_type="shadow_evidence",
                           status="PASS", spec_hash=spec.spec_hash)
    with pytest.raises(StoreError, match="human approval"):
        store.transition(sid, 1, lc.DEMO, evidence_refs=(rid,),
                         actor="factory")
    store.transition(sid, 1, lc.DEMO, evidence_refs=(rid,),
                     actor="owner", human_approval=True,
                     reason="owner approved demo")
    assert store.current_state(sid) == lc.DEMO
    # the promotion decision is auditable
    with store.session() as sess:
        from mql5bot.factory.models import PromotionDecision
        from sqlalchemy import select
        rows = list(sess.scalars(select(PromotionDecision).where(
            PromotionDecision.strategy_id == sid)))
    assert rows and rows[-1].human_approval is True
    assert rows[-1].actor == "owner"


def test_rejected_preserves_evidence_rows(store, spec):
    _register_executable(store, spec)
    sid = spec.strategy_id
    run_id = store.record_run(sid, 1, run_type="parse", status="PASS",
                              spec_hash=spec.spec_hash)
    store.transition(sid, 1, lc.PARSED, evidence_refs=(run_id,),
                     actor="factory")
    store.transition(sid, 1, lc.REJECTED, actor="gate:gate2",
                     reason="backtest insufficient")
    # evidence still queryable
    with store.session() as sess:
        from mql5bot.factory.models import ValidationRun
        from sqlalchemy import select
        rows = list(sess.scalars(select(ValidationRun).where(
            ValidationRun.strategy_id == sid)))
    assert len(rows) == 1                          # preserved, not purged


def test_restart_preserves_everything(store, spec, tmp_path):
    path = tmp_path / "factory.db"
    st1 = FactoryStore(path)
    st1.register_strategy(spec, created_by="t")
    run_id = st1.record_run(spec.strategy_id, 1, run_type="parse",
                            status="PASS", spec_hash=spec.spec_hash)
    st1.transition(spec.strategy_id, 1, lc.PARSED,
                   evidence_refs=(run_id,), actor="factory")
    st2 = FactoryStore(path)                       # "restart"
    assert st2.current_state(spec.strategy_id) == lc.PARSED
    assert [e.to_state for e in st2.history(spec.strategy_id)] == \
        ["PARSED"]
    # re-submitting after restart creates no duplicate identity
    _, created = st2.register_strategy(spec, created_by="t")
    assert not created


def test_rerunning_validation_appends_never_mutates(store, spec):
    _register_executable(store, spec)
    r1 = store.record_run(spec.strategy_id, 1, run_type="backtest",
                          status="PASS", spec_hash=spec.spec_hash)
    r2 = store.record_run(spec.strategy_id, 1, run_type="backtest",
                          status="FAIL", spec_hash=spec.spec_hash)
    assert r1 != r2
    with store.session() as sess:
        from mql5bot.factory.models import ValidationRun
        from sqlalchemy import select
        rows = list(sess.scalars(select(ValidationRun)))
        assert [r.status for r in rows] == ["PASS", "FAIL"]


def test_claims_never_merge_into_metrics(store, spec):
    _register_executable(store, spec, claims=[
        {"metric": "win_rate", "value": 0.82,
         "source_url": "https://example.com/x"}])
    store.record_run(spec.strategy_id, 1, run_type="backtest",
                     status="PASS", spec_hash=spec.spec_hash,
                     metrics={"win_rate": 0.57})
    with store.session() as sess:
        from mql5bot.factory.models import StrategyClaim, ValidationMetric
        from sqlalchemy import select
        claims = list(sess.scalars(select(StrategyClaim)))
        metrics = list(sess.scalars(select(ValidationMetric)))
    assert len(claims) == 1 and claims[0].claimed_value == "0.82"
    assert len(metrics) == 1 and metrics[0].value == pytest.approx(0.57)


def test_spec_json_is_the_normalized_document(store, spec):
    _register_executable(store, spec)
    with store.session() as sess:
        from mql5bot.factory.models import StrategyVersion
        from sqlalchemy import select
        row = sess.scalar(select(StrategyVersion))
    assert json.loads(row.spec_json) == spec.document
