"""IMPORT-SELFHEAL-1 (owner request 2026-10-13, CLAUDE.md exception 1.e).

gate_run58 (ab312d5, FULL run) stopped at stage 4:

    [import] EURUSD.G2 REFUSED [symbol_state]: adopt-in-place:
    CustomRatesDelete left 5760 bar(s) on EURUSD.G2; a prior fixture's
    bars must never survive into this dataset (last_error=0)

The owner deleted EURUSD.G2 by hand, and gate_run59 imported it
``created_fresh`` and certified. The importer now does that itself:

- When the adopt wipe leaves bars behind, it drops the survivor through
  the hardened ``DropCustomSymbolChecked``: it closes other charts, polls
  the asynchronous ChartClose, makes a bounded deselect, a bounded delete
  and a SymbolExist verify.
- It then recreates the symbol on the created-fresh path, and the record
  carries ``selfheal_leftover_bars``.
- It refuses only when that drop fails too, naming both the leftover bars
  and the failing call.
- A freshly created symbol that still shows bars refuses as well, so no
  prior fixture's bar ever survives into the dataset.

These are source pins on the importer the gate compiles (stage 1 strict
compile is its compile proof). Built, unit-tested, never run live.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = (REPO / "mql5/Scripts/Mql5Bot/Mql5BotImportFixture.mq5").read_text(
    encoding="utf-8")
BODY = SRC[SRC.index("void OnStart()"):]


def _leftover_block() -> str:
    i = BODY.index("if(leftoverBars > 0)")
    return BODY[i:BODY.index("if(needCreate)", i)]


def test_leftover_bars_drop_and_recreate_instead_of_refusing():
    blk = _leftover_block()
    assert "DropCustomSymbolChecked(sym, wc, le)" in blk
    # only after a successful drop does the import switch to the fresh path
    i = blk.index("DropCustomSymbolChecked(sym, wc, le)")
    after = blk[blk.index("return; }", i):]
    for line in ("g_selfHealBars   = leftoverBars;",
                 'g_symbolState    = "unresolved";',
                 "needCreate       = true;", "adopted          = false;",
                 "adoptDiffs       = 0;", "g_adoptRewritten = -1;"):
        assert line in after, line


def test_a_failed_drop_still_refuses_naming_bars_and_call():
    blk = _leftover_block()
    i = blk.index("if(!DropCustomSymbolChecked(sym, wc, le))")
    refusal = blk[i:blk.index("return; }", i)]
    assert 'RefuseAt(outPath, sym, "symbol_state",' in refusal
    for text in ("adopt-in-place: CustomRatesDelete left ",
                 " bar(s) on ", "self-heal drop failed: ", "+wc+",
                 "g_dropAttempts", "must never survive into this",
                 "Operator remediation"):
        assert text in refusal, text
    # the refusal reports the drop's error and the state it was in
    assert refusal.rstrip().endswith("le);")
    assert "g_symbolState" not in refusal


def test_the_recreate_runs_the_unchanged_fresh_path():
    i = BODY.index("if(leftoverBars > 0)")
    order = [BODY.index(x, i) for x in (
        "DropCustomSymbolChecked(sym, wc, le)", "needCreate       = true;",
        "if(needCreate)", "CustomSymbolCreate(sym, InpSymbolGroup)",
        'g_symbolState = "created_fresh";', "int freshBars = Bars(sym, tf);",
        "ApplySymbolProperties(sym")]
    assert order == sorted(order), order


def test_a_fresh_symbol_with_bars_refuses():
    i = BODY.index('g_symbolState = "created_fresh";')
    blk = BODY[i:BODY.index("\n     }\n", i)]
    assert "int freshBars = Bars(sym, tf);" in blk
    assert "if(freshBars > 0)" in blk
    assert 'RefuseAt(outPath, sym, "symbol_state",' in blk
    assert "must never survive into this dataset" in blk
    assert "CleanupAfterFail(sym)" in blk          # no debris left behind


def test_the_record_names_the_self_heal_on_both_writers():
    fn = SRC[SRC.index("string SymbolStateJson()"):]
    fn = fn[:fn.index("\n  }\n")]
    assert "if(g_selfHealBars >= 0)" in fn
    assert '\\"selfheal_leftover_bars\\":' in fn
    assert "int    g_selfHealBars   = -1;" in SRC
    # both the refusal and the success record carry SymbolStateJson()
    assert SRC.count("SymbolStateJson()") >= 3


def test_the_adopt_wipe_and_the_broker_symbol_refusal_are_unchanged():
    # the wipe and its zero-bar check still run first on every adopt
    i = BODY.index("CustomRatesDelete(sym, 0, LONG_MAX);")
    assert BODY.index("int leftoverBars = Bars(sym, tf);", i) < \
        BODY.index("if(leftoverBars > 0)", i)
    # a NON-custom (broker) symbol is never dropped or shadowed
    j = BODY.index("if(!isCustom)")
    broker = BODY[j:BODY.index("return; }", j)]
    assert "refusing to shadow a broker symbol" in broker
    assert j < BODY.index("DropCustomSymbolChecked(sym")
    # the round-trip dataset-hash check that earns the PASS is untouched
    assert "!= manifest dataset_hash" in SRC
