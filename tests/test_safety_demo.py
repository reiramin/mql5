"""lost_response (TradeManager fault hook, tester) and the demo harness for
restart / netting / hedging (docs/SAFETY_DEMO_PLAN.md).

Self-tests only: a green test here is NOT MT5 evidence. The fault-hook and
probe lines are the strings the new test-only MQL5 code prints; no MT5 run
has printed them yet. The harness runs here against a FAKE terminal.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from mql5bot import demo_harness as dh
from mql5bot import mt5tester as mt
from mql5bot import owner_gate as og
from mql5bot import safety_legs as sl
from mql5bot import stage8_package as s8p
from test_owner_gate import SAFETY_DEMO_LOGS, SAFETY_WINDOWS
from test_stage8_package_from_gate import REPO, run26  # noqa: F401

EA = (REPO / "mql5/Experts/Mql5Bot/Mql5Bot.mq5").read_text(
    encoding="utf-8", errors="replace")
TM = (REPO / "mql5/Include/Mql5Bot/TradeManager.mqh").read_text(
    encoding="utf-8", errors="replace")
SYM = "EURUSD.G2"


# ---------------------------------------------------------------------------
# MQL5 source: default OFF, guarded, the live path unchanged
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["InpTestLostResponses",
                                  "InpTestUnsentTimeouts",
                                  "InpTestDemoProbe"])
def test_new_ea_inputs_default_off_and_mirrored(name):
    m = re.search(rf"^input\s+int\s+{name}\s*=\s*0;", EA, re.MULTILINE)
    assert m
    assert mt.EA_INPUT_DEFAULTS[name] == 0


def test_ea_hooks_are_guarded():
    assert re.search(r"if\(InpTestLostResponses > 0 \|\| "
                     r"InpTestUnsentTimeouts > 0\)\s*\n\s*"
                     r"g_trade\.TestFaults\(", EA)
    assert re.search(r"if\(InpTestDemoProbe > 0\)\s*\n\s*"
                     r"TestDemoProbePump\(\);", EA)
    # the probe replaces the strategy only while it runs
    assert re.search(r"if\(InpTestDemoProbe > 0\)\s*\n\s*return;", EA)
    assert EA.count("TestDemoProbePump()") == 2


def test_trade_manager_hook_defaults_to_zero_and_keeps_the_send():
    assert "m_testDropResponses = 0;" in TM
    assert "m_testSuppressSends = 0;" in TM
    # at 0 the else-branch is the former single line, unchanged
    assert re.search(
        r"if\(m_testSuppressSends > 0\)\s*\{.*?\}\s*else\s*\{\s*"
        r"rc = MarketChain\(dir, lots, slDist, tpDist, comment, res, lat, "
        r"slip\);\s*if\(m_testDropResponses > 0 && IsSuccessRetcode\(rc\)\)",
        TM, re.DOTALL)
    # retries never pass through the hook (ExecuteQueued calls MarketChain)
    q = TM[TM.index("void              ExecuteQueued"):]
    assert "m_testDropResponses" not in q[:3000]
    assert "m_testSuppressSends" not in q[:3000]


def test_the_messages_the_graders_read_are_printed():
    assert "TEST 8c lost_response: SUPPRESSED send of %s " in TM
    assert "TEST 8c lost_response: DROPPED response of " in TM
    assert '"[mql5bot] EXEC|%s|%s|%s|%d|%.2f|%d|%s"' in TM
    for s in ("TEST demo: START probe=%d magic=%I64d ",
              "TEST demo: SNAPSHOT %s margin_mode=%d ",
              "TEST demo: PROBE position opened",
              "TEST demo: CLEANUP closed %d"):
        assert s in EA


# ---------------------------------------------------------------------------
# lost_response grader
# ---------------------------------------------------------------------------

LR = SAFETY_WINDOWS["lost_response"]


def test_lost_response_pass():
    d = sl.grade("lost_response", LR, "", SYM)
    assert d["observed_result"] == "LOST_RESPONSE_ADOPTED_NO_DUPLICATE"
    assert d["facts"]["retried_once"] == 1
    assert d["facts"]["adopted_from_history"] == 1


def test_lost_response_a_resend_after_a_dropped_answer_is_a_duplicate():
    extra = LR.rstrip("\n").split("\n")
    req = next(ln for ln in extra if "08:46:00   instant" in ln)
    w = "\n".join(extra + [req]) + "\n"           # a second send at 08:46
    assert sl.grade("lost_response", w, "", SYM)["observed_result"] == \
        "DUPLICATE_SEND:c2:2"


def test_lost_response_not_adopted():
    w = LR.replace("EXEC|open_verified|", "EXEC|open_queued|")
    assert sl.grade("lost_response", w, "", SYM)["observed_result"] == \
        "NOT_ADOPTED:c2"


def test_lost_response_retry_not_done():
    w = LR.replace("EXEC|open_retry|", "EXEC|open_retry_giveup|")
    assert sl.grade("lost_response", w, "", SYM)["observed_result"] == \
        "RETRY_NOT_DONE:c1"


def test_lost_response_not_triggered_and_inconclusive():
    assert sl.grade("lost_response", "x\n", "", SYM)["observed_result"] == \
        "NOT_TRIGGERED"
    only_drop = "\n".join(ln for ln in LR.split("\n")
                          if "c1" not in ln and "08:01:01" not in ln)
    assert sl.grade("lost_response", only_drop, "", SYM)[
        "observed_result"] == "INCONCLUSIVE_ONE_FAULT_KIND_MISSING"


# ---------------------------------------------------------------------------
# demo graders
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["restart", "netting", "hedging"])
def test_demo_graders_pass_on_the_reference_logs(name):
    d = sl.grade(name, SAFETY_DEMO_LOGS[name], "", "")
    assert d["observed_result"] == d["expected_result"] == \
        og.SAFETY_PINNED_EXPECTED[name]


@pytest.mark.parametrize("old,new,observed", [
    ("10:01:00] [INFO] TEST demo: START probe=1 magic=123",
     "10:01:00] [INFO] TEST demo: START probe=1 magic=999", "MAGIC_CHANGED"),
    ("magic=123 own_positions=1 registry=1 engine=0",
     "magic=123 own_positions=0 registry=0 engine=0",
     "POSITION_LOST_AT_RESTART"),
    ("SNAPSHOT heartbeat margin_mode=2 own_positions=1",
     "SNAPSHOT heartbeat margin_mode=2 own_positions=2",
     "DUPLICATE_EXPOSURE:1"),
    ("TEST demo: PROBE position opened", "x", "PROBE_NOT_OPENED"),
])
def test_restart_failures(old, new, observed):
    log = SAFETY_DEMO_LOGS["restart"].replace(old, new)
    assert sl.grade("restart", log, "", "")["observed_result"] == observed


def test_restart_without_a_second_start():
    log = "\n".join(SAFETY_DEMO_LOGS["restart"].split("\n")[:2]) + "\n"
    assert sl.grade("restart", log, "", "")["observed_result"] == \
        "NO_RESTART"


def test_netting_on_a_hedging_account_is_wrong_mode():
    log = SAFETY_DEMO_LOGS["netting"].replace("margin_mode=0",
                                              "margin_mode=2")
    assert sl.grade("netting", log, "", "")["observed_result"] == \
        "WRONG_ACCOUNT_MODE:2"


def test_netting_with_two_positions_is_not_netted():
    log = SAFETY_DEMO_LOGS["netting"].replace(
        "positions=[5:sell:0.01:123]",
        "positions=[6:sell:0.02:123,5:buy:0.01:123]")
    assert sl.grade("netting", log, "", "")["observed_result"] == \
        "NOT_NETTED:2"


def test_hedging_registry_holding_the_foreign_magic_is_not_isolated():
    log = SAFETY_DEMO_LOGS["hedging"].replace(
        "own_positions=2 registry=2 positions=[7:",
        "own_positions=2 registry=3 positions=[7:")
    assert sl.grade("hedging", log, "", "")["observed_result"] == \
        "NOT_ISOLATED:own=2,registry=3"


# ---------------------------------------------------------------------------
# builder + verifier: demo evidence bound to this gate's EX5
# ---------------------------------------------------------------------------

def _demo_dir(tmp_path, name, log, ex5):
    d = tmp_path / "demo" / name
    d.mkdir(parents=True)
    (d / "ealog.txt").write_text(log, encoding="utf-8")
    (d / "run.json").write_text(json.dumps({"test": name,
                                            "ex5_sha256": ex5}))
    return tmp_path / "demo"


def _rebuild(run, tmp_path, demo):
    _, pkg, ev = run
    return s8p.build_package(
        repo=REPO, package=pkg, gate_evidence=ev,
        data_folder=tmp_path / "data", golds=["gold2"],
        symbolspec_export=tmp_path / "EURUSD.json",
        host={"os": "Windows (test)", "timezone": "UTC"},
        demo_evidence=demo), pkg


def _ex5(tmp_path):
    return s8p._sha(tmp_path / "data/MQL5/Experts/Mql5Bot/Mql5Bot.ex5")


def test_demo_run_with_this_gates_ex5_is_graded_and_verified(
        run26, tmp_path):  # noqa: F811
    demo = _demo_dir(tmp_path, "netting", SAFETY_DEMO_LOGS["netting"],
                     _ex5(tmp_path).upper())
    rec, pkg = _rebuild(run26, tmp_path, demo)
    doc = json.loads((pkg / "safety/netting.json").read_text())
    assert doc["observed_result"] == "NET_ONE_POSITION_PER_SYMBOL"
    assert doc["raw_evidence"]["path"] == "safety/raw/netting_ealog.txt"
    assert og.verify_safety(pkg)["netting"]["state"] == og.VALID
    # tests with no harness run stay unbuilt
    assert "no demo harness run" in rec["not_built"]["safety/restart.json"]


def test_demo_run_of_another_binary_is_never_used(run26, tmp_path):  # noqa: F811
    demo = _demo_dir(tmp_path, "netting", SAFETY_DEMO_LOGS["netting"],
                     "0" * 64)
    rec, pkg = _rebuild(run26, tmp_path, demo)
    assert not (pkg / "safety/netting.json").exists()
    assert "evidence of another binary" in \
        rec["not_built"]["safety/netting.json"]


def test_forged_demo_pass_over_a_failing_log_is_invalid(
        run26, tmp_path):  # noqa: F811
    bad = SAFETY_DEMO_LOGS["netting"].replace("margin_mode=0",
                                              "margin_mode=2")
    demo = _demo_dir(tmp_path, "netting", bad, _ex5(tmp_path))
    _, pkg = _rebuild(run26, tmp_path, demo)
    path = pkg / "safety/netting.json"
    doc = json.loads(path.read_text())
    assert doc["observed_result"] == "WRONG_ACCOUNT_MODE:2"
    doc["observed_result"] = "NET_ONE_POSITION_PER_SYMBOL"
    path.write_text(json.dumps(doc))
    cp = subprocess.run([sys.executable,
                         str(REPO / "tools/owner_evidence_bind.py"),
                         "manifest", str(pkg), "--frozen",
                         str(REPO / s8p.FROZEN_INPUTS_REL)],
                        capture_output=True, text=True, check=True)
    (pkg / "archive_manifest.json").write_text(cp.stdout)
    rep = og.verify_safety(pkg)["netting"]
    assert rep["state"] == og.INVALID
    assert "re-grades the bound windows as 'WRONG_ACCOUNT_MODE:2'" in \
        rep["reasons"][0]


def test_decider_and_ps1_pass_the_demo_evidence():
    src = (REPO / "tools/owner_gate_decide.py").read_text("utf-8")
    assert "demo_evidence=args.demo_evidence or None" in src
    ps1 = (REPO / "tools/owner_gate.ps1").read_text("utf-8")
    assert '[string]$DemoEvidence = ""' in ps1
    assert '$demoArgs = @("--demo-evidence", $demoDir)' in ps1
    assert "+ $demoArgs + $customSpecArgs)" in ps1


# ---------------------------------------------------------------------------
# the harness, against a fake terminal
# ---------------------------------------------------------------------------

ACC = {"hedging": {"login": "1111", "password": "s3cret-h",
                   "server": "Demo-Server"},
       "netting": {"login": "2222", "password": "s3cret-n",
                   "server": "Demo-Server"}}


@pytest.fixture()
def accounts(tmp_path):
    p = tmp_path / "home" / "demo_accounts.json"
    p.parent.mkdir()
    p.write_text(json.dumps(ACC))
    return p


def test_accounts_inside_the_repo_are_refused():
    with pytest.raises(dh.HarnessError, match="inside the repository"):
        dh.load_account(REPO / "demo_accounts.json", "hedging", REPO)


def test_accounts_need_a_complete_role(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"hedging": {"login": "1"}}))
    with pytest.raises(dh.HarnessError, match="no complete 'hedging'"):
        dh.load_account(p, "hedging", REPO)


def test_startup_ini_and_preset():
    ini = dh.startup_ini(ACC["hedging"], "p.set")
    for line in ("[Common]", "Login=1111", "Server=Demo-Server",
                 "AllowLiveTrading=1", "[StartUp]",
                 r"Expert=Mql5Bot\Mql5Bot", "ExpertParameters=p.set",
                 "Symbol=EURUSD", "Period=M1"):
        assert line in ini
    pre = dh.preset_text(2)
    assert "InpTestDemoProbe=2" in pre
    assert "s3cret" not in pre


class FakeTerminal:
    """Plays the EA: on launch, reads the [StartUp] ini (it must exist and
    hold the password while the terminal starts), and writes the EA log as
    the EA would -- UTF-16 with BOM, re-created on every start."""

    def __init__(self, data: Path):
        self.data, self.launches, self.ini_seen = data, [], []
        self.position_open = False
        self.logdir = data / dh.LOG_DIR_REL
        self.logdir.mkdir(parents=True)

    def __call__(self, argv):
        ini = Path(argv[1].split(":", 1)[1])
        text = ini.read_text(encoding="utf-16")
        self.ini_seen.append(text)
        preset = re.search(r"ExpertParameters=(\S+)", text).group(1)
        probe = int(re.search(r"InpTestDemoProbe=(\d)", (
            self.data / dh.PRESET_DIR_REL / preset).read_text()).group(1))
        n = len(self.launches)
        self.launches.append(probe)
        own = 1 if self.position_open else 0
        lines = [(f"[2026.10.07 10:0{n}:00] [INFO] TEST demo: START "
                  f"probe={probe} magic=123 own_positions={own} "
                  f"registry={own} engine=0 margin_mode=2")]
        if probe == 1 and not self.position_open:
            self.position_open = True
            lines.append(f"[2026.10.07 10:0{n}:05] [INFO] TEST demo: PROBE "
                         "position opened")
        elif probe == 1:
            lines.append(f"[2026.10.07 10:0{n}:10] [INFO] TEST demo: "
                         "SNAPSHOT heartbeat margin_mode=2 own_positions=1 "
                         "registry=1 positions=[5:buy:0.01:123]")
        elif probe == 3:
            self.position_open = False
            lines.append(f"[2026.10.07 10:0{n}:05] [INFO] TEST demo: "
                         "CLEANUP closed 1")
        (self.logdir / "mql5bot_EURUSD_M1_2026.10.07.log").write_bytes(
            ("\n".join(lines) + "\n").encode("utf-16"))
        return self

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


def _harness(tmp_path, accounts, test):
    data = tmp_path / "data"
    (data / dh.EA_REL).parent.mkdir(parents=True)
    (data / dh.EA_REL).write_bytes(b"ex5")
    fake = FakeTerminal(data)
    h = dh.Harness(test=test, terminal="terminal64.exe", data_folder=data,
                   accounts=accounts, repo=REPO, out_dir=tmp_path / "out",
                   launch=fake, sleep=lambda s: None, timeout_s=3,
                   hold_s=1, observe_s=1)
    return h, fake


def test_restart_run_kills_relaunches_cleans_up_and_grades(tmp_path, accounts):
    h, fake = _harness(tmp_path, accounts, "restart")
    rec = h.run()
    assert rec["error"] is None, rec
    assert fake.launches == [1, 1, 3]
    assert any("KILLED" in s["step"] for s in rec["steps"])
    log = (tmp_path / "out/restart/ealog.txt").read_text()
    # lines of the first start survive the EA re-creating its log file
    assert "PROBE position opened" in log and log.count("START probe=1") == 2
    assert sl.grade("restart", log, "", "")["observed_result"] == \
        "RESTART_RECOVERED_NO_DUPLICATE"
    assert rec["ex5_sha256"] == s8p._sha_bytes(b"ex5")


def test_credentials_never_reach_the_evidence_or_stay_on_disk(
        tmp_path, accounts):
    h, fake = _harness(tmp_path, accounts, "restart")
    h.run()
    assert all("Password=s3cret-h" in t for t in fake.ini_seen)
    out = tmp_path / "out" / "restart"
    for f in out.iterdir():
        text = f.read_text()
        assert "s3cret" not in text and "1111" not in text \
            and "Demo-Server" not in text
    assert h._tmp is None            # the temp ini dir was removed


def test_a_missing_ea_line_times_out_and_is_recorded(tmp_path, accounts):
    h, _ = _harness(tmp_path, accounts, "netting")
    rec = h.run()                    # the fake never prints CLEANUP for 2
    assert rec["error"] and "timeout" in rec["error"]
    assert json.loads((tmp_path / "out/netting/run.json").read_text())[
        "error"] == rec["error"]


def test_netting_uses_the_netting_account(tmp_path, accounts):
    h, fake = _harness(tmp_path, accounts, "netting")
    h.run()
    assert "Login=2222" in fake.ini_seen[0]


def test_cli_refuses_without_accounts(tmp_path):
    cp = subprocess.run([sys.executable,
                         str(REPO / "tools/demo_safety_harness.py"), "run",
                         "--test", "restart", "--terminal", "t.exe",
                         "--data-folder", str(tmp_path), "--accounts",
                         str(tmp_path / "none.json"), "--out",
                         str(tmp_path / "o")],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 1
    assert "no accounts file" in json.loads(cp.stdout)["error"]
