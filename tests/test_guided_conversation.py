"""Tests for the guided strategy conversation (mql5bot.factory.conversation)
and its two API routes.

The load-bearing guarantees: an unspecified parameter becomes a QUESTION and is
never invented; a failed validation is reported WITH its reason; and no route
in this flow can move a strategy past the Python stages.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from fastapi.testclient import TestClient
from mql5bot.api.main import create_app
from mql5bot.factory import conversation
from mql5bot.factory.conversation import GuidedConversation
from mql5bot.factory.store import FactoryStore


def _client(tmp_path):
    store = FactoryStore(tmp_path / "api.db")
    return store, TestClient(create_app(store))


# -- the conversation engine (no HTTP) ---------------------------------------

def test_ambiguous_parameter_becomes_a_question_never_invented():
    conv = GuidedConversation(interpreter="template")
    step = conv.start("RSI is low, buy", symbol="EURUSD", timeframe="H1")
    assert step.needs_answers is True
    assert any("rsi_threshold" in q for q in step.questions)
    # the number is never invented — not in the restatement, not in the draft
    assert "30" not in step.restatement
    assert "ambiguous" in json.dumps(step.draft)  # operand stays a sentinel


def test_failed_validation_is_reported_with_its_reason():
    conv = GuidedConversation()
    v = conv.validate({})            # empty draft: schema-invalid
    assert v.passed is False
    assert "SCHEMA_INVALID" in v.reason or "SchemaInvalid" in v.reason


def test_valid_draft_passes_python_validation():
    conv = GuidedConversation(interpreter="template")
    step = conv.start("EMA 10 crosses above EMA 30",
                      symbol="EURUSD", timeframe="H1")
    v = conv.validate(step.draft)
    assert v.passed is True


def test_remaining_path_shows_the_11_stage_gate_as_not_done():
    conv = GuidedConversation()
    v = conv.validate({})
    joined = " ".join(v.remaining_after_python)
    assert "11-stage" in joined
    assert "NOT yet passed" in joined


def test_conversation_engine_never_promotes_past_python():
    src = inspect.getsource(conversation)
    # call patterns that would move a strategy forward — none may appear
    for forbidden in (".transition(", "check_transition",
                      "register_strategy", "promote("):
        assert forbidden not in src


# -- the two API routes ------------------------------------------------------

def test_guided_start_route_asks_a_question(tmp_path):
    _, c = _client(tmp_path)
    r = c.post("/guided/start", data={
        "idea": "RSI is low, buy", "symbol": "EURUSD", "timeframe": "H1"})
    assert r.status_code == 200
    body = r.json()
    assert body["needs_answers"] is True
    assert any("rsi_threshold" in q for q in body["questions"])
    # the remaining path (incl. the MT5 gate) is surfaced, not hidden
    assert any("11-stage" in step for step in body["remaining_after_python"])


def test_guided_validate_route_reports_failure_reason(tmp_path):
    _, c = _client(tmp_path)
    r = c.post("/guided/validate", data={"draft": "{}"})
    assert r.status_code == 200
    body = r.json()
    assert body["passed"] is False
    assert body["reason"]


def test_guided_validate_route_passes_a_valid_draft(tmp_path):
    _, c = _client(tmp_path)
    start = c.post("/guided/start", data={
        "idea": "EMA 10 crosses above EMA 30",
        "symbol": "EURUSD", "timeframe": "H1"}).json()
    r = c.post("/guided/validate",
               data={"draft": json.dumps(start["draft"])})
    assert r.json()["passed"] is True


def test_no_guided_route_transitions_a_strategy(tmp_path):
    # The guided endpoints only call the conversation engine; the API module's
    # guided handlers never wire a lifecycle transition.
    api_src = Path("python/mql5bot/api/main.py").read_text()
    assert "guided_start" in api_src and "guided_validate" in api_src
    # locate the guided handlers and assert neither calls store.transition
    lo = api_src.index("def guided_start")
    hi = api_src.index("__all__")
    guided_block = api_src[lo:hi]
    assert ".transition(" not in guided_block
    assert "human_approval=True" not in guided_block
