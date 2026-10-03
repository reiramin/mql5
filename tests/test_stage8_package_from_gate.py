"""Stage 8: the gate builds the evidence package from its OWN measured outputs.

gate_run26 (HEAD 918f7bf, -Golds gold2) FAILED stage 8
NOT_VERIFIED_RECONCILIATION_MISSING with a package holding only the two log
trade lists; first_divergence was None because the trade comparison never ran.

These tests build a tmp tree shaped like gate_run26 and pin:

  * the builder writes compile/, symbolspec/, gate/stage_5.json,
    real_tick_coverage.json (NONE), environment.json (measured fields only),
    reconciliation/gold2.json and archive_manifest.json (owner_evidence_bind);
  * a NOT_APPLICABLE leg is state NOT_APPLICABLE -- never MISSING, never a
    fabricated raw/parsed report -- and NONE coverage never reaches
    MT5_VALIDATED;
  * safety/*.json are never written;
  * first_divergence (and the per-trade one) is surfaced while stage 8 FAILs.

The tester windows are assembled from MEASURED lines (gate runs 16/17) plus
DEAL lines in the EA's own Logger format; the log trade list is produced by
the real tester_log_grader. The compile log is the real owner log with its
Mql5Bot ex5 hash replaced by the hash of the fake EX5 bytes (SYNTHETIC). None
of this is MT5 evidence.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from mql5bot import gate_selfcheck as gs
from mql5bot import owner_gate as og
from mql5bot import stage8_package as s8p
from mql5bot import tester_log_grader as tlg

REPO = Path(__file__).resolve().parents[1]
CAPTURE = REPO / "tests" / "data" / "owner_gate" / "tester_log_gate_runs_16_17.txt"
OWNER_COMPILE_LOG = REPO / "logs_owner" / "compile-20260917-201954.log"
VERIFY = REPO / "tools" / "verify_owner_mt5_gate.py"
DECIDE = REPO / "tools" / "owner_gate_decide.py"
PS1 = (REPO / "tools" / "owner_gate.ps1").read_text(encoding="utf-8")
REAL_EA_HASH = "64EE5F824E4B6B55327DF10125866D173F85484053392590279E53647E0BDB7E"

# 2 round trips (4 deals): entries pnl 0, exits pnl != 0 (EA DEAL format)
DEALS = [
    "[2024.01.02 08:01:00] [INFO] DEAL #2 EURUSD.G2 vol=0.01 price=1.09589 pnl=0.00",
    "[2024.01.02 08:07:00] [INFO] DEAL #3 EURUSD.G2 vol=0.01 price=1.09659 pnl=-0.70",
    "[2024.01.02 08:46:00] [INFO] DEAL #4 EURUSD.G2 vol=0.28 price=1.09700 pnl=0.00",
    "[2024.01.02 09:12:00] [INFO] DEAL #5 EURUSD.G2 vol=0.28 price=1.09650 pnl=-14.00",
]


def _window(model_line: str) -> str:
    lines = [ln for ln in CAPTURE.read_text(encoding="utf-8").splitlines()
             if ln and not ln.startswith("#") and "EURUSD.G1" not in ln
             and "generating" not in ln]
    return "\n".join([model_line, *lines,
                      ("[2024.01.02 00:00:00] [INFO] generic DSL execution "
                       "enabled: gold2_multifactor"), *DEALS]) + "\n"


def _stage5_record() -> dict:
    """The stage-5 record shape owner_gate.ps1 Record-Stage writes, with the
    real NOT_APPLICABLE reason the decider produces for the committed gold2."""
    d = gs.derive_tester_inputs(REPO / "artifacts/gold_2/manifest.json",
                                REPO / "artifacts/gold_2/gold2_fixture.csv",
                                "artifacts/gold_2/gold2_fixture.csv")
    na = d["real_ticks_leg"]["reason"]
    return {"stage": 5, "name": "tester_legs", "status": "PASS_FROM_LOG",
            "reason": ("[scope: gold2; PARTIAL run -- certifies nothing] legs: "
                       "0 passed from report, 2 passed from log, 0 blocked, 0 "
                       "failed, 1 not applicable. gold2_m1_ohlc: exit 1; "
                       "PASS_FROM_LOG; gold2_every_tick: exit 1; PASS_FROM_LOG; "
                       f"gold2_real_ticks: {na} -- leg NOT launched, NOT a pass"),
            "scope": ["gold2"], "partial": True, "artifacts": [],
            "utc": "2026-10-03T12:00:00.0000000Z"}


@pytest.fixture()
def run26(tmp_path):
    """gate evidence dir + data folder + package, as after gate_run26's
    stage 5 and the stage-8 log-trade placement."""
    ev, data, pkg = tmp_path / "gate_ev", tmp_path / "data", tmp_path / "pkg"
    ev.mkdir()
    ex5 = data / "MQL5" / "Experts" / "Mql5Bot" / "Mql5Bot.ex5"
    ex5.parent.mkdir(parents=True)
    ex5.write_bytes(b"synthetic ex5 bytes for the package test")
    fake = s8p._sha(ex5).upper()
    log = OWNER_COMPILE_LOG.read_text(encoding="utf-8-sig").replace(
        REAL_EA_HASH, fake)
    (ev / "compile-20260917-201954.log").write_text(log, encoding="utf-8")
    (ev / "stage_5.json").write_text(json.dumps(_stage5_record()),
                                     encoding="ascii")
    spec = tmp_path / "EURUSD.json"
    spec.write_text(json.dumps({"symbol": "EURUSD", "server": "MetaQuotes-Demo",
                                "point": 1e-05, "exported_at": "2026.10.03 11:00"}),
                    encoding="utf-8")
    for model, req, line in (
            ("m1_ohlc", 1, "EURUSD.G2,M1 (MetaQuotes-Demo): 1 minutes OHLC ticks generating"),
            ("every_tick", 0, "EURUSD.G2,M1 (MetaQuotes-Demo): every tick generating")):
        win = _window(line)
        (ev / f"tester_gold2_{model}_window.txt").write_text(win, encoding="utf-8")
        grade = tlg.grade_leg_from_log(window_text=win, symbol="EURUSD.G2",
                                       requested_model=req,
                                       leg=f"gold2_{model}",
                                       expected_strategy="gold2_multifactor")
        assert grade["outcome"] == "PASS_FROM_LOG", grade["reason"]
        trades = ev / f"tester_gold2_{model}_log_trades.json"
        trades.write_text(json.dumps(tlg.log_trade_list(grade, win.encode())),
                          encoding="utf-8")
        placed = tlg.place_log_trades(trades, pkg, "gold2", model, REPO)
        assert placed["ok"], placed["reasons"]
    rec = s8p.build_package(repo=REPO, package=pkg, gate_evidence=ev,
                            data_folder=data, golds=["gold2"],
                            symbolspec_export=spec,
                            host={"os": "Windows (test)", "timezone": "UTC"})
    return rec, pkg, ev


def _verify(pkg: Path, tmp_path: Path) -> dict:
    out = tmp_path / "reconciliation_verify.json"
    cp = subprocess.run([sys.executable, str(VERIFY), str(pkg), "--repo",
                         str(REPO), "--golds", "gold2", "--out", str(out)],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 1, cp.stdout + cp.stderr   # never positive
    return json.loads(out.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# the builder
# ---------------------------------------------------------------------------

def test_builder_writes_the_gate_measured_artifacts(run26):
    rec, pkg, _ = run26
    assert rec["ok"], rec
    for rel in ("compile/compile.log", "compile/compile_metadata.json",
                "compile/Mql5Bot.ex5", "symbolspec/symbolspec.json",
                "gate/stage_5.json", "real_tick_coverage.json",
                "environment.json", "reconciliation/gold2.json",
                "archive_manifest.json"):
        assert (pkg / rel).is_file(), rel
    meta = json.loads((pkg / "compile/compile_metadata.json").read_text())
    assert meta["EX5_SHA256"] == s8p._sha(pkg / "compile/Mql5Bot.ex5")
    assert meta["COMPILER_LOG_SHA256"] == s8p._sha(pkg / "compile/compile.log")
    assert meta["COMPILE_TIMESTAMP"] == "2026-09-17T20:19:54+00:00"
    assert meta["COMPILER_VERSION"] == "5.0.0.6184"
    assert (meta["ERRORS"], meta["WARNINGS"]) == (0, 0)
    # nothing measured the terminal build in these windows: omitted, not filled
    assert "TERMINAL_BUILD" not in meta


def test_coverage_is_none_for_the_bar_only_gold_never_full(run26):
    _, pkg, _ = run26
    cov = json.loads((pkg / "real_tick_coverage.json").read_text())
    assert cov["coverage"] == og.REAL_TICK_COVERAGE_NONE
    assert cov["leg_launched"] is False
    assert cov["golds"]["gold2"]["fixture"] == "artifacts/gold_2/gold2_fixture.csv"
    assert cov["golds"]["gold2"]["leg"] == "not launched"
    assert "actual_model_from_report" not in cov


def test_environment_carries_measured_fields_only(run26):
    _, pkg, _ = run26
    env = json.loads((pkg / "environment.json").read_text())
    assert env["server"] == "MetaQuotes-Demo"
    assert env["symbol"] == "EURUSD"
    assert env["tester_symbols"] == {"gold2": "EURUSD.G2"}
    for gap in ("broker", "terminal_build", "account_mode"):
        assert gap not in env and gap in env["unmeasured"]


def test_not_applicable_leg_gets_no_fabricated_report(run26):
    _, pkg, _ = run26
    assert not (pkg / "gold2" / "real_ticks.htm").exists()
    assert not (pkg / "parsed" / "gold2_real_ticks.json").exists()
    recon = json.loads((pkg / "reconciliation/gold2.json").read_text())
    rt = recon["bindings"]["tester_models"]["real_ticks"]
    assert rt == {"not_applicable": True, "outcome": og.STAGE5_NOT_APPLICABLE,
                  "requested": 4,
                  "fixture": "artifacts/gold_2/gold2_fixture.csv"}


def test_safety_is_never_fabricated(run26):
    rec, pkg, _ = run26
    assert not (pkg / "safety").exists()
    for name in og.SAFETY_TESTS + ("netting", "hedging"):
        assert f"safety/{name}.json" in rec["not_built"]


def test_archive_manifest_is_owner_evidence_bind_output(run26):
    _, pkg, _ = run26
    man = json.loads((pkg / "archive_manifest.json").read_text())
    files = {str(p.relative_to(pkg)).replace("\\", "/")
             for p in pkg.rglob("*") if p.is_file()} - {"archive_manifest.json"}
    assert set(man["artifacts"]) == files
    for rel, digest in man["artifacts"].items():
        assert s8p._sha(pkg / rel) == digest


def test_reconciliation_pairs_python_and_mt5_entries(run26):
    _, pkg, _ = run26
    recon = json.loads((pkg / "reconciliation/gold2.json").read_text())
    trades = [e for e in recon["events"] if "trade_index" in e]
    first = [e for e in trades if e["trade_index"] == 0]
    assert {e["model"] for e in first} == {"m1_ohlc", "every_tick"}
    e0 = first[0]
    # python entry 0 = expected_execution 2024-01-01T08:00 signal, filled
    # one M1 bar later at 08:01, approved 1.4 lots; MT5 entry 0 = deal #2
    assert e0["fields"]["timestamp"] == {"python": "2024-01-01T08:01:00",
                                         "mt5": "2024-01-02T08:01:00"}
    assert e0["fields"]["volume"] == {"python": 1.4, "mt5": 0.01}
    assert "side" in e0["unmeasured_mt5_fields"]
    count = recon["events"][-1]["fields"]
    assert count["entry_count:m1_ohlc"] == {"python": 62, "mt5": 2}


def test_rebuild_replaces_only_what_the_gate_built(run26, tmp_path):
    _, pkg, ev = run26
    owner_file = pkg / "safety" / "owner_note.txt"
    owner_file.parent.mkdir()
    owner_file.write_text("owner", encoding="utf-8")
    rec = s8p.build_package(repo=REPO, package=pkg, gate_evidence=ev,
                            data_folder=None, golds=["gold2"],
                            symbolspec_export=None)
    assert owner_file.is_file()
    # the EX5 and symbolspec could not be rebuilt: the stale copies are gone
    assert not (pkg / "compile/Mql5Bot.ex5").exists()
    assert not (pkg / "symbolspec/symbolspec.json").exists()
    assert "compile/Mql5Bot.ex5" in rec["removed_previous_build"]


def test_mt5_entry_pairing_is_refused_when_alternation_fails():
    deals = [{"ticket": 1, "pnl": 0.0}, {"ticket": 2, "pnl": 3.0},
             {"ticket": 3, "pnl": 5.0}]
    entries, why = s8p.mt5_entries(deals)
    assert entries is None and "refused" in why


def test_ex5_not_matching_the_stage1_hash_is_not_packaged(tmp_path, run26):
    _, _, ev = run26
    data = tmp_path / "other_data"
    ex5 = data / "MQL5" / "Experts" / "Mql5Bot" / "Mql5Bot.ex5"
    ex5.parent.mkdir(parents=True)
    ex5.write_bytes(b"a different binary")
    pkg = tmp_path / "pkg2"
    rec = s8p.build_package(repo=REPO, package=pkg, gate_evidence=ev,
                            data_folder=data, golds=["gold2"],
                            symbolspec_export=None)
    assert not (pkg / "compile/Mql5Bot.ex5").exists()
    assert "not the binary stage 1 compiled" in rec["not_built"]["compile/Mql5Bot.ex5"]


# ---------------------------------------------------------------------------
# the verifier on the built package
# ---------------------------------------------------------------------------

def test_not_applicable_is_never_missing_and_never_present(run26, tmp_path):
    _, pkg, _ = run26
    rep = _verify(pkg, tmp_path)
    for kind in ("raw", "parsed"):
        assert rep["artifacts"][f"{kind}_gold2_real_ticks"]["state"] == \
            og.NOT_APPLICABLE
        assert f"{kind}_gold2_real_ticks" not in rep["missing"]
    assert rep["not_applicable_legs"] == ["gold2:real_ticks"]
    assert rep["gold"]["gold2"]["trade_sources"]["real_ticks"] == \
        og.TRADE_SOURCE_NOT_APPLICABLE
    assert rep["real_tick_coverage"]["state"] == og.VALID
    assert rep["real_tick_coverage"]["coverage"] == og.REAL_TICK_COVERAGE_NONE


def test_verdict_is_never_positive_and_safety_stays_missing(run26, tmp_path):
    _, pkg, _ = run26
    rep = _verify(pkg, tmp_path)
    assert rep["verdict"] not in og.POSITIVE_VERDICTS
    assert rep["verdict"] != og.MT5_VALIDATED_PARTIAL_SCOPE
    assert {n: rep["safety"][n]["state"] for n in rep["safety"]} == {
        n: og.MISSING for n in og.SAFETY_TESTS + ("netting", "hedging")}


def test_first_divergence_is_surfaced_on_a_fail(run26, tmp_path):
    _, pkg, _ = run26
    rep = _verify(pkg, tmp_path)
    div = rep["first_divergence"]["gold2"]
    assert div is not None
    trade = rep["first_trade_divergence"]["gold2"]
    assert trade["first_divergent_field"] == "timestamp"
    assert (trade["python_value"], trade["mt5_value"]) == (
        "2024-01-01T08:01:00", "2024-01-02T08:01:00")
    assert trade["trade_index"] == 0
    assert trade["classification"] == og.TIMESTAMP_MISMATCH
    # the gate HEAD is not the frozen anchor, so the chain does not verify:
    # the divergence is OBSERVED, never the verifier's binding-verified one
    assert trade["binding_verified"] is False
    note = s8p.divergence_note(rep, ["gold2"])
    assert "first per-trade divergence: field 'timestamp'" in note
    assert "[observed; binding chain NOT verified]" in note


def test_cli_divergence_note_quotes_the_report(run26, tmp_path):
    _, pkg, _ = run26
    _verify(pkg, tmp_path)
    cp = subprocess.run([sys.executable, str(DECIDE), "--repo", str(REPO),
                         "stage8-divergence-note", "--verify",
                         str(tmp_path / "reconciliation_verify.json"),
                         "--golds", "gold2"],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 0, cp.stderr
    assert "python='2024-01-01T08:01:00'" in json.loads(cp.stdout)["note"]


def test_full_coverage_beside_a_not_applicable_leg_is_a_mismatch(run26, tmp_path):
    _, pkg, _ = run26
    cov = pkg / "real_tick_coverage.json"
    cov.write_text(json.dumps({"coverage": "REAL_TICK_COVERAGE_UNKNOWN",
                               "requested_model": "x", "actual_model_from_report": "x",
                               "requested_interval": "a", "actual_interval": "a",
                               "broker": "b", "symbol": "EURUSD"}))
    rep = og.run_gate(pkg, {"source": {"commit": "x"}}, ["gold2"])
    assert rep["real_tick_coverage"]["state"] == og.MISMATCHED
    assert rep["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH


def test_none_coverage_claiming_an_actual_model_is_invalid(run26):
    _, pkg, _ = run26
    cov_path = pkg / "real_tick_coverage.json"
    cov = json.loads(cov_path.read_text())
    cov["actual_model_from_report"] = "Every tick based on real ticks"
    cov_path.write_text(json.dumps(cov))
    assert og.verify_real_tick_coverage(pkg)["state"] == og.INVALID


def test_none_coverage_without_the_stage5_record_is_a_mismatch(run26):
    _, pkg, _ = run26
    (pkg / og.GATE_STAGE5_REL).unlink()
    assert og.verify_real_tick_coverage(pkg)["state"] == og.MISMATCHED
    rep = og.run_gate(pkg, {"source": {"commit": "x"}}, ["gold2"])
    # without the record the NA slots are plain MISSING again
    assert rep["artifacts"]["raw_gold2_real_ticks"]["state"] == og.MISSING


def test_a_report_for_a_not_applicable_leg_is_invalid(run26):
    _, pkg, _ = run26
    (pkg / "gold2").mkdir()
    (pkg / "gold2" / "real_ticks.htm").write_text("<html/>")
    scan = og.scan_package(pkg)
    assert scan["raw_gold2_real_ticks"]["state"] == og.INVALID


def test_tester_models_cannot_claim_not_applicable_without_the_record(run26):
    _, pkg, _ = run26
    recon_path = pkg / "reconciliation/gold2.json"
    recon = json.loads(recon_path.read_text())
    recon["bindings"]["tester_models"]["every_tick"] = {
        "not_applicable": True, "outcome": og.STAGE5_NOT_APPLICABLE}
    recon_path.write_text(json.dumps(recon))
    frozen = {"source_commit": recon["bindings"]["source_commit"],
              "gold2": {}}
    rep = og.verify_reconciliation(pkg, "gold2", frozen, {})
    assert rep["state"] == og.MISMATCHED
    assert any("does not mark it NOT_APPLICABLE" in r for r in rep["reasons"])


# ---------------------------------------------------------------------------
# owner_gate.ps1 wiring (source)
# ---------------------------------------------------------------------------

def _s8() -> str:
    s = PS1.index('Enter-Stage 8 "reconciliation"')
    return PS1[s:PS1.index("STAGE 9", s)]


def test_ps1_builds_the_package_before_stage8_verifies():
    s8 = _s8()
    assert s8.index('Invoke-Decide @("place-log-trades"') \
        < s8.index('Invoke-Decide @("build-stage8-package"') \
        < s8.index("verify_owner_mt5_gate.py")
    assert '"--gate-evidence", $Evidence' in s8
    assert '"--symbolspec", $SymbolSpecExport' in s8


def test_ps1_quotes_the_divergence_and_classifies_only_verified_ones():
    s8 = _s8()
    assert 'Invoke-Decide @("stage8-divergence-note"' in s8
    note = s8.index("stage8-divergence-note")
    assert note < s8.index('Record-Stage 8 "reconciliation" "PASS"')
    assert '(Get-DataProp $fd "binding_verified") -eq $true' in s8
