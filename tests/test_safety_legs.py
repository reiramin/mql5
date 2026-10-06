"""Safety sub-checks 8a-8d that run in the Strategy Tester
(docs/SAFETY_8A_8D_PLAN.md; owner authorization 2026-10-06).

Self-tests only: a green test here is NOT MT5 evidence. Windows below are
SYNTHETIC lines in MEASURED formats: the tester-log prefix and MT5's
`instant ... sl: tp:` request line are gate_run35's
(tester_gold2_*_window.txt); the EA log prefix `[time] [LEVEL] msg` is
Logger.mqh's (gate_run35 DEAL lines). The `TEST 8a/8b` messages are the
strings the new test-only EA hooks print; no MT5 run has printed them yet.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys

import pytest
from mql5bot import mt5tester as mt
from mql5bot import owner_gate as og
from mql5bot import safety_legs as sl
from mql5bot import stage8_package as s8p
from test_stage8_package_from_gate import PS1, REPO, run26  # noqa: F401

EA = (REPO / "mql5" / "Experts" / "Mql5Bot" / "Mql5Bot.mq5").read_text(
    encoding="utf-8", errors="replace")
SYM = "EURUSD.G2"
_P = "CJ\t0\t00:57:44.780\tCore 1\t"


def _req(t: str, side: str, vol: float, price: str = "1.09720") -> str:
    return (f"{_P}{t}   instant {side} {vol} {SYM} at {price} sl: 1.09658 "
            f"tp: 1.09814 ({price} / {price} / {price})")


def _close(t: str) -> str:
    return f"{_P}{t}   instant sell 0.01 {SYM} at 1.09746, close #2 (x)"


def _ea(t: str, level: str, msg: str) -> str:
    return f"{_P}{t}   [{t}] [{level}] {msg}"


def _win(*lines: str) -> str:
    return "\n".join(lines) + "\n"


BASELINE = _win(_req("2024.01.02 08:01:00", "sell", 0.01),
                _req("2024.01.02 08:46:00", "buy", 0.28),
                _req("2024.01.02 12:00:00", "buy", 0.30),
                _req("2024.01.03 08:01:00", "buy", 3.52))


# ---------------------------------------------------------------------------
# EA source: test-only inputs, default OFF, hooks guarded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,default", [
    ("InpTestKillSwitchAfterEntries", "0"), ("InpTestStripSlEntries", "0"),
    ("InpTestSafetyLog", "false")])
def test_ea_test_inputs_exist_and_default_off(name, default):
    m = re.search(rf"^input\s+\S+\s+{name}\s*=\s*([^;]+);", EA, re.MULTILINE)
    assert m and m.group(1).strip() == default
    assert mt.EA_INPUT_DEFAULTS[name] in (0, False)


def test_every_test_hook_is_guarded_by_its_input():
    # each hook is entered only behind its non-default input
    assert re.search(r"if\(InpTestStripSlEntries > 0\)\s*\n\s*"
                     r"TestSlStripPump\(\);", EA)
    assert re.search(r"if\(InpTestKillSwitchAfterEntries > 0\)\s*\n\s*\{\s*"
                     r"\n\s*g_testEntries\+\+;", EA)
    assert re.search(r"if\(InpTestSafetyLog\)\s*\n\s*g_log\.Info\("
                     r"StringFormat\(\"TEST 8a meta:", EA)
    # TestSlStripPump is called from that one guarded site only
    assert EA.count("TestSlStripPump()") == 2  # the call + the definition
    # the kill-switch trip is the existing RiskManager API, REASON_MANUAL
    assert "g_risk.TripKillSwitch(REASON_MANUAL);" in EA


def test_the_messages_the_graders_read_are_the_ones_the_ea_prints():
    assert "TEST 8a kill switch: LATCHED after entry %d " in EA
    assert '"(state=%d reason=%d AllowsNewTrades=%s)"' in EA
    assert "TEST 8a meta: risk_approved=%.2f scaled=%.4f " in EA
    assert '"final=%.2f base_weight=%.4f"' in EA
    assert "TEST 8b sl: STRIPPED #%I64u sl %.5f -> %.5f " in EA
    assert "TEST 8b sl: RESTORED #%I64u sl=%.5f" in EA
    assert "TEST 8b sl: #%I64u closed before an SL was " in EA
    assert 'g_log.Error("DAILY LOSS LIMIT HIT' in EA


# ---------------------------------------------------------------------------
# graders
# ---------------------------------------------------------------------------

def test_kill_switch_passes_with_zero_orders_after_the_latch():
    w = _win(_req("2024.01.02 08:01:00", "sell", 0.01),
             _ea("2024.01.02 08:01:00", "WARN",
                 "TEST 8a kill switch: LATCHED after entry 1 (state=2 "
                 "reason=1 AllowsNewTrades=false)"),
             _close("2024.01.02 08:01:10"))
    d = sl.grade("kill_switch", w, BASELINE, SYM)
    assert d["observed_result"] == d["expected_result"] == \
        "ZERO_NEW_ORDERS_WHILE_LATCHED"
    assert d["facts"]["baseline_entries_after_latch"] == 3
    assert d["passed"] is True


def test_kill_switch_with_an_order_after_the_latch_fails():
    w = _win(_req("2024.01.02 08:01:00", "sell", 0.01),
             _ea("2024.01.02 08:01:00", "WARN",
                 "TEST 8a kill switch: LATCHED after entry 1 (state=2 "
                 "reason=1 AllowsNewTrades=false)"),
             _req("2024.01.02 08:46:00", "buy", 0.28))
    d = sl.grade("kill_switch", w, BASELINE, SYM)
    assert d["observed_result"] == "NEW_ORDERS_AFTER_LATCH:1"
    assert d["passed"] is False


def test_kill_switch_without_baseline_entries_is_inconclusive():
    w = _win(_ea("2024.01.03 08:01:00", "WARN",
                 "TEST 8a kill switch: LATCHED after entry 1 (state=2 "
                 "reason=1 AllowsNewTrades=false)"))
    d = sl.grade("kill_switch", w, BASELINE, SYM)
    assert d["observed_result"] == \
        "INCONCLUSIVE_NO_BASELINE_ENTRY_AFTER_LATCH"


def test_kill_switch_never_latched():
    d = sl.grade("kill_switch", BASELINE, BASELINE, SYM)
    assert d["observed_result"] == "NOT_LATCHED"


def test_risk_veto_holds_for_the_day():
    w = _win(_req("2024.01.02 08:01:00", "sell", 0.01),
             _ea("2024.01.02 08:40:00", "ERROR",
                 "DAILY LOSS LIMIT HIT — trading paused for today "
                 "(persisted)"),
             _req("2024.01.03 08:01:00", "buy", 3.52))  # next day: allowed
    d = sl.grade("risk_veto", w, BASELINE, SYM)
    assert d["observed_result"] == "ENTRIES_VETOED_FOR_THE_DAY"
    assert d["facts"]["baseline_entries_after_halt_same_day"] == 2


def test_risk_veto_broken_by_a_same_day_entry():
    w = _win(_ea("2024.01.02 08:40:00", "ERROR", "DAILY LOSS LIMIT HIT"),
             _req("2024.01.02 12:00:00", "buy", 0.30))
    d = sl.grade("risk_veto", w, BASELINE, SYM)
    assert d["observed_result"] == "ENTRY_AFTER_VETO:1"


def test_risk_veto_never_triggered():
    assert sl.grade("risk_veto", BASELINE, BASELINE, SYM)[
        "observed_result"] == "NOT_TRIGGERED"


def _meta(t: str, approved: float, final: float) -> str:
    return _ea(t, "INFO", f"TEST 8a meta: risk_approved={approved:.2f} "
               f"scaled={final:.4f} final={final:.2f} base_weight=0.5000")


def test_meta_reduce_every_size_at_or_below_the_approval():
    w = _win(_meta("2024.01.02 08:01:00", 0.02, 0.01),
             _req("2024.01.02 08:01:00", "sell", 0.01),
             _meta("2024.01.02 08:46:00", 0.56, 0.28),
             _req("2024.01.02 08:46:00", "buy", 0.28))
    d = sl.grade("meta_reduce", w, "", SYM)
    assert d["observed_result"] == "ALL_SIZES_LE_RISK_APPROVED"
    assert d["facts"]["reduced"] == 2
    assert d["facts"]["base_weight"] == 0.5


def test_meta_reduce_a_size_above_approval_fails():
    w = _win(_meta("2024.01.02 08:01:00", 0.02, 0.03),
             _req("2024.01.02 08:01:00", "sell", 0.03))
    d = sl.grade("meta_reduce", w, "", SYM)
    assert d["observed_result"] == "SIZE_ABOVE_RISK_APPROVED:1"


def test_meta_reduce_sent_volume_must_be_the_final_size():
    w = _win(_meta("2024.01.02 08:01:00", 0.04, 0.02),
             _req("2024.01.02 08:01:00", "sell", 0.03))
    d = sl.grade("meta_reduce", w, "", SYM)
    assert d["observed_result"] == "SENT_VOLUME_NOT_THE_FINAL_SIZE:1"


def test_meta_reduce_nothing_reduced_is_inconclusive():
    w = _win(_meta("2024.01.02 08:01:00", 0.01, 0.01),
             _req("2024.01.02 08:01:00", "sell", 0.01))
    assert sl.grade("meta_reduce", w, "", SYM)["observed_result"] == \
        "INCONCLUSIVE_NOTHING_REDUCED"


def _strip(t, ticket, after="0.00000"):
    return _ea(t, "WARN", f"TEST 8b sl: STRIPPED #{ticket} sl 1.09658 -> "
               f"{after} (modify done)")


def _restore(t, ticket):
    return _ea(t, "INFO", f"TEST 8b sl: RESTORED #{ticket} sl=1.09660")


def test_sl_verify_stripped_and_restored():
    w = _win(_strip("2024.01.02 08:01:01", 2), _restore("2024.01.02 08:01:02", 2),
             _strip("2024.01.02 08:46:01", 4), _restore("2024.01.02 08:46:02", 4))
    d = sl.grade("sl_verify", w, "", SYM)
    assert d["observed_result"] == "SL_STRIPPED_AND_RESTORED"
    assert d["facts"]["restored"] == 2


def test_sl_verify_a_stop_never_restored_fails():
    w = _win(_strip("2024.01.02 08:01:01", 2), _restore("2024.01.02 08:01:02", 2),
             _strip("2024.01.02 08:46:01", 4))
    assert sl.grade("sl_verify", w, "", SYM)["observed_result"] == \
        "SL_NOT_RESTORED:1"


def test_sl_verify_a_strip_that_did_not_apply_is_not_counted():
    w = _win(_strip("2024.01.02 08:01:01", 2, after="1.09658"))
    d = sl.grade("sl_verify", w, "", SYM)
    assert d["observed_result"] == "INCONCLUSIVE_NOTHING_RESTORED"
    assert d["facts"]["strip_not_applied"] == ["2"]


def test_sl_verify_closed_before_restore_is_not_a_pass_alone():
    w = _win(_strip("2024.01.02 08:01:01", 2),
             _ea("2024.01.02 08:02:00", "WARN",
                 "TEST 8b sl: #2 closed before an SL was restored"))
    assert sl.grade("sl_verify", w, "", SYM)["observed_result"] == \
        "INCONCLUSIVE_NOTHING_RESTORED"


def test_tester_and_demo_sets_cover_the_eight_artifacts_once():
    tester, demo = set(sl.TESTER_SAFETY_LEGS), set(sl.DEMO_ONLY)
    assert tester == {"kill_switch", "risk_veto", "meta_reduce", "sl_verify"}
    assert demo == {"lost_response", "restart", "netting", "hedging"}
    assert tester | demo == set(og.SAFETY_TESTS) | {"netting", "hedging"}
    for spec in sl.TESTER_SAFETY_LEGS.values():
        assert set(spec["inputs"]) <= set(mt.EA_INPUT_DEFAULTS)


# ---------------------------------------------------------------------------
# verifier: observed must equal expected (SAFETY-RESULT-1)
# ---------------------------------------------------------------------------

def _safety_pkg(tmp_path, observed, expected="ZERO_NEW_ORDERS_WHILE_LATCHED"):
    raw = tmp_path / "safety" / "raw" / "kill_switch_window.txt"
    raw.parent.mkdir(parents=True)
    raw.write_text("window\n")
    (tmp_path / "safety" / "kill_switch.json").write_text(json.dumps({
        "action": "a", "initial_state": "i", "resulting_state": "r",
        "observed_result": observed, "expected_result": expected,
        "raw_evidence": {"path": "safety/raw/kill_switch_window.txt",
                         "sha256": hashlib.sha256(b"window\n").hexdigest()}}))
    return og.verify_safety(tmp_path)["kill_switch"]


def test_a_safety_file_is_valid_only_when_observed_is_expected(tmp_path):
    assert _safety_pkg(tmp_path, "ZERO_NEW_ORDERS_WHILE_LATCHED")["state"] \
        == og.VALID


def test_a_failed_safety_test_is_never_valid(tmp_path):
    rep = _safety_pkg(tmp_path, "NEW_ORDERS_AFTER_LATCH:2")
    assert rep["state"] == og.INVALID
    assert "observed 'NEW_ORDERS_AFTER_LATCH:2', required " \
        "'ZERO_NEW_ORDERS_WHILE_LATCHED'" in rep["reasons"][0]


def test_a_safety_file_without_expected_result_is_invalid(tmp_path):
    rep = _safety_pkg(tmp_path, "pass", expected="")
    assert rep["state"] == og.INVALID
    assert "expected_result" in rep["reasons"][0]


# ---------------------------------------------------------------------------
# builder: safety/ only from this gate's safety leg windows
# ---------------------------------------------------------------------------

def _rebuild(run, tmp_path, windows: dict[str, str]):
    _, pkg, ev = run
    for name, text in windows.items():
        (ev / f"tester_{sl.leg_tag(name)}_window.txt").write_text(
            text, encoding="utf-8")
    return s8p.build_package(
        repo=REPO, package=pkg, gate_evidence=ev,
        data_folder=tmp_path / "data", golds=["gold2"],
        symbolspec_export=tmp_path / "EURUSD.json",
        host={"os": "Windows (test)", "timezone": "UTC"}), pkg


def test_builder_grades_and_binds_a_safety_leg(run26, tmp_path):  # noqa: F811
    w = _win(_strip("2024.01.02 08:01:01", 2), _restore("2024.01.02 08:01:02", 2))
    rec, pkg = _rebuild(run26, tmp_path, {"sl_verify": w})
    assert rec["ok"], rec
    doc = json.loads((pkg / "safety/sl_verify.json").read_text())
    assert doc["observed_result"] == "SL_STRIPPED_AND_RESTORED"
    assert doc["raw_evidence"]["path"] == "safety/raw/sl_verify_window.txt"
    assert doc["raw_evidence"]["sha256"] == s8p._sha(
        pkg / "safety/raw/sl_verify_window.txt")
    assert doc["baseline_evidence"]["path"] == \
        "safety/raw/baseline_gold2_m1_ohlc_window.txt"
    man = json.loads((pkg / "archive_manifest.json").read_text())
    assert "safety/raw/sl_verify_window.txt" in man["artifacts"]
    assert og.verify_safety(pkg)["sl_verify"]["state"] == og.VALID
    # a leg that did not run is never written
    assert not (pkg / "safety/kill_switch.json").exists()
    assert "the tester leg did not run" in \
        rec["not_built"]["safety/kill_switch.json"]


def test_builder_writes_a_failing_leg_and_the_verifier_refuses_it(
        run26, tmp_path):  # noqa: F811
    w = _win(_req("2024.01.02 08:01:00", "sell", 0.01))  # never latched
    _, pkg = _rebuild(run26, tmp_path, {"kill_switch": w})
    doc = json.loads((pkg / "safety/kill_switch.json").read_text())
    assert doc["observed_result"] == "NOT_LATCHED"
    assert doc["passed"] is False
    assert og.verify_safety(pkg)["kill_switch"]["state"] == og.INVALID


def test_demo_only_artifacts_are_never_built(run26, tmp_path):  # noqa: F811
    rec, pkg = _rebuild(run26, tmp_path, {})
    for name in sl.DEMO_ONLY:
        rel = og.LAYOUT.get(name, f"safety/{name}.json")
        assert not (pkg / rel).exists()
        assert rec["not_built"][rel].startswith("demo-only")


# ---------------------------------------------------------------------------
# CLI + ps1 wiring
# ---------------------------------------------------------------------------

def _decide(*args):
    return subprocess.run([sys.executable,
                           str(REPO / "tools" / "owner_gate_decide.py"),
                           "--repo", str(REPO), *args],
                          capture_output=True, text=True, check=False)


def test_cli_safety_leg_inputs():
    cp = _decide("safety-leg-inputs", "--test", "kill_switch")
    assert cp.returncode == 0, cp.stderr
    d = json.loads(cp.stdout)
    assert d["input_args"] == ["InpTestKillSwitchAfterEntries=1"]
    assert (d["tag"], d["model"]) == ("safety_kill_switch", 1)
    cp = _decide("safety-leg-inputs", "--test", "meta_reduce")
    assert json.loads(cp.stdout)["input_args"] == [
        "InpBaseGateWeight=0.5", "InpTestSafetyLog=true"]


def test_cli_refuses_a_demo_only_test():
    cp = _decide("safety-leg-inputs", "--test", "restart")
    assert cp.returncode == 1
    assert "demo-only" in json.loads(cp.stdout)["reasons"][0]


def _s8() -> str:
    s = PS1.index('Enter-Stage 8 "reconciliation"')
    return PS1[s:PS1.index("STAGE 9", s)]


def test_ps1_runs_the_tester_safety_legs_before_the_package_build():
    s8 = _s8()
    assert s8.index('Invoke-Decide @("safety-leg-inputs"') < \
        s8.index('Invoke-Decide (@("build-stage8-package"')
    assert '@("kill_switch", "risk_veto", "meta_reduce", "sl_verify")' in s8
    # the leg runs on the gold leg's own inputs PLUS the test inputs
    assert 'Invoke-Decide @("stage5-leg-inputs"' in s8
    assert "Save-TesterWindowLog $stag $sMarks $sStart" in s8
    # demo-only tests are never launched
    for name in sl.DEMO_ONLY:
        assert f'"{name}"' not in s8.split("foreach ($stest in")[1][:120]
