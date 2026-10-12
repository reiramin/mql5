"""SPEC-WAIT-1 (owner decision 2026-10-12, CLAUDE.md exception 1.d).

gate_run56 (32664ac, FULL run): gold1 18/18 and gold2 37/37 MATCH, 7 of 8
safety results VALID. restart was MISSING: on the probe-3 relaunch the EA
failed OnInit with "symbol spec build failed: tick_value_loss <= 0" (init
code 1) while the terminal journal shows "connection to MetaQuotes-Demo
lost" twice. The EA failed safe, but a restart during a slow broker
connection left an open position unmanaged.

Now a LIVE start on a symbol that is not synchronized yet waits in
WAITING_SYMBOL: INIT_SUCCEEDED, no orders, no management, no START line,
the spec build retried on OnTimer/OnTick, bounded by InpSpecWaitSeconds
(default 60). In the Strategy Tester a failed build fails init exactly as
before, so the gold legs are unchanged.

The three decision functions are EXECUTED here from
mql5/Include/Mql5Bot/SymbolSpec.mqh through a strict line transpiler
(one `if(...)` / one `return ...;` per line, anything else refused), so
the tests read the source the EA compiles.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from mql5bot import mt5tester as mt

REPO = Path(__file__).resolve().parents[1]
SPEC = (REPO / "mql5/Include/Mql5Bot/SymbolSpec.mqh").read_text("utf-8")
EA = (REPO / "mql5/Experts/Mql5Bot/Mql5Bot.mq5").read_text("utf-8")
CONST = {m.group(1): int(m.group(2)) for m in re.finditer(
    r"^#define (SPEC_WAIT_\w+)\s+(\d+)$", SPEC, re.MULTILINE)}
READY, WAIT, GIVE_UP = (CONST["SPEC_WAIT_READY"], CONST["SPEC_WAIT_WAIT"],
                        CONST["SPEC_WAIT_GIVE_UP"])


def _expr(text: str) -> str:
    text = text.replace("&&", " and ").replace("||", " or ")
    text = re.sub(r"!(?!=)", " not ", text)
    text = re.sub(r"\btrue\b", "True", text)
    text = re.sub(r"\bfalse\b", "False", text)
    for k, v in CONST.items():
        text = re.sub(rf"\b{k}\b", str(v), text)
    assert not re.search(r"\b[A-Z][A-Z_]{3,}\b", re.sub(r'"[^"]*"', "", text)), \
        f"unmapped constant in {text!r}"
    return text


def _transpile(name: str) -> str:
    m = re.search(rf"^\S[^\n]*\b{name}\((?P<params>[^)]*)\)\s*\n  \{{\n"
                  rf"(?P<body>.*?)\n  \}}\n", SPEC, re.DOTALL | re.MULTILINE)
    assert m, f"{name} not found in SymbolSpec.mqh"
    params = [p.split()[-1] for p in m["params"].split(",")]
    out = [f"def {name}({', '.join(params)}):"]
    for line in m["body"].split("\n"):
        indent = len(line) - len(line.lstrip(" "))
        code = line.strip()
        assert indent % 3 == 0, f"{name}: odd indent {line!r}"
        pad = "    " * (indent // 3)
        if c := re.fullmatch(r"if\((.*)\)", code):
            out.append(f"{pad}if {_expr(c[1])}:")
        elif c := re.fullmatch(r"return (.*);", code):
            out.append(f"{pad}return {_expr(c[1])}")
        else:
            raise AssertionError(f"{name}: line the transpiler refuses: "
                                 f"{line!r}")
    return "\n".join(out)


NS: dict = {}
for _fn in ("SpecReasonIsUnsynced", "SpecMayWait", "SpecWaitDecision"):
    exec(_transpile(_fn), NS)                       # noqa: S102


# --------------------------------------------------------------------------
# the decision functions
# --------------------------------------------------------------------------

@pytest.mark.parametrize("reason,want", [
    ("point <= 0", True), ("tick_size <= 0", True),
    ("tick_value_loss <= 0", True), ("tick_value_profit <= 0", True),
    ("contract_size <= 0", True),
    ("volume_min <= 0", False), ("invalid digits", False),
    ("missing currency info", False), ("", False),
])
def test_unsynced_reasons(reason, want):
    assert NS["SpecReasonIsUnsynced"](reason) is want


def test_never_waits_in_the_tester():
    for synced in (True, False):
        for reason in ("tick_value_loss <= 0", "volume_min <= 0"):
            assert NS["SpecMayWait"](True, synced, reason) is False


def test_waits_live_when_unsynced_or_not_synchronized():
    assert NS["SpecMayWait"](False, True, "tick_value_loss <= 0") is True
    assert NS["SpecMayWait"](False, False, "volume_min <= 0") is True
    # a synchronized symbol with a real spec defect never waits
    assert NS["SpecMayWait"](False, True, "volume_min <= 0") is False


class FakeSymbol:
    """A symbol whose tick value reads 0 until it synchronizes after
    ``sync_after`` build attempts (or never, with None)."""

    def __init__(self, sync_after: int | None):
        self.calls, self.sync_after = 0, sync_after

    def build(self) -> tuple[bool, bool, str]:
        """(built, synchronized, reason) -- one BuildSymbolSpec call."""
        self.calls += 1
        synced = self.sync_after is not None and self.calls > self.sync_after
        return (synced, synced, "" if synced else "tick_value_loss <= 0")


def _run(sym: FakeSymbol, limit_s: int, in_tester: bool = False):
    """OnInit + one SpecWaitPump per second, as the EA wires them.
    Returns (init_result, trace, seconds_waited)."""
    built, synced, reason = sym.build()
    if built:
        return "INIT_SUCCEEDED", ["START"], 0
    if not NS["SpecMayWait"](in_tester, synced, reason):
        return "INIT_FAILED", [], 0
    trace = ["WAITING_SYMBOL"]
    waited = 0
    while True:
        waited += 1                                    # OnTimer, 1 s
        built, synced, reason = sym.build()
        waitable = built or NS["SpecMayWait"](False, synced, reason)
        step = NS["SpecWaitDecision"](built, waitable, waited, limit_s)
        if step == WAIT:
            continue
        trace.append("START" if step == READY else "GAVE_UP")
        return "INIT_SUCCEEDED", trace, waited


def test_symbol_that_syncs_after_n_calls_starts_once_built():
    init, trace, waited = _run(FakeSymbol(sync_after=7), limit_s=60)
    assert init == "INIT_SUCCEEDED"
    assert trace == ["WAITING_SYMBOL", "START"]       # START only once built
    assert waited == 7


def test_symbol_that_never_syncs_gives_up_at_the_bound():
    sym = FakeSymbol(sync_after=None)
    init, trace, waited = _run(sym, limit_s=60)
    assert init == "INIT_SUCCEEDED"
    assert trace == ["WAITING_SYMBOL", "GAVE_UP"]
    assert waited == 60
    assert sym.calls == 61                             # bounded retries


def test_tester_fails_init_exactly_as_before():
    init, trace, _ = _run(FakeSymbol(sync_after=3), limit_s=60,
                          in_tester=True)
    assert (init, trace) == ("INIT_FAILED", [])


def test_a_synced_spec_starts_at_once():
    assert _run(FakeSymbol(sync_after=0), 60) == ("INIT_SUCCEEDED",
                                                   ["START"], 0)


# --------------------------------------------------------------------------
# the EA wiring
# --------------------------------------------------------------------------

def _body(sig: str) -> str:
    i = EA.index(sig)
    return EA[i:EA.index("\n  }\n", i)]


def test_input_default_and_python_mirror():
    assert re.search(r"^input int\s+InpSpecWaitSeconds = 60;", EA,
                     re.MULTILINE)
    assert mt.EA_INPUT_DEFAULTS["InpSpecWaitSeconds"] == 60


def test_oninit_waits_only_on_a_waitable_failure():
    init = _body("int OnInit()")
    i = init.index("if(!BuildSymbolSpec(g_symbol, g_spec))")
    branch = init[i:]
    assert ("bool inTester = MQLInfoInteger(MQL_TESTER) != 0 ||\n"
            "                      MQLInfoInteger(MQL_OPTIMIZATION) != 0;"
            ) in branch
    assert ("if(!SpecMayWait(inTester, SymbolIsSynchronized(g_symbol), "
            "g_spec.reason))") in branch
    # not waitable: the former failure, unchanged
    assert branch.index('g_log.Error("symbol spec build failed: " + '
                        'g_spec.reason);') < branch.index("return INIT_FAILED;")
    assert "g_specWaiting   = true;" in branch
    assert branch.index("EventSetTimer(1);") < branch.index(
        "return INIT_SUCCEEDED;")
    assert init.rstrip().endswith("return InitAfterSpec();")


def test_start_line_and_trading_setup_only_after_the_spec_is_built():
    after = EA[EA.index("int InitAfterSpec()"):]
    after = after[:after.index("\n  }\n")]
    assert "TEST demo: START probe=%d" in after
    assert "g_trade.Init(" in after
    oninit = _body("int OnInit()")
    assert "TEST demo: START" not in oninit
    assert "g_trade.Init(" not in oninit


@pytest.mark.parametrize("sig", ["void OnTimer()", "void OnTick()"])
def test_handlers_only_pump_while_waiting(sig):
    body = _body(sig)
    first = body.index("{") + 1
    assert body[first:].lstrip().startswith("if(g_specWaiting)")
    guard = body[first:body.index("return;", first)]
    assert "SpecWaitPump();" in guard


def test_trade_transactions_ignored_while_waiting():
    body = _body("void OnTradeTransaction(")
    first = body.index("{") + 1
    assert body[first:].lstrip().startswith(
        "if(g_specWaiting)           // SPEC-WAIT-1: no magic/registry yet\n"
        "      return;")


def test_pump_runs_the_deferred_init_or_gives_up_bounded():
    pump = _body("void SpecWaitPump()")
    assert "SpecWaitDecision(built, waitable, waited, InpSpecWaitSeconds)" \
        in pump
    assert "if(InitAfterSpec() == INIT_SUCCEEDED)" in pump
    assert "gave up after %d s " in pump and "WAITING_SYMBOL)" in pump
    assert pump.rstrip().endswith("ExpertRemove();")
