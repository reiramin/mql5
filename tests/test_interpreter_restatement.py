"""Restatement is DERIVED from the scrubbed draft (defects A + B).

The restatement is the human-review gate — a wrong restatement is worse than a
wrong draft, because the operator approves what they READ. Two invariants,
pinned here in English AND Persian on BOTH the template and the LLM path:

  A) the template path must not prepend a fixed "EMA crosses" sentence (or an
     EMA assumption) to a draft that has no EMA in it;
  B) the LLM path must not pass the provider's own restatement through — a
     threshold the grounding stripped must never be restated as fact.

The shared guarantee: a NUMBER appears in the restatement only if it is
present in the draft, and EVERY element the draft contains (each entry
condition, the stop, the target) is mentioned.
"""

from __future__ import annotations

import json
import re

from mql5bot.factory.interpreter import (
    LlmInterpreter,
    TemplateInterpreter,
    restate_from_draft,
)
from mql5bot.factory.providers import ResearchMaterial

MARKET = {"symbol": "EURUSD", "timeframe": "H1"}
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _numbers_in(text: str) -> set[float]:
    return {float(m.group(0)) for m in _NUM.finditer(text)}


def _draft_numbers(obj) -> set[float]:
    """Every numeric JSON value in the draft (bools/strings excluded)."""
    out: set[float] = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= _draft_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _draft_numbers(v)
    return out


def _assert_no_ungrounded_number(restatement: str, draft: dict) -> None:
    draft_nums = _draft_numbers(draft)
    for n in _numbers_in(restatement):
        assert any(abs(n - d) < 1e-9 for d in draft_nums), (
            f"restatement number {n} is NOT present in the draft: {restatement!r}")


def _model(payload: dict):
    def call(system: str, user: str) -> str:
        return json.dumps(payload, ensure_ascii=False)
    return call


# ---------------------------------------------------------------------------
# the shared function directly
# ---------------------------------------------------------------------------

def test_restate_from_draft_mentions_every_element_and_only_draft_numbers():
    draft = {
        "indicators": [
            {"id": "ema_f", "kind": "EMA", "period": 20},
            {"id": "ema_s", "kind": "EMA", "period": 50},
            {"id": "rsi_m", "kind": "RSI", "period": 14}],
        "entry": {"mode": "state", "long": {"and": [
            {"cross": "ABOVE", "a": {"ind": "ema_f"}, "b": {"ind": "ema_s"}},
            {"left": {"ind": "rsi_m"}, "cmp": "GT", "right": {"const": 55}}]},
            "short": {}},
        "exit": {"sl": {"model": "atr", "mult": 2},
                 "tp": {"model": "atr", "mult": 3}},
    }
    r = restate_from_draft(draft)
    # every element is named
    assert "EMA(20)" in r and "EMA(50)" in r and "RSI(14)" in r
    assert "crosses above" in r
    assert "stop-loss at 2 ATR" in r and "take-profit at 3 ATR" in r
    _assert_no_ungrounded_number(r, draft)


def test_restate_from_draft_words_an_ambiguous_threshold_never_a_number():
    draft = {
        "indicators": [{"id": "rsi_m", "kind": "RSI", "period": 14}],
        "entry": {"mode": "state",
                  "long": {"left": {"ind": "rsi_m"}, "cmp": "LT",
                           "right": {"ambiguous": "rsi_threshold"}},
                  "short": {}},
        "exit": {},
    }
    r = restate_from_draft(draft)
    assert "RSI(14)" in r
    assert "threshold that must be supplied" in r
    assert "30" not in r  # a scrubbed threshold is never numbered
    _assert_no_ungrounded_number(r, draft)


def test_restate_from_draft_placeholder_when_empty():
    draft = {"indicators": [], "entry": {"long": {}, "short": {}}, "exit": {}}
    assert "placeholder" in restate_from_draft(draft)


# ---------------------------------------------------------------------------
# DEFECT A — template path never prepends EMA to a non-EMA draft
# ---------------------------------------------------------------------------

def test_template_rsi_only_english_has_no_ema_in_restatement():
    r = TemplateInterpreter().interpret(
        ResearchMaterial("USER_TEXT", "t", "Buy when RSI is low"),
        market=MARKET)
    assert "EMA" not in r.restatement
    assert "crosses" not in r.restatement
    assert "RSI" in r.restatement
    # and no EMA assumption is attached to an RSI-only draft
    assert not any("EMA-cross" in a for a in r.assumptions)
    _assert_no_ungrounded_number(r.restatement, r.draft)


def test_template_rsi_only_persian_has_no_ema_in_restatement():
    # "RSI is low, buy" in Persian — defect A's own example shape
    r = TemplateInterpreter().interpret(
        ResearchMaterial("USER_TEXT", "fa", "RSI پایینه بخر"), market=MARKET)
    assert "EMA" not in r.restatement and "crosses" not in r.restatement
    assert "RSI" in r.restatement
    assert not any("EMA-cross" in a for a in r.assumptions)
    _assert_no_ungrounded_number(r.restatement, r.draft)


def test_template_ema_rsi_sltp_mentions_every_element_english():
    text = ("Buy when EMA20 crosses EMA50 upward and RSI is above 55. "
            "SL 2 ATR, TP 3 ATR.")
    r = TemplateInterpreter().interpret(
        ResearchMaterial("USER_TEXT", "t", text), market=MARKET)
    assert "EMA(20)" in r.restatement and "EMA(50)" in r.restatement
    assert "RSI(14)" in r.restatement
    # the stop and target were missing before — now both are named
    assert "stop-loss at 2 ATR" in r.restatement
    assert "take-profit at 3 ATR" in r.restatement
    _assert_no_ungrounded_number(r.restatement, r.draft)


# ---------------------------------------------------------------------------
# DEFECT B — LLM path never restates the provider's stripped number as fact
# ---------------------------------------------------------------------------

def test_llm_cheating_restatement_is_replaced_by_draft_derived_english():
    # the provider CHEATS: it both invents const 30 AND restates "below 30"
    cheat = _model({
        "restatement": "Buy when RSI is below 30.",
        "indicators": [{"id": "rsi_m", "kind": "RSI", "period": 14}],
        "long": {"left": {"ind": "rsi_m"}, "cmp": "LT",
                 "right": {"const": 30}},
        "short": {}, "exit": {}, "ambiguities": [], "unsupported": []})
    r = LlmInterpreter(cheat).interpret(
        ResearchMaterial("USER_TEXT", "t", "Trade when RSI is low"),
        market=MARKET)
    # the one number the system refused is NOT shown to the operator as fact
    assert "30" not in r.restatement
    assert "30" not in json.dumps(r.draft)
    assert "threshold that must be supplied" in r.restatement
    _assert_no_ungrounded_number(r.restatement, r.draft)


def test_llm_cheating_restatement_is_replaced_by_draft_derived_persian():
    cheat = _model({
        "restatement": "خرید وقتی RSI زیر ۳۰ باشد.",
        "indicators": [{"id": "rsi_m", "kind": "RSI", "period": 14}],
        "long": {"left": {"ind": "rsi_m"}, "cmp": "LT",
                 "right": {"const": 30}},
        "short": {}, "exit": {}, "ambiguities": [], "unsupported": []})
    r = LlmInterpreter(cheat).interpret(
        ResearchMaterial("USER_TEXT", "fa", "وقتی RSI پایین است بخر"),
        market=MARKET)
    assert "30" not in r.restatement and "۳۰" not in r.restatement
    assert "threshold that must be supplied" in r.restatement
    _assert_no_ungrounded_number(r.restatement, r.draft)


def test_llm_grounded_restatement_names_every_element_and_only_draft_numbers():
    payload = {
        "restatement": "totally unrelated provider prose that we must ignore",
        "indicators": [
            {"id": "ema_f", "kind": "EMA", "period": 20, "applied": "close"},
            {"id": "ema_s", "kind": "EMA", "period": 50, "applied": "close"},
            {"id": "rsi_m", "kind": "RSI", "period": 14, "applied": "close"}],
        "long": {"and": [
            {"cross": "ABOVE", "a": {"ind": "ema_f"}, "b": {"ind": "ema_s"}},
            {"left": {"ind": "rsi_m"}, "cmp": "GT", "right": {"const": 55}}]},
        "short": {"cross": "BELOW", "a": {"ind": "ema_f"}, "b": {"ind": "ema_s"}},
        "exit": {"sl": {"model": "atr", "mult": 1.5},
                 "tp": {"model": "atr", "mult": 3}},
        "ambiguities": [], "unsupported": []}
    text = ("Buy when EMA20 crosses EMA50 upward and RSI is above 55. "
            "SL 1.5 ATR, TP 3 ATR.")
    r = LlmInterpreter(_model(payload)).interpret(
        ResearchMaterial("USER_TEXT", "t", text), market=MARKET)
    # the provider's prose is gone; the restatement is the draft's own content
    assert "unrelated provider prose" not in r.restatement
    assert "EMA(20)" in r.restatement and "EMA(50)" in r.restatement
    assert "RSI(14)" in r.restatement
    assert "stop-loss at 1.5 ATR" in r.restatement
    assert "take-profit at 3 ATR" in r.restatement
    _assert_no_ungrounded_number(r.restatement, r.draft)
