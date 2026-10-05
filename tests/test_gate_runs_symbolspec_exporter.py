"""The owner gate RUNS Mql5BotExportSymbolSpec itself, and only fresh exports
are ever used.

gate_run31 (HEAD 4803520): stage 1 compiled the S8-SPEC-2 exporter (0/0) and
the EA registered all 37 of its own entries, BUT
owner_mt5_package/symbolspec/symbolspec.json was the OLD file -- keys
[schema, exported_at, account_login, account_currency, account_margin_mode,
server, symbol], exported_at "2026.09.15 20:14:16 GMT". owner_gate.ps1 only
copied data\\broker_exports\\EURUSD.json and never ran the exporter, so the
flat fields and spread_points never existed, the fill model fell back to
the manifest spread and entry_price stayed 18/37.

These tests pin:

* the startup ini the gate writes for the exporter, for BOTH symbols --
  (a) the broker symbol EURUSD (stage 3) and (b) the custom gold symbol
  EURUSD.G2 (stage 4, after import) -- by EXECUTING the gate's own
  Invoke-TerminalScript under pwsh;
* Invoke-SymbolSpecExport end to end under pwsh with a fake terminal that
  writes an export for the ini's Symbol=: a fresh export passes, and a stale
  file left at the path (the 2026-09-15 shape) FAILs naming the file;
* the committed freshness decision (gate_selfcheck.symbolspec_export_
  freshness) rejects the 2026-09-15 file;
* stage8_package takes symbolspec + spread from the CUSTOM-symbol export and
  records which file and symbol they came from.

Nothing here is MT5 evidence: the "terminal" is a shell script.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from mql5bot import gate_selfcheck as gs
from mql5bot import owner_gate as og
from mql5bot import stage8_package as s8p

REPO = Path(__file__).resolve().parents[1]
PS1 = (REPO / "tools" / "owner_gate.ps1").read_text(encoding="utf-8")
DECIDE = REPO / "tools" / "owner_gate_decide.py"

# the exact top-level keys + exported_at of the stale file gate_run31
# packaged (owner_mt5_package/symbolspec/symbolspec.json)
STALE_2026_09_15 = {
    "schema": "mql5bot.broker_export/1",
    "exported_at": "2026.09.15 20:14:16 GMT",
    "account_login": 0,
    "account_currency": "USD",
    "account_margin_mode": 2,
    "server": "MetaQuotes-Demo",
    "symbol": {"name": "EURUSD", "point": 1e-05},
}
RUN_START = "2026-10-05T09:00:00.1234567+00:00"
NOW = "2026-10-05T09:30:00+00:00"


def _pwsh() -> str | None:
    exe = shutil.which("pwsh") or shutil.which("powershell")
    if exe:
        return exe
    cand = Path.home() / ".dotnet" / "tools" / "pwsh"
    return str(cand) if cand.is_file() else None


def _fn(name: str) -> str:
    """The gate's own function source, verbatim."""
    i = PS1.index(f"function {name}")
    return PS1[i:PS1.index("\n}\n", i) + 3]


def _fresh_doc(symbol: str, when: str, spread: int = 2) -> dict:
    return {"schema": "mql5bot.broker_export/1", "server": "MetaQuotes-Demo",
            "broker": "MetaQuotes Ltd.", "timestamp": when,
            "terminal_build": 6184, "spread_points": spread,
            "symbol": {"name": symbol}}


# ------------------------------------------------- freshness (committed py)

def test_freshness_rejects_the_2026_09_15_file(tmp_path):
    f = tmp_path / "EURUSD.json"
    f.write_text(json.dumps(STALE_2026_09_15), encoding="utf-8")
    rep = gs.symbolspec_export_freshness(f, "EURUSD", RUN_START, NOW)
    assert rep["ok"] is False
    joined = " | ".join(rep["reasons"])
    # named, with its own date, and both independent defects reported
    assert str(f) in joined
    assert "STALE" in joined and "2026.09.15 20:14:16 GMT" in joined
    assert "terminal_build missing" in joined
    assert rep["export_time_key"] == "exported_at"


def test_freshness_accepts_an_export_from_this_run(tmp_path):
    f = tmp_path / "EURUSD.G2.json"
    f.write_text(json.dumps(_fresh_doc("EURUSD.G2", "2026-10-05T09:12:03Z")),
                 encoding="utf-8")
    rep = gs.symbolspec_export_freshness(f, "EURUSD.G2", RUN_START, NOW)
    assert rep["ok"] is True, rep["reasons"]
    assert (rep["terminal_build"], rep["spread_points"]) == (6184, 2)
    assert rep["symbol_exported"] == "EURUSD.G2"


@pytest.mark.parametrize("when,why", [
    ("2026-10-05T08:59:59Z", "STALE"),       # one second before the run
    ("2026-10-05T09:30:01Z", "STALE"),       # after 'now'
    ("not-a-time", "no parsable export time"),
])
def test_freshness_window_is_exact_to_the_second(tmp_path, when, why):
    f = tmp_path / "x.json"
    f.write_text(json.dumps(_fresh_doc("EURUSD", when)), encoding="utf-8")
    rep = gs.symbolspec_export_freshness(f, "EURUSD", RUN_START, NOW)
    assert rep["ok"] is False and why in " ".join(rep["reasons"])


def test_freshness_boundaries_are_inclusive_at_second_resolution(tmp_path):
    # the run start is floored to the second (TimeGMT has no fractions)
    for when in ("2026-10-05T09:00:00Z", "2026-10-05T09:30:00Z"):
        f = tmp_path / "b.json"
        f.write_text(json.dumps(_fresh_doc("EURUSD", when)), encoding="utf-8")
        assert gs.symbolspec_export_freshness(
            f, "EURUSD", RUN_START, NOW)["ok"], when


def test_freshness_refuses_wrong_symbol_missing_build_and_missing_file(
        tmp_path):
    f = tmp_path / "x.json"
    doc = _fresh_doc("EURUSD", "2026-10-05T09:10:00Z")
    f.write_text(json.dumps(doc), encoding="utf-8")
    rep = gs.symbolspec_export_freshness(f, "EURUSD.G2", RUN_START, NOW)
    assert not rep["ok"] and "!= requested 'EURUSD.G2'" in rep["reasons"][0]
    doc.pop("terminal_build")
    f.write_text(json.dumps(doc), encoding="utf-8")
    rep = gs.symbolspec_export_freshness(f, "EURUSD", RUN_START, NOW)
    assert not rep["ok"] and "terminal_build missing" in rep["reasons"][0]
    rep = gs.symbolspec_export_freshness(tmp_path / "nope.json", "EURUSD",
                                         RUN_START, NOW)
    assert not rep["ok"] and "export file missing" in rep["reasons"][0]


def test_decider_cli_emits_the_verdict_and_exit_code(tmp_path):
    f = tmp_path / "EURUSD.json"
    f.write_text(json.dumps(STALE_2026_09_15), encoding="utf-8")
    cp = subprocess.run([sys.executable, str(DECIDE), "--repo", str(REPO),
                         "symbolspec-fresh", "--export", str(f), "--symbol",
                         "EURUSD", "--run-start", RUN_START, "--now", NOW],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 1, cp.stderr
    out = json.loads(cp.stdout)
    assert out["ok"] is False and out["file"] == str(f)


# ------------------------------------------------ the ps1 wiring (static)

def test_ps1_runs_the_exporter_in_stage3_and_after_stage4_import():
    s3 = PS1[PS1.index('Enter-Stage 3 "broker_parity"'):
             PS1.index('Enter-Stage 4 "fixture_import"')]
    # (a) broker symbol, BEFORE the parity tool reads data\broker_exports
    assert 'Invoke-SymbolSpecExport "EURUSD"' in s3
    assert s3.index('Invoke-SymbolSpecExport "EURUSD"') \
        < s3.index("broker_symbol_parity.py")
    assert 'Copy-Item -LiteralPath $SymbolSpecExport -Destination $parityEurusd' in s3
    # the override is kept, named, and judged by the same freshness rule
    assert '$brokerSpecSource = "owner-supplied file"' in s3
    assert '"symbolspec-fresh", "--export", $SymbolSpecExport' in s3
    # the stale default-copy path is gone
    assert 'Join-Path $RepoRoot "data\\broker_exports\\EURUSD.json"' not in PS1
    s4 = PS1[PS1.index('Enter-Stage 4 "fixture_import"'):
             PS1.index('Enter-Stage 5 "tester_legs"')]
    # (b) custom symbol, AFTER the import outcome passed, per gold
    assert s4.index('"stage4-outcome"') < s4.index(
        "Invoke-SymbolSpecExport $g.name")
    assert "$Script:CustomSpecs[$g.gold] = $cx.evidence" in s4
    # FAIL names the file (the reasons carry it), never a fallback
    fn = _fn("Invoke-SymbolSpecExport")
    assert '"symbolspec-fresh", "--export", $judged' in fn
    assert "[symbolspec_not_fresh]" in fn


# ----------------------------------------------- ps1 executed under pwsh

_FAKE_TERMINAL = r"""#!/bin/bash
# stand-in terminal: read Symbol= from the /config ini, write an export
ini="${1#/config:}"
sym=$(grep '^Symbol=' "$ini" | tr -d '\r' | cut -d= -f2)
[ "$FAKE_MODE" = "nothing" ] && exit 0
out="$FAKE_DATA/MQL5/Files/Mql5Bot/broker_exports/$sym.json"
mkdir -p "$(dirname "$out")"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '{"schema":"mql5bot.broker_export/1","timestamp":"%s","terminal_build":6184,"spread_points":2,"broker":"MetaQuotes Ltd.","server":"MetaQuotes-Demo","symbol":{"name":"%s"}}' "$now" "$sym" > "$out"
"""


def _harness(tmp_path: Path, body: str) -> str:
    funcs = "".join(_fn(n) for n in (
        "Get-Sha256", "New-Artifact", "ConvertTo-ProcArg", "Get-ProcArgs",
        "Invoke-Decide", "Get-DataProp", "Invoke-TerminalScript",
        "Invoke-SymbolSpecExport"))
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$Evidence = '{tmp_path / 'ev'}'",
        f"$DataFolder = '{tmp_path / 'data'}'",
        f"$RepoRoot = '{REPO}'",
        f"$Decide = '{DECIDE}'",
        f"$Python = '{sys.executable}'",
        f"$TerminalPath = '{tmp_path / 'terminal.sh'}'",
        "$Portable = $false",
        "$TimeoutSec = 60",
        "New-Item -ItemType Directory -Force -Path $Evidence | Out-Null",
        funcs, body])


def _run(tmp_path: Path, body: str, mode: str = "write"):
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    term = tmp_path / "terminal.sh"
    term.write_text(_FAKE_TERMINAL, encoding="ascii")
    term.chmod(term.stat().st_mode | stat.S_IEXEC)
    script = tmp_path / "harness.ps1"
    script.write_text(_harness(tmp_path, body), encoding="utf-8")
    env = dict(os.environ, FAKE_MODE=mode, FAKE_DATA=str(tmp_path / "data"))
    return subprocess.run([pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass",
                           "-File", str(script)], capture_output=True,
                          text=True, env=env, check=False, timeout=180)


def test_exporter_ini_for_the_broker_and_the_custom_symbol(tmp_path):
    """EXECUTES the gate's Invoke-TerminalScript: the [StartUp] ini for
    both exporter launches, byte for byte."""
    calls = [
        f'Invoke-TerminalScript "Mql5Bot\\Mql5BotExportSymbolSpec" '
        f'"export_symbolspec_{sym}" "mql5bot_export_symbolspec_{sym}.set" '
        f'"{sym}" | Out-Null'
        for sym in ("EURUSD", "EURUSD.G2")]
    # the importer launch passes no symbol: its ini is unchanged
    calls.append('Invoke-TerminalScript "Mql5Bot\\Mql5BotImportFixture" '
                 '"import_EURUSD.G2" "mql5bot_import_EURUSD.G2.set" '
                 '| Out-Null')
    cp = _run(tmp_path, "\n".join(calls), mode="nothing")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    ev = tmp_path / "ev"
    for sym in ("EURUSD", "EURUSD.G2"):
        ini = (ev / f"export_symbolspec_{sym}.ini").read_bytes()
        assert ini == (
            "[StartUp]\r\n"
            "Script=Mql5Bot\\Mql5BotExportSymbolSpec\r\n"
            f"Symbol={sym}\r\n"
            f"ScriptParameters=mql5bot_export_symbolspec_{sym}.set\r\n"
            "ShutdownTerminal=1\r\n").encode("ascii"), ini
    imp = (ev / "import_EURUSD.G2.ini").read_bytes()
    assert imp == (b"[StartUp]\r\nScript=Mql5Bot\\Mql5BotImportFixture\r\n"
                   b"ScriptParameters=mql5bot_import_EURUSD.G2.set\r\n"
                   b"ShutdownTerminal=1\r\n")


def test_invoke_symbolspec_export_passes_a_fresh_export(tmp_path):
    """EXECUTES Invoke-SymbolSpecExport end to end (preset staged +
    validated by committed python, terminal launched with Symbol=, output
    byte-copied into evidence, freshness judged by committed python)."""
    start = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    cp = _run(tmp_path, "\n".join([
        f"$Script:RunStartUtc = '{start}'",
        '$r = Invoke-SymbolSpecExport "EURUSD.G2"',
        '"OK=" + $r.ok', '"EVIDENCE=" + $r.evidence',
        '"REASONS=" + (@($r.reasons) -join " | ")']))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "OK=True" in cp.stdout, cp.stdout
    ev = tmp_path / "ev"
    assert f"EVIDENCE={ev / 'symbolspec_EURUSD.G2.json'}" in cp.stdout
    doc = json.loads((ev / "symbolspec_EURUSD.G2.json").read_text())
    assert doc["symbol"]["name"] == "EURUSD.G2"
    # the preset delivered the inputs explicitly (UTF-16LE, MQL5\Presets)
    staged = tmp_path / "data/MQL5/Presets/mql5bot_export_symbolspec_EURUSD.G2.set"
    # UTF-16LE with BOM -- the same encoding as the importer's presets
    assert staged.read_bytes().decode("utf-16-le") == (
        "﻿InpExportDir=Mql5Bot\\broker_exports\\\r\n"
        "InpDenomProbeTicks=100\r\n")


def test_invoke_symbolspec_export_fails_on_a_stale_file_naming_it(tmp_path):
    """The exporter wrote nothing; the 2026-09-15 file a previous run left
    at the output path is NOT used -- the result names it and says STALE."""
    out = tmp_path / "data/MQL5/Files/Mql5Bot/broker_exports/EURUSD.json"
    out.parent.mkdir(parents=True)
    out.write_text(json.dumps(STALE_2026_09_15), encoding="utf-8")
    start = datetime.now(timezone.utc).isoformat()
    cp = _run(tmp_path, "\n".join([
        f"$Script:RunStartUtc = '{start}'",
        '$r = Invoke-SymbolSpecExport "EURUSD"',
        '"OK=" + $r.ok', '"EVIDENCE=" + $r.evidence',
        '"REASONS=" + (@($r.reasons) -join " | ")']), mode="nothing")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "OK=False" in cp.stdout and "EVIDENCE=\n" in cp.stdout + "\n"
    reasons = cp.stdout[cp.stdout.index("REASONS="):]
    assert "[symbolspec_not_fresh]" in reasons
    assert "symbolspec_EURUSD.json" in reasons          # the file, named
    assert "STALE" in reasons and "2026.09.15 20:14:16 GMT" in reasons


# --------------------------------------- stage8: the custom-symbol export

def test_package_takes_symbolspec_and_spread_from_the_custom_export(
        tmp_path):
    """build_package with BOTH exports: the slot holds the custom-symbol
    export (EURUSD.G2), and the build record + reconciliation name the file
    and symbol; the broker export is not packaged. The custom export has
    gate_run34's shape -- live spread_points 0 -- and the fill model takes
    its configured custom_fixed_spread_points, never the live 0."""
    from tests.test_stage8_package_from_gate import FLAT_EXPORT, _build

    broker = dict(FLAT_EXPORT, spread_points=0)
    custom = dict(FLAT_EXPORT, spread_points=0, custom_symbol=True,
                  spread_float=False, custom_fixed_spread_points=1,
                  symbol={"name": "EURUSD.G2", "point": 1e-05})
    custom_file = tmp_path / "symbolspec_EURUSD.G2.json"
    custom_file.write_text(json.dumps(custom), encoding="utf-8")
    rec, pkg, _ = _build(tmp_path, broker,
                         symbolspec_custom={"gold2": custom_file})
    slot = pkg / og.LAYOUT["symbolspec"]
    assert slot.read_bytes() == custom_file.read_bytes()
    src = rec["symbolspec_source"]
    assert src["gold"] == "gold2" and src["symbol"] == "EURUSD.G2"
    assert src["file"] == str(custom_file)
    assert src["sha256"] == s8p._sha(custom_file)
    assert src["basis"].startswith("custom-symbol export")
    # the record is IN the package
    in_pkg = json.loads((pkg / s8p.GATE_BUILD_REL).read_text())
    assert in_pkg["symbolspec_source"] == src
    recon = json.loads((pkg / "reconciliation/gold2.json").read_text())
    fm = recon["fill_model"]
    assert fm["inputs"]["spread_points"] == 1.0   # fixed, never live 0
    assert fm["buy"] == \
        "ask_open=bid+custom_fixed_spread(1 points, symbolspec export)"
    assert fm["spread_source"]["file"] == str(custom_file)
    assert fm["spread_source"]["symbol"] == "EURUSD.G2"


def test_package_without_a_custom_export_says_it_used_the_broker_one(
        tmp_path):
    from tests.test_stage8_package_from_gate import FLAT_EXPORT, _build

    rec, _, _ = _build(tmp_path, FLAT_EXPORT)
    src = rec["symbolspec_source"]
    assert src["basis"] == ("stage-3 broker export (no custom-symbol export "
                            "supplied)")
    assert src["gold"] is None and src["symbol"] == "EURUSD"
