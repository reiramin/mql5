"""Owner decision 2026-10-03 (DECISIONS.md option 2): the real_ticks leg of a
BAR-ONLY gold is NOT_APPLICABLE_BAR_ONLY_FIXTURE.

Pins:

  * bar-only is DERIVED from the committed manifest + fixture (header is the
    bar schema, manifest declares no tick dataset) -- never assumed; anything
    else keeps the real_ticks leg mandatory exactly as before;
  * a bar-only gold's real_ticks leg is NOT launched, is recorded with a
    reason naming the fixture, and is NEVER counted as a pass: the stage-5
    tally lists it apart, the stage reason states real-tick coverage NONE,
    and gate_summary.json carries "real_tick_coverage": "NONE (bar-only
    fixture)" for that gold;
  * stage 5 may then pass (PASS_FROM_LOG when a leg is log-graded) only when
    every APPLICABLE leg passes; a stage with no applicable passing leg FAILS;
  * the certification report states real-tick coverage NONE.

The .ps1 tests EXECUTE the real stage-5 blocks under pwsh with the real
decider on the real manifests; per-leg tester outcomes are SIMULATED inputs
(no terminal runs). None of this is MT5 evidence.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from mql5bot import certify
from mql5bot import gate_selfcheck as gs

REPO = Path(__file__).resolve().parents[1]
PS1 = REPO / "tools" / "owner_gate.ps1"
SRC = PS1.read_text(encoding="utf-8")
DECIDE = REPO / "tools" / "owner_gate_decide.py"
GOLD1 = ("artifacts/gold/manifest.json", "artifacts/gold/gold_fixture.csv")
GOLD2 = ("artifacts/gold_2/manifest.json", "artifacts/gold_2/gold2_fixture.csv")
NONE_COV = "NONE (bar-only fixture)"
NA = "NOT_APPLICABLE_BAR_ONLY_FIXTURE"


def _pwsh() -> str | None:
    for cand in ("pwsh", str(Path.home() / ".dotnet" / "tools" / "pwsh"),
                 "powershell"):
        found = shutil.which(cand) or (cand if Path(cand).is_file() else None)
        if found:
            return found
    return None


def _tick_gold(tmp_path: Path) -> tuple[Path, Path]:
    """A gold whose fixture carries tick columns (NOT bar-only)."""
    man = json.loads((REPO / GOLD2[0]).read_text(encoding="utf-8"))
    mp = tmp_path / "tick_manifest.json"
    mp.write_text(json.dumps(man), encoding="utf-8")
    fx = tmp_path / "tick_fixture.csv"
    fx.write_text("time,bid,ask,last,volume\n"
                  "2024-01-01 00:00:00,1.1,1.10001,1.1,1\n"
                  "2024-01-02 00:00:00,1.1,1.10001,1.1,1\n", encoding="utf-8")
    return mp, fx


# ---------------------------------------------------------------------------
# the decision (pure Python)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gold", [GOLD1, GOLD2])
def test_committed_golds_are_derived_bar_only(gold):
    r = gs.derive_tester_inputs(REPO / gold[0], REPO / gold[1], gold[1])
    assert r["ok"], r["reasons"]
    assert r["bar_only"] is True
    assert r["fixture_ticks"]["header"] == list(gs.BAR_FIXTURE_COLUMNS)
    rt = r["real_ticks_leg"]
    assert rt["applicable"] is False
    assert rt["outcome"] == NA
    assert r["real_tick_coverage"] == NONE_COV
    # the reason names the fixture and says it is not a pass
    assert gold[1] in rt["reason"]
    assert "NOT a pass" in rt["reason"]
    # evidence scoping: gold2's gate_run lines never justify gold1's verdict
    assert "gate_run" not in rt["reason"]


def test_tick_schema_fixture_keeps_real_ticks_required(tmp_path):
    mp, fx = _tick_gold(tmp_path)
    r = gs.derive_tester_inputs(mp, fx)
    assert r["ok"], r["reasons"]
    assert r["bar_only"] is False
    assert r["real_ticks_leg"]["applicable"] is True
    assert r["real_ticks_leg"]["outcome"] is None
    assert r["real_tick_coverage"] == gs.REAL_TICK_COVERAGE_NOT_MEASURED
    assert "REQUIRED" in r["real_ticks_leg"]["reason"]


def test_manifest_declaring_tick_data_keeps_real_ticks_required(tmp_path):
    man = json.loads((REPO / GOLD2[0]).read_text(encoding="utf-8"))
    man["tick_dataset_hash"] = "0" * 64
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps(man), encoding="utf-8")
    t = gs.fixture_tick_content(mp, REPO / GOLD2[1])
    assert t["bar_only"] is False
    assert any("tick_dataset_hash" in x for x in t["reasons"])
    assert gs.real_ticks_leg_decision(t)["applicable"] is True


def test_unreadable_fixture_is_never_assumed_bar_only(tmp_path):
    t = gs.fixture_tick_content(REPO / GOLD2[0], tmp_path / "absent.csv")
    assert t["bar_only"] is False
    assert gs.real_ticks_leg_decision(t)["applicable"] is True


def test_cli_tester_inputs_names_the_fixture_repo_relative():
    cp = subprocess.run([sys.executable, str(DECIDE), "--repo", str(REPO),
                         "tester-inputs", "--manifest", str(REPO / GOLD2[0]),
                         "--fixture", str(REPO / GOLD2[1])],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 0, cp.stderr
    payload = json.loads(cp.stdout)
    assert payload["real_ticks_leg"]["outcome"] == NA
    assert f"fixture {GOLD2[1]} is bar-only" in payload["real_ticks_leg"]["reason"]


# ---------------------------------------------------------------------------
# owner_gate.ps1 stage 5 -- the real blocks, EXECUTED under pwsh
# ---------------------------------------------------------------------------

def _fn(name: str) -> str:
    s = SRC.index("function " + name)
    return SRC[s:SRC.index("\n}", s) + 2]


def _derive_block() -> str:
    s = SRC.index("foreach ($gk in @($Script:Scope)) {\n    $meta = $goldMeta[$gk]\n    $ti = Invoke-Decide")
    return SRC[s:SRC.index("\n}\n", s) + 3]


def _na_block() -> str:
    s = SRC.index("    # OWNER DECISION 2026-10-03: real_ticks on a bar-only")
    e = SRC.index("        continue\n    }\n", s)
    return SRC[s:e + len("        continue\n    }\n")]


def _tally_block() -> str:
    s = SRC.index("$legTally = (")
    p = SRC.index('Record-Stage 5 "tester_legs" "PASS" (', s)
    return SRC[s:SRC.index("\n}\n", p) + 3]


def _run_stage5(tmp_path: Path, golds: dict[str, tuple[str, str]],
                models: list[str], outcomes: dict[str, str]):
    """Run derive + per-leg NA decision + tally. ``outcomes`` maps a LAUNCHED
    leg tag to a simulated grade (PASS_FROM_LOG or a FAIL outcome)."""
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    fns = "\n".join(_fn(n) for n in (
        "Get-Sha256", "New-Artifact", "ConvertTo-ProcArg", "Get-ProcArgs",
        "Invoke-Decide", "Get-DataProp", "Record-Stage", "Resolve-GateResult",
        "Finish-Gate"))
    meta = "\n".join(
        f'    {g} = @{{ manifest = "{m}"; fixture = "{f}" }}'
        for g, (m, f) in golds.items())
    legs = ",\n".join(f'    @{{ gold = "{g}"; model = "{m}" }}'
                      for g in golds for m in models)
    sim = "\n".join(f'$sim["{k}"] = "{v}"' for k, v in outcomes.items())
    scope = ", ".join(f'"{g}"' for g in golds)
    script = tmp_path / "stage5.ps1"
    script.write_text(f"""Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
{fns}
$RepoRoot = '{REPO}'
$Python = '{sys.executable}'
$Decide = '{DECIDE}'
$Evidence = '{evidence}'
$Script:Stages = New-Object System.Collections.ArrayList
$Script:Blocked = $null
$Script:Stage5FromLog = $false
$Script:RealTickCoverage = [ordered]@{{}}
$Script:Scope = @({scope})
$Script:Partial = $false
$Script:Excluded = @()
$Script:ScopeError = ""
$Script:CurStageNum = 5
$Script:CurStageName = "tester_legs"
$goldMeta = @{{
{meta}
}}
$legs = @(
{legs}
)
$legArt = New-Object System.Collections.ArrayList
$legReasons = New-Object System.Collections.ArrayList
$legOk = $true
$legBlocked = $false
$legFromReport = 0
$legFromLog = 0
$legBlockedN = 0
$legFailN = 0
$legNotApplicableN = 0
$naNotes = New-Object System.Collections.ArrayList
$launched = New-Object System.Collections.ArrayList
$sim = @{{}}
{sim}
$derived = @{{}}
{_derive_block()}
foreach ($leg in $legs) {{
    $gk = $leg.gold
    $d = $derived[$gk]
    $reportName = "{{0}}_{{1}}" -f $gk, $leg.model
    $legTag = $reportName
{_na_block()}
    [void]$launched.Add($legTag)
    if ($sim[$legTag] -eq "PASS_FROM_LOG") {{
        $legFromLog++
        [void]$legReasons.Add(("{{0}}: PASS_FROM_LOG (simulated)" -f $legTag))
    }} else {{
        $legOk = $false
        $legFailN++
        [void]$legReasons.Add(("{{0}}: {{1}} (simulated)" -f $legTag, $sim[$legTag]))
    }}
}}
[IO.File]::WriteAllText((Join-Path $Evidence "launched.json"), (ConvertTo-Json @($launched)))
{_tally_block()}
Finish-Gate "tester_legs_passed"
""", encoding="utf-8")
    cp = subprocess.run([pwsh, "-NoProfile", "-File", str(script)],
                        capture_output=True, text=True, check=False)
    summary_path = evidence / "gate_summary.json"
    assert summary_path.is_file(), cp.stdout + cp.stderr
    summary = json.loads(summary_path.read_text(encoding="ascii"))
    launched = json.loads((evidence / "launched.json").read_text())
    stage5 = {s["stage"]: s for s in summary["stages"]}[5]
    return cp, summary, stage5, launched


MODELS = ["m1_ohlc", "every_tick", "real_ticks"]


def test_bar_only_gold_real_ticks_not_launched_and_stage_can_pass(tmp_path):
    _cp, summary, s5, launched = _run_stage5(
        tmp_path, {"gold2": GOLD2}, MODELS,
        {"gold2_m1_ohlc": "PASS_FROM_LOG", "gold2_every_tick": "PASS_FROM_LOG"})
    # the leg is NOT launched
    assert launched == ["gold2_m1_ohlc", "gold2_every_tick"]
    # every applicable leg passed -> stage 5 passes, log-graded
    assert s5["status"] == "PASS_FROM_LOG", s5["reason"]
    reason = s5["reason"]
    # NOT_APPLICABLE is tallied apart and NEVER as a pass
    assert "0 passed from report, 2 passed from log" in reason
    assert "1 not applicable (NOT_APPLICABLE_BAR_ONLY_FIXTURE" in reason
    assert f"Real-tick coverage NONE: gold2: real-tick coverage {NONE_COV}" in reason
    assert (f"gold2_real_ticks: {NA}: fixture {GOLD2[1]} is bar-only"
            in reason)
    assert summary["real_tick_coverage"] == {"gold2": NONE_COV}
    # stage 5 passed, so the gate did not stop on it
    assert summary["first_blocking"] is None


def test_not_applicable_never_rescues_a_failed_applicable_leg(tmp_path):
    cp, _summary, s5, _launched = _run_stage5(
        tmp_path, {"gold2": GOLD2}, MODELS,
        {"gold2_m1_ohlc": "PASS_FROM_LOG", "gold2_every_tick": "FAIL"})
    assert s5["status"] == "FAIL"
    assert "1 passed from log" in s5["reason"]
    assert "1 failed, 1 not applicable" in s5["reason"]
    assert "GATE_RESULT=tester_legs" in cp.stdout


def test_only_not_applicable_legs_is_a_fail_not_a_pass(tmp_path):
    _cp, summary, s5, launched = _run_stage5(
        tmp_path, {"gold2": GOLD2}, ["real_ticks"], {})
    assert launched == []
    assert s5["status"] == "FAIL"
    assert "0 passed from report, 0 passed from log" in s5["reason"]
    assert "no applicable tester leg passed" in s5["reason"]
    assert summary["real_tick_coverage"] == {"gold2": NONE_COV}


def test_non_bar_only_gold_still_requires_real_ticks(tmp_path):
    mp, fx = _tick_gold(tmp_path)
    _cp, summary, s5, launched = _run_stage5(
        # the .ps1 joins $RepoRoot with the manifest/fixture paths
        tmp_path, {"gold2": (os.path.relpath(mp, REPO),
                             os.path.relpath(fx, REPO))}, MODELS,
        {"gold2_m1_ohlc": "PASS_FROM_LOG", "gold2_every_tick": "PASS_FROM_LOG",
         "gold2_real_ticks": "FAIL_NO_TICK_HISTORY"})
    # the real_ticks leg IS launched and its failure fails the stage
    assert launched == ["gold2_m1_ohlc", "gold2_every_tick", "gold2_real_ticks"]
    assert s5["status"] == "FAIL"
    assert "0 not applicable" in s5["reason"]
    assert "gold2_real_ticks: FAIL_NO_TICK_HISTORY" in s5["reason"]
    assert NONE_COV not in s5["reason"]
    assert summary["real_tick_coverage"] == {
        "gold2": gs.REAL_TICK_COVERAGE_NOT_MEASURED}


def test_ps1_na_branch_touches_no_pass_counter():
    block = "\n".join(ln for ln in _na_block().splitlines()
                      if not ln.lstrip().startswith("#"))
    for counter in ("$legFromReport", "$legFromLog", "$legBlockedN",
                    "$legOk", "$legBlocked"):
        assert counter not in block
    assert "$legNotApplicableN++" in block
    assert "continue" in block


def test_ps1_stage10_states_real_tick_coverage_everywhere():
    s = SRC[SRC.index("SCOPED RUN STOPS HERE"):]
    assert s.count('Record-Stage 10 "certify"') == 4
    for line in s.splitlines():
        if 'Record-Stage 10 "certify"' in line:
            assert "$covNote" in line, line
    assert '"--real-tick-coverage", $pair' in s


# ---------------------------------------------------------------------------
# the certification report (stage 10)
# ---------------------------------------------------------------------------

def _report(coverage: dict | None) -> str:
    cfg = certify.CertifyConfig(strategy="gold2_multifactor")
    rep = certify.run_certification(cfg, run_tester=None,
                                    runner_note="no terminal (test)")
    if coverage is not None:
        rep["real_tick_coverage"] = coverage
    return certify.render_report(rep)


def test_certification_report_states_coverage_none():
    text = _report({"gold2": NONE_COV})
    assert "## Real-Tick Coverage" in text
    assert f"- gold2: real-tick coverage {NONE_COV}" in text
    assert NA in text
    assert "VERDICT: NOT VERIFIED" in text


def test_certification_report_without_coverage_is_unchanged():
    assert "Real-Tick Coverage" not in _report(None)


def test_certify_strategy_cli_rejects_malformed_coverage(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"strategy": "x"}), encoding="utf-8")
    cp = subprocess.run([sys.executable, str(REPO / "tools" / "certify_strategy.py"),
                         "--config", str(cfg), "--real-tick-coverage", "gold2"],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 2
    assert "GOLD=COVERAGE" in cp.stderr


def test_certify_strategy_cli_writes_coverage_into_the_report(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"strategy": "x"}), encoding="utf-8")
    out = tmp_path / "r.md"
    subprocess.run([sys.executable, str(REPO / "tools" / "certify_strategy.py"),
                    "--config", str(cfg), "--out", str(out),
                    "--real-tick-coverage", f"gold2={NONE_COV}"],
                   capture_output=True, text=True, check=False)
    assert f"- gold2: real-tick coverage {NONE_COV}" in out.read_text(
        encoding="utf-8")
