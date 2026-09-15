"""Operator console tests (mission §57-§59/§73): Kanban board, explicit
approval UX, safety page — plus §73 source-scan proofs that the UI/API
layer can never mark a strategy LIVE nor skip lifecycle stages."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mql5bot.api.main import KANBAN_COLUMNS, SafetyHub, create_app
from mql5bot.discovery.safety import (
    AllocationCircuitBreaker,
    KillSwitch,
    KillSwitchObservation,
)
from mql5bot.dsl.parse import parse_spec
from mql5bot.factory.lifecycle import PROMOTIONS
from mql5bot.factory.store import FactoryStore

from tests.test_dsl_core import _base_doc

API_SRC = Path("python/mql5bot/api/main.py").read_text()


def _seed_strategy(store: FactoryStore, sid: str = "api_demo_strat",
                   *, to_state: str | None = "SHADOW"):
    doc = _base_doc()
    doc["strategy_id"] = sid
    spec = parse_spec(doc)
    store.register_strategy(spec, created_by="test")
    cur = store.current_state(sid)
    while to_state is not None and cur != to_state:
        nxt, (rtype,) = PROMOTIONS[cur][0], PROMOTIONS[cur][1]
        if rtype == "demo_evidence":      # not reachable from UI flow
            break
        rid = store.record_run(sid, 1, run_type=rtype, status="PASS",
                               spec_hash=spec.spec_hash)
        store.transition(sid, 1, nxt, evidence_refs=(rid,),
                         actor="factory")
        cur = store.current_state(sid)
    return spec


def _client(tmp_path, **kw):
    store = FactoryStore(tmp_path / "api.db")
    app = create_app(store, **kw)
    return store, TestClient(app)


# ----------------------------------------------------------------- board


def test_board_lists_kanban_columns_and_strategy(tmp_path):
    store, client = _client(tmp_path)
    _seed_strategy(store)
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    for col in KANBAN_COLUMNS:
        assert col in body
    assert "api_demo_strat" in body
    assert "SHADOW" in body


def test_strategy_detail_and_404(tmp_path):
    store, client = _client(tmp_path)
    _seed_strategy(store)
    assert client.get("/strategies/api_demo_strat").status_code == 200
    assert client.get("/strategies/does_not_exist").status_code == 404


# -------------------------------------------------------------- approvals


def test_explicit_approval_moves_shadow_to_demo(tmp_path):
    store, client = _client(tmp_path)
    spec = _seed_strategy(store)
    rid = store.record_run("api_demo_strat", 1,
                           run_type="shadow_evidence", status="PASS",
                           spec_hash=spec.spec_hash)
    resp = client.post("/approvals", data={
        "sid": "api_demo_strat", "decision": "APPROVED",
        "actor": "owner", "reason": "shadow stats reviewed",
        "evidence": str(rid), "version": "1"},
        follow_redirects=False)
    assert resp.status_code == 303
    assert store.current_state("api_demo_strat") == "DEMO"
    with store.session() as sess:
        from mql5bot.factory.models import PromotionDecision
        from sqlalchemy import select
        rows = list(sess.scalars(select(PromotionDecision).where(
            PromotionDecision.strategy_id == "api_demo_strat")))
    assert rows[-1].human_approval is True
    assert rows[-1].actor == "ui:owner"


def test_approval_requires_reason_and_evidence(tmp_path):
    store, client = _client(tmp_path)
    _seed_strategy(store)
    # missing evidence → store refuses (409)
    r1 = client.post("/approvals", data={
        "sid": "api_demo_strat", "decision": "APPROVED",
        "actor": "owner", "reason": "looks fine", "evidence": "",
        "version": "1"})
    assert r1.status_code == 409
    assert store.current_state("api_demo_strat") == "SHADOW"
    # blank reason → 422
    r2 = client.post("/approvals", data={
        "sid": "api_demo_strat", "decision": "APPROVED",
        "actor": "owner", "reason": "  ", "evidence": "1",
        "version": "1"})
    assert r2.status_code == 422


def test_denial_records_alert_without_state_change(tmp_path):
    store, client = _client(tmp_path)
    _seed_strategy(store)
    r = client.post("/approvals", data={
        "sid": "api_demo_strat", "decision": "DENIED",
        "actor": "owner", "reason": "metrics degraded", "version": "1"},
        follow_redirects=False)
    assert r.status_code == 303
    assert store.current_state("api_demo_strat") == "SHADOW"
    with store.session() as sess:
        from mql5bot.factory.models import Alert
        from sqlalchemy import select
        alerts = list(sess.scalars(select(Alert).where(
            Alert.code == "APPROVAL_DENIED")))
    assert alerts and "metrics degraded" in alerts[-1].message


# ----------------------------------------------------------------- safety


def test_safety_page_shows_kill_switch_and_reset(tmp_path):
    ks = KillSwitch()
    ks.evaluate(KillSwitchObservation(daily_dd_pct=99.0))
    hub = SafetyHub(ks, AllocationCircuitBreaker())
    _, client = _client(tmp_path, safety=hub)
    body = client.get("/safety").text
    assert "EMERGENCY_HALT" in body
    r = client.post("/safety/killswitch/reset", data={
        "actor": "owner", "reason": "investigated; false alarm"},
        follow_redirects=False)
    assert r.status_code == 303
    assert ks.state.value == "NORMAL"


def test_safety_reset_requires_actor_and_reason(tmp_path):
    hub = SafetyHub(KillSwitch(), AllocationCircuitBreaker())
    _, client = _client(tmp_path, safety=hub)
    r = client.post("/safety/killswitch/reset", data={
        "actor": "", "reason": ""})
    assert r.status_code == 422


def test_score_rows_render_when_score_fn_given(tmp_path):
    store, client = _client(tmp_path, score_fn=lambda sid: {
        "score": 0.61, "score_version": "discovery-1.0", "rows": [
            {"component": "oos_survival", "raw": 1.0, "normalized": 1.0,
             "weight": 0.12, "contribution": 0.12, "available": True}],
        "pol_hash": "x" * 64})
    _seed_strategy(store)
    body = client.get("/strategies/api_demo_strat").text
    assert "0.6100" in body and "oos_survival" in body


# ---------------------------------------------- §73 source-isolation proofs


def test_source_proof_ui_cannot_mark_live():
    """§73: no route in the API/UI layer may transition anything to
    LIVE (incl. via variables holding it) — activation is owner-only."""
    tree = ast.parse(API_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", getattr(func, "id", ""))
            if name == "transition":
                # third positional arg or target= keyword
                args = node.args
                if args:
                    target = args[2]
                    if isinstance(target, ast.Constant) and \
                            target.value == "LIVE":
                        pytest.fail("API layer transitions to LIVE")
                for kwarg in node.keywords:
                    if kwarg.arg == "target" and \
                            isinstance(kwarg.value, ast.Constant) and \
                            kwarg.value.value == "LIVE":
                        pytest.fail("API layer transitions to LIVE")
    # the UI-proposable map must not contain LIVE as a TARGET
    assert "LIVE_SMALL" in API_SRC
    # DEMO → LIVE_SMALL is a legal human-gated promotion; the LIVE
    # TARGET never appears as a UI-proposable value
    assert '"LIVE_SMALL": "LIVE"' not in API_SRC
    assert '"DEMO": "LIVE_SMALL"' in API_SRC


def test_source_proof_ui_only_proposes_next_stage():
    """§73: UI_PROPOSABLE maps each state to exactly the legal next
    promotion per the lifecycle machine — no skips."""
    for cur, nxt in {"SHADOW": "DEMO", "DEMO": "LIVE_SMALL"}.items():
        legal = PROMOTIONS[cur][0]
        assert nxt == legal, f"UI proposed {cur}→{nxt}, machine says " \
                             f"{cur}→{legal}"
    # no other state is UI-proposable
    assert set(PROMOTIONS) >= {"DRAFT", "VALIDATED", "BACKTESTED",
                               "OOS_SURVIVOR"}


def test_source_proof_approvals_require_human_flag():
    """The only transition call in the API layer passes
    human_approval=True and a 'ui:'-prefixed actor (auditable)."""
    assert "human_approval=True" in API_SRC
    assert 'actor=f"ui:{actor}"' in API_SRC


def test_promotions_require_store_evidence_even_for_ui(tmp_path):
    """The store re-validates: UI approval with a foreign strategy's
    evidence is refused (cross-strategy evidence is not evidence)."""
    store, client = _client(tmp_path)
    _seed_strategy(store)
    other_spec = _seed_strategy(store, sid="other_strategy_x")
    foreign = store.record_run("other_strategy_x", 1,
                               run_type="shadow_evidence",
                               status="PASS",
                               spec_hash=other_spec.spec_hash)
    r = client.post("/approvals", data={
        "sid": "api_demo_strat", "decision": "APPROVED",
        "actor": "owner", "reason": "try foreign evidence",
        "evidence": str(foreign), "version": "1"})
    assert r.status_code == 409
    assert store.current_state("api_demo_strat") == "SHADOW"


# ------------------------------------- §51/§52 research console additions


def test_board_includes_paused_degraded_columns(tmp_path):
    store, client = _client(tmp_path)
    _seed_strategy(store)
    body = client.get("/").text
    for col in ("DEGRADED", "PAUSED"):
        assert col in body


def test_one_click_campaign_registers_idempotently(tmp_path):
    store, client = _client(tmp_path)
    data = {"idea": "fade exhausted trends on gold",
            "source": "community paste about ICT silver bullet",
            "dataset": "synthetic-default", "actor": "owner"}
    r1 = client.post("/campaigns", data=data, follow_redirects=False)
    assert r1.status_code == 303
    r2 = client.post("/campaigns", data=data, follow_redirects=False)
    assert r2.status_code == 303
    with store.session() as sess:
        from mql5bot.factory.models import DiscoveryCampaign
        from sqlalchemy import func, select
        n = sess.scalar(select(func.count()).select_from(
            DiscoveryCampaign))
        row = sess.scalars(select(DiscoveryCampaign)).one()
    assert n == 1                       # idempotent by idea+actor hash
    assert row.status == "PAUSED"       # no runner → honest PAUSED
    assert row.manifest["autonomy"] == "RESEARCH_AUTOMATION"
    assert row.manifest["source_text_hash"]


def test_research_page_lists_campaigns_and_warns_without_runner(tmp_path):
    _, client = _client(tmp_path)
    client.post("/campaigns", data={
        "idea": "ma pullback", "source": "", "dataset": "x",
        "actor": "owner"})
    body = client.get("/research").text
    assert "ma pullback" in body
    assert "runner is not configured" in body.lower() or \
        "not configured" in body.lower()


def test_campaign_requires_idea_and_actor(tmp_path):
    _, client = _client(tmp_path)
    r = client.post("/campaigns", data={"idea": "", "actor": ""})
    assert r.status_code == 422


def test_research_runner_invoked_when_configured(tmp_path):
    calls = []

    def runner(payload):
        calls.append(payload)
        return {"campaign_id": payload["campaign_id"],
                "status": "RUNNING", "candidates": 0}

    store = FactoryStore(tmp_path / "rr.db")
    client = TestClient(create_app(store, research_runner=runner,
                                   campaign_query=list))
    r = client.post("/campaigns", data={
        "idea": "breakout retest", "source": "", "dataset": "d",
        "actor": "owner"}, follow_redirects=False)
    assert r.status_code == 303
    assert calls and calls[0]["manifest"]["hypothesis"] == \
        "breakout retest"
    with store.session() as sess:
        from mql5bot.factory.models import DiscoveryCampaign
        from sqlalchemy import select
        row = sess.scalars(select(DiscoveryCampaign)).one()
    assert row.status == "RUNNING"
