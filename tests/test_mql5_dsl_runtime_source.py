"""Product-blocker regression tests for the INTEGRATED MQL5 generic
runtime SOURCE (mission §10/§12/§13).

The runtime now lives under ``mql5/`` (integrated, not the old staging
tree). The MQL5 tree cannot be compiled on Mac, so these tests pin the
fixed behaviour two ways, neither of which inspects comments:

1. ALGORITHM MIRRORS — the exact canonical-JSON + SHA-256 strategy the
   MQL5 loader encodes (raw lexical number tokens, ordinal key sort,
   Python-style string escaping, the _floatify token mapping) is
   re-implemented here and must reproduce every golden fixture's
   ``bundle_hash`` / ``spec_hash`` / ``semantic_hash`` byte-for-byte,
   and must DETECT tampering.  The OLD loader only checked bundle_hash
   PRESENCE — no algorithm existed, so these assertions could not have
   held.

2. STRUCTURAL SOURCE PINS — comment-stripped source must contain the
   fail-closed constructs (hash re-derivation invoked, identity
   binding, contract pins, whole-spec ambiguity refusal, market API,
   implemented filters, no stub for DONCHIAN/HIGHEST/LOWEST) and the
   capability matrix must match the Python side exactly.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from mql5bot.dsl.normalize import canon_json
from mql5bot.indicator_universe import MQL5_STAGED_RUNTIME_KINDS

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ROOT / "mql5" / "Include" / "Mql5Bot"
SCRIPTS = ROOT / "mql5" / "Scripts" / "Mql5Bot"
GOLD = ROOT / "artifacts" / "dsl_parity"
MANIFEST = json.loads((GOLD / "manifest.json").read_text())
NAMES = sorted(MANIFEST["fixtures"])

# normalize.NON_SEMANTIC — mirrored in DslCanon.mqh DSL_NON_SEMANTIC_KEYS
NON_SEMANTIC = {"name", "description", "source", "claims", "hypothesis",
                "metadata", "params"}


# ---------------------------------------------------------------------------
# The MQL5 canonicalization algorithm, re-implemented faithfully
# ---------------------------------------------------------------------------


class RawNum(str):
    """A number's exact lexical token (mirror of CDslJson raw capture)."""


def _refuse_constant(name):  # NaN/Infinity are not canonical JSON
    raise ValueError(f"non-canonical constant {name}")


def mirror_parse(text: str):
    return json.loads(text, parse_float=RawNum, parse_int=RawNum,
                      parse_constant=_refuse_constant)


def mirror_escape(s: str) -> str:
    """DslCanonEscape: Python json.dumps ensure_ascii escaping, emitted
    per UTF-16 code unit exactly like MQL5 strings."""
    out = ['"']
    for ch in s:
        c = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif c == 8:
            out.append("\\b")
        elif c == 12:
            out.append("\\f")
        elif c < 0x20 or c > 0x7E:
            data = ch.encode("utf-16-be")
            for i in range(0, len(data), 2):
                unit = int.from_bytes(data[i:i + 2], "big")
                out.append(f"\\u{unit:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def mirror_number(tok: str, floatify: bool) -> str:
    """DslCanonNumber: raw token verbatim; floatify appends '.0' to an
    integer token (refusing >15-digit integers), maps -0/-0.0 -> 0.0."""
    if not floatify:
        return tok
    if tok in ("-0", "-0.0"):
        return "0.0"
    if "." in tok or "e" in tok or "E" in tok:
        return tok
    digits = len(tok) - (1 if tok.startswith("-") else 0)
    if digits > 15:
        raise ValueError(f"integer too large to floatify: {tok}")
    return tok + ".0"


def mirror_canon(obj, floatify: bool, exclude: frozenset = frozenset()
                 ) -> str:
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, RawNum):
        return mirror_number(str(obj), floatify)
    if isinstance(obj, str):
        return mirror_escape(obj)
    if isinstance(obj, list):
        return "[" + ",".join(mirror_canon(v, floatify)
                              for v in obj) + "]"
    if isinstance(obj, dict):
        # ordinal UTF-16 code-unit key sort (DslKeyCompare)
        items = sorted(((k, v) for k, v in obj.items()
                        if k not in exclude),
                       key=lambda kv: kv[0].encode("utf-16-be"))
        return "{" + ",".join(mirror_escape(k) + ":"
                              + mirror_canon(v, floatify)
                              for k, v in items) + "}"
    raise TypeError(f"non-canonical node {type(obj)}")


def mirror_bundle_hash(text: str) -> str:
    env = mirror_parse(text)
    canon = mirror_canon(env, False, exclude=frozenset({"bundle_hash"}))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def mirror_identity_hashes(text: str) -> tuple[str, str]:
    """(spec_hash, semantic_hash) re-derived exactly as DslBundle.mqh
    does: floatified semantic core + the 4-key spec-hash envelope."""
    env = mirror_parse(text)
    spec = env["spec"]
    core = mirror_canon(spec, True, exclude=frozenset(NON_SEMANTIC))
    semantic = hashlib.sha256(core.encode("utf-8")).hexdigest()
    spec_input = ("{\"schema_version\":"
                  + mirror_escape(spec["schema_version"])
                  + ",\"semantic\":" + core
                  + ",\"strategy_id\":" + mirror_escape(
                      spec["strategy_id"])
                  + ",\"version\":" + mirror_number(str(spec["version"]),
                                                    True)
                  + "}")
    return (hashlib.sha256(spec_input.encode("utf-8")).hexdigest(),
            semantic)


# ---------------------------------------------------------------------------
# 1. the algorithm reproduces every golden fixture's hashes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_mql5_hash_algorithm_reproduces_bundle_hash(name):
    """The raw-token canonicalization the MQL5 loader implements must
    reproduce canon_json + _binding_hash byte-for-byte.  The OLD loader
    had no algorithm at all (presence check only)."""
    text = (GOLD / name / "bundle.json").read_text()
    env = json.loads(text)
    assert mirror_bundle_hash(text) == env["bundle_hash"]
    assert env["bundle_hash"] == MANIFEST["fixtures"][name]["bundle_hash"]


@pytest.mark.parametrize("name", NAMES)
def test_mql5_hash_algorithm_reproduces_identity_hashes(name):
    """spec_hash + semantic_hash re-derivation (identity binding) must
    match the Python normalize pipeline exactly."""
    text = (GOLD / name / "bundle.json").read_text()
    ident = json.loads(text)["identity"]
    spec_hash, semantic_hash = mirror_identity_hashes(text)
    assert spec_hash == ident["spec_hash"]
    assert semantic_hash == ident["semantic_hash"]


def test_mql5_hash_algorithm_detects_tampering():
    """A single tampered digit anywhere in the envelope changes the
    re-derived hash — the check the OLD loader could not perform."""
    name = "canonical_ema_rsi_atr"
    text = (GOLD / name / "bundle.json").read_text()
    good = mirror_bundle_hash(text)
    tampered = text.replace('"period": 20.0', '"period": 21.0', 1)
    assert tampered != text
    assert mirror_bundle_hash(tampered) != good
    # identity binding breaks too
    spec_hash, _ = mirror_identity_hashes(tampered)
    assert spec_hash != json.loads(text)["identity"]["spec_hash"]


def test_mirror_escape_matches_python_json_dumps():
    """The MQL5 escape rules must equal json.dumps(ensure_ascii=True)
    for every string class the bundle format can carry."""
    samples = ["", "plain", 'quote " backslash \\', "line\nfeed\t\r",
               "control \x01\x1f", "unicode é ü ‰ 🎯", "EURUSD", "H1",
               "\x08\x0c mixed \x7f", "ключ 键"]
    for s in samples:
        assert mirror_escape(s) == json.dumps(s), repr(s)


def test_mirror_floatify_matches_normalize():
    """The token-level floatify mapping equals canon_json(_floatify(x))
    for representative numeric leaves."""
    from mql5bot.dsl.normalize import _floatify
    for value, tok in [(1, "1"), (55, "55"), (0, "0"), (-3, "-3"),
                       (2.5, "2.5"), (0.001, "0.001"), (20.0, "20.0"),
                       (1.5e-05, "1.5e-05"), (-0.0, "-0.0")]:
        assert mirror_number(tok, True) == canon_json(_floatify(value)), tok
    with pytest.raises(ValueError):
        mirror_number("12345678901234567", True)  # >15 digits: refused


def test_mirror_canon_equals_canon_json_on_plain_documents():
    """End-to-end: for every golden bundle the raw-token serializer and
    the reference canon_json agree on the identical text."""
    for name in NAMES:
        text = (GOLD / name / "bundle.json").read_text()
        assert mirror_canon(mirror_parse(text), False) \
            == canon_json(json.loads(text)), name


# ---------------------------------------------------------------------------
# 2. structural source pins (comment-stripped — never comment text)
# ---------------------------------------------------------------------------


def _code(path: Path) -> str:
    src = path.read_text()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def test_bundle_loader_verifies_hash_and_identity_in_code():
    code = _code(INCLUDE / "DslBundle.mqh")
    # bundle_hash is DERIVED and compared (not merely present)
    assert "DeriveBundleHash(json, derived)" in code
    assert "bundle_hash mismatch" in code
    # identity binding is re-derived from content
    assert "DeriveSemanticCore" in code
    assert "DeriveSpecHash" in code
    assert "identity.spec_hash does not bind the spec" in code
    assert "identity.semantic_hash does not bind the spec" in code
    # ambiguity refusal covers the WHOLE spec, not only entry
    assert "HasAmbiguous(json, spec)" in code
    assert 'HasAmbiguous(json, json.Member(spec,"entry"))' not in code
    # indicator_contracts presence + version pin enforcement
    assert "missing indicator_contracts" in code
    assert "DslKindContractVersion" in code
    assert "contract drift" in code
    # explicit runtime market-compatibility API
    assert "MarketMatches(const string symbol" in code
    assert "market mismatch" in code


def test_supported_kinds_pin_matches_python_capability_matrix():
    src = (INCLUDE / "DslBundle.mqh").read_text()
    m = re.search(r'DslSupportedKinds\(\)\s*\{\s*return\s*"\|([A-Z|]+)\|"',
                  src)
    assert m, "DslSupportedKinds() literal not found"
    kinds = {k for k in m.group(1).split("|") if k}
    assert kinds == set(MQL5_STAGED_RUNTIME_KINDS)


def test_runtime_implements_python_filter_semantics_in_code():
    code = _code(INCLUDE / "DslRuntime.mqh")
    # implemented (fixture-verified) + refused-fail-closed filters are
    # all named in the source
    for construct in ("trading_days", "session", "max_spread_points",
                      "max_atr_pct", "forbidden", "cooldown_bars"):
        assert construct in code, construct
    # missing/unverified feeds are refused, never guessed
    assert code.count("refusing to guess") >= 3
    # cooldown reads the ORIGINAL vector (the old in-place scan diverged)
    assert "orig" in code and "ArrayResize(orig" in code
    # CROSS evaluates generic operands via the shared operand grammar
    assert "CrossSign(const int aOp, const int bOp" in code
    assert "EvalOperand(aOp, bar)" in code
    # unsupported constructs FAIL the evaluation (fail closed)
    assert "EvalFail" in code
    assert "refusing to approximate" in code


def test_canonical_indicator_ports_exist_and_runner_uses_them():
    ind = _code(INCLUDE / "DslIndicators.mqh")
    # ONLY the kinds the committed fixtures + channels need are ported;
    # SMA/BBANDS/MACD are deliberately absent (loader refuses them).
    for fn in ("DslEma", "DslRsi", "DslAtr", "DslDonchian", "DslHighest",
               "DslLowest", "DslNumpySum"):
        assert f"{fn}(" in ind, fn
    for absent in ("DslSma(", "DslBollinger(", "DslMacd("):
        assert absent not in ind, absent
    # the shared series builder computes DONCHIAN/HIGHEST/LOWEST, not stubs
    series = _code(INCLUDE / "DslSeries.mqh")
    for call in ("DslDonchian(", "DslHighest(", "DslLowest("):
        assert call in series, call
    assert "TODO(owner)" not in (INCLUDE / "DslSeries.mqh").read_text()
    assert "unsupported indicator kind" in series
    # the runner exports the FULL parity trace with provenance
    runner = _code(SCRIPTS / "DslParityRunner.mq5")
    assert "TODO(owner)" not in (SCRIPTS / "DslParityRunner.mq5").read_text()
    plain = runner.replace('\\"', '"')
    for field in ('"position_hash":', '"events":', '"exit_geometry":',
                  '"positions":', '"bundle_hash":', '"ohlc_sha256":'):
        assert field in plain, field
    # no CopyRates / live-history path in the runner (fixture bytes only)
    assert "CopyRates" not in runner


def test_bundle_loader_has_no_unverified_acceptance_path():
    """The old fail mode: a bundle with bundle_hash PRESENT was
    accepted without verification.  The Load() path must now derive
    and compare before reaching the spec."""
    code = _code(INCLUDE / "DslBundle.mqh")
    load_body = code[code.index("bool              Load("):]
    derive_at = load_body.index("DeriveBundleHash")
    spec_ok_at = load_body.index("m_spec = spec")
    assert derive_at < spec_ok_at


# ---------------------------------------------------------------------------
# Reserved-keyword collision guard
#
# The HOTFIX cause: ``input`` (an MQL5 reserved keyword) was used as a local
# variable name in DslBundle.mqh::DeriveSpecHash, breaking the owner's strict
# compile ("error 149: unexpected token").  This scanner fails if ANY MQL5
# reserved word is declared as a variable/parameter name anywhere under
# ``mql5/`` — so that class of compile break cannot silently return.  It is
# deliberately conservative: it only flags a reserved word sitting in the
# *name* position of a declaration (after a type/qualifier, before a
# declarator terminator), never a legitimate use as a type, qualifier, or
# operator (``const int x``, ``new Foo()``, ``delete p``, ``return x`` all
# pass).
# ---------------------------------------------------------------------------

# MQL5 reserved words that must never be used as a declared identifier.
MQL5_RESERVED = frozenset({
    # data types
    "bool", "char", "uchar", "short", "ushort", "int", "uint", "long",
    "ulong", "double", "float", "string", "datetime", "color", "void",
    "matrix", "vector", "complex",
    # keywords / specifiers
    "break", "case", "class", "const", "continue", "default", "delete",
    "do", "else", "enum", "export", "extern", "false", "for", "if",
    "input", "new", "operator", "override", "private", "protected",
    "public", "return", "sinput", "sizeof", "static", "struct", "switch",
    "template", "this", "true", "typename", "virtual", "volatile", "while",
    "final", "register", "group",
})

# Builtin type tokens that can open a declaration (so the next token is a name).
_MQL5_BUILTIN_TYPES = frozenset({
    "bool", "char", "uchar", "short", "ushort", "int", "uint", "long",
    "ulong", "double", "float", "string", "datetime", "color", "void",
    "matrix", "vector", "complex",
})

# TYPE token: a builtin type OR a user type (Uppercase-first identifier —
# the codebase convention for classes/structs/enums, e.g. CDslJson, MqlTick,
# ENUM_TIMEFRAMES).  A declaration is TYPE [&|*] NAME <declarator-terminator>.
_TYPE_RE = (r"(?:" + "|".join(sorted(_MQL5_BUILTIN_TYPES, key=len,
            reverse=True)) + r"|[A-Z]\w*)")
_RESERVED_RE = "|".join(sorted(MQL5_RESERVED, key=len, reverse=True))
_DECL_RE = re.compile(
    r"\b" + _TYPE_RE + r"\s*[&*]?\s*\b(" + _RESERVED_RE + r")\b\s*(?=[;,=\[\)])"
)


def _strip_comments_and_literals(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    text = re.sub(r'"(\\.|[^"\\])*"', '""', text)
    text = re.sub(r"'(\\.|[^'\\])*'", "''", text)
    return text


def test_no_mql5_reserved_word_declared_as_identifier():
    violations = []
    for path in sorted((ROOT / "mql5").rglob("*.mq*")):
        clean = _strip_comments_and_literals(path.read_text(encoding="utf-8"))
        for m in _DECL_RE.finditer(clean):
            line = clean[:m.start()].count("\n") + 1
            violations.append(
                f"{path.relative_to(ROOT)}:{line}: reserved word "
                f"'{m.group(1)}' used as identifier — '{m.group(0).strip()}'"
            )
    assert not violations, (
        "MQL5 reserved keyword(s) declared as variable/parameter names "
        "(will break the owner strict compile):\n" + "\n".join(violations)
    )


def test_reserved_word_guard_is_not_vacuous():
    """The guard must actually flag the exact HOTFIX bug pattern and
    common declaration forms, while leaving legitimate uses alone."""
    def flagged(snippet: str) -> bool:
        return bool(_DECL_RE.search(_strip_comments_and_literals(snippet)))

    assert flagged('string input = "x";')          # the original bug
    assert flagged("int export;")
    assert flagged("void Fn(double input, int color) {}")
    assert flagged("MqlTick &new;")
    # legitimate uses must not trip the guard
    assert not flagged("const int x = 3;")
    assert not flagged("static double y;")
    assert not flagged("input double Lots = 0.1;")
    assert not flagged("virtual void Foo();")
    assert not flagged("new CDslJson();")
    assert not flagged("delete ptr;")
    assert not flagged("return x;")
