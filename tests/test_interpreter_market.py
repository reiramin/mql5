"""Interpreter market-resolution regression tests (mission §6).

The interpreter MUST NOT guess ``market.symbol`` / ``market.timeframe``
from the description.  Before this fix ``factory/interpreter.py`` wrote a
hard-coded ``{"symbol": "EURUSD", "timeframe": "H1"}`` into every draft —
a silent guess that would become a *real* traded market the moment a
human bumped the draft to an executable version.  These tests pin the
correct fail-closed behaviour:

* no implicit symbol / no implicit timeframe;
* an unresolved market is a VISIBLE ambiguity;
* the draft parses (so it can be shown/stored) but is NEVER executable;
* an EXECUTABLE version (> 0) with an unresolved market is REJECTED by
  the schema (fail-closed) — a guess can never reach a runtime;
* an EXPLICIT owner-chosen market is preserved verbatim.

Every assertion here fails under the old EURUSD/H1-guessing code.
"""

from __future__ import annotations

import json

import pytest
from mql5bot.dsl import parse_spec
from mql5bot.dsl.errors import SchemaInvalid
from mql5bot.factory.interpreter import TemplateInterpreter
from mql5bot.factory.providers import ResearchMaterial

# recognized EN description WITH SL/TP (no missing-SL ambiguity), so the
# ONLY residual ambiguity is the market — isolating the §6 behaviour.
EN = ("Buy when EMA20 crosses EMA50 upward and RSI is above 55. "
      "SL 1.5 ATR, TP 3 ATR.")


def _interpret(text=EN, **kw):
    return TemplateInterpreter().interpret(
        ResearchMaterial("USER_TEXT", "t", text), **kw)


def test_no_implicit_symbol_or_timeframe():
    """The draft market is UNRESOLVED (empty), never a guessed default."""
    r = _interpret()
    assert r.draft["market"] == {"symbol": "", "timeframe": ""}
    # the old guess must not appear anywhere in the draft
    assert "EURUSD" not in json.dumps(r.draft)
    assert "H1" not in json.dumps(r.draft)


def test_unresolved_market_is_a_visible_ambiguity():
    r = _interpret()
    kinds = {a.get("kind") for a in r.ambiguities}
    names = {a.get("name") for a in r.ambiguities}
    assert "UNRESOLVED_MARKET" in kinds
    assert "market" in names
    assert r.needs_review is True


def test_unresolved_draft_parses_but_is_not_executable():
    """A draft (version 0) parses for review/storage but never runs, and
    the unresolved market surfaces as a blocking ambiguity in the spec."""
    r = _interpret()
    spec = parse_spec(dict(r.draft, version=0))
    assert not spec.executable
    amb_names = {a["name"] for a in spec.ambiguities}
    assert {"market_symbol", "market_timeframe"} <= amb_names


def test_executable_version_with_unresolved_market_is_rejected():
    """Fail-closed: an executable version (> 0) can NEVER carry an
    unresolved market — the schema rejects it outright, so a guessed or
    absent market can never reach a runtime."""
    r = _interpret()
    with pytest.raises(SchemaInvalid):
        parse_spec(dict(r.draft, strategy_id="mkt_test", version=1))


def test_explicit_market_is_preserved_and_executable():
    """An EXPLICIT owner-chosen market is preserved verbatim, clears the
    market ambiguity, and yields an executable version."""
    mk = {"symbol": "XAUUSD", "timeframe": "M15"}
    r = _interpret(market=mk)
    assert r.draft["market"] == mk
    assert all(a.get("kind") != "UNRESOLVED_MARKET" for a in r.ambiguities)
    spec = parse_spec(dict(r.draft, strategy_id="mkt_test", version=1))
    assert spec.executable
    assert spec.market.symbol == "XAUUSD"
    assert spec.market.timeframe == "M15"


def test_partial_market_stays_unresolved():
    """Supplying only the symbol (no timeframe) is still UNRESOLVED — the
    interpreter never fills the missing half."""
    r = _interpret(market={"symbol": "EURUSD"})
    assert r.draft["market"] == {"symbol": "EURUSD", "timeframe": ""}
    assert any(a.get("kind") == "UNRESOLVED_MARKET" for a in r.ambiguities)
    with pytest.raises(SchemaInvalid):
        parse_spec(dict(r.draft, strategy_id="mkt_test", version=1))


def test_unrecognized_text_also_has_unresolved_market():
    """Even when no pattern is recognized, market stays unresolved (never
    a guessed EURUSD/H1 placeholder)."""
    r = _interpret("this is not a strategy description at all")
    assert r.draft["market"] == {"symbol": "", "timeframe": ""}
    assert any(a.get("kind") == "UNRESOLVED_MARKET" for a in r.ambiguities)
