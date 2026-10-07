"""R10: owner_gate.ps1 reads decider output StrictMode-safely.

gate_run21 (HEAD 0c5da2f) FAILED stage 5 with
``UNHANDLED_ERROR: The property 'bundle_evidence' cannot be found on this
object``: stage5-leg-inputs refuses gold1 (ok=false,
missing=engine_config.allow_short) and that answer carries no
``bundle_evidence`` key; under ``Set-StrictMode -Version 2.0`` the bare read
``$li.data.bundle_evidence`` throws, so the trap failed the whole stage
before any gold2 leg launched.

These tests pin the fix:

  * the decider's real answer for the committed gold1 manifest has no
    ``bundle_evidence`` (the input that crashed the gate);
  * no bare ``.data.<property>`` read of decider output remains in the .ps1
    — every read goes through Get-DataProp;
  * the stage-5 leg-input block, EXECUTED under StrictMode 2.0 with the real
    decider on the real manifests, records the gold1 legs as
    ``[input_underivable] engine_config.allow_short -- leg NOT launched``,
    still reaches every gold2 leg, and leaves the stage failed ($legOk false);
  * the same block with the old bare read reproduces the gate_run21 crash.

The .ps1 tests skip only when no PowerShell host exists. None of this is MT5
evidence: no terminal runs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PS1 = REPO / "tools" / "owner_gate.ps1"
SRC = PS1.read_text(encoding="utf-8")
DECIDE = REPO / "tools" / "owner_gate_decide.py"
GOLD1_MANIFEST = REPO / "artifacts" / "gold" / "manifest.json"
GOLD2_MANIFEST = REPO / "artifacts" / "gold_2" / "manifest.json"


def _pwsh() -> str | None:
    for cand in ("pwsh", str(Path.home() / ".dotnet" / "tools" / "pwsh"),
                 "powershell"):
        found = shutil.which(cand) or (cand if Path(cand).is_file() else None)
        if found:
            return found
    return None


def _fn(name: str) -> str:
    s = SRC.index("function " + name)
    return SRC[s:SRC.index("\n}", s) + 2]


def _leg_inputs(manifest: Path, symbol: str, leg: str, out: Path):
    cp = subprocess.run([sys.executable, str(DECIDE), "--repo", str(REPO),
                         "stage5-leg-inputs", "--manifest", str(manifest),
                         "--symbol", symbol, "--leg", leg,
                         "--out-dir", str(out)],
                        capture_output=True, text=True, check=False)
    return cp.returncode, json.loads(cp.stdout)


# ---------------------------------------------------------------------------
# the decider output that crashed gate_run21
# ---------------------------------------------------------------------------

def test_gold1_leg_inputs_derive_the_gold1_strategy(tmp_path):
    # S8-GOLD1-REGEN: the regenerated manifest pins engine_config
    rc, out = _leg_inputs(GOLD1_MANIFEST, "EURUSD.G1", "gold1_m1_ohlc",
                          tmp_path)
    assert rc == 0 and out["ok"] is True
    assert out["strategy_id"] == "ema_crossover_ref"
    assert Path(out["bundle_evidence"]).is_file()


def test_gold2_leg_inputs_derive_the_gold2_strategy(tmp_path):
    rc, out = _leg_inputs(GOLD2_MANIFEST, "EURUSD.G2", "gold2_m1_ohlc",
                          tmp_path)
    assert rc == 0 and out["ok"] is True
    assert out["strategy_id"] == "gold2_multifactor"
    assert Path(out["bundle_evidence"]).is_file()


# ---------------------------------------------------------------------------
# static audit: no bare property read of decider/verifier output
# ---------------------------------------------------------------------------

def test_ps1_has_no_bare_property_read_of_decider_output():
    # $x.data.<prop> (decider), $recon.<prop> (verifier), $fd.<prop>
    # (verifier sub-object) and $d.<prop> for derived tester inputs
    bare = re.findall(r"\$\w+\.data\.[A-Za-z_]\w*", SRC)
    bare += re.findall(r"\$(?:recon|fd)\.[A-Za-z_]\w*", SRC)
    bare += [m for m in re.findall(r"\$d\.[A-Za-z_]\w*", SRC)
             if m not in ("$d.ok", "$d.data")]
    assert bare == []


def test_get_data_prop_checks_membership_before_reading():
    fn = _fn("Get-DataProp")
    assert "PSObject.Properties.Name) -contains $name" in fn
    assert "DECIDER_OUTPUT_MISSING" in fn


def test_ps1_parses():
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    cmd = ("$e=$null; [System.Management.Automation.Language.Parser]::"
           f"ParseFile('{PS1}', [ref]$null, [ref]$e) | Out-Null; "
           "if ($e) { $e | ForEach-Object { $_.Message }; exit 1 }")
    cp = subprocess.run([pwsh, "-NoProfile", "-Command", cmd],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 0, cp.stdout + cp.stderr


@pytest.mark.parametrize("obj,expr,expected", [
    ("[pscustomobject]@{ ok = $false; missing = 'x' }", "'bundle_evidence'",
     "<null>"),
    ("[pscustomobject]@{ ok = $false; missing = 'x' }", "'missing'", "x"),
    ("$null", "'missing'", "<null>"),
    ("@{ a = 1 }", "'a'", "1"),
])
def test_get_data_prop_under_strict_mode(tmp_path, obj, expr, expected):
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    script = tmp_path / "t.ps1"
    script.write_text(
        "Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n"
        + _fn("Get-DataProp")
        + f"\n$v = Get-DataProp ({obj}) {expr}\n"
        + "if ($null -eq $v) { '<null>' } else { [string]$v }\n",
        encoding="utf-8")
    cp = subprocess.run([pwsh, "-NoProfile", "-File", str(script)],
                        capture_output=True, text=True, check=False)
    assert cp.stdout.strip() == expected, cp.stderr


def test_get_data_prop_required_throws_a_named_error(tmp_path):
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    script = tmp_path / "t.ps1"
    script.write_text(
        "Set-StrictMode -Version 2.0\n$ErrorActionPreference = 'Stop'\n"
        + _fn("Get-DataProp")
        + "\nGet-DataProp ([pscustomobject]@{ ok = $true }) 'deposit' "
          "-Required\n", encoding="utf-8")
    cp = subprocess.run([pwsh, "-NoProfile", "-File", str(script)],
                        capture_output=True, text=True, check=False)
    assert cp.returncode != 0
    assert "DECIDER_OUTPUT_MISSING" in cp.stdout + cp.stderr
    assert "deposit" in cp.stdout + cp.stderr


# ---------------------------------------------------------------------------
# the stage-5 leg-input block, EXECUTED under StrictMode 2.0
# ---------------------------------------------------------------------------

def _legs_block() -> str:
    s = SRC.index("$legs = @(\n")
    e = SRC.index("\n)", s) + 2
    scope = SRC.index("$legs = @($legs | Where-Object", e)
    return SRC[s:e] + "\n" + SRC[scope:SRC.index("\n", scope)]


def _leg_input_block() -> str:
    s = SRC.index('    $li = Invoke-Decide @("stage5-leg-inputs"')
    e = SRC.index("$legStrategy = ", s)
    return SRC[s:SRC.index("\n", e)]


def _gold1_without_engine_config(tmp_path: Path) -> Path:
    """A gold1 manifest whose allow-short rule is underivable (the shape of
    the pre-S8-GOLD1-REGEN manifest): the refusal path under test."""
    doc = json.loads(GOLD1_MANIFEST.read_text(encoding="utf-8"))
    doc.pop("engine_config")
    path = tmp_path / "gold1_no_engine_config.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    # the ps1 joins $RepoRoot with the manifest: pass it repo-relative
    return Path(os.path.relpath(path, REPO))


def _run_leg_inputs(tmp_path: Path, scope: list[str],
                    block: str | None = None,
                    gold1_manifest: str = "artifacts/gold/manifest.json"):
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    fns = "\n".join(_fn(n) for n in ("Get-Sha256", "New-Artifact",
                                     "ConvertTo-ProcArg", "Get-ProcArgs",
                                     "Invoke-Decide", "Get-DataProp"))
    scope_ps = ", ".join(f'"{g}"' for g in scope)
    script = tmp_path / "stage5_leg_inputs.ps1"
    script.write_text(f"""Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
{fns}
$RepoRoot = '{REPO}'
$Python = '{sys.executable}'
$Decide = '{DECIDE}'
$Evidence = '{evidence}'
$DataFolder = ""
$Script:Scope = @({scope_ps})
$goldMeta = @{{
    gold1 = @{{ symbol = "EURUSD.G1"; manifest = '{gold1_manifest}' }}
    gold2 = @{{ symbol = "EURUSD.G2"; manifest = "artifacts/gold_2/manifest.json" }}
}}
{_legs_block()}
$legArt = New-Object System.Collections.ArrayList
$legReasons = New-Object System.Collections.ArrayList
$legOk = $true
$legFailN = 0
$launched = New-Object System.Collections.ArrayList
foreach ($leg in $legs) {{
    $gk = $leg.gold
    $meta = $goldMeta[$gk]
    $sym = $meta.symbol
    $legTag = "{{0}}_{{1}}" -f $gk, $leg.model
{block if block is not None else _leg_input_block()}
    [void]$launched.Add(("{{0}}={{1}}" -f $legTag, $legStrategy))
}}
[ordered]@{{ legOk = $legOk; legFailN = $legFailN; reasons = @($legReasons);
    launched = @($launched) }} | ConvertTo-Json -Depth 4
""", encoding="utf-8")
    return subprocess.run([pwsh, "-NoProfile", "-File", str(script)],
                          capture_output=True, text=True, check=False)


def test_stage5_gold1_refusal_is_recorded_and_gold2_legs_still_run(tmp_path):
    cp = _run_leg_inputs(tmp_path, ["gold1", "gold2"],
                         gold1_manifest=str(_gold1_without_engine_config(
                             tmp_path)))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    out = json.loads(cp.stdout)
    # the stage stays FAILED: gold1's legs did not run
    assert out["legOk"] is False
    assert out["legFailN"] == 3
    reasons = out["reasons"]
    assert len(reasons) == 3
    for model in ("m1_ohlc", "every_tick", "real_ticks"):
        assert any(r.startswith(f"gold1_{model}: [input_underivable] "
                                "engine_config.allow_short")
                   and r.endswith("-- leg NOT launched") for r in reasons)
    # every gold2 leg got past input derivation with the gold2 strategy
    assert out["launched"] == [f"gold2_{m}=gold2_multifactor"
                               for m in ("m1_ohlc", "every_tick",
                                         "real_ticks")]


def test_stage5_real_gold1_and_gold2_legs_all_derive(tmp_path):
    # S8-GOLD1-REGEN: the committed gold1 manifest pins engine_config
    cp = _run_leg_inputs(tmp_path, ["gold1", "gold2"])
    assert cp.returncode == 0, cp.stdout + cp.stderr
    out = json.loads(cp.stdout)
    assert out["legOk"] is True and out["reasons"] == []
    models = ("m1_ohlc", "every_tick", "real_ticks")
    assert out["launched"] == [f"gold1_{m}=ema_crossover_ref"
                               for m in models] + \
        [f"gold2_{m}=gold2_multifactor" for m in models]


def test_stage5_scoped_to_gold2_derives_only_gold2_legs(tmp_path):
    cp = _run_leg_inputs(tmp_path, ["gold2"])
    assert cp.returncode == 0, cp.stdout + cp.stderr
    out = json.loads(cp.stdout)
    assert out["legOk"] is True and out["reasons"] == []
    assert len(out["launched"]) == 3
    assert all(x.startswith("gold2_") for x in out["launched"])


def test_the_old_bare_read_reproduces_the_gate_run21_crash(tmp_path):
    old = _leg_input_block().replace(
        '(Get-DataProp $li.data "bundle_evidence")',
        "$li.data.bundle_evidence")
    assert "$li.data.bundle_evidence" in old
    cp = _run_leg_inputs(tmp_path, ["gold1", "gold2"], block=old,
                         gold1_manifest=str(_gold1_without_engine_config(
                             tmp_path)))
    assert cp.returncode != 0
    assert "bundle_evidence" in cp.stderr + cp.stdout
    assert "cannot be found on this object" in cp.stderr + cp.stdout
