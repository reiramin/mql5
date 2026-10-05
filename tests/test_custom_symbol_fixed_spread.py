"""Owner authorization (Sal, 2026-10-05): a scoped mql5/ exception for
EXACTLY mql5/Scripts/Mql5Bot/Mql5BotImportFixture.mq5 and
mql5/Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5.

gate_run34 (HEAD a17aed7): the custom symbol exported spread_points 0
while the tester filled every buy at bid + 2 points; the manifest spread
is 1.

Importer: SYMBOL_SPREAD_FLOAT=false and SYMBOL_SPREAD = manifest
cost_config.spread_points (refused if not an integer), rates[i].spread the
same value, both read back into verified_properties, mirrored in the adopt
precheck (counted in adopt_properties_rewritten); the round-trip dataset
hash check is unchanged.

Exporter: a custom symbol skips the 60 s sync wait and writes both probes
as {ok:false, reason:"NOT_APPLICABLE_CUSTOM_SYMBOL_BARS_ONLY"};
custom_fixed_spread_points = SYMBOL_SPREAD when SYMBOL_SPREAD_FLOAT is
false; a flat "tick_value" (SYMBOL_TRADE_TICK_VALUE).

Gate: the custom symbol's NOT_APPLICABLE probe is RECORDED at stage 4,
never failed.

MQL5 cannot be compiled on this host (no metaeditor64.exe): the .mq5 edits
are source-pinned here; the strict-compile 0/0 proof is the owner's stage-1
gate. Built, unit-tested, never run live.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from mql5bot import gate_selfcheck as gs

REPO = Path(__file__).resolve().parents[1]
IMPORTER = (REPO / "mql5/Scripts/Mql5Bot/Mql5BotImportFixture.mq5"
            ).read_text(encoding="utf-8")
EXPORTER = (REPO / "mql5/Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5"
            ).read_text(encoding="utf-8")
PS1 = (REPO / "tools/owner_gate.ps1").read_text(encoding="utf-8")
NA = "NOT_APPLICABLE_CUSTOM_SYMBOL_BARS_ONLY"


def _function(src: str, head: str) -> str:
    """Body of the MQL5 function whose signature starts with ``head``."""
    i = src.index(head)
    j = src.index("\n  }\n", i)
    return src[i:j]


# ------------------------------------------------------------- importer

def test_importer_sets_fixed_spread_float_first_then_value():
    body = _function(IMPORTER, "bool ApplySymbolProperties(")
    assert "const long spreadPoints)" in body
    f = body.index('SetI(sym, SYMBOL_SPREAD_FLOAT, "SYMBOL_SPREAD_FLOAT", 0,')
    v = body.index('SetI(sym, SYMBOL_SPREAD, "SYMBOL_SPREAD", spreadPoints,')
    assert f < v
    assert '"manifest.cost_config.spread_points");' in body[v:]


def test_importer_adopt_precheck_mirrors_both_spread_properties():
    body = _function(IMPORTER, "int CountPropertyDiffs(")
    assert 'DiffI(sym, SYMBOL_SPREAD_FLOAT, "SYMBOL_SPREAD_FLOAT", 0);' in body
    assert ('DiffI(sym, SYMBOL_SPREAD, "SYMBOL_SPREAD", spreadPoints);'
            in body)
    # a differing spread forces the re-apply, counted on the record
    assert "g_adoptRewritten = adoptDiffs;" in IMPORTER
    assert "if(needCreate || adoptDiffs > 0)" in IMPORTER
    # both call sites pass the spread
    assert IMPORTER.count("ccyMargin, spreadPoints)") == 2


def test_importer_spread_comes_from_the_manifest_and_must_be_an_integer():
    i = IMPORTER.index('int ccfg = man.Member(mroot, "cost_config");')
    block = IMPORTER[i:IMPORTER.index("long spreadPoints = (long)spreadCfg;",
                                      i)]
    assert 'ReqNum(man, ccfg, "spread_points", spreadCfg, missing)' in block
    assert "spreadCfg != MathFloor(spreadCfg)" in block
    assert "spreadCfg < 0.0" in block
    assert block.count('RefuseAt(outPath, sym, "collect_properties",') == 2
    assert "refused, never rounded" in block


def test_importer_bars_carry_the_fixed_spread():
    assert "rates[i].spread       = (int)spreadPoints;" in IMPORTER
    assert "rates[i].spread       = 0;" not in IMPORTER


def test_importer_reads_both_back_into_verified_properties():
    i = IMPORTER.index("---- 3b. verify_properties")
    block = IMPORTER[i:IMPORTER.index("if(!vok)", i)]
    assert ('vok = VerI(sym, SYMBOL_SPREAD_FLOAT, "SYMBOL_SPREAD_FLOAT", 0) '
            '&& vok;') in block
    assert ('vok = VerI(sym, SYMBOL_SPREAD, "SYMBOL_SPREAD", spreadPoints) '
            '&& vok;') in block


def test_importer_roundtrip_hash_check_unchanged_and_spread_free():
    assert "if(roundtripSha != datasetHash)" in IMPORTER
    # the round-trip serialisation is OHLC + tick volume: a bar's spread
    # field cannot move the dataset hash
    sig = re.search(r"string SerializeCsv\(([^)]*)\)", IMPORTER)
    assert sig and "spread" not in sig.group(1).lower()


def test_python_stage4_classifier_accepts_the_new_rows_only_when_ok():
    base = {"derived_tick_values": {"properties": [
        {"enum": e, "readback": "0"} for e in gs.DERIVED_TICK_VALUE_ENUMS]}}
    rows = [{"enum": "SYMBOL_SPREAD_FLOAT", "expected": "0", "ok": True,
             "readback": "0"},
            {"enum": "SYMBOL_SPREAD", "expected": "1", "ok": True,
             "readback": "1"}]
    assert gs.properties_verified(dict(base, verified_properties=rows))["ok"]
    rows[1] = dict(rows[1], ok=False, readback="0")
    bad = gs.properties_verified(dict(base, verified_properties=rows))
    assert bad["ok"] is False and "SYMBOL_SPREAD" in bad["reason"]


# ------------------------------------------------------------- exporter

def test_exporter_custom_symbol_skips_the_sync_wait_and_probes():
    assert f'#define PROBE_NA_CUSTOM     "{NA}"' in EXPORTER
    main = _function(EXPORTER, "void Main()")
    assert ("bool isCustom = (SymbolInfoInteger(sym, SYMBOL_CUSTOM) != 0);"
            in main)
    assert ("string syncUnmet = isCustom ? PROBE_NA_CUSTOM : "
            "WaitForSymbolReady(sym);") in main
    assert "if(mid > 0.0 && !isCustom)" in main
    assert "int denomMaxAttempts = isCustom ? 0 : DENOM_RETRY_MAX;" in main
    assert main.count("bool isCustom") == 1


def test_exporter_custom_probe_json_is_ok_false_with_the_reason():
    main = _function(EXPORTER, "void Main()")
    i = main.index("   if(isCustom)\n     {\n      //--- bars-only custom")
    block = main[i:main.index("   else\n", i)]
    for probe in ("margin_probe", "denomination_probe"):
        k = block.index(f'JsonQuote("{probe}")')
        seg = block[k:k + 300]
        assert 'JsonQuote("ok") + ": false,' in seg
        assert 'JsonQuote("reason") + ": " + JsonQuote(PROBE_NA_CUSTOM)' in seg


def test_exporter_flat_tick_value_and_fixed_spread():
    assert ('j += "  " + JsonQuote("tick_value") + ": " + DoubleToString('
            'SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE), 12)') in EXPORTER
    assert ('JsonQuote("custom_fixed_spread_points") + ": " + ((isCustom && '
            '!spreadFloat) ? IntegerToString(spreadPoints) : "null")'
            in EXPORTER)
    assert ("long spreadPoints = SymbolInfoInteger(sym, SYMBOL_SPREAD);"
            in EXPORTER)


def test_exporter_custom_symbol_document_parses(tmp_path):
    """The custom branch's JSON skeleton, rendered the way the exporter
    concatenates it, is a valid document with both probes NOT_APPLICABLE."""
    main = _function(EXPORTER, "void Main()")
    i = main.index("   if(isCustom)\n     {\n      //--- bars-only custom")
    block = main[i:main.index("   else\n", i)]
    parts = re.findall(r'j \+= (.*);', block)
    text = ""
    for expr in parts:
        # JsonQuote(x) -> a C literal whose content is the JSON string "x"
        expr = expr.replace("JsonQuote(PROBE_NA_CUSTOM)",
                            json.dumps(json.dumps(NA)))
        expr = re.sub(r'JsonQuote\("([^"]*)"\)', lambda m: json.dumps(
            json.dumps(m.group(1))), expr)
        # what remains is a '+'-chain of C string literals
        text += "".join(json.loads(lit) for lit in
                        re.findall(r'"(?:[^"\\]|\\.)*"', expr))
    doc = json.loads('{"symbol": {"name": "EURUSD.G2",\n' + text)
    assert doc["symbol"]["margin_probe"] == {"ok": False, "reason": NA}
    assert doc["symbol"]["denomination_probe"] == {"ok": False,
                                                   "reason": NA}


# ------------------------------------------------- gate (stage 4 record)

def _export(tmp_path, probes):
    doc = {"schema": "mql5bot.broker_export/1",
           "timestamp": datetime.now(timezone.utc).strftime(
               "%Y-%m-%dT%H:%M:%SZ"),
           "terminal_build": 5430, "custom_symbol": True,
           "spread_points": 1, "custom_fixed_spread_points": 1,
           "symbol": dict({"name": "EURUSD.G2"}, **probes)}
    p = tmp_path / "symbolspec_EURUSD.G2.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_freshness_records_not_applicable_probes_and_still_passes(tmp_path):
    p = _export(tmp_path, {"margin_probe": {"ok": False, "reason": NA},
                           "denomination_probe": {"ok": False,
                                                  "reason": NA}})
    start = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    out = gs.symbolspec_export_freshness(p, "EURUSD.G2", start)
    assert out["ok"] is True, out["reasons"]
    assert out["probes"] == {"margin_probe": {"ok": False, "reason": NA},
                             "denomination_probe": {"ok": False,
                                                    "reason": NA}}
    assert out["probe_note"] == (
        f"margin_probe {NA} (recorded, not a failure); "
        f"denomination_probe {NA} (recorded, not a failure)")


def test_freshness_never_judges_probes_it_only_records_them(tmp_path):
    p = _export(tmp_path, {"denomination_probe": {
        "ok": False, "reason": "BUY OrderCalcProfit failed"}})
    start = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    out = gs.symbolspec_export_freshness(p, "EURUSD.G2", start)
    assert out["ok"] is True
    assert out["probe_note"] == (
        "margin_probe absent; denomination_probe ok=False reason='BUY "
        "OrderCalcProfit failed'")


def test_ps1_stage4_records_the_probes_and_never_fails_on_them():
    fn = PS1[PS1.index("function Invoke-SymbolSpecExport"):]
    fn = fn[:fn.index("\n}\n")]
    assert '$probeNote = [string](Get-DataProp $fr.data "probe_note")' in fn
    assert "probes = $probeNote" in fn
    assert "$Script:CustomProbes = @{}" in PS1
    assert "$Script:CustomProbes[$g.gold] = $cx.probes" in PS1
    pass_line = next(ln for ln in PS1.splitlines()
                     if ln.startswith('Record-Stage 4 "fixture_import" "PASS"'))
    assert "custom-symbol probes (recorded, never failed): {1}" in pass_line
    assert "$Script:CustomProbes[$_]" in pass_line
    # no stage-4 FAIL is keyed on a probe
    s4 = PS1[PS1.index('Enter-Stage 4'):PS1.index('Enter-Stage 5')]
    assert "probe" not in "".join(
        ln for ln in s4.splitlines() if '"FAIL"' in ln).lower()


_NA_TERMINAL = r"""#!/bin/bash
ini="${1#/config:}"
sym=$(grep '^Symbol=' "$ini" | tr -d '\r' | cut -d= -f2)
out="$FAKE_DATA/MQL5/Files/Mql5Bot/broker_exports/$sym.json"
mkdir -p "$(dirname "$out")"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
na='{"ok":false,"reason":"NOT_APPLICABLE_CUSTOM_SYMBOL_BARS_ONLY"}'
printf '{"schema":"mql5bot.broker_export/1","timestamp":"%s","terminal_build":5430,"custom_symbol":true,"spread_points":1,"custom_fixed_spread_points":1,"symbol":{"name":"%s","margin_probe":%s,"denomination_probe":%s}}' "$now" "$sym" "$na" "$na" > "$out"
"""


def test_invoke_symbolspec_export_records_not_applicable_probe(tmp_path):
    """EXECUTES Invoke-SymbolSpecExport under pwsh with a fake terminal
    that writes a custom-symbol export carrying both NOT_APPLICABLE
    probes: ok, and the probe record comes back for stage 4."""
    from tests.test_gate_runs_symbolspec_exporter import _harness, _pwsh

    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    term = tmp_path / "terminal.sh"
    term.write_text(_NA_TERMINAL, encoding="ascii")
    term.chmod(term.stat().st_mode | stat.S_IEXEC)
    start = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    script = tmp_path / "harness.ps1"
    script.write_text(_harness(tmp_path, "\n".join([
        f"$Script:RunStartUtc = '{start}'",
        '$r = Invoke-SymbolSpecExport "EURUSD.G2"',
        '"OK=" + $r.ok', '"PROBES=" + $r.probes',
        '"REASONS=" + (@($r.reasons) -join " | ")'])), encoding="utf-8")
    env = dict(os.environ, FAKE_DATA=str(tmp_path / "data"))
    cp = subprocess.run([pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass",
                         "-File", str(script)], capture_output=True,
                        text=True, env=env, check=False, timeout=180)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "OK=True" in cp.stdout, cp.stdout
    assert (f"PROBES=margin_probe {NA} (recorded, not a failure); "
            f"denomination_probe {NA} (recorded, not a failure)"
            in cp.stdout), cp.stdout
    assert "REASONS=\n" in cp.stdout + "\n"
