"""Script-parameter shadowing in ``tools/owner_gate.ps1`` (gate_run22).

PowerShell variable names are case-insensitive. PR #7 added the parameter
``[string[]]$Golds``; stage 4 still assigned a local ``$golds = @( @{...} )``,
which is the SAME variable. The ``[string[]]`` type constraint converted every
hashtable to the string "System.Collections.Hashtable", so ``$_.gold`` threw
under StrictMode ("The property 'gold' cannot be found on this object") and
stage 4 failed in every run, scoped or not.

The earlier tests executed stage-4 snippets WITHOUT the real param block, so the
constraint never applied. These tests pin:

  * static: no assignment outside the param block may case-insensitively name
    a script parameter, except the listed intentional reassignments;
  * executed (pwsh): the REAL param block, scope block and stage-4 gold list,
    cut from the script, run under StrictMode 2.0 give the right entries, and
    the old ``$golds`` spelling fails in the same harness.

The pwsh tests skip only when no PowerShell host exists. They are not MT5
evidence.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PS1 = REPO / "tools" / "owner_gate.ps1"

# Script parameters the script reassigns ON PURPOSE (resolving defaults from
# the environment / install locations). Every other script parameter is
# read-only after the param block.
INTENTIONAL_REASSIGNMENTS = {"DataFolder", "TerminalPath", "MetaEditorPath", "SymbolSpecExport"}

_ASSIGN = re.compile(
    r"\$(?:script:|local:|global:)?([A-Za-z_]\w*)\s*(?:[+\-*/%]?=)(?!=)", re.IGNORECASE
)
_FOREACH = re.compile(r"\bforeach\s*\(\s*\$([A-Za-z_]\w*)\s+in\b", re.IGNORECASE)


def _source() -> str:
    return PS1.read_text(encoding="utf-8-sig")


def _param_block(lines: list[str]) -> tuple[int, int]:
    """(first, last) 0-based line indexes of the top-level ``param(...)`` block."""
    start = next(i for i, ln in enumerate(lines) if ln.startswith("param("))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith(")"))
    return start, end


def _param_names(src: str) -> list[str]:
    lines = src.splitlines()
    start, end = _param_block(lines)
    names = []
    for ln in lines[start + 1:end]:
        code = ln.split("#", 1)[0]
        m = re.search(r"\$([A-Za-z_]\w*)", code)
        if m:
            names.append(m.group(1))
    return names


def _code_lines(src: str):
    """(1-based line no, code) outside the param block, comments removed."""
    lines = src.splitlines()
    start, end = _param_block(lines)
    in_block_comment = False
    for i, ln in enumerate(lines):
        if start <= i <= end:
            continue
        if in_block_comment:
            if "#>" in ln:
                in_block_comment = False
            continue
        stripped = ln.lstrip()
        if stripped.startswith("<#"):
            in_block_comment = "#>" not in stripped
            continue
        if stripped.startswith("#"):
            continue
        yield i + 1, ln


def _collisions(src: str) -> list[str]:
    params = {n.lower(): n for n in _param_names(src)}
    allowed = {n.lower() for n in INTENTIONAL_REASSIGNMENTS}
    found = []
    for no, code in _code_lines(src):
        for rx in (_ASSIGN, _FOREACH):
            for m in rx.finditer(code):
                key = m.group(1).lower()
                if key in params and key not in allowed:
                    found.append(f"line {no}: ${m.group(1)} (parameter ${params[key]}): {code.strip()}")
    return found


# ---------------------------------------------------------------------------
# static
# ---------------------------------------------------------------------------

def test_param_block_is_parsed():
    names = _param_names(_source())
    assert "Golds" in names and "DataFolder" in names and "TimeoutSec" in names
    assert INTENTIONAL_REASSIGNMENTS <= set(names)


def test_no_local_variable_shadows_a_script_parameter():
    assert _collisions(_source()) == []


def test_the_check_catches_the_gate_run22_collision():
    old = _source().replace("$goldImports", "$golds")
    hits = _collisions(old)
    assert hits and all("$golds (parameter $Golds)" in h for h in hits)


def test_intentional_reassignments_are_still_present():
    # keep the allow-list honest: each entry must still be a real reassignment
    src = _source()
    for name in INTENTIONAL_REASSIGNMENTS:
        assert any(
            m.group(1) == name
            for _, code in _code_lines(src)
            for m in _ASSIGN.finditer(code)
        ), name


# ---------------------------------------------------------------------------
# executed under pwsh: the real param block + scope + stage-4 gold list
# ---------------------------------------------------------------------------

def _pwsh() -> str | None:
    for cand in ("pwsh", str(Path.home() / ".dotnet" / "tools" / "pwsh"), "powershell"):
        found = shutil.which(cand) or (cand if Path(cand).is_file() else None)
        if found:
            return found
    return None


def _cut(lines: list[str], first: str, last: str) -> str:
    """Lines from the one starting with ``first`` through the one starting with ``last``."""
    i = next(n for n, ln in enumerate(lines) if ln.startswith(first))
    j = next(n for n in range(i, len(lines)) if lines[n].startswith(last))
    return "\n".join(lines[i:j + 1])


def _harness(stage4_var: str = "$goldImports") -> str:
    lines = _source().splitlines()
    start, end = _param_block(lines)
    param = "\n".join(lines[start:end + 1])
    scope = _cut(lines, "$Script:AllGolds = @(", "$Script:Partial = ")
    gold_list = _cut(lines, "$goldImports = @(", "$goldImports = @($goldImports | Where-Object")
    if stage4_var != "$goldImports":
        gold_list = gold_list.replace("$goldImports", stage4_var)
    out = (
        "$rows = @(" + stage4_var + " | ForEach-Object { [ordered]@{ gold = $_.gold; name = $_.name } })\n"
        "[Console]::Out.Write((ConvertTo-Json -InputObject $rows -Compress))\n"
    )
    prologue = 'Set-StrictMode -Version 2.0\n$ErrorActionPreference = "Stop"'
    return f"{param}\n{prologue}\n{scope}\n{gold_list}\n{out}"


def _run(tmp_path: Path, body: str, *args: str) -> subprocess.CompletedProcess:
    exe = _pwsh()
    if exe is None:
        pytest.skip("no PowerShell host")
    script = tmp_path / "stage4_goldlist.ps1"
    script.write_text(body, encoding="utf-8")
    return subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-File", str(script), *args],
        capture_output=True, text=True, timeout=120, check=False,
    )


def test_real_stage4_gold_list_default_run_has_both_golds(tmp_path):
    p = _run(tmp_path, _harness())
    assert p.returncode == 0, p.stderr
    rows = json.loads(p.stdout)
    assert [r["gold"] for r in rows] == ["gold1", "gold2"]
    assert [r["name"] for r in rows] == ["EURUSD.G1", "EURUSD.G2"]


def test_real_stage4_gold_list_scoped_to_gold2(tmp_path):
    p = _run(tmp_path, _harness(), "-Golds", "gold2")
    assert p.returncode == 0, p.stderr
    rows = json.loads(p.stdout)
    assert len(rows) == 1
    assert rows[0]["gold"] == "gold2" and rows[0]["name"] == "EURUSD.G2"


def test_old_golds_spelling_fails_in_the_same_harness(tmp_path):
    # gate_run22: the local $golds IS the [string[]]$Golds parameter
    p = _run(tmp_path, _harness("$golds"))
    assert p.returncode != 0
    assert "The property 'gold' cannot be found on this object" in p.stderr
