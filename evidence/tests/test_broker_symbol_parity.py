"""AEGIS Phase 3 — broker/symbol parity machinery.

Pins the FIELD MAP (every mandated broker fact has a named owner-export
field, a Python SymbolSpec side or an explicit runtime-authority marker, and
a tolerance), the strict fail-fast export schema, the never-invent rule (no
owner export ⇒ PENDING, no fabricated numbers anywhere), the independent
tick-value denomination witness, and behavioural sizer parity against exported
grids.
"""

import ast
import codecs
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "python"))

from broker_symbol_parity import (
    FIELD_MAP,
    REQUIRED_ASSET_CLASSES,
    assess_tick_value_denomination,
    asset_classes_covered,
    compare_symbol,
    load_owner_export,
    render_markdown,
    sizer_behaviour_parity,
    tick_value_denomination,
)

MQL5_EXPORT_SCRIPT = REPO / "mql5/Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5"


def _synthetic_export(tmp_path, **over):
    sym = {
        "name": "EURUSD", "digits": 5, "point": 1e-05, "tick_size": 1e-05,
        "tick_value_profit": 1.0, "tick_value_loss": 1.0,
        "contract_size": 100000.0, "volume_min": 0.01, "volume_max": 100.0,
        "volume_step": 0.01, "volume_limit": 0.0, "stops_level_points": 0,
        "freeze_level_points": 0, "currency_profit": "USD", "currency_base": "EUR",
        "currency_margin": "USD",
        "account_currency": "USD",
        "trade_mode": 4, "filling_mode_mask": 1, "order_mode": 0,
        "expiration_mode_mask": 15, "margin_initial": 0.0,
        "margin_maintenance": 0.0,
        "denomination_probe": {
            "ok": True, "reason": "", "last_error": 0,
            "source": "OrderCalcProfit", "calc_mode": 0,
            "account_leverage": 100.0, "account_currency": "USD",
            "currency_profit": "USD", "currency_margin": "USD", "currency_base": "EUR",
            "bid": 1.1, "ask": 1.1001, "tick_size_at_probe": 1e-5,
            "probe_ticks": 100, "lot_size": 1.0, "move": 0.001,
            "buy_loss_profit": -100.0, "sell_gain_profit": 100.0,
            "tick_value_loss_at_probe": 1.0, "tick_value_profit_at_probe": 1.0,
        },
    }
    sym.update(over)
    doc = {"schema": "mql5bot.broker_export/1", "symbol": sym}
    p = tmp_path / "EURUSD.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return doc


# ---------------------------------------------------------------------------
# field map completeness (the mandated parity surface)
# ---------------------------------------------------------------------------


def test_field_map_covers_every_mandated_broker_fact():
    mandated = {
        "tick_size", "tick_value_profit", "tick_value_loss", "contract_size",
        "volume_min", "volume_max", "volume_step", "volume_limit",
        "margin_initial", "margin_maintenance", "trade_mode",
        "filling_mode_mask", "order_mode", "stops_level_points",
        "freeze_level_points", "digits", "point", "currency_profit",
    }
    assert mandated <= set(FIELD_MAP)
    # every mapped field declares a tolerance and at least one consumer
    for _py, _mq, consumers, tag in FIELD_MAP.values():
        assert consumers, "field without consumer annotation"
        assert tag in ("exact", "rel1e-12", "rel1e-9")


def test_python_side_fields_exist_on_symbolspec():
    from mql5bot.symbolspec import SymbolSpec
    for py_attr, _mq, _c, _t in FIELD_MAP.values():
        if py_attr is not None:
            assert py_attr in SymbolSpec.__dataclass_fields__


def test_mql5_ssymbolspec_has_every_mapped_member():
    src = (REPO / "mql5/Include/Mql5Bot/SymbolSpec.mqh").read_text(encoding="utf-8")
    for field, (_py, mq_member, _c, _t) in FIELD_MAP.items():
        if mq_member is not None:
            assert mq_member in src, f"SSymbolSpec missing {mq_member} ({field})"


def test_export_script_dumps_every_mandated_field():
    src = MQL5_EXPORT_SCRIPT.read_text(encoding="utf-8")
    for field in FIELD_MAP:
        assert f'JsonQuote("{field}")' in src, f"export script misses {field}"
    # and an OrderCalcMargin probe so margin parity has runtime authority
    assert "OrderCalcMargin" in src


def test_exporter_denomination_ok_requires_both_calls_and_expected_signs():
    src = MQL5_EXPORT_SCRIPT.read_text(encoding="utf-8")
    assert "bool buyOk = OrderCalcProfit" in src
    assert "bool sellOk = OrderCalcProfit" in src
    assert "buyLossProfit < 0.0" in src
    assert "sellGainProfit > 0.0" in src
    assert re.search(
        r"denomOk\s*=\s*buyOk\s*&&\s*sellOk\s*&&"
        r"\s*buyLossProfit\s*<\s*0\.0\s*&&"
        r"\s*sellGainProfit\s*>\s*0\.0",
        src,
    ), "denomOk must be gated by both calls and both expected signs"
    assert "denomOk = sellOk" not in src


def test_required_asset_classes_pinned():
    assert REQUIRED_ASSET_CLASSES == ("FX", "METAL", "INDEX_CFD", "CRYPTO")


# ---------------------------------------------------------------------------
# strict schema — fail fast, never repair
# ---------------------------------------------------------------------------


def test_load_owner_export_rejects_wrong_schema_and_missing_fields(tmp_path):
    doc = _synthetic_export(tmp_path)
    doc["schema"] = "some/other"
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="wrong schema"):
        load_owner_export(p)

    doc2 = _synthetic_export(tmp_path)
    del doc2["symbol"]["tick_value_loss"]
    p2 = tmp_path / "bad2.json"
    p2.write_text(json.dumps(doc2), encoding="utf-8")
    with pytest.raises(ValueError, match="missing fields"):
        load_owner_export(p2)


def test_main_exit_code_fails_closed_when_nothing_verified(tmp_path, monkeypatch):
    """The machine gate (exit code) must FAIL CLOSED: an empty exports dir
    is NOT VERIFIED (exit 2), never a pass (old code returned 0 whenever no
    row was a MISMATCH, so 'nothing verified' read as PASS to CI)."""
    from broker_symbol_parity import main

    empty = tmp_path / "no_exports"
    empty.mkdir()
    monkeypatch.setattr(sys, "argv", [
        "broker_symbol_parity", "--exports", str(empty),
        "--out-json", str(tmp_path / "parity_report.json"),
    ])
    assert main() == 2


def test_missing_export_reports_pending_and_fabricates_nothing(capsys):
    from broker_symbol_parity import build_report
    exports, rows, coverage = build_report(
        REPO / "data/broker_exports/definitely-missing-dir")
    assert exports == [] and rows == []
    assert all(v.startswith("PENDING") for v in coverage.values())
    md = render_markdown([], [], coverage)
    assert "NOT VERIFIED" in md and "PENDING" in md
    out = capsys.readouterr()  # no exception; no invented numbers in doc
    assert out.err == ""


# ---------------------------------------------------------------------------
# comparison semantics
# ---------------------------------------------------------------------------


def test_compare_flags_mismatch_within_tolerance(tmp_path):
    from mql5bot.symbolspec import SymbolSpec
    model = SymbolSpec()  # defaults == the synthetic EURUSD export
    doc = _synthetic_export(tmp_path, tick_value_loss=1.0000000001)
    rows = compare_symbol(doc, model)
    by = {r.field: r for r in rows}
    assert by["tick_value_loss"].status == "MATCH"      # inside rel 1e-9
    doc_off = _synthetic_export(tmp_path, tick_value_loss=1.1)
    by_off = {r.field: r for r in compare_symbol(doc_off, model)}
    assert by_off["tick_value_loss"].status == "MISMATCH"  # outside tolerance
    doc2 = _synthetic_export(tmp_path, volume_step=0.001)
    by2 = {r.field: r for r in compare_symbol(doc2, model)}
    assert by2["volume_step"].status == "MISMATCH"      # exact-tolerance field


def test_runtime_authority_fields_marked_n_a_not_matched(tmp_path):
    doc = _synthetic_export(tmp_path)
    rows = compare_symbol(doc, None)
    by = {r.field: r for r in rows}
    for runtime_field in ("trade_mode", "filling_mode_mask", "margin_initial"):
        assert by[runtime_field].status == "N_A"
        assert "runtime" in by[runtime_field].python or \
            "runtime" in by[runtime_field].detail


def test_account_currency_denomination_uses_independent_ordercalcprofit_witness(tmp_path):
    doc = _synthetic_export(tmp_path)
    assessment = assess_tick_value_denomination(doc)
    assert assessment["verdict"] == "ACCOUNT_CURRENCY"
    assert tick_value_denomination(doc) == "ACCOUNT_CURRENCY"
    assert assessment["account_loss_tick"] == pytest.approx(1.0)
    assert assessment["account_profit_tick"] == pytest.approx(1.0)


def test_profit_currency_denomination_requires_separated_witness(tmp_path):
    doc = _synthetic_export(
        tmp_path,
        account_currency="EUR",
        denomination_probe={
            **_synthetic_export(tmp_path)["symbol"]["denomination_probe"],
            "account_currency": "EUR", "buy_loss_profit": -108.0,
            "sell_gain_profit": 108.0,
        },
    )
    assessment = assess_tick_value_denomination(doc)
    assert assessment["verdict"] == "PROFIT_CURRENCY"
    assert assessment["status"] == "MATCH"


def test_missing_failed_and_ambiguous_probes_are_pending(tmp_path):
    missing = _synthetic_export(tmp_path)
    del missing["symbol"]["denomination_probe"]
    assert tick_value_denomination(missing) == "UNVERIFIED"

    failed = _synthetic_export(tmp_path, denomination_probe={
        **_synthetic_export(tmp_path)["symbol"]["denomination_probe"],
        "ok": False, "reason": "OrderCalcProfit failed", "last_error": 4756,
    })
    assert assess_tick_value_denomination(failed)["status"] == "PENDING"

    ambiguous = _synthetic_export(tmp_path, denomination_probe={
        **_synthetic_export(tmp_path)["symbol"]["denomination_probe"],
        "buy_loss_profit": -100.5, "sell_gain_profit": 100.5,
    })
    assert assess_tick_value_denomination(ambiguous)["verdict"] == "UNVERIFIED"
    assert assess_tick_value_denomination(ambiguous)["status"] == "PENDING"


def test_sizer_behaviour_parity_on_exported_grid(tmp_path):
    doc = _synthetic_export(tmp_path, tick_size=0.25, point=0.01,
                            volume_step=0.1, volume_min=0.1,
                            denomination_probe={
                                **_synthetic_export(tmp_path)["symbol"]["denomination_probe"],
                                "tick_size_at_probe": 0.25, "move": 25.0,
                                "buy_loss_profit": -100.0, "sell_gain_profit": 100.0,
                            })
    rows = sizer_behaviour_parity(doc)
    by = {r.field: r for r in rows}
    # floor semantics: 0.1 + 0.4×0.1 = 0.14 → floored to 0.1 (never up)
    assert by["sizer.normalize_volume(floor)"].owner == pytest.approx(0.14)
    assert by["sizer.normalize_volume(floor)"].python == pytest.approx(0.1)
    assert by["sizer.loss_per_lot"].status == "MATCH"


def test_crypto_style_grid_non_point_tick_size(tmp_path):
    # index/crypto CFDs where tick_size is a multiple of point — the sizer
    # must use tick_size (not digits/point) for rounding
    doc = _synthetic_export(tmp_path, name="BTCUSD", digits=2, point=0.01,
                            tick_size=0.5, contract_size=1.0,
                            tick_value_loss=0.5,
                            denomination_probe={
                                **_synthetic_export(tmp_path)["symbol"]["denomination_probe"],
                                "tick_size_at_probe": 0.5, "move": 50.0,
                                "buy_loss_profit": -50.0, "sell_gain_profit": 50.0,
                                "tick_value_loss_at_probe": 0.5,
                                "tick_value_profit_at_probe": 0.5,
                            })
    rows = sizer_behaviour_parity(doc)
    by = {r.field: r for r in rows}
    assert by["sizer.loss_per_lot"].status == "MATCH"
    # The witness is independently sufficient here; the non-point tick size
    # remains covered by the same per-symbol assessment.
    assert tick_value_denomination(doc) == "ACCOUNT_CURRENCY"


def test_loss_per_lot_tolerates_rounded_owner_tick_value(tmp_path):
    """P0-1: sizer.loss_per_lot compares the exported (rounded, printed-
    precision) SYMBOL_TRADE_TICK_VALUE_LOSS against the full-precision
    OrderCalcProfit witness. A broker-rounding difference inside the 1%
    denomination band (the same band RiskManager.GetLots enforces) is a
    MATCH; a larger gap is a real MISMATCH."""
    # witness (probe) fixes tick value at 1.0 (buy_loss_profit/-probe_ticks).
    # Reported tick value 1.005 is 0.5% off -> within the band -> MATCH.
    doc = _synthetic_export(tmp_path, tick_value_loss=1.005)
    by = {r.field: r for r in sizer_behaviour_parity(doc)}
    assert by["sizer.loss_per_lot"].status == "MATCH"
    # 2% off is beyond the denomination band -> MISMATCH (not silently hidden)
    doc_off = _synthetic_export(tmp_path, tick_value_loss=1.02)
    by_off = {r.field: r for r in sizer_behaviour_parity(doc_off)}
    assert by_off["sizer.loss_per_lot"].status == "MISMATCH"


def test_probe_field_contract_is_optional_and_not_field_mapped():
    from broker_symbol_parity import DENOMINATION_PROBE_FIELDS
    assert set(DENOMINATION_PROBE_FIELDS) == {
        "ok", "reason", "last_error", "source", "calc_mode", "account_leverage",
        "account_currency", "currency_profit", "currency_margin", "currency_base",
        "bid", "ask", "tick_size_at_probe", "probe_ticks", "lot_size", "move",
        "buy_loss_profit", "sell_gain_profit", "tick_value_loss_at_probe",
        "tick_value_profit_at_probe",
    }
    assert "denomination_probe" not in FIELD_MAP
    source = MQL5_EXPORT_SCRIPT.read_text(encoding="utf-8")
    for field in DENOMINATION_PROBE_FIELDS:
        assert f'JsonQuote("{field}")' in source


def test_witness_sign_inversion_is_rejected(tmp_path):
    doc = _synthetic_export(tmp_path, denomination_probe={
        **_synthetic_export(tmp_path)["symbol"]["denomination_probe"],
        "buy_loss_profit": 100.0, "sell_gain_profit": -100.0,
    })
    assessment = assess_tick_value_denomination(doc)
    assert assessment["verdict"] == "UNVERIFIED"
    assert assessment["status"] == "PENDING"
    assert "sign" in assessment["reason"]


def test_witness_scaling_and_tolerance_separation_guards(tmp_path):
    base = _synthetic_export(tmp_path)
    probe = base["symbol"]["denomination_probe"]
    scaled = _synthetic_export(tmp_path, denomination_probe={
        **probe, "probe_ticks": 200, "move": 0.002,
        "buy_loss_profit": -200.0, "sell_gain_profit": 200.0,
    })
    assert tick_value_denomination(scaled) == "ACCOUNT_CURRENCY"
    near = _synthetic_export(tmp_path, denomination_probe={
        **probe, "buy_loss_profit": -100.9, "sell_gain_profit": 100.9,
    })
    assert tick_value_denomination(near) == "UNVERIFIED"
    separated = _synthetic_export(tmp_path, denomination_probe={
        **probe, "buy_loss_profit": -108.0, "sell_gain_profit": 108.0,
    })
    assert tick_value_denomination(separated) == "PROFIT_CURRENCY"


def test_no_circular_derivation_or_global_fx_state():
    source = (REPO / "tools" / "broker_symbol_parity.py").read_text(encoding="utf-8")
    assert "derived_pl_check" not in source
    assert "fx_profit_to_deposit" not in source
    assert "global FX" not in source
    assert "contract_size * tick_size" in source
    assert "loss_tv /" not in source and "tick_value_loss /" not in source


def test_per_symbol_independence_and_btc_not_hidden_by_other_symbol(tmp_path):
    eur = _synthetic_export(tmp_path, name="EURUSD")
    btc = _synthetic_export(tmp_path, name="BTCUSD", contract_size=1.0,
                            tick_size=0.5, tick_value_loss=0.5,
                            tick_value_profit=0.5,
                            denomination_probe={
                                **eur["symbol"]["denomination_probe"],
                                "currency_base": "BTC", "tick_size_at_probe": 0.5,
                                "move": 50.0, "buy_loss_profit": -50.0,
                                "sell_gain_profit": 50.0,
                                "tick_value_loss_at_probe": 0.5,
                                "tick_value_profit_at_probe": 0.5,
                            })
    assert tick_value_denomination(eur) == "ACCOUNT_CURRENCY"
    assert tick_value_denomination(btc) == "ACCOUNT_CURRENCY"
    btc["symbol"]["denomination_probe"]["ok"] = False
    assert tick_value_denomination(btc) == "UNVERIFIED"
    assert tick_value_denomination(eur) == "ACCOUNT_CURRENCY"


def test_old_export_without_probe_remains_valid_and_pending(tmp_path):
    doc = _synthetic_export(tmp_path)
    del doc["symbol"]["denomination_probe"]
    path = tmp_path / "old.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert load_owner_export(path) == doc
    assert tick_value_denomination(doc) == "UNVERIFIED"
    assert assess_tick_value_denomination(doc)["status"] == "PENDING"


# ---------------------------------------------------------------------------
# exporter JSON escaping — 2026-09-09 owner-export defect
#
# The owner's real MT5 run produced `"path": "Forex\EURUSD"` — a raw
# backslash inside a JSON string — so tools/broker_symbol_parity.py skipped
# the export with "Invalid \escape" and the owner evidence was lost.
#
# Three layers, cheapest and most independent first:
#
# 1. the JSON contract itself, asserted WITHOUT reading any MQL5 source text:
#    the canonical RFC 8259 string encoding, a json.loads round-trip, and the
#    counter-example showing that the pre-fix output was not JSON at all;
# 2. the exporter source contract: the rules declared in the .mq5 helper must
#    produce that same encoding.  Extraction is layout-agnostic — indentation,
#    line breaks, parameter/variable names and quoting style are irrelevant,
#    and both a StringReplace() table and a per-character switch are read —
#    because the tests pin SEMANTICS, never formatting.  The rules are then
#    REPLAYED the way MQL5 applies them and re-validated as JSON;
# 3. the harness behaviour: an escaped export is parsed and counted, a
#    malformed one is skipped and never repaired;
# 4. the file-encoding contract: the BYTES the exporter writes must be the
#    bytes the owner reader decodes (UTF-8, no BOM) — escaping the string
#    values is not enough while the file layer is code-page dependent.
#
# MetaEditor cannot run in this sandbox (same constraint as
# tests/test_mql5_sources.py).  If the helper is ever rewritten in a style the
# extractor cannot read, the failure message says so explicitly — layer 1
# keeps the contract pinned either way.
# ---------------------------------------------------------------------------

#: every character class JSON forbids raw inside a string literal, plus the
#: values that must survive untouched.  U+0000 is not exercised: a NUL cannot
#: occur in broker text, so its MQL5 round-trip is not part of this contract.
JSON_STRING_SAMPLES = [
    "EURUSD",            # ordinary text must not be corrupted
    "Forex\\EURUSD",   # <-- the observed defect (SYMBOL_PATH)
    "Forex\\Sub\\EURUSD",
    "C:\\Users\\mt5",
    'say "hello"',
    "line1\nline2",
    "carriage\rreturn",
    "tab\there",
    "back\bspace",
    "form\ffeed",
    "vertical\x0btab",
    "control\x01char",
    'mixed "quote" and \\backslash\\ and\nnewline',
    "US30",
    "Ørsta",             # non-ASCII passes through untouched
    "DAX40.GI",
    "",
]

#: characters RFC 8259 requires a JSON writer to escape with a NAMED sequence
NAMED_ESCAPE_CHARS = ["\\", '"', "\n", "\r", "\t", "\b", "\f"]


def _json_string_literal(value: str) -> str:
    """The canonical encoding of a string value — what the exporter must emit.
    Derived from the JSON encoder itself (never a hand-copied table): named
    escapes, ``\\u00xx`` for the rest of the control range, and every other
    character copied through, because MQL5 writes the document as-is
    (``ensure_ascii=False``).  Canonical also means minimal: a writer that
    over-escapes (``\\/`` for a slash) is rejected, so the exported bytes stay
    comparable with every other JSON producer."""
    return json.dumps(value, ensure_ascii=False)


# --- layer 1: the JSON contract, independent of the MQL5 source ------------


@pytest.mark.parametrize("value", JSON_STRING_SAMPLES)
def test_json_string_literal_contract_round_trips(value):
    document = '{"symbol": {"path": ' + _json_string_literal(value) + "}}"
    assert json.loads(document)["symbol"]["path"] == value


def test_unescaped_broker_value_is_not_json_at_all():
    """The pre-fix behaviour (quote without escaping) as a counter-example:
    this is what made the owner export unparsable, and it is what a regression
    to ``return "\\"" + s + "\\"";`` would produce again."""
    broken = '{"symbol": {"path": "Forex' + chr(92) + 'EURUSD"}}'
    assert chr(92) + "EURUSD" in broken          # raw backslash in the document
    with pytest.raises(json.JSONDecodeError, match=r"Invalid \\escape"):
        json.loads(broken)
    fixed = ('{"symbol": {"path": '
             + _json_string_literal("Forex\\EURUSD") + "}}")
    assert json.loads(fixed)["symbol"]["path"] == "Forex\\EURUSD"


# --- layer 2: the exporter source contract (semantics, not layout) ---------

_MQL5_LITERAL_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_MQL5_SIMPLE_ESCAPES = {
    "n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "'": "'",
}

# StringReplace(target, "<find>" | ShortToString(<code>), "<replacement>")
_REPLACE_RULE_RE = re.compile(
    r"StringReplace\s*\(\s*\w+\s*,\s*"
    r'(?:"((?:[^"\\]|\\.)*)"'
    r"|ShortToString\s*\(\s*(?:\(\s*ushort\s*\)\s*)?(0x[0-9A-Fa-f]+|\d+)\s*\))"
    r'\s*,\s*"((?:[^"\\]|\\.)*)"\s*\)')

# case <char|code>: out += "<replacement>";
_CASE_RULE_RE = re.compile(
    r"case\s+(?:\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'"
    r"|(0x[0-9A-Fa-f]+|\d+))\s*:\s*\w+\s*(?:\+=|=)\s*\"((?:[^\"\\]|\\.)*)\"\s*;")


def _mql5_constant(text: str) -> str:
    """Decode an MQL5 string/character constant (the escape forms the
    exporter's serialization can legitimately use)."""
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        i += 1
        assert i < len(text), f"truncated MQL5 escape in {text!r}"
        nxt = text[i]
        if nxt in _MQL5_SIMPLE_ESCAPES:
            out.append(_MQL5_SIMPLE_ESCAPES[nxt])
            i += 1
        elif nxt in "xX":
            j = i + 1
            while (j < len(text) and j - i <= 4
                   and text[j] in "0123456789abcdefABCDEF"):
                j += 1
            digits = text[i + 1:j]
            assert digits, f"empty hex escape in {text!r}"
            out.append(chr(int(digits, 16)))
            i = j
        else:
            raise AssertionError(
                f"unsupported MQL5 escape \\{nxt} in {text!r}: the extractor"
                " knows \\n \\r \\t \\\\ \\\" \\' and \\x<hex> (the forms"
                " MQL5 documents for string constants)")
    return "".join(out)


def _exporter_source() -> str:
    return MQL5_EXPORT_SCRIPT.read_text(encoding="utf-8")


def _mql5_function(name_pattern: str, src: str | None = None) -> tuple[str, str]:
    """Return (name, body) of the first `string <name>(...) { ... }` helper
    whose name matches, located by brace matching: indentation, line breaks,
    brace placement and parameter naming are all irrelevant."""
    src = _exporter_source() if src is None else src
    m = re.search(r"^[ \t]*string[ \t]+(\w*" + name_pattern + r"\w*)[ \t]*\("
                  r"[^)]*\)\s*\{", src, re.MULTILINE)
    assert m, (
        f"no `string *{name_pattern}*()` helper found in the exporter: with no"
        " escaping every string value would be written raw again (the "
        "2026-09-09 defect)")
    depth, i = 0, m.end() - 1
    while i < len(src):
        ch = src[i]
        if ch in "\"'":                     # step over constants
            quote, i = ch, i + 1
            while i < len(src) and src[i] != quote:
                i += 2 if src[i] == "\\" else 1
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return m.group(1), src[m.end():i]
        i += 1
    raise AssertionError("unbalanced braces in the exporter helper")


def _control_bound(body: str) -> int:
    """Exclusive upper bound of a generic ``\\u00xx`` control-character rule in
    the helper body, or 0 when the helper has none (then it must list every
    control character explicitly)."""
    for literal in _MQL5_LITERAL_RE.findall(body):
        decoded = _mql5_constant(literal)
        if decoded.startswith("\\u") and "%04x" in decoded.lower():
            m = re.search(r"<\s*(0x[0-9A-Fa-f]+|\d+)", body)
            return int(m.group(1), 0) if m else 0
    return 0


def _escape_rules(body: str) -> tuple[list[tuple[str, str]], int]:
    """(ordered rules, control bound) of an escaping helper body.  A rule is a
    (find, replacement) pair, read from either implementation style."""
    found: list[tuple[int, tuple[str, str]]] = []
    for m in _REPLACE_RULE_RE.finditer(body):
        find_lit, code, repl_lit = m.group(1), m.group(2), m.group(3)
        find = _mql5_constant(find_lit) if find_lit is not None else chr(int(code, 0))
        found.append((m.start(), (find, _mql5_constant(repl_lit))))
    for m in _CASE_RULE_RE.finditer(body):
        lit, char, code, repl_lit = m.groups()
        if lit is not None:
            find = _mql5_constant(lit)
        elif char is not None:
            find = _mql5_constant(char)
        else:
            find = chr(int(code, 0))
        found.append((m.start(), (find, _mql5_constant(repl_lit))))
    found.sort(key=lambda item: item[0])
    return [rule for _, rule in found], _control_bound(body)


def _exporter_escaped(value: str) -> str:
    """Apply the exporter's own escape rules to a string the way the MQL5 code
    would: a StringReplace() table is applied sequentially in source order
    (that order is part of the algorithm), a per-character helper maps each
    code unit independently (so the order of its cases is irrelevant)."""
    body = _mql5_function("[Ee]scape")[1]
    rules, bound = _escape_rules(body)
    table = dict(rules)
    if re.search(r"\bStringReplace\s*\(", body):
        out = value
        for find, repl in rules:
            out = out.replace(find, repl)
        for code in range(1, bound):
            out = out.replace(chr(code), f"\\u{code:04x}")
        return out
    return "".join(
        table[ch] if ch in table
        else (f"\\u{ord(ch):04x}" if 1 <= ord(ch) < bound else ch)
        for ch in value)


def _render_like_exporter(doc, escape) -> str:
    """Serialize a document the way the exporter does: keys and string VALUES
    go through the escaper, at the string-value level only, and the finished
    document is never post-processed."""
    if isinstance(doc, str):
        return '"' + escape(doc) + '"'
    if isinstance(doc, bool):
        return "true" if doc else "false"
    if isinstance(doc, (int, float)):
        return json.dumps(doc)
    if isinstance(doc, dict):
        return "{" + ", ".join(
            '"' + escape(k) + '": ' + _render_like_exporter(v, escape)
            for k, v in doc.items()) + "}"
    if isinstance(doc, list):
        return "[" + ", ".join(_render_like_exporter(v, escape) for v in doc) + "]"
    raise AssertionError(f"unserializable value {doc!r}")


def test_exporter_declares_a_rule_for_every_character_json_forbids():
    name, body = _mql5_function("[Ee]scape")
    rules, bound = _escape_rules(body)
    table = dict(rules)
    assert table or bound, (
        f"{name}() exposes no escape rule the extractor can read — if the "
        f"implementation style changed, teach _escape_rules() about it "
        "(layer 1 pins the JSON semantics independently)")
    # the named escapes must be exactly the canonical JSON forms
    for ch in NAMED_ESCAPE_CHARS:
        expected = _json_string_literal(ch)[1:-1]
        assert table.get(ch) == expected, (
            f"{name}() must turn {ch!r} into {expected!r}, "
            f"got {table.get(ch)!r}")
    # a backslash introduced later would corrupt the escapes added before it
    if re.search(r"\bStringReplace\s*\(", body):
        assert rules[0][0] == "\\", (
            f"{name}() must escape the backslash BEFORE introducing any "
            "other escape sequence")
    # nothing in the control range may survive raw, whether it is listed
    # one-by-one or covered by a generic rule
    raw = [code for code in range(1, 0x20)
           if chr(code) not in table and not (bound and code < bound)]
    assert not raw, (
        f"{name}() leaves {len(raw)} control character(s) raw "
        f"(first: U+{raw[0]:04X}) — JSON forbids them")


def test_exporter_escaped_values_decode_back_to_the_broker_value():
    problems = []
    for value in JSON_STRING_SAMPLES:
        literal = '"' + _exporter_escaped(value) + '"'
        if literal != _json_string_literal(value):
            problems.append(f"{value!r}: emits {literal}, canonical is "
                            f"{_json_string_literal(value)}")
            continue
        document = '{"symbol": {"path": ' + literal + "}}"
        try:
            if json.loads(document)["symbol"]["path"] != value:
                problems.append(f"{value!r}: round-trip changed the value")
        except json.JSONDecodeError as exc:
            problems.append(f"{value!r}: produces invalid JSON ({exc})")
    assert not problems, (
        "exporter escaping differs from JSON semantics:\n"
        + "\n".join(problems))


def test_every_broker_string_reaches_the_document_through_the_quoting_helper():
    """Statements (not physical lines) are scanned, so wrapped or reindented
    code is judged exactly like a single long line."""
    src = _exporter_source()
    quote_name, quote_body = _mql5_function("[Qq]uote")
    escape_name = _mql5_function("[Ee]scape")[0]
    # the quoting helper escapes; it does not merely wrap
    assert re.search(r"\b" + escape_name + r"\s*\(", quote_body), (
        f"{quote_name}() must delegate to {escape_name}() — quoting without "
        "escaping is the 2026-09-09 defect")
    main = src[src.index("void Main"):]
    offenders = []
    for statement in re.findall(r"j\s*\+=\s*(.*?);", main, re.DOTALL):
        code = "\n".join(line.split("//")[0] for line in statement.splitlines())
        reads_broker_text = ("SymbolInfoString(" in code
                             or "AccountInfoString(" in code
                             or "TimeToString(" in code)
        if reads_broker_text and not re.search(r"\b" + quote_name + r"\s*\(", code):
            offenders.append(" ".join(code.split()))
    assert not offenders, (
        f"string value(s) written without {quote_name}(): {offenders}")


# --- layer 3: harness behaviour on escaped vs malformed exports ------------


def test_exporter_output_is_accepted_by_the_parity_harness(tmp_path, capsys):
    """End-to-end for the fix: the document the fixed exporter builds is
    accepted by load_owner_export()/build_report() — no 'skipping malformed
    export' warning — and counts as the FX portion of the gate only."""
    from broker_symbol_parity import build_report
    doc = _synthetic_export(tmp_path, path="Forex\\EURUSD")
    p = tmp_path / "EURUSD.json"
    p.write_text(_render_like_exporter(doc, _exporter_escaped), encoding="utf-8")
    # the bytes on disk carry the escaped form, not the raw one
    assert '"path": ' + _json_string_literal("Forex\\EURUSD") \
        in p.read_text(encoding="utf-8")
    assert load_owner_export(p) == doc
    exports, rows, coverage = build_report(tmp_path)
    assert capsys.readouterr().err == "", "a valid export must not be skipped"
    assert len(exports) == 1 and rows
    assert coverage["FX"] == "exported: EURUSD"
    # one FX export does not complete the gate: the rest stays pending
    assert all(coverage[cls].startswith("PENDING")
               for cls in ("METAL", "INDEX_CFD", "CRYPTO"))


def test_malformed_export_is_skipped_and_never_repaired(tmp_path, capsys):
    """The pre-fix bytes, and the fail-closed rule that must keep applying:
    malformed JSON is reported and skipped, never silently repaired."""
    from broker_symbol_parity import build_report
    doc = _synthetic_export(tmp_path, path="Forex\\EURUSD")
    p = tmp_path / "EURUSD.json"
    raw = _render_like_exporter(doc, lambda value: value)   # old JsonQuote
    with pytest.raises(json.JSONDecodeError, match=r"Invalid \\escape"):
        json.loads(raw)
    p.write_text(raw, encoding="utf-8")
    exports, rows, coverage = build_report(tmp_path)
    err = capsys.readouterr().err
    assert "skipping malformed export" in err and "Invalid \\escape" in err
    assert exports == [] and rows == []
    assert all(v.startswith("PENDING") for v in coverage.values())


# --- layer 4: the exported BYTES must be what the owner reader decodes -----
#
# Escaping the string values is only half of a text file contract: the file
# layer has to write them in the encoding the Python side reads.
# tools/broker_symbol_parity.py::load_owner_export() declares
# read_text(encoding="utf-8"), so an export written in the terminal's ANSI code
# page (FileOpen's default, CP_ACP) is machine-dependent bytes, and the
# deliberately non-ASCII-tolerant escaping of layer 1/2 turns that into a
# skipped owner export.  The contract is asserted by EXECUTING the reader on
# candidate bytes, and only then tied back to the exporter source, so neither
# test depends on how that source is formatted.

#: reader declarations that expect BOM-less UTF-8 on disk
UTF8_READER_CODECS = ("utf-8", "utf8", "utf-8-sig")

#: what each MQL5 FileOpen code page puts on disk.  CP_ACP/CP_THREAD_ACP/
#: CP_OEMCP are machine-dependent BY DEFINITION — that is the defect; the
#: Python names below are the Western-European instantiation, used only to
#: show such bytes are not UTF-8.  A text file opened without FILE_ANSI is
#: UTF-16 with a BOM, which the code page never applies to.
MQL5_CODEPAGE_PYTHON = {
    "CP_UTF8": "utf-8",
    "CP_UTF7": "utf-7",
    "CP_ACP": "cp1252",
    "CP_THREAD_ACP": "cp1252",
    "CP_OEMCP": "cp850",
}


def _owner_reader_declared_encoding() -> str:
    """The encoding the repository's owner-export loader declares."""
    src = (REPO / "tools" / "broker_symbol_parity.py").read_text(encoding="utf-8")
    start = src.index("def load_owner_export(")
    nxt = src.find("\ndef ", start + 10)
    body = src[start:] if nxt < 0 else src[start:nxt]
    found = re.search(r"""encoding\s*=\s*["']([^"']+)["']""", body)
    assert found, (
        "load_owner_export() declares no explicit encoding: the export file "
        "encoding is a cross-language contract and must not fall back to a "
        "platform default on either side")
    return found.group(1).lower()


def _split_mql5_args(call: str) -> list[str]:
    """Split an argument list on top-level commas, respecting MQL5 string and
    character constants, so commas inside a literal cannot shift positions."""
    args, buf, depth, i = [], "", 0, 0
    while i < len(call):
        ch = call[i]
        if ch in "\"'":
            quote, start = ch, i
            i += 1
            while i < len(call) and call[i] != quote:
                i += 2 if call[i] == "\\" else 1
            buf += call[start:i + 1]
            i += 1
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            args.append(buf)
            buf = ""
        else:
            buf += ch
        i += 1
    args.append(buf)
    return [a.strip() for a in args]


def _export_write_open_calls() -> list[dict]:
    """Every FileOpen() in the exporter that opens a file for writing,
    normalised to its flag set and code-page constant.  Argument ORDER,
    spacing, line breaks and the flag expression layout are irrelevant: a
    code page is only required to be present, and the flags are compared as a
    set."""
    src = _exporter_source()
    calls = []
    for match in re.finditer(r"FileOpen\s*\(", src):
        i, depth = match.end(), 1
        while i < len(src) and depth:
            depth += 1 if src[i] == "(" else (-1 if src[i] == ")" else 0)
            i += 1
        args = _split_mql5_args(src[match.end():i - 1])
        if len(args) < 2 or "FILE_WRITE" not in args[1]:
            continue
        codepage = None
        if len(args) >= 4:
            last = args[-1]
            if re.fullmatch(r"CP_[A-Z0-9_]+", last):
                codepage = last
            elif last.lstrip("-").isdigit():
                codepage = {65001: "CP_UTF8", 65000: "CP_UTF7"}.get(int(last))
        calls.append({
            "flags": set(re.findall(r"FILE_[A-Z0-9_]+", " ".join(args))),
            "codepage": codepage,
            "text": ", ".join(args),
        })
    assert calls, "the exporter has no FileOpen(... FILE_WRITE ...) call"
    return calls


def _document_as_the_exporter_writes_it(doc) -> str:
    """The document text: keys and string values escaped exactly as layer 1
    defines (canonical JSON, non-ASCII preserved), quotes added."""
    return _render_like_exporter(doc, lambda value: _json_string_literal(value)[1:-1])


def test_exporter_writes_the_encoding_the_owner_reader_declares():
    reader = _owner_reader_declared_encoding()
    src = _exporter_source()
    explicit_utf8_bytes = (re.search(r"StringToCharArray\s*\([^;]*CP_UTF8", src)
                           and re.search(r"FileWriteArray\s*\(", src))
    for call in _export_write_open_calls():
        flags, codepage = call["flags"], call["codepage"]
        assert "FILE_UNICODE" not in flags, (
            "FILE_UNICODE on a text file writes UTF-16 with a BOM, which "
            f"read_text(encoding={reader!r}) cannot decode")
        text_route = {"FILE_TXT", "FILE_ANSI"} <= flags and codepage == "CP_UTF8"
        byte_route = "FILE_BIN" in flags and explicit_utf8_bytes
        assert text_route or byte_route, (
            "the export is not written as BOM-less UTF-8 "
            f"(FileOpen({call['text']})). The owner reader declares "
            f"encoding={reader!r}, so a text file needs FILE_TXT | FILE_ANSI "
            "plus the CP_UTF8 code page — the code page is IGNORED without "
            "FILE_ANSI, and omitting it means CP_ACP, i.e. the machine's ANSI "
            "code page — or an explicit StringToCharArray(..., CP_UTF8) + "
            "FileWriteArray() byte write.")
        if reader in UTF8_READER_CODECS and "FILE_BIN" not in flags:
            requested = codepage or "CP_ACP (default)"
            written = MQL5_CODEPAGE_PYTHON.get(codepage or "CP_ACP")
            assert written == "utf-8", (
                f"the exporter requests code page {requested}, which writes "
                f"{written} bytes, while the owner reader decodes {reader!r}")


def _bytes_the_exporter_file_layer_produces(text: str, call: dict) -> bytes:
    """Model the exporter's file layer from the parsed FileOpen call: the code
    page it requests decides the bytes on disk.  CP_ACP is instantiated as
    cp1252 because that is the owner's Western-European Windows ANSI page;
    the point of the pin is that the bytes must not depend on that at all."""
    flags, codepage = call["flags"], call["codepage"]
    if "FILE_BIN" in flags:
        return text.encode("utf-8")        # explicit StringToCharArray(CP_UTF8)
    if "FILE_ANSI" not in flags:
        return text.encode("utf-16")       # Unicode text file, BOM included
    return text.encode(MQL5_CODEPAGE_PYTHON.get(codepage or "CP_ACP"))


def test_the_code_page_the_exporter_requests_is_readable_by_the_owner_reader(
        tmp_path):
    """Pipes the exporter's own file-layer settings through the repository
    reader: document -> bytes as FileOpen would write them -> load_owner_export.
    A non-ASCII broker value must survive that trip, so a revert to the
    code-page-dependent text file (or to Unicode/BOM output) fails here for the
    real reason — the owner export would be skipped, not repaired."""
    doc = _synthetic_export(tmp_path, path=r"Forex\EURUSD",
                            description="Ørsta «EUR» ±1")
    text = _document_as_the_exporter_writes_it(doc)
    p = tmp_path / "EURUSD.json"
    for call in _export_write_open_calls():
        p.write_bytes(_bytes_the_exporter_file_layer_produces(text, call))
        assert load_owner_export(p) == doc, (
            f"FileOpen({call['text']}) puts bytes on disk that "
            "load_owner_export() cannot read")


def test_owner_reader_accepts_only_bom_less_utf8_bytes(tmp_path):
    """The encoding contract executed against the repository reader: the same
    document is accepted as BOM-less UTF-8 — including the non-ASCII
    characters the escaper deliberately passes through — and rejected as
    code-page bytes, UTF-16 bytes or BOM-prefixed UTF-8."""
    doc = _synthetic_export(tmp_path, path="Forex\\EURUSD",
                            description="Ørsta «EUR» ±1")
    text = _document_as_the_exporter_writes_it(doc)
    variants = {
        "utf-8": text.encode("utf-8"),
        "cp1252": text.encode("cp1252"),
        "utf-16": text.encode("utf-16"),
        "utf-8+bom": codecs.BOM_UTF8 + text.encode("utf-8"),
    }
    p = tmp_path / "EURUSD.json"
    accepted = {}
    for name, data in variants.items():
        p.write_bytes(data)
        try:
            accepted[name] = load_owner_export(p)
        except ValueError:                     # Unicode/JSONDecodeError
            accepted[name] = None
    assert accepted["utf-8"] == doc, "valid UTF-8 bytes must load unchanged"
    assert accepted["utf-8"]["symbol"]["description"] == "Ørsta «EUR» ±1"
    for name in ("cp1252", "utf-16", "utf-8+bom"):
        assert accepted[name] is None, (
            f"{name}: the owner reader must not accept this encoding — that is "
            "why the exporter pins CP_UTF8 with FILE_ANSI and no BOM")


def test_ascii_only_exports_hide_the_encoding_defect(tmp_path):
    """Why this was invisible on the owner's EURUSD run: pure-ASCII broker
    text is byte-identical in UTF-8 and in a Windows ANSI code page. The defect
    class bites only when a path/server/currency carries a non-ASCII
    character — which the escaper is explicitly specified to preserve."""
    plain = _document_as_the_exporter_writes_it(_synthetic_export(tmp_path))
    assert plain.encode("utf-8") == plain.encode("cp1252")
    exotic = _document_as_the_exporter_writes_it(
        _synthetic_export(tmp_path, path="Ørsta\\EURUSD"))
    assert exotic.encode("utf-8") != exotic.encode("cp1252")
    with pytest.raises(UnicodeDecodeError):
        exotic.encode("cp1252").decode("utf-8")


def test_export_in_the_wrong_code_page_is_skipped_and_never_repaired(tmp_path,
                                                                     capsys):
    """The harness stays fail-closed for encoding, exactly as for malformed
    JSON: a code-page-mismatched export is reported and skipped, never
    transcoded or repaired."""
    from broker_symbol_parity import build_report
    doc = _synthetic_export(tmp_path, path="Forex\\EURUSD", description="Ørsta")
    text = _document_as_the_exporter_writes_it(doc)
    (tmp_path / "EURUSD.json").write_bytes(text.encode("cp1252"))
    exports, rows, coverage = build_report(tmp_path)
    err = capsys.readouterr().err
    assert "skipping malformed export" in err and "codec can't decode" in err
    assert exports == [] and rows == []
    assert all(v.startswith("PENDING") for v in coverage.values())


# ---------------------------------------------------------------------------
# asset-class coverage — the classifier that decides whether the owner has
# exported at least one symbol per required class
# ---------------------------------------------------------------------------
#
# Proven defect (real owner exports, 2026-09-10): the classifier walked the
# classes with ONE if/elif chain, so the first rule that matched a symbol
# claimed it outright.  The owner's XAUEUR export (SYMBOL_PATH
# ``Metals\XAUEUR``) satisfied the FX branch through the bare shape test
# ``len(name) == 6 and name.isalpha()``, the METAL branch was never reached, and
# the report said "FX: exported: XAUEUR" while METAL stayed PENDING.  Coverage
# is a per-class property, not a partition of the symbol universe: the class
# checks must be independent, the generic FX shape test must not outrank
# specific evidence, and a class representative must be chosen by an explicit
# deterministic policy instead of last-write-wins over the caller's (or the
# filesystem's) iteration order.

#: the four owner export identities as the audit recorded them (name +
#: SYMBOL_PATH only — no broker number is involved in the classification)
FOUR_OWNER_EXPORT_EVIDENCE = [
    ("EURUSD", "Forex\\EURUSD"),
    ("XAUEUR", "Metals\\XAUEUR"),
    ("US30", "Indices\\US30"),
    ("BTC", "Crypto\\BTC"),
]

#: docs/BROKER_SYMBOL_PARITY.md requires one owner export per class, so all
#: four must be populated by those four exports
FOUR_CLASS_COVERAGE = {
    "FX": "exported: EURUSD",
    "METAL": "exported: XAUEUR",
    "INDEX_CFD": "exported: US30",
    "CRYPTO": "exported: BTC",
}


def _classification_doc(name: str, path: str | None = None) -> dict:
    """Minimal export document for classifier tests: the coverage report reads
    ``symbol.name`` and ``symbol.path`` and nothing else.  Schema-valid
    full-fixture documents are exercised end-to-end by
    test_coverage_is_independent_of_candidate_order()."""
    sym = {"name": name}
    if path is not None:
        sym["path"] = path
    return {"symbol": sym}


def _write_exports(tmp_path, pairs) -> Path:
    """Materialise one export per (name, path) pair as ``<NAME>.json`` in a
    fresh directory, built by this module's own fixture so the numbers are the
    repository's synthetic defaults — never invented broker evidence."""
    out = tmp_path / "exports"
    scratch = tmp_path / "scratch"
    out.mkdir(parents=True)
    scratch.mkdir(parents=True)
    for name, path in pairs:
        doc = _synthetic_export(scratch, name=name,
                                **({} if path is None else {"path": path}))
        (scratch / "EURUSD.json").unlink()
        (out / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")
    return out


def test_one_export_per_class_covers_all_four_classes():
    coverage = asset_classes_covered(
        [_classification_doc(name, path) for name, path in FOUR_OWNER_EXPORT_EVIDENCE])
    assert coverage == FOUR_CLASS_COVERAGE


def test_metal_export_is_not_counted_as_fx_by_its_name_shape():
    """The exact real-world regression: XAUEUR is six alphabetic characters,
    which used to be enough to take the FX slot and hide the METAL one."""
    assert len("XAUEUR") == 6 and "XAUEUR".isalpha()      # the collision cause
    coverage = asset_classes_covered([_classification_doc("XAUEUR", "Metals\\XAUEUR")])
    assert coverage["METAL"] == "exported: XAUEUR"
    assert coverage["FX"].startswith("PENDING")
    # with no path at all, a name a specific class claims is still not FX
    coverage = asset_classes_covered([_classification_doc("XAUEUR")])
    assert coverage["METAL"] == "exported: XAUEUR"
    assert coverage["FX"].startswith("PENDING")
    # and it never displaces a symbol that genuinely evidences FX
    coverage = asset_classes_covered([
        _classification_doc("XAUEUR", "Metals\\XAUEUR"),
        _classification_doc("EURUSD", "Forex\\EURUSD")])
    assert coverage["FX"] == "exported: EURUSD"
    assert coverage["METAL"] == "exported: XAUEUR"


def test_fx_shape_rule_is_a_fallback_not_an_evidence_override():
    """The constrained generic rule: a 6-letter alphabetic ticker counts as FX
    only when the export carries no class evidence, and never for a name a
    specific class claims.  No equally broad rule replaces it."""
    # preserved legitimate use: a path-less pair is still FX
    assert (asset_classes_covered([_classification_doc("EURUSD")])["FX"]
            == "exported: EURUSD")
    # a path that evidences another class is never re-routed to FX
    for name, path, cls in [("US30", "Indices\\US30", "INDEX_CFD"),
                            ("XAUEUR", "Metals\\XAUEUR", "METAL"),
                            ("XAGUSD", "Metals\\XAGUSD", "METAL")]:
        coverage = asset_classes_covered([_classification_doc(name, path)])
        assert coverage[cls] == f"exported: {name}"
        assert coverage["FX"].startswith("PENDING"), f"{name} stole the FX slot"
    # uninformative folder + no name witness: nothing is claimed, ever
    coverage = asset_classes_covered([_classification_doc("US30", "Other\\US30")])
    assert all(v.startswith("PENDING") for v in coverage.values())
    # the xau marker itself is METAL evidence wherever it appears
    coverage = asset_classes_covered([_classification_doc("XAUEUR", "Other\\XAUEUR")])
    assert coverage["METAL"] == "exported: XAUEUR"
    assert coverage["FX"].startswith("PENDING")


def test_a_symbol_can_represent_more_than_one_class():
    """Independence is what the bug needed: classes are not mutually
    exclusive, so a symbol carrying two kinds of evidence counts toward both
    instead of being consumed by the first rule."""
    coverage = asset_classes_covered([_classification_doc("BTCUSD", "Forex\\BTCUSD")])
    assert coverage["FX"] == "exported: BTCUSD"
    assert coverage["CRYPTO"] == "exported: BTCUSD"
    # and an unrelated class is still honestly PENDING
    assert coverage["METAL"].startswith("PENDING")
    assert coverage["INDEX_CFD"].startswith("PENDING")


def test_coverage_is_independent_of_candidate_order(tmp_path):
    """Alphabetical, reverse-alphabetical, explicit (metal-first) and
    filesystem order must all yield the identical class -> representative
    mapping, including through build_report() on real files."""
    docs = [_classification_doc(name, path) for name, path in FOUR_OWNER_EXPORT_EVIDENCE]
    alphabetical = sorted(docs, key=lambda d: d["symbol"]["name"])
    explicit = [docs[1], docs[3], docs[0], docs[2]]        # metal, crypto, fx, index
    orders = [docs, alphabetical, list(reversed(alphabetical)), explicit]
    serialised = {json.dumps(asset_classes_covered(o), sort_keys=True) for o in orders}
    assert serialised == {json.dumps(FOUR_CLASS_COVERAGE, sort_keys=True)}

    from broker_symbol_parity import build_report
    forward = _write_exports(tmp_path / "forward", FOUR_OWNER_EXPORT_EVIDENCE)
    backward = _write_exports(tmp_path / "backward", list(reversed(FOUR_OWNER_EXPORT_EVIDENCE)))
    exports_a, rows_a, coverage_a = build_report(forward)
    exports_b, rows_b, coverage_b = build_report(backward)
    assert coverage_a == coverage_b == FOUR_CLASS_COVERAGE
    assert len(exports_a) == len(exports_b) == 4
    assert len(rows_a) == len(rows_b)
    md = render_markdown(exports_a, rows_a, coverage_a)
    assert '"METAL": "exported: XAUEUR"' in md        # the row the audit needed


def test_first_valid_candidate_in_sorted_order_represents_a_class():
    """The explicit policy: sorted by name (then path), first valid match wins
    and is never overwritten — so duplicate candidates are deterministic.  The
    input order is deliberately the WRONG way round for last-write-wins."""
    fx = [_classification_doc("EURUSD", "Forex\\EURUSD"),
          _classification_doc("GBPUSD", "Forex\\GBPUSD")]
    metals = [_classification_doc("XAGUSD", "Metals\\XAGUSD"),
              _classification_doc("XAUUSD", "Metals\\XAUUSD")]
    for docs in (fx, list(reversed(fx))):
        assert asset_classes_covered(docs)["FX"] == "exported: EURUSD"
    for docs in (metals, list(reversed(metals))):
        assert asset_classes_covered(docs)["METAL"] == "exported: XAGUSD"


def test_the_classifier_has_no_class_stealing_if_elif_chain():
    """Structural, not cosmetic (``ast``, so reformatting cannot dodge it): an
    if/elif chain that lets several mutually exclusive branches each assign a
    coverage value is the defect, whatever the current symbols happen to do."""
    src = (REPO / "tools" / "broker_symbol_parity.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    functions = {node.name: node for node in tree.body
                 if isinstance(node, ast.FunctionDef)}
    def assigns_coverage(stmts) -> bool:
        """True if these statements of ONE branch assign a coverage value (the
        chained elif is a separate branch, so it is not walked here)."""
        for stmt in stmts:
            for child in ast.walk(stmt):
                if isinstance(child, ast.Assign) and any(
                        isinstance(target, ast.Subscript)
                        and ast.unparse(target.value) == "out"
                        for target in child.targets):
                    return True
        return False

    offenders = []
    for name in ("asset_classes_covered", "_asset_classes_supported"):
        fn = functions.get(name)
        assert fn is not None, f"{name}() has disappeared from the harness"
        for node in ast.walk(fn):
            if not (isinstance(node, ast.If) and len(node.orelse) == 1
                    and isinstance(node.orelse[0], ast.If)):
                continue
            if assigns_coverage(node.body) and assigns_coverage(node.orelse[0].body):
                offenders.append(f"{name}(): line {node.lineno}, if/elif branches "
                                 "both assign out[...]")
    assert not offenders, (
        "asset-class coverage must be decided by independent checks, not by an "
        "if/elif chain where the first matching rule consumes the symbol "
        "(that is how Metals\\XAUEUR was counted as FX): " + "; ".join(offenders))
