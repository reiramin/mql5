"""FILL-MODE-1: the EA picks a filling mode the broker actually allows.

gate_run40 (restart demo run): every open was rejected with INVALID_FILL /
"[Unsupported filling mode]". SpecIsFillingAllowed tested the
ENUM_ORDER_TYPE_FILLING *index* (FOK 0, IOC 1, RETURN 2) as a bit of the
SYMBOL_FILLING_MODE *flag mask* (SYMBOL_FILLING_FOK 1, SYMBOL_FILLING_IOC 2).
On EURUSD (mask 1, gate_run44 parity_report.json) it therefore sent IOC and
had nothing to fall back to.

The three selection functions are EXECUTED here from
mql5/Include/Mql5Bot/SymbolSpec.mqh: a strict line transpiler turns their
one-`if`/one-`return`-per-line MQL5 into Python and refuses any other line,
so these tests read the source the EA compiles, not a mirror of it.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
MQL5 = REPO / "mql5"
SPEC = (MQL5 / "Include/Mql5Bot/SymbolSpec.mqh").read_text(encoding="utf-8")
TM = (MQL5 / "Include/Mql5Bot/TradeManager.mqh").read_text(encoding="utf-8")
EA = (MQL5 / "Experts/Mql5Bot/Mql5Bot.mq5").read_text(encoding="utf-8")

# MQL5 reference values
FOK, IOC, RETURN, NONE = 0, 1, 2, -1            # ENUM_ORDER_TYPE_FILLING
REQUEST, INSTANT, MARKET, EXCHANGE = 0, 1, 2, 3  # ENUM_SYMBOL_TRADE_EXECUTION
CONST = {
    "ORDER_FILLING_FOK": FOK, "ORDER_FILLING_IOC": IOC,
    "ORDER_FILLING_RETURN": RETURN,
    "SYMBOL_FILLING_FOK": 1, "SYMBOL_FILLING_IOC": 2,
    "SYMBOL_TRADE_EXECUTION_REQUEST": REQUEST,
    "SYMBOL_TRADE_EXECUTION_INSTANT": INSTANT,
    "SYMBOL_TRADE_EXECUTION_MARKET": MARKET,
    "SYMBOL_TRADE_EXECUTION_EXCHANGE": EXCHANGE,
}


def _function(name: str) -> tuple[str, list[str]]:
    """Signature and body lines of a top-level MQL5 function."""
    m = re.search(rf"^\S[^\n]*\b{name}\((?P<params>[^)]*)\)\s*\n  \{{\n"
                  rf"(?P<body>.*?)\n  \}}\n", SPEC, re.DOTALL | re.MULTILINE)
    assert m, f"{name} not found in SymbolSpec.mqh"
    params = [p.split()[-1].lstrip("&") for p in m["params"].split(",")]
    return f"def {name}({', '.join(params)}):", m["body"].split("\n")


def _expr(text: str) -> str:
    text = text.replace("(ENUM_ORDER_TYPE_FILLING)-1", "-1")
    text = text.replace("(long)", "")                # integer casts: no-ops
    text = text.replace("&&", " and ").replace("||", " or ")
    for k, v in CONST.items():
        text = re.sub(rf"\b{k}\b", str(v), text)
    assert not re.search(r"\b[A-Z][A-Z_]{3,}\b", text), \
        f"unmapped constant in {text!r}"
    assert "!" not in text.replace("!=", ""), f"bare ! in {text!r}"
    return text


def _transpile(name: str) -> str:
    head, body = _function(name)
    out = [head]
    for line in body:
        indent = len(line) - len(line.lstrip(" "))
        code = line.strip()
        assert indent % 3 == 0, f"{name}: odd indent {line!r}"
        pad = "    " * (indent // 3)
        if m := re.fullmatch(r"if\((.*)\)", code):
            out.append(f"{pad}if {_expr(m[1])}:")
        elif m := re.fullmatch(r"return (.*);", code):
            out.append(f"{pad}return {_expr(m[1])}")
        else:
            raise AssertionError(f"{name}: line the transpiler refuses: "
                                 f"{line!r}")
    return "\n".join(out)


NS: dict = {}
for _fn in ("SpecIsFillingAllowed", "SpecPreferredFilling",
            "SpecNextFilling"):
    exec(_transpile(_fn), NS)                       # noqa: S102


def spec(mask: int, exemode: int) -> SimpleNamespace:
    return SimpleNamespace(fillingMode=mask, executionMode=exemode)


def allowed(mask: int, exemode: int) -> list[int]:
    return [f for f in (FOK, IOC, RETURN)
            if NS["SpecIsFillingAllowed"](spec(mask, exemode), f)]


# masks 1, 2, 3 (and 0) x every execution mode; written out, not computed:
# FOK/IOC from their flags, RETURN in every mode but Market execution
TABLE = [
    # mask exemode    allowed               preferred
    (1, REQUEST,  [FOK, RETURN],       FOK),
    (1, INSTANT,  [FOK, RETURN],       FOK),
    (1, MARKET,   [FOK],               FOK),
    (1, EXCHANGE, [FOK, RETURN],       FOK),
    (2, REQUEST,  [IOC, RETURN],       IOC),
    (2, INSTANT,  [IOC, RETURN],       IOC),
    (2, MARKET,   [IOC],               IOC),
    (2, EXCHANGE, [IOC, RETURN],       IOC),
    (3, REQUEST,  [FOK, IOC, RETURN],  FOK),
    (3, INSTANT,  [FOK, IOC, RETURN],  FOK),
    (3, MARKET,   [FOK, IOC],          FOK),
    (3, EXCHANGE, [FOK, IOC, RETURN],  FOK),
    (0, REQUEST,  [RETURN],            RETURN),
    (0, INSTANT,  [RETURN],            RETURN),
    (0, MARKET,   [],                  NONE),
    (0, EXCHANGE, [RETURN],            RETURN),
]


@pytest.mark.parametrize("mask,exemode,want_allowed,want_pref", TABLE)
def test_allowed_and_preferred_per_mask_and_execution_mode(
        mask, exemode, want_allowed, want_pref):
    assert allowed(mask, exemode) == want_allowed
    assert NS["SpecPreferredFilling"](spec(mask, exemode)) == want_pref
    # the preferred mode is always one the broker allows
    assert want_pref == NONE or want_pref in allowed(mask, exemode)


def test_gate_run40_eurusd_fok_only_market_execution_sends_fok():
    # EURUSD filling_mode_mask 1 (gate_run44 live export), Market execution
    s = spec(1, MARKET)
    assert NS["SpecPreferredFilling"](s) == FOK
    assert not NS["SpecIsFillingAllowed"](s, IOC)   # what the bug sent
    assert NS["SpecNextFilling"](s, FOK) == NONE


@pytest.mark.parametrize("mask,exemode,current,want", [
    (3, MARKET, FOK, IOC),
    (3, EXCHANGE, FOK, IOC),
    (1, MARKET, FOK, NONE),
    (1, EXCHANGE, FOK, RETURN),
    (2, REQUEST, IOC, RETURN),
    (2, MARKET, IOC, NONE),
    (3, EXCHANGE, RETURN, NONE),      # never re-sends the same mode
    (0, INSTANT, RETURN, NONE),
])
def test_next_filling_moves_strictly_forward_to_an_allowed_mode(
        mask, exemode, current, want):
    nxt = NS["SpecNextFilling"](spec(mask, exemode), current)
    assert nxt == want
    assert nxt == NONE or (nxt > current and nxt in allowed(mask, exemode))


def test_the_spec_carries_the_execution_mode():
    assert "long              executionMode;" in SPEC
    assert ("out.executionMode     = SymbolInfoInteger(symbol, "
            "SYMBOL_TRADE_EXEMODE);") in SPEC


def test_choose_filling_logs_once_per_symbol_and_falls_back_to_fok():
    i = SPEC.index("ENUM_ORDER_TYPE_FILLING SpecChooseFilling(")
    body = SPEC[i:SPEC.index("\n  }\n", i)]
    assert "SpecPreferredFilling(spec)" in body
    assert "filling = ORDER_FILLING_FOK;" in body          # none allowed
    # once per symbol: a registry checked before the single PrintFormat
    assert body.index("if(g_specFillingLogged[i] == spec.name)") \
        < body.index("PrintFormat(")
    assert body.count("PrintFormat(") == 1
    assert '"[mql5bot] FILLING|%s|%s|filling_mode_mask=%I64d|exemode=%I64d%s"' \
        in body


def _code(text: str) -> str:
    """Source without // comments and string literals."""
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    return re.sub(r"//[^\n]*", "", text)


def test_no_hard_coded_filling_mode_in_a_live_order_path():
    for path in sorted(MQL5.rglob("*.mq*")):
        rel = path.relative_to(REPO).as_posix()
        code = _code(path.read_text(encoding="utf-8", errors="replace"))
        if rel != "mql5/Include/Mql5Bot/SymbolSpec.mqh":
            assert not re.search(r"\bORDER_FILLING_(FOK|IOC|RETURN|BOC)\b",
                                 code), f"hard-coded filling mode in {rel}"
        for rhs in re.findall(r"\btype_filling\s*=\s*([^;]+);", code):
            rhs = rhs.strip()
            assert rhs == "filling" or rhs.startswith("SpecChooseFilling("), \
                f"{rel}: type_filling = {rhs}"


def test_every_live_deal_chooses_through_spec_choose_filling():
    tm = _code(TM)
    # TradeManager opens and closes
    assert tm.count("SpecChooseFilling(m_spec)") == 2
    assert "SpecPreferredFilling(" not in tm
    # the demo probe orders (DemoCloseAll, DemoForeignOrder)
    ea = _code(EA)
    for fn in ("int DemoCloseAll()", "bool DemoForeignOrder("):
        i = ea.index(fn)
        body = ea[i:ea.index("\n  }\n", i)]
        assert "req.type_filling = SpecChooseFilling(g_spec);" in body, fn
