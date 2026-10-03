"""Scoped owner-gate runs (``owner_gate.ps1 -Golds gold2``).

A scoped run is PARTIAL: evidence about the scoped golds only. It pins:

  * a scoped run can never end ``certified`` or
    ``certified_with_log_graded_legs`` — GATE_RESULT is
    ``partial_<last stage reached>``;
  * ``gate_summary.json`` carries ``"scope": ["gold2"]`` and
    ``"certifiable": false``; it and every stage record carry the scope, the
    partial flag and the excluded golds with the reason;
  * stages 9 (archive manifest) and 10 (certify) are REFUSED in a scoped
    run — recorded, never entered, their tools never run;
  * stage 8's verifier examines only the scoped golds and its best verdict
    is MT5_VALIDATED_PARTIAL_SCOPE, which is not a positive verdict;
  * the default (all golds) behaviour is unchanged.

The .ps1 tests EXECUTE the script under pwsh (the MQL5BOT_GATE_FAULT hook
stops it at a stage boundary); they skip only when no PowerShell host exists.
Verifier tests use synthetic packages and are NOT MT5 evidence.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from mql5bot import owner_gate as og
from test_owner_gate import FROZEN, _build_manifest, _w, build_package

REPO = Path(__file__).resolve().parents[1]
PS1 = REPO / "tools" / "owner_gate.ps1"
VERIFY = REPO / "tools" / "verify_owner_mt5_gate.py"


def _pwsh() -> str | None:
    for cand in ("pwsh", str(Path.home() / ".dotnet" / "tools" / "pwsh"),
                 "powershell"):
        found = shutil.which(cand) or (cand if Path(cand).is_file() else None)
        if found:
            return found
    return None


# ---------------------------------------------------------------------------
# the verifier (stage 8) — scoped to gold2
# ---------------------------------------------------------------------------

def _drop_gold1(root: Path) -> Path:
    for model in og.MODELS:
        (root / "gold1" / f"{model}.htm").unlink()
        (root / "parsed" / f"gold1_{model}.json").unlink()
    (root / "reconciliation" / "gold1.json").unlink()
    _w(root / "archive_manifest.json", _build_manifest(root))
    return root


def test_scoped_verify_of_a_gold2_only_package_is_partial_not_positive(tmp_path):
    root = _drop_gold1(build_package(tmp_path))
    rep = og.run_gate(root, FROZEN, ("gold2",))
    assert rep["verdict"] == og.MT5_VALIDATED_PARTIAL_SCOPE
    assert rep["verdict"] not in og.POSITIVE_VERDICTS
    assert rep["scope"] == ["gold2"] and rep["partial"] is True
    assert [e["gold"] for e in rep["excluded"]] == ["gold1"]
    assert set(rep["gold"]) == {"gold2"}
    assert rep["gold"]["gold2"]["result"] == "MATCH"
    assert rep["missing"] == []
    assert rep["artifacts"]["raw_gold1_m1_ohlc"]["state"] == og.OUT_OF_SCOPE
    assert rep["archive_manifest"]["state"] == og.VALID
    assert any("certifies nothing" in r for r in rep["reasons"])


def test_scoped_verify_is_partial_even_when_every_gold_is_present(tmp_path):
    rep = og.run_gate(build_package(tmp_path), FROZEN, ("gold2",))
    assert rep["verdict"] == og.MT5_VALIDATED_PARTIAL_SCOPE


def test_scope_never_hides_a_scoped_gold_failure(tmp_path):
    root = build_package(tmp_path, diverge_gold2=("signal", 1, -1))
    rep = og.run_gate(root, FROZEN, ("gold2",))
    assert rep["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH
    assert rep["gold"]["gold2"]["result"] == "DIVERGENT"


def test_default_verify_is_unchanged(tmp_path):
    full = og.run_gate(build_package(tmp_path / "a"), FROZEN)
    assert full["verdict"] == og.MT5_VALIDATED
    assert full["partial"] is False and full["excluded"] == []
    assert full["scope"] == ["gold1", "gold2"]
    # without a scope, a missing gold1 is still missing
    gone = og.run_gate(_drop_gold1(build_package(tmp_path / "b")), FROZEN)
    assert gone["verdict"] != og.MT5_VALIDATED
    assert "reconciliation_gold1" in gone["missing"]


def test_unknown_or_empty_scope_is_refused(tmp_path):
    with pytest.raises(ValueError):
        og.run_gate(tmp_path, FROZEN, ("gold3",))
    with pytest.raises(ValueError):
        og.run_gate(tmp_path, FROZEN, ())


def _verify_cli(pkg: Path, *extra: str) -> subprocess.CompletedProcess:
    frozen = pkg.parent / "frozen.json"
    frozen.write_text(json.dumps(FROZEN), encoding="utf-8")
    return subprocess.run([sys.executable, str(VERIFY), str(pkg), "--frozen",
                           str(frozen), "--repo", str(REPO), *extra],
                          capture_output=True, text=True, check=False)


def test_verify_cli_scoped_run_exits_nonzero_and_records_scope(tmp_path):
    root = _drop_gold1(build_package(tmp_path / "pkg"))
    out = tmp_path / "report.json"
    cp = _verify_cli(root, "--golds", "gold2", "--out", str(out))
    assert cp.returncode == 1          # a partial verdict is not positive
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["verdict"] == og.MT5_VALIDATED_PARTIAL_SCOPE
    assert rep["scope"] == ["gold2"]
    assert _verify_cli(root, "--golds", "gold3").returncode == 2


# ---------------------------------------------------------------------------
# owner_gate.ps1 — executed
# ---------------------------------------------------------------------------

def _run_gate(tmp_path: Path, *args: str, fault: str | None = None):
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "owner_gate.ps1").write_bytes(PS1.read_bytes())
    env = dict(os.environ)
    env.pop("MQL5BOT_GATE_FAULT", None)
    if fault:
        env["MQL5BOT_GATE_FAULT"] = fault
    cp = subprocess.run([pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass",
                         "-File", str(tools / "owner_gate.ps1"), *args],
                        capture_output=True, text=True, env=env,
                        cwd=str(tmp_path), check=False)
    summaries = list(tmp_path.rglob("gate_summary.json"))
    summary = (json.loads(summaries[0].read_text(encoding="ascii"))
               if summaries else None)
    stage0 = list(tmp_path.rglob("stage_0.json"))
    rec = json.loads(stage0[0].read_text(encoding="ascii")) if stage0 else None
    return cp, summary, rec


def test_ps1_scoped_run_ends_partial_and_records_scope(tmp_path):
    cp, summary, rec = _run_gate(tmp_path, "-Golds", "gold2",
                                 fault="self_protection")
    assert cp.returncode == 1
    assert "GATE_RESULT=partial_self_protection" in cp.stdout
    assert summary["gate_result"] == "partial_self_protection"
    assert summary["unscoped_result"] == "self_protection"
    assert summary["scope"] == ["gold2"]
    assert summary["certifiable"] is False
    assert summary["partial"] is True
    assert [e["gold"] for e in summary["excluded"]] == ["gold1"]
    assert "not compared, validated or certified" in \
        summary["excluded"][0]["reason"]
    # the stage record states the scope too
    assert rec["scope"] == ["gold2"] and rec["partial"] is True
    assert rec["reason"].startswith("[scope: gold2; PARTIAL run")


def test_ps1_default_run_is_unchanged(tmp_path):
    cp, summary, rec = _run_gate(tmp_path, fault="self_protection")
    assert "GATE_RESULT=self_protection" in cp.stdout
    assert "partial_" not in cp.stdout
    assert summary["gate_result"] == "self_protection"
    assert summary["partial"] is False
    assert summary["certifiable"] is True
    assert summary["scope"] == ["gold1", "gold2"]
    assert summary["excluded"] == []
    assert not rec["reason"].startswith("[scope:")


def test_ps1_comma_list_naming_every_gold_is_not_partial(tmp_path):
    cp, summary, _ = _run_gate(tmp_path, "-Golds", "gold2,gold1",
                               fault="self_protection")
    assert "GATE_RESULT=self_protection" in cp.stdout
    assert summary["partial"] is False
    assert summary["scope"] == ["gold1", "gold2"]


def test_ps1_unknown_gold_fails_stage_0_and_is_partial(tmp_path):
    cp, summary, rec = _run_gate(tmp_path, "-Golds", "gold3")
    assert "GATE_RESULT=partial_self_protection" in cp.stdout
    assert rec["status"] == "FAIL"
    assert "[invalid_scope]" in rec["reason"] and "gold3" in rec["reason"]
    assert summary["scope_error"]
    assert summary["certifiable"] is False


def _fn(src: str, name: str) -> str:
    s = src.index("function " + name)
    return src[s:src.index("\n}", s) + 2]


@pytest.mark.parametrize("partial,stage,asked,expected", [
    (True, "certify", "certified", "partial_certify"),
    (True, "certify", "certified_with_log_graded_legs", "partial_certify"),
    (True, "reconciliation", "reconciliation", "partial_reconciliation"),
    (True, "tester_legs", "tester_legs_blocked", "partial_tester_legs"),
    (False, "certify", "certified", "certified"),
    (False, "certify", "certified_with_log_graded_legs",
     "certified_with_log_graded_legs"),
])
def test_resolve_gate_result_never_lets_a_partial_run_certify(
        tmp_path, partial, stage, asked, expected):
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    script = tmp_path / "t.ps1"
    script.write_text(
        _fn(PS1.read_text(encoding="utf-8"), "Resolve-GateResult")
        + f"\n$Script:Partial = ${str(partial).lower()}\n"
        + f"$Script:CurStageName = '{stage}'\n"
        + f"Write-Output (Resolve-GateResult '{asked}')\n", encoding="utf-8")
    cp = subprocess.run([pwsh, "-NoProfile", "-File", str(script)],
                        capture_output=True, text=True, check=False)
    assert cp.stdout.strip() == expected, cp.stderr


# ---------------------------------------------------------------------------
# owner_gate.ps1 — wiring (source)
# ---------------------------------------------------------------------------

SRC = PS1.read_text(encoding="utf-8")


def _stage(start: str, end: str) -> str:
    s = SRC.index(start)
    return SRC[s:SRC.index(end, s)]


def test_ps1_finish_gate_always_resolves_through_the_scope():
    fg = _fn(SRC, "Finish-Gate")
    assert "$gateResult = Resolve-GateResult $gateResult" in fg
    for key in ("scope", "certifiable", "partial", "excluded",
                "unscoped_result"):
        assert f"{key} " in fg or f"{key}=" in fg.replace(" ", "")
    assert 'if ($gateResult -eq "certified") { exit 0 }' in fg


def test_ps1_scopes_imports_legs_and_the_stage_8_comparison():
    s4 = _stage('Enter-Stage 4 "fixture_import"', 'Enter-Stage 5')
    assert "$goldImports = @($goldImports | Where-Object { $Script:Scope -contains $_.gold })" in s4
    s5 = _stage('Enter-Stage 5 "tester_legs"', "STAGE 8")
    assert "$legs = @($legs | Where-Object { $Script:Scope -contains $_.gold })" in s5
    assert 'foreach ($gk in @("gold1", "gold2"))' not in s5
    s8 = _stage('Enter-Stage 8 "reconciliation"', "STAGE 9")
    assert '"--golds", (@($Script:Scope) -join ",")' in s8
    assert 'foreach ($gld in @($Script:Scope))' in s8
    # the partial verdict is accepted ONLY by a partial run
    assert '($Script:Partial -and (Get-DataProp $recon "verdict") -eq ' \
        '"MT5_VALIDATED_PARTIAL_SCOPE")' in s8


def _refusal_block() -> str:
    s = SRC.index("if ($Script:Partial) {", SRC.index("SCOPED RUN STOPS HERE"))
    return SRC[s:SRC.index("\n}", s) + 2]


def _coverage_note_lines() -> str:
    """The $covPairs/$covNote lines the stage-9/10 records append."""
    s = SRC.index("$covPairs = ", SRC.index("SCOPED RUN STOPS HERE"))
    return SRC[s:SRC.index("if ($Script:Partial) {", s)]


def test_ps1_partial_run_refuses_stages_9_and_10_before_entering_them():
    refusal = SRC.index(_refusal_block())
    assert refusal > SRC.index('Enter-Stage 8 "reconciliation"')
    assert refusal < SRC.index('Enter-Stage 9 "archive_manifest"')
    assert refusal < SRC.index('"owner_evidence_bind.py"')
    assert refusal < SRC.index('(Join-Path $PSScriptRoot "certify_strategy.py")')
    block = _refusal_block()
    assert 'Record-Stage 9 "archive_manifest" "REFUSED"' in block
    assert 'Record-Stage 10 "certify" "REFUSED"' in block
    assert "[refused_scoped_run]" in block
    assert 'Finish-Gate "reconciliation"' in block
    # the belt-and-braces guard inside stage 10 still precedes the certifier
    s10 = _stage('Enter-Stage 10 "certify"', 'Finish-Gate "certified"')
    guard = s10.index("if ($Script:Partial)")
    assert guard < s10.index('(Join-Path $PSScriptRoot "certify_strategy.py")')
    assert '"REFUSED"' in s10[guard:s10.index("\n}", guard)]


@pytest.mark.parametrize("partial", [True, False])
def test_ps1_refusal_block_executed(tmp_path, partial):
    """Run the real refusal block + Record-Stage/Finish-Gate after a
    stage-8 PASS: a scoped run ends partial_reconciliation with stages 9/10
    REFUSED and certifiable=false; an unscoped run falls through to stage 9."""
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    fns = "\n".join(_fn(SRC, n) for n in (
        "Get-Sha256", "Record-Stage", "Resolve-GateResult", "Finish-Gate"))
    scope = '@("gold2")' if partial else '@("gold1", "gold2")'
    excluded = ('@([ordered]@{ gold = "gold1"; reason = "excluded" })'
                if partial else "@()")
    script = tmp_path / "t.ps1"
    script.write_text(f"""Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$Evidence = '{tmp_path}'
$Script:Stages = New-Object System.Collections.ArrayList
$Script:Blocked = $null
$Script:Stage5FromLog = $false
$Script:Scope = {scope}
$Script:Partial = ${str(partial).lower()}
$Script:Excluded = {excluded}
$Script:ScopeError = ""
$Script:CurStageNum = 8
$Script:CurStageName = "reconciliation"
$Script:RealTickCoverage = [ordered]@{{ gold2 = "NONE (bar-only fixture)" }}
{fns}
Record-Stage 8 "reconciliation" "PASS" "synthetic" @() | Out-Null
{_coverage_note_lines()}
{_refusal_block()}
Write-Output "REACHED_STAGE_9"
""", encoding="utf-8")
    cp = subprocess.run([pwsh, "-NoProfile", "-File", str(script)],
                        capture_output=True, text=True, check=False)
    if not partial:
        assert cp.returncode == 0 and "REACHED_STAGE_9" in cp.stdout
        assert "GATE_RESULT" not in cp.stdout
        return
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "REACHED_STAGE_9" not in cp.stdout
    assert "GATE_RESULT=partial_reconciliation" in cp.stdout
    assert "certified" not in cp.stdout.split("GATE_RESULT=")[1]
    summary = json.loads((tmp_path / "gate_summary.json").read_text(
        encoding="ascii"))
    assert summary["gate_result"] == "partial_reconciliation"
    assert summary["scope"] == ["gold2"]
    assert summary["certifiable"] is False
    by_stage = {s["stage"]: s for s in summary["stages"]}
    assert by_stage[8]["status"] == "PASS"
    for n in (9, 10):
        assert by_stage[n]["status"] == "REFUSED"
        assert "[refused_scoped_run]" in by_stage[n]["reason"]
    # the stage-10 record and the summary state real-tick coverage NONE
    assert ("[real-tick coverage: gold2=NONE (bar-only fixture)]"
            in by_stage[10]["reason"])
    assert summary["real_tick_coverage"] == {
        "gold2": "NONE (bar-only fixture)"}
