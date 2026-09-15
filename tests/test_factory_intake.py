"""Factory intake tests (mission §9-§14, §22/§25/§44/§48, §59.3/.10).

Covers: provider paste-first safety, deterministic EN/FA interpretation
parity, ambiguity handling ("RSI is low" stays ambiguous), AUTHOR_CLAIM
separation, campaign manifests with selection-bias accounting, and
budgeted parameter mutations as children.
"""

from __future__ import annotations

import json

import pytest
from mql5bot.dsl import parse_spec
from mql5bot.factory.claims import extract_claims
from mql5bot.factory.interpreter import TemplateInterpreter
from mql5bot.factory.providers import ResearchMaterial, get_provider
from mql5bot.factory.research import Campaign, parameter_mutations

EN = ("Buy when EMA20 crosses EMA50 upward and RSI is above 55. "
      "SL 1.5 ATR, TP 3 ATR.")
FA = ("این استراتژی را بساز: وقتی EMA20 بالای EMA50 کراس کرد و RSI "
      "بالای ۵۵ بود خرید کن، حد ضرر 1.5 ATR و تارگت 3 ATR.")


# ------------------------------------------------------------ providers


def test_user_submission_provider_always_available():
    r = get_provider("user_submission").fetch("Buy when EMA5 crosses EMA20 upward")
    assert r.status == "OK"
    assert r.material.source_type == "USER_TEXT"


def test_url_providers_refuse_or_report_unavailable_never_fabricate():
    for name in ("tradingview", "article", "research_paper"):
        r = get_provider(name).fetch("https://example.com/x")
        assert r.status in {"UNAVAILABLE", "REFUSED"}
        assert r.material is None
        assert "paste" in r.why.lower() or "disabled" in r.why.lower()


def test_unknown_provider_named_not_silent():
    with pytest.raises(KeyError):
        get_provider("twitter_scraper_9000")


def test_oversized_submission_refused():
    r = get_provider("user_submission").fetch("x" * 200_000)
    assert r.status == "REFUSED"


# ------------------------------------------------------------ interpreter


def test_en_fa_normalize_to_equivalent_semantics():
    """Mission §11/§59.3: equivalent descriptions normalize
    equivalently (dedup hash of the parsed drafts)."""
    interp = TemplateInterpreter()
    r_en = interp.interpret(ResearchMaterial("USER_TEXT", "t", EN))
    r_fa = interp.interpret(ResearchMaterial("USER_TEXT", "t", FA))
    d1 = parse_spec(dict(r_en.draft, strategy_id="same_id", version=1))
    d2 = parse_spec(dict(r_fa.draft, strategy_id="same_id", version=1))
    assert d1.dedup_hash == d2.dedup_hash
    assert d1.semantic_hash == d2.semantic_hash


def test_persian_digits_normalize():
    interp = TemplateInterpreter()
    r = interp.interpret(ResearchMaterial("USER_TEXT", "t", FA))
    rsi = next(i for i in r.draft["indicators"]
               if i["id"] == "rsi_m")
    assert rsi["period"] == 14
    thr = r.draft["entry"]["long"]["and"][1]["right"]
    assert thr == {"const": 55.0}          # ۵۵ → 55


def test_rsi_low_never_becomes_rsi_30():
    """Mission §10: ambiguity is reported, never resolved by guess."""
    interp = TemplateInterpreter()
    r = interp.interpret(ResearchMaterial(
        "USER_TEXT", "rsi low", "Trade when RSI is low"))
    names = [a["name"] for a in r.ambiguities]
    assert "rsi_threshold" in names
    assert "30" not in json.dumps(r.draft)     # no invented threshold
    spec = parse_spec(dict(r.draft, version=0))
    assert not spec.executable


def test_missing_sl_is_an_explicit_ambiguity():
    interp = TemplateInterpreter()
    r = interp.interpret(ResearchMaterial(
        "USER_TEXT", "no sl", "Buy when EMA10 crosses EMA30 upward"))
    kinds = [a["kind"] for a in r.ambiguities]
    assert "MISSING_SL" in kinds


def test_interpretation_is_deterministic():
    interp = TemplateInterpreter()
    m = ResearchMaterial("USER_TEXT", "t", EN)
    r1, r2 = interp.interpret(m), interp.interpret(m)
    assert json.dumps(r1.draft, sort_keys=True) == \
        json.dumps(r2.draft, sort_keys=True)


def test_autonomous_research_mode_yields_ranges_not_values():
    interp = TemplateInterpreter()
    r = interp.interpret(ResearchMaterial(
        "USER_TEXT", "low", "Trade when RSI is low"),
        autonomous_research=True)
    amb = next(a for a in r.ambiguities
               if a["name"] == "rsi_threshold")
    assert amb["range"] == [10.0, 40.0]        # explicit research range


# ------------------------------------------------------------ claims


def test_claim_extraction_deterministic_and_separated():
    text = ("The author claims a win rate of 82%, Sharpe 2.1, max "
            "drawdown 15%, CAGR 40% over 500 trades with PF 1.9.")
    claims = extract_claims(text)
    by = {c["metric"]: c for c in claims}
    assert by["win_rate"]["value"] == pytest.approx(0.82)
    assert by["sharpe"]["value"] == pytest.approx(2.1)
    assert by["max_drawdown"]["value"] == pytest.approx(0.15)
    assert by["cagr"]["value"] == pytest.approx(0.40)  # ratio
    assert by["trades"]["value"] == 500.0
    assert by["profit_factor"]["value"] == pytest.approx(1.9)
    assert all(c["note"].startswith("AUTHOR_CLAIM") for c in claims)


def test_no_claims_in_silent_text():
    assert extract_claims("Buy when EMA5 crosses EMA20.") == []


# ------------------------------------------------------------ campaigns


def _campaign() -> Campaign:
    return Campaign(
        campaign_id="camp-1", parent_strategy_id="parent",
        parent_version=1,
        search_space={"max_candidates": 5,
                      "grid": {"fast": [10, 12, 15]}},
        data_version="synthetic-2024H1", data_timestamps="2024-01..06",
        cost_model="costs-1.0", broker_assumptions="specs.SYNTH",
        methodology="walk-forward + CPCV/PBO + MC",
        gate_versions=["gates-1.0.0"], code_commit="HEAD",
        dsl_version="1.0", random_seed=7,
        created_at="2026-09-06T00:00:00+00:00")


def test_campaign_manifest_records_budget_and_selection_warning():
    c = _campaign()
    assert "research_selection_bias_warning" not in c.manifest()
    interp = TemplateInterpreter()
    m = interp.interpret(ResearchMaterial("USER_TEXT", "t", EN))
    for note, period in (("fast=18", 18), ("fast=25", 25)):
        doc = json.loads(json.dumps(m.draft))
        doc["indicators"][0]["period"] = period
        doc["strategy_id"] = f"child_{period}"
        doc["version"] = 1
        c.register_candidate(parse_spec(doc), mutation_note=note)
    man = c.manifest()
    assert man["candidate_count"] == 2
    assert man["mutation_count"] == 2
    assert "research_selection_bias_warning" in man
    assert man["n_trials_for_dsr"] == 2
    c.select("child_18", "highest WFE in-campaign")
    man = c.manifest()
    assert man["selected_candidate"]["strategy_id"] == "child_18"
    assert len(c.manifest_hash()) == 64       # sha256 hex


def test_campaign_manifest_hash_is_stable_and_sensitive():
    c1, c2 = _campaign(), _campaign()
    assert c1.manifest_hash() == c2.manifest_hash()
    c1.register_candidate(parse_spec(dict(
        TemplateInterpreter().interpret(
            ResearchMaterial("USER_TEXT", "t", EN)).draft,
        strategy_id="cand_x", version=1)))
    assert c1.manifest_hash() != c2.manifest_hash()


def test_campaign_budget_is_enforced():
    c = _campaign()
    m = TemplateInterpreter().interpret(
        ResearchMaterial("USER_TEXT", "t", EN))
    for i in range(5):
        doc = dict(m.draft, strategy_id=f"cand_{i}", version=1)
        c.register_candidate(parse_spec(doc))
    with pytest.raises(ValueError, match="budget"):
        c.register_candidate(parse_spec(dict(m.draft,
                                             strategy_id="cand_9",
                                             version=1)))


def test_mutations_are_children_with_new_docs_never_parent_edits():
    interp = TemplateInterpreter()
    r = interp.interpret(ResearchMaterial("USER_TEXT", "t", EN))
    parent = parse_spec(dict(r.draft, strategy_id="p_base", version=1))
    muts = parameter_mutations(parent, {"rsi_min": [50, 60],
                                        "period": [10, 25]},
                               max_variants=10)
    # rsi_min resolves to const 55 in the parent → not a declared param
    # → only the indicator-period axis mutates
    assert all(m["mutation_note"].startswith("period=") for m in muts)
    assert len(muts) == 2
    for m in muts:
        assert m["document"]["version"] == 0
        assert parent.document["indicators"][0]["period"] == 20
    assert [m["mutation_note"] for m in muts] == \
        ["period=10", "period=25"]


def test_mutation_of_unknown_param_is_honest_noop():
    interp = TemplateInterpreter()
    r = interp.interpret(ResearchMaterial("USER_TEXT", "t", EN))
    parent = parse_spec(dict(r.draft, strategy_id="p_base", version=1))
    assert parameter_mutations(parent, {"no_such": [1, 2]}) == []
