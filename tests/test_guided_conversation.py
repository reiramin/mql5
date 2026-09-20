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
from mql5bot.factory.conversation import GuidedConversation, acceptance_token
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
    # accept the (empty) draft so validation actually runs, then it is
    # schema-invalid — the reason names why
    v = conv.validate({}, accepted_token=acceptance_token({}))
    assert v.passed is False
    assert "SCHEMA_INVALID" in v.reason or "SchemaInvalid" in v.reason


def test_valid_draft_passes_schema_check_only():
    conv = GuidedConversation(interpreter="template")
    step = conv.start("EMA 10 crosses above EMA 30",
                      symbol="EURUSD", timeframe="H1")
    v = conv.validate(step.draft, accepted_token=step.acceptance_token)
    assert v.passed is True


def test_pass_headline_does_not_claim_the_strategy_was_tested():
    # A schema pass must not read, in EITHER language, as "it was tested".
    conv = GuidedConversation(interpreter="template")
    step = conv.start("EMA 10 crosses above EMA 30",
                      symbol="EURUSD", timeframe="H1")
    headline = conv.validate(
        step.draft, accepted_token=step.acceptance_token).verdict_fa
    # the headline itself names the scope (schema/structure only)
    assert "SCHEMA" in headline
    assert "structure only" in headline
    # and it explicitly says the strategy was NOT tested, in both languages
    assert "NOT been tested" in headline
    assert "آزمایش نشده" in headline          # Persian: "has not been tested"
    # it must NOT overstate — no unqualified "Python validation PASSED",
    # no bare Persian "اعتبارسنجی پایتون گذشت" (Python validation passed)
    assert "Python validation PASSED" not in headline
    assert "اعتبارسنجی پایتون گذشت" not in headline
    # "tested"/"validated" never appear as an unqualified positive claim
    lowered = headline.lower()
    assert "tested" not in lowered.replace("not been tested", "")
    assert "validated" not in lowered.replace("schema-validated", "")


def test_remaining_steps_list_research_validation_and_the_mt5_gate():
    conv = GuidedConversation()
    steps = conv.validate({}).remaining_after_schema
    joined = " ".join(steps)
    # (a) the Python research validation — backtest/robustness/OOS, not run
    assert any("research validation" in s for s in steps)
    assert "backtest" in joined
    assert "NOT run here" in joined
    # (b) the owner-run 11-stage MT5 gate
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
    assert any("11-stage" in step for step in body["remaining_after_schema"])


def test_guided_validate_route_passes_a_valid_draft(tmp_path):
    _, c = _client(tmp_path)
    start = c.post("/guided/start", data={
        "idea": "EMA 10 crosses above EMA 30",
        "symbol": "EURUSD", "timeframe": "H1"}).json()
    r = c.post("/guided/validate", data={
        "draft": json.dumps(start["draft"]),
        "accepted_token": start["acceptance_token"]})
    assert r.json()["passed"] is True


# -- acceptance of the restatement is REQUIRED -------------------------------

def test_no_ambiguity_draft_cannot_be_validated_without_acceptance():
    conv = GuidedConversation(interpreter="template")
    step = conv.start("EMA 10 crosses above EMA 30, stop 2 ATR, take profit 3 ATR",
                      symbol="EURUSD", timeframe="H1")
    # a well-formed draft with NO open questions — but still not agreed to
    assert step.needs_answers is False
    assert step.ambiguities == []
    v = conv.validate(step.draft)                 # no accepted_token -> REFUSED
    assert v.passed is False
    assert "not accepted" in v.reason
    # accepting it (the token the owner was shown) then lets validation run
    ok = conv.validate(step.draft, accepted_token=step.acceptance_token)
    assert ok.passed is True


def test_acceptance_of_one_restatement_does_not_validate_a_different_draft():
    conv = GuidedConversation(interpreter="template")
    a = conv.start("EMA 10 crosses above EMA 30",
                   symbol="EURUSD", timeframe="H1")
    b = conv.start("EMA 5 crosses above EMA 20",
                   symbol="EURUSD", timeframe="H1")
    assert a.acceptance_token != b.acceptance_token
    # the token accepted for draft A must NOT validate draft B
    v = conv.validate(b.draft, accepted_token=a.acceptance_token)
    assert v.passed is False
    assert "not accepted" in v.reason


def test_refusal_names_the_reason_in_both_languages():
    conv = GuidedConversation(interpreter="template")
    step = conv.start("EMA 10 crosses above EMA 30",
                      symbol="EURUSD", timeframe="H1")
    v = conv.validate(step.draft)                 # unaccepted -> refusal
    assert v.passed is False
    assert "RESTATEMENT NOT CONFIRMED" in v.verdict_fa      # English
    assert "بازنویسی تأیید نشده است" in v.verdict_fa        # Persian


def test_guided_validate_route_refuses_an_unaccepted_draft(tmp_path):
    _, c = _client(tmp_path)
    start = c.post("/guided/start", data={
        "idea": "EMA 10 crosses above EMA 30",
        "symbol": "EURUSD", "timeframe": "H1"}).json()
    # post the draft WITHOUT the acceptance token
    r = c.post("/guided/validate",
               data={"draft": json.dumps(start["draft"])})
    assert r.status_code == 200
    body = r.json()
    assert body["passed"] is False
    assert "not accepted" in body["reason"]
    assert "RESTATEMENT NOT CONFIRMED" in body["verdict_fa"]


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
