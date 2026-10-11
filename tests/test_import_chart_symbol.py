"""IMPORT-CHART-1: the importer's [StartUp] ini always names a REAL broker
symbol chart, never a gold's custom symbol.

gate_run41/42 (gold1): stage 4 refused EURUSD.G1 at 'symbol_state'
(5306 / 4305: SymbolSelect(false) failed). import_EURUSD.G1.ini had no
Symbol=, so MT5 ran the importer on whatever chart it restored. A symbol
whose chart hosts the running script can never be deselected. These tests
EXECUTE the gate's own importer launch line under pwsh, for every gold, and
read the ini it writes.

Nothing here is MT5 evidence: the "terminal" is a shell script.
"""

from __future__ import annotations

import re
import subprocess

import pytest
from test_gate_runs_symbolspec_exporter import PS1, _harness, _pwsh

# every gold's custom symbol, as the gate itself lists them ($goldImports)
CUSTOM = re.findall(r'@\{ gold = "gold\d"; name = "([^"]+)"', PS1)
IMPORT_CALL = re.compile(
    r'^ *\$run = Invoke-TerminalScript "Mql5Bot\\Mql5BotImportFixture" .*$',
    re.MULTILINE)


def _line(pattern: str) -> str:
    hits = re.findall(pattern, PS1, re.MULTILINE)
    assert len(hits) == 1, (pattern, hits)
    return hits[0]


def test_the_gate_lists_both_golds_custom_symbols():
    assert CUSTOM == ["EURUSD.G1", "EURUSD.G2"]


def test_the_import_chart_is_a_broker_symbol_and_never_a_custom_one():
    sym = _line(r'^\$ImportChartSymbol = "([^"]*)"$')
    per = _line(r'^\$ImportChartPeriod = "([^"]*)"$')
    assert (sym, per) == ("EURUSD", "H1")
    assert sym not in CUSTOM
    # the same real symbol the gate exports and parity-checks in stage 3
    assert 'Invoke-SymbolSpecExport "EURUSD"' in PS1
    # the gate refuses before any import if the chart is ever a custom one
    s4 = PS1[PS1.index('Enter-Stage 4 "fixture_import"'):
             PS1.index("foreach ($g in $goldImports)")]
    assert "if ($customSymbolNames -contains $ImportChartSymbol)" in s4
    assert "[import_chart_is_custom]" in s4
    # ...and the list it checks is every gold, taken BEFORE -Golds scoping
    assert "$customSymbolNames = @($allGoldImports" in s4
    assert s4.index("$allGoldImports = $goldImports") \
        < s4.index("$goldImports = @($goldImports | Where-Object")


def test_there_is_exactly_one_importer_launch_and_it_names_the_chart():
    calls = IMPORT_CALL.findall(PS1)
    assert len(calls) == 1, calls
    assert calls[0].rstrip().endswith(
        "$setName $ImportChartSymbol $ImportChartPeriod"), calls[0]


@pytest.mark.parametrize("custom", CUSTOM)
def test_importer_ini_names_the_broker_chart_for_every_gold(tmp_path,
                                                            custom):
    """EXECUTES the gate's importer launch line verbatim (with its
    constants) and reads the ini it wrote."""
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    consts = "\n".join(re.findall(
        r'^\$ImportChart(?:Symbol|Period) = "[^"]*"$', PS1, re.MULTILINE))
    body = "\n".join([
        consts,
        f'$g = @{{ name = "{custom}" }}',
        f'$setName = "mql5bot_import_{custom}.set"',
        IMPORT_CALL.findall(PS1)[0].strip(),
    ])
    script = tmp_path / "harness.ps1"
    script.write_text(_harness(tmp_path, body), encoding="utf-8")
    term = tmp_path / "terminal.sh"
    term.write_bytes(b"#!/bin/bash\nexit 0\n")
    term.chmod(0o755)
    cp = subprocess.run([pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass",
                         "-File", str(script)], capture_output=True,
                        text=True, check=False, timeout=180)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    ini = (tmp_path / "ev" / f"import_{custom}.ini").read_bytes()
    assert ini == (
        "[StartUp]\r\n"
        "Script=Mql5Bot\\Mql5BotImportFixture\r\n"
        "Symbol=EURUSD\r\n"
        "Period=H1\r\n"
        f"ScriptParameters=mql5bot_import_{custom}.set\r\n"
        "ShutdownTerminal=1\r\n").encode("ascii"), ini
    lines = ini.decode("ascii").split("\r\n")
    symbols = [x.split("=", 1)[1] for x in lines if x.startswith("Symbol=")]
    assert len(symbols) == 1 and symbols[0] not in CUSTOM
