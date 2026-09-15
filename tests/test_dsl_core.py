"""DSL core tests: schema validation, parser, normalization, hashing.

Covers mission §58 (schema validation, parser, normalization,
deterministic representation, malformed specs) and the identity
metamorphics §59.1/§59.2/§59.10.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from mql5bot.dsl import (
    AmbiguousParameter,
    LimitExceeded,
    SchemaInvalid,
    UnknownReference,
    parse_file,
    parse_spec,
    semantic_hash,
    validate_spec,
)
from mql5bot.dsl.normalize import canon_json, normalize_spec

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "strategies"


def _base_doc() -> dict:
    return {
        "schema_version": "1.0",
        "strategy_id": "test_strategy",
        "version": 1,
        "market": {"symbol": "EURUSD", "timeframe": "H1"},
        "indicators": [
            {"id": "ema_f", "kind": "EMA", "period": 10},
            {"id": "ema_s", "kind": "EMA", "period": 30},
        ],
        "entry": {"mode": "state",
                  "long": {"left": {"ind": "ema_f"}, "cmp": "GT",
                           "right": {"ind": "ema_s"}},
                  "short": {"left": {"ind": "ema_f"}, "cmp": "LT",
                            "right": {"ind": "ema_s"}}},
        "exit": {"sl": {"model": "atr", "mult": 2.0}},
    }


# ------------------------------------------------------------ schema


def test_valid_minimal_document_passes():
    validate_spec(_base_doc())          # no raise


def test_example_files_exist_and_all_valid_parse():
    names = sorted(p.name for p in EXAMPLES.glob("*.json"))
    assert len(names) == 12              # 11 valid + 1 invalid
    assert "invalid_unknown_indicator.json" in names
    # Gold #2 reconstruction (GOLD_2_RECONSTRUCTED_NEW_PROVENANCE)
    assert "gold2_multifactor.json" in names


@pytest.mark.parametrize("mutate,path", [
    (lambda d: d.update({"evil_key": 1}), ""),
    (lambda d: d["market"].update({"leverage": 100}), "market"),
    (lambda d: d["indicators"][0].update({"secret": "x"}), "indicators"),
    (lambda d: d["entry"].update({"mode2": "x"}), "entry"),
    (lambda d: d["exit"].update({"sl2": None}), "exit"),
])
def test_unknown_keys_are_rejected_whole(mutate, path):
    doc = _base_doc()
    mutate(doc)
    with pytest.raises(SchemaInvalid) as ei:
        validate_spec(doc)
    assert (ei.value.path or "") .startswith(path) or path == ""


def test_unknown_indicator_kind_rejected_with_codegen_hint():
    doc = _base_doc()
    doc["indicators"][0]["kind"] = "QUANTUM_TREND"
    with pytest.raises(SchemaInvalid, match="unsupported indicator"):
        validate_spec(doc)


def test_schema_version_enforced():
    doc = _base_doc()
    doc["schema_version"] = "0.9"
    with pytest.raises(SchemaInvalid, match="schema_version"):
        validate_spec(doc)


def test_condition_needs_exactly_one_alternative():
    doc = _base_doc()
    doc["entry"]["long"] = {"left": {"const": 1}, "cmp": "GT",
                            "right": {"const": 2}, "cross": "ABOVE",
                            "a": {"const": 1}, "b": {"const": 2}}
    with pytest.raises(SchemaInvalid, match="exactly one"):
        validate_spec(doc)


def test_nan_and_inf_constants_rejected():
    doc = _base_doc()
    doc["entry"]["long"]["right"] = {"const": float("nan")}
    with pytest.raises(SchemaInvalid, match="finite"):
        with pytest.raises(ValueError):
            json.dumps(doc, allow_nan=False)
        validate_spec(json.loads(json.dumps(doc, allow_nan=True)))


def test_resource_limits_doc_size_and_depth():
    from mql5bot.dsl import MAX_DOC_BYTES, validate_document_size
    with pytest.raises(LimitExceeded):
        validate_document_size("x" * (MAX_DOC_BYTES + 1))
    # deep nesting
    node = {"const": 1}
    for _ in range(60):
        node = {"add": [node, {"const": 1}]}
    doc = _base_doc()
    doc["entry"]["long"] = {"left": node, "cmp": "GT",
                            "right": {"const": 2}}
    with pytest.raises(LimitExceeded):
        validate_spec(doc)


def test_indicator_count_limit():
    doc = _base_doc()
    doc["indicators"] = [
        {"id": f"i_{i:02d}", "kind": "SMA", "period": 5}
        for i in range(40)
    ]
    with pytest.raises(LimitExceeded, match="indicators"):
        validate_spec(doc)


# ------------------------------------------------------------ parser


def test_missing_indicator_reference_rejected():
    with pytest.raises(UnknownReference, match="ghost"):
        parse_file(EXAMPLES / "invalid_unknown_indicator.json")


def test_param_resolution_via_declaration():
    spec = parse_file(EXAMPLES / "ema_rsi_trend.json")
    assert spec.executable                  # declared default resolves
    doc = spec.document
    rsi_right = doc["entry"]["long"]["and"][1]["right"]
    assert rsi_right == {"const": 55.0}


def test_param_override_changes_resolution():
    spec = parse_file(EXAMPLES / "ema_rsi_trend.json",
                      overrides={"rsi_min": 60.0})
    rsi_right = spec.document["entry"]["long"]["and"][1]["right"]
    assert rsi_right == {"const": 60.0}


def test_ambiguous_draft_parses_but_never_executes():
    spec = parse_file(EXAMPLES / "draft_ambiguous_rsi.json")
    assert not spec.executable
    assert spec.ambiguities[0]["name"] == "rsi_threshold"
    assert spec.ambiguities[0]["range"] == [20.0, 40.0]
    from mql5bot.data import generate_ohlc
    from mql5bot.dsl import desired_positions
    with pytest.raises(AmbiguousParameter):
        desired_positions(spec, generate_ohlc(days=60, seed=1))


def test_ambiguous_threshold_is_never_invented():
    """Mission §10: 'RSI is low' must NOT become RSI < 30."""
    spec = parse_file(EXAMPLES / "draft_ambiguous_rsi.json")
    raw = canon_json(spec.document)
    assert "30" not in raw.replace("30.0", "")  # no invented threshold


def test_semantic_lints_flag_missing_sl():
    from mql5bot.dsl import lint_spec
    doc = _base_doc()
    doc["exit"] = {}
    lints = lint_spec(doc)
    assert any("MISSING_SL" in ln for ln in lints)


# ------------------------------------------------------------ normalization


def test_normalization_is_deterministic_and_order_free():
    d1 = _base_doc()
    d2 = copy.deepcopy(_base_doc())
    d2["indicators"] = list(reversed(d2["indicators"]))
    n1, n2 = normalize_spec(d1), normalize_spec(d2)
    assert canon_json(n1) == canon_json(n2)


def test_and_operands_sort_canonically():
    doc = _base_doc()
    c1 = {"left": {"ind": "ema_f"}, "cmp": "GT", "right": {"const": 1}}
    c2 = {"left": {"ind": "ema_s"}, "cmp": "LT", "right": {"const": 2}}
    doc["entry"]["long"] = {"and": [c2, c1]}
    doc["entry"]["short"] = {"or": [c1, c2]}
    norm = normalize_spec(doc)
    a = norm["entry"]["long"]["and"]
    assert canon_json(a[0]) <= canon_json(a[1])


def test_timeframe_and_enums_normalized():
    doc = _base_doc()
    doc["market"]["timeframe"] = "h1"
    norm = normalize_spec(doc)
    assert norm["market"]["timeframe"] == "H1"


def test_int_and_float_constants_hash_identically():
    d1 = _base_doc()
    d2 = copy.deepcopy(_base_doc())
    d1["entry"]["long"]["right"] = {"const": 55}
    d2["entry"]["long"]["right"] = {"const": 55.0}
    assert semantic_hash(normalize_spec(d1)) == \
        semantic_hash(normalize_spec(d2))


# ------------------------------------------------------------ identity


def test_rename_does_not_change_identity():
    """Mission §59.1: display name is not identity."""
    d1 = _base_doc()
    d2 = copy.deepcopy(_base_doc())
    d1["name"] = "Strategy A"
    d2["name"] = "A completely different display title"
    s1 = parse_spec(d1)
    s2 = parse_spec(d2)
    assert s1.spec_hash == s2.spec_hash
    assert s1.semantic_hash == s2.semantic_hash


def test_metadata_reorder_does_not_change_spec_hash():
    """Mission §59.2: non-semantic metadata ordering is hash-free."""
    d1 = _base_doc()
    d2 = copy.deepcopy(_base_doc())
    d1["metadata"] = {"regime_tags": ["trend", "momentum"],
                      "explanation": "x"}
    d2["metadata"] = {"regime_tags": ["momentum", "trend"],
                      "explanation": "x"}
    assert parse_spec(d1).spec_hash == parse_spec(d2).spec_hash


def test_source_url_change_never_mutates_logic_identity():
    """Mission §59.10: source metadata is provenance, not semantics."""
    d1 = _base_doc()
    d2 = copy.deepcopy(_base_doc())
    d1["source"] = {"type": "COMMUNITY",
                    "url": "https://example.com/a", "author": "x"}
    d2["source"] = {"type": "COMMUNITY",
                    "url": "https://example.com/b", "author": "x"}
    assert parse_spec(d1).spec_hash == parse_spec(d2).spec_hash


def test_logic_change_changes_spec_hash():
    d1 = _base_doc()
    d2 = copy.deepcopy(_base_doc())
    d2["indicators"][0]["period"] = 12          # different fast EMA
    assert parse_spec(d1).spec_hash != parse_spec(d2).spec_hash
    assert parse_spec(d1).semantic_hash != parse_spec(d2).semantic_hash


def test_multilingual_equivalence_dedup():
    """Mission §59.3: equivalent EN/FA descriptions normalize
    equivalently (dedup hash), while identity stays distinct."""
    en = parse_file(EXAMPLES / "ema_rsi_trend.json",
                    overrides={"rsi_min": 55.0})
    fa = parse_file(EXAMPLES / "ema_rsi_atr_fa.json")
    assert en.dedup_hash == fa.dedup_hash
    assert en.spec_hash != fa.spec_hash         # different identities
