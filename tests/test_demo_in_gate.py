"""DEMO-IN-GATE-1: owner_gate.ps1 -DemoSafety runs the demo harness INSIDE
the gate (stage 7) with THIS run's stage-1 EX5, then grades it at stage 8.

gate_run47 (fdd7b58): the gate_run46 demo runs were rejected because their
EX5 (4f03256d...) was another compile's than the gate's stage-1 EX5
(d9a5609c...) at the SAME HEAD -- MetaEditor output differs per compile.
The binding rule stays; the runs now come from the same gate run.

Covered here: the committed decisions (market window, preflight, the
post-harness outcome), the decider CLI, the stage layout in the .ps1, and
Invoke-DemoInGate EXECUTED under pwsh with a stand-in harness. Nothing here
is MT5 evidence.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from mql5bot import demo_harness as dh

REPO = Path(__file__).resolve().parents[1]
PS1 = (REPO / "tools" / "owner_gate.ps1").read_text(encoding="utf-8")
DECIDE = REPO / "tools" / "owner_gate_decide.py"
ACC = {"hedging": {"login": "1111", "password": "s3cret-h",
                   "server": "Demo-Server"},
       "netting": {"login": "2222", "password": "s3cret-n",
                   "server": "Demo-Server"}}
OPEN = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)      # Wednesday


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# ------------------------------------------------------- market window

@pytest.mark.parametrize("when,closed", [
    ("2026-10-16T19:59", False),   # Friday, before the widened close
    ("2026-10-16T20:00", True),    # Friday 20:00 UTC
    ("2026-10-17T12:00", True),    # Saturday
    ("2026-10-18T22:14", True),    # Sunday, before the widened open
    ("2026-10-18T22:15", False),   # Sunday 22:15 UTC
    ("2026-10-19T00:00", False),   # Monday
    ("2026-10-14T10:00", False),   # Wednesday
    ("2026-10-14T20:44", False),   # before the daily rollover window
    ("2026-10-14T20:45", True),    # daily rollover (server midnight)
    ("2026-10-14T22:14", True),
    ("2026-10-14T22:15", False),
])
def test_market_window(when, closed):
    reason = dh.fx_market_closed(_utc(when))
    assert (reason is not None) is closed
    if closed:
        assert reason.startswith(("FX market closed", "FX daily rollover"))


# ----------------------------------------------------------- preflight

@pytest.fixture()
def accounts(tmp_path):
    p = tmp_path / "home" / "demo_accounts.json"
    p.parent.mkdir()
    p.write_text(json.dumps(ACC))
    return p


def test_preflight_passes_with_both_accounts_and_an_open_market(accounts):
    r = dh.demo_preflight(accounts, REPO, OPEN)
    assert r["ok"] is True and r["reasons"] == []


def test_preflight_refuses_a_missing_accounts_file_by_name(tmp_path):
    r = dh.demo_preflight(tmp_path / "none.json", REPO, OPEN)
    assert r["ok"] is False
    assert len(r["reasons"]) == 1             # named once, not per role
    assert r["reasons"][0].startswith("[demo_accounts_missing] no accounts")


def test_preflight_refuses_an_incomplete_role(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"hedging": ACC["hedging"]}))
    r = dh.demo_preflight(p, REPO, OPEN)
    assert r["reasons"] == [("[demo_accounts_missing] accounts file has no "
                            "complete 'netting' entry (login, password, "
                            "server)")]


def test_preflight_refuses_a_closed_market(accounts):
    r = dh.demo_preflight(accounts, REPO, _utc("2026-10-17T12:00"))
    assert r["ok"] is False
    assert r["reasons"][0].startswith("[market_closed] FX market closed")


def test_preflight_never_reads_out_a_credential(accounts):
    text = json.dumps(dh.demo_preflight(accounts, REPO,
                                        _utc("2026-10-17T12:00")))
    assert "s3cret" not in text and "1111" not in text \
        and "2222" not in text and "Demo-Server" not in text


def test_accounts_inside_the_repo_are_refused():
    r = dh.demo_preflight(REPO / "demo_accounts.json", REPO, OPEN)
    assert r["ok"] is False and "inside the repository" in r["reasons"][0]


# --------------------------------------------- after the harness: outcome

def _run(out: Path, test: str, *, status="COMPLETED", restore_ok=True,
         unmet="", check=True, reason=""):
    d = out / test
    d.mkdir(parents=True, exist_ok=True)
    restore = {"ok": restore_ok, "reason": reason, "margin_mode": 2}
    if check:
        restore["connect_check"] = {"sync_unmet": unmet, "synced": not unmet,
                                    "margin_mode": 2}
    (d / "run.json").write_text(json.dumps({
        "status": status, "error": None if status == "COMPLETED" else "x",
        "restore": restore}), encoding="utf-8")


def test_outcome_passes_when_every_restore_is_connected(tmp_path):
    for t in dh.TESTS:
        _run(tmp_path, t)
    r = dh.demo_in_gate_outcome(tmp_path)
    assert r["ok"] is True and r["reasons"] == []
    assert set(r["tests"]) == set(dh.TESTS)


def test_a_failed_test_with_a_good_restore_is_graded_later_not_here(tmp_path):
    for t in dh.TESTS:
        _run(tmp_path, t, status="FAILED" if t == "netting" else "COMPLETED")
    r = dh.demo_in_gate_outcome(tmp_path)
    assert r["ok"] is True                      # stage 8 grades the test
    assert r["tests"]["netting"]["status"] == "FAILED"


def test_a_not_connected_restore_fails_loudly(tmp_path):
    for t in dh.TESTS:
        _run(tmp_path, t)
    _run(tmp_path, "hedging", restore_ok=False, unmet=dh.NOT_CONNECTED,
         reason="restore failed: connection check: a credential-less launch "
                "is NOT connected")
    r = dh.demo_in_gate_outcome(tmp_path)
    assert r["ok"] is False
    assert r["reasons"] == [("[demo_restore_not_connected] hedging: restore "
                            "failed: connection check: a credential-less "
                            "launch is NOT connected")]


def test_a_restore_without_a_connection_check_fails(tmp_path):
    for t in dh.TESTS:
        _run(tmp_path, t, check=(t != "restart"))
    r = dh.demo_in_gate_outcome(tmp_path)
    assert r["reasons"] == [("[demo_restore_not_connected] restart: no "
                            "connection check recorded")]


def test_a_missing_run_fails(tmp_path):
    _run(tmp_path, "restart")
    r = dh.demo_in_gate_outcome(tmp_path)
    assert [x.split(":")[0] for x in r["reasons"]] == [
        "[demo_run_missing] netting", "[demo_run_missing] hedging"]


# ---------------------------------------------------------- decider CLI

def _decide(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(DECIDE), "--repo", str(REPO),
                           *args], capture_output=True, text=True,
                          check=False)


def test_decider_demo_preflight(accounts):
    ok = _decide("demo-preflight", "--accounts", str(accounts),
                 "--now", "2026-10-14T10:00:00Z")
    assert ok.returncode == 0 and json.loads(ok.stdout)["ok"] is True
    closed = _decide("demo-preflight", "--accounts", str(accounts),
                     "--now", "2026-10-17T12:00:00Z")
    assert closed.returncode == 1
    assert json.loads(closed.stdout)["reasons"][0].startswith(
        "[market_closed]")


def test_decider_demo_in_gate_outcome(tmp_path):
    for t in dh.TESTS:
        _run(tmp_path, t)
    assert _decide("demo-in-gate-outcome", "--dir",
                   str(tmp_path)).returncode == 0
    _run(tmp_path, "netting", restore_ok=False, unmet=dh.NOT_CONNECTED)
    assert _decide("demo-in-gate-outcome", "--dir",
                   str(tmp_path)).returncode == 1


# ------------------------------------------------------- the .ps1 layout

def test_ps1_has_the_switch_and_no_stage_7_without_it():
    assert "[switch]$DemoSafety" in PS1
    assert "[string]$DemoAccounts" in PS1
    i = PS1.index('Enter-Stage 7 "demo_safety"')
    guard = PS1.rindex("if ($DemoSafety) {", 0, i)
    assert PS1[guard:i].count("\n") <= 2        # the guard opens stage 7


def test_ps1_preflights_at_stage_0_and_refuses_both_sources():
    s0 = PS1[PS1.index('Enter-Stage 0 "self_protection"'):
             PS1.index('Enter-Stage 1 "strict_compile"')]
    assert '(@("demo-preflight") + $demoAccArgs)' in s0
    assert "[demo_args_conflict]" in s0
    # the preflight decides BEFORE stage 0 can PASS
    assert s0.index("demo-preflight") < s0.index(
        'Record-Stage 0 "self_protection" "PASS"')


def test_ps1_stage_7_sits_between_stage_5_and_stage_8():
    s5 = PS1.index('Enter-Stage 5 "tester_legs"')
    s7 = PS1.index('Enter-Stage 7 "demo_safety"')
    s8 = PS1.index('Enter-Stage 8 "reconciliation"')
    assert s5 < s7 < s8
    body = PS1[s7:s8]
    # market re-checked (it may have closed during stages 1-5), harness
    # into THIS run's evidence dir, a failed restore is a loud FAIL
    assert '(@("demo-preflight") + $demoAccArgs)' in body
    assert '$demoInGateDir = Join-Path $Evidence "demo_safety"' in body
    assert "Invoke-DemoInGate $demoInGateDir $demoAccArgs" in body
    assert "[demo_terminal_not_restored]" in body
    assert body.count('Finish-Gate "demo_safety"') == 2
    assert "NOT a safety grade" in body


def test_ps1_stage_8_grades_this_runs_demo_dir_first():
    assert ('$demoDir = if ($demoInGateDir) { $demoInGateDir } elseif '
            '($DemoEvidence) { $DemoEvidence } else') in PS1


def test_ps1_function_runs_each_test_with_this_runs_terminal_and_data():
    fn = _fn("Invoke-DemoInGate")
    assert '@("restart", "netting", "hedging")' in fn
    for arg in ('"--terminal", $TerminalPath', '"--data-folder", $DataFolder',
                '"--out", $outDir'):
        assert arg in fn
    assert '@("demo-in-gate-outcome", "--dir", $outDir)' in fn


# --------------------------------------- Invoke-DemoInGate under pwsh

def _pwsh() -> str | None:
    exe = shutil.which("pwsh") or shutil.which("powershell")
    if exe:
        return exe
    cand = Path.home() / ".dotnet" / "tools" / "pwsh"
    return str(cand) if cand.is_file() else None


def _fn(name: str) -> str:
    i = PS1.index(f"function {name}")
    return PS1[i:PS1.index("\n}\n", i) + 3]


_FAKE_HARNESS = r'''
import json, os, sys
a = sys.argv[1:]
test = a[a.index("--test") + 1]
out = a[a.index("--out") + 1]
d = os.path.join(out, test)
os.makedirs(d, exist_ok=True)
bad = os.environ.get("FAKE_BAD_TEST") == test
restore = {"ok": not bad, "margin_mode": 2,
           "reason": ("restore failed: connection check: a credential-less "
                      "launch is NOT connected") if bad else "",
           "connect_check": {"sync_unmet": "terminal not connected" if bad
                             else "", "synced": not bad, "margin_mode": 2}}
json.dump({"status": "FAILED" if bad else "COMPLETED", "restore": restore,
           "argv": a}, open(os.path.join(d, "run.json"), "w"))
print(json.dumps({"ok": not bad}))
sys.exit(1 if bad else 0)
'''


def _run_fn(tmp_path: Path, bad: str = ""):
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    fake = tmp_path / "fake_harness.py"
    fake.write_text(_FAKE_HARNESS, encoding="utf-8")
    funcs = "".join(_fn(n) for n in (
        "Get-Sha256", "New-Artifact", "ConvertTo-ProcArg", "Get-ProcArgs",
        "Invoke-Decide", "Get-DataProp", "Invoke-DemoInGate"))
    body = "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$Evidence = '{tmp_path / 'ev'}'",
        f"$DataFolder = '{tmp_path / 'data'}'",
        f"$RepoRoot = '{REPO}'",
        f"$Decide = '{DECIDE}'",
        f"$Python = '{sys.executable}'",
        "$TerminalPath = 'C:\\MT5\\terminal64.exe'",
        f"$Script:DemoHarnessScript = '{fake}'",
        "New-Item -ItemType Directory -Force -Path $Evidence | Out-Null",
        funcs,
        ("$r = Invoke-DemoInGate (Join-Path $Evidence 'demo_safety') "
         "@('--accounts', 'C:\\acc.json')"),
        ("[Console]::Out.Write((ConvertTo-Json -InputObject @{ ok = $r.ok; "
         "reasons = @($r.reasons); ran = @($r.ran) } -Compress))"),
    ])
    script = tmp_path / "h.ps1"
    script.write_text(body, encoding="utf-8")
    env = dict(os.environ, FAKE_BAD_TEST=bad)
    cp = subprocess.run([pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass",
                         "-File", str(script)], capture_output=True,
                        text=True, env=env, check=False, timeout=300)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    return json.loads(cp.stdout[cp.stdout.index("{"):]), tmp_path / "ev"


def test_invoke_demo_in_gate_runs_all_three_into_this_runs_dir(tmp_path):
    r, ev = _run_fn(tmp_path)
    assert r["ok"] is True and r["reasons"] == []
    assert r["ran"] == ["restart=exit 0", "netting=exit 0", "hedging=exit 0"]
    for t in dh.TESTS:
        argv = json.loads((ev / "demo_safety" / t / "run.json").read_text(
            ))["argv"]
        assert argv[argv.index("--terminal") + 1] == "C:\\MT5\\terminal64.exe"
        assert argv[argv.index("--data-folder") + 1] == str(tmp_path / "data")
        assert argv[argv.index("--out") + 1] == str(ev / "demo_safety")
        assert argv[argv.index("--accounts") + 1] == "C:\\acc.json"


def test_invoke_demo_in_gate_fails_when_a_restore_is_not_connected(tmp_path):
    r, _ = _run_fn(tmp_path, bad="netting")
    assert r["ok"] is False
    assert r["reasons"] == [
        ("[demo_restore_not_connected] netting: restore failed: connection "
        "check: a credential-less launch is NOT connected")]
    assert "netting=exit 1" in r["ran"]


def test_no_credential_reaches_the_gate_evidence(tmp_path):
    _, ev = _run_fn(tmp_path)
    for f in ev.rglob("*"):
        if f.is_file():
            text = f.read_text(errors="replace")
            assert not re.search(r"s3cret|Password=", text), f
