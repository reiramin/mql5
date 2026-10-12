"""STAGE10-CERT-1: stage 10 certifies the stage-8 verifier verdict.

gate_run55 (90041fe, gold2 -DemoSafety) reached MT5_VALIDATED_BAR_MODELS_
PARTIAL_SCOPE with nothing missing. Reading the code for an UNSCOPED run
showed stage 10 could never certify: it ran tools/certify_strategy.py,
which needs artifacts/owner_mt5_gate/certify_config.json (absent -> stage
10 SKIP, GATE_RESULT=reconciliation) and runs a separate real-market
ladder with a REQUIRED real-ticks leg. Owner decision 2026-10-12: stage 10
issues a certificate of the verifier's verdict, bound by the stage-9
archive manifest, and refuses by name otherwise.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from mql5bot import gate_certificate as gc

REPO = Path(__file__).resolve().parents[1]
PS1 = (REPO / "tools" / "owner_gate.ps1").read_text(encoding="utf-8")
SAFETY = {
    "hedging": "INDEPENDENT_POSITIONS_ISOLATED_BY_MAGIC",
    "kill_switch": "ZERO_NEW_ORDERS_WHILE_LATCHED",
    "lost_response": "LOST_RESPONSE_ADOPTED_NO_DUPLICATE",
    "meta_reduce": "ALL_SIZES_LE_RISK_APPROVED",
    "netting": "NET_ONE_POSITION_PER_SYMBOL",
    "restart": "RESTART_RECOVERED_NO_DUPLICATE",
    "risk_veto": "ENTRIES_VETOED_FOR_THE_DAY",
    "sl_verify": "SL_STRIPPED_AND_RESTORED",
}
# the shape of gate_run55's reconciliation_verify.json, UNSCOPED (both
# golds), as an unscoped run's verifier writes it -- test input
REPORT = {
    "verdict": "MT5_VALIDATED_BAR_MODELS", "partial": False, "missing": [],
    "verifier": "mql5bot.owner_gate",
    "compile": {"source_commit_relation": {"recorded": "abc123"}},
    "gold": {"gold1": {"result": "MATCH", "state": "VALID",
                       "entry_counts": {"m1_ohlc": {"paired": 18}}},
             "gold2": {"result": "MATCH", "state": "VALID",
                       "entry_counts": {"m1_ohlc": {"paired": 37}}}},
    "safety": {k: {"state": "VALID", "result": v, "reasons": []}
               for k, v in SAFETY.items()},
    "log_sourced_legs": ["gold1:m1_ohlc", "gold2:m1_ohlc"],
}
COV = {"gold1": "NONE (bar-only fixture)", "gold2": "NONE (bar-only fixture)"}


def _setup(tmp_path, report=None, bind=True, sha=None):
    ev = tmp_path / "ev"
    ev.mkdir(parents=True)
    v = ev / "reconciliation_verify.json"
    v.write_text(json.dumps(report or REPORT), encoding="utf-8")
    real = hashlib.sha256(v.read_bytes()).hexdigest()
    arts = {"reconciliation_verify.json": sha or real} if bind else {}
    m = ev / "archive_manifest.json"
    m.write_text(json.dumps({"artifacts": arts, "identity": {}}),
                 encoding="utf-8")
    return v, m, ev / "certificate"


def test_unscoped_bar_models_verdict_is_certified(tmp_path):
    v, m, out = _setup(tmp_path)
    r = gc.issue_certificate(v, m, out, coverage=COV)
    assert r["ok"] is True, r
    cert = json.loads((out / "certificate.json").read_text())
    assert cert["verdict"] == "MT5_VALIDATED_BAR_MODELS"
    assert cert["certificate_scope"] == "bar models"
    assert "no real-tick claim" in cert["scope_statement"]
    assert cert["claims"]["real_ticks"] == "none"
    assert "No profitability claim" in cert["claims"]["profitability"]
    assert cert["reconciliation_verify_sha256"] == \
        hashlib.sha256(v.read_bytes()).hexdigest()
    assert cert["source_commit"] == "abc123"
    assert set(cert["safety"]) == set(SAFETY)
    assert cert["real_tick_coverage"] == COV
    md = (out / "certificate.md").read_text()
    assert "MT5_VALIDATED_BAR_MODELS" in md and "No profitability claim" in md


def _mut(**kw):
    rep = copy.deepcopy(REPORT)
    for path, value in kw.items():
        node = rep
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        if value is KeyError:
            del node[keys[-1]]
        else:
            node[keys[-1]] = value
    return rep


@pytest.mark.parametrize("report,needle", [
    (_mut(verdict="MT5_VALIDATED_BAR_MODELS_PARTIAL_SCOPE"),
     "is not certifiable"),
    (_mut(verdict="NOT_VERIFIED_ARTIFACT_MISMATCH"), "is not certifiable"),
    (_mut(partial=True), "is partial"),
    (_mut(missing=["safety_restart"]), "missing evidence"),
    (_mut(gold__gold1=KeyError), "does not cover every gold"),
    (_mut(gold__gold2__result="DIVERGENT"), "gold2: result 'DIVERGENT'"),
    (_mut(safety__restart__state="INVALID"), "safety restart"),
    (_mut(safety={}), "no safety results"),
])
def test_every_refusal_is_named_and_writes_nothing(tmp_path, report, needle):
    v, m, out = _setup(tmp_path, report)
    r = gc.issue_certificate(v, m, out, coverage=COV)
    assert r["ok"] is False
    assert any(needle in x for x in r["reasons"]), r["reasons"]
    assert not out.exists()


def test_manifest_must_bind_this_exact_report(tmp_path):
    v, m, out = _setup(tmp_path, bind=False)
    r = gc.issue_certificate(v, m, out)
    assert not r["ok"] and "does not bind" in r["reasons"][0]
    v2, m2, out2 = _setup(tmp_path / "x", sha="0" * 64)
    r = gc.issue_certificate(v2, m2, out2)
    assert not r["ok"] and "the report is" in r["reasons"][0]


def test_decider_cli(tmp_path):
    v, m, out = _setup(tmp_path)
    cp = subprocess.run(
        [sys.executable, str(REPO / "tools" / "owner_gate_decide.py"),
         "issue-certificate", "--verify", str(v), "--manifest", str(m),
         "--out", str(out), "--real-tick-coverage",
         "gold1=NONE (bar-only fixture)"],
        capture_output=True, text=True, check=False)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    doc = json.loads(cp.stdout)
    assert doc["ok"] and doc["certificate_scope"] == "bar models"


def _stage(start: str, end: str) -> str:
    s = PS1.index(start)
    return PS1[s:PS1.index(end, s)]


def test_unscoped_run_reaches_stages_9_and_10_and_certifies_the_verdict():
    s8 = _stage('Enter-Stage 8 "reconciliation"', "STAGE 9 --")
    # stage 8 accepts an unscoped MT5_VALIDATED_BAR_MODELS (S8-CEILING-1)
    assert ('if ($s8Verdict -eq "MT5_VALIDATED" -or $s8Verdict -eq '
            '"MT5_VALIDATED_BAR_MODELS"') in s8
    # only a PARTIAL run stops before stage 9
    stop = PS1.index("if ($Script:Partial) {",
                     PS1.index("SCOPED RUN STOPS HERE"))
    assert stop < PS1.index('Enter-Stage 9 "archive_manifest"')
    s10 = _stage('Enter-Stage 10 "certify"', 'Finish-Gate "certified"')
    assert ('@("issue-certificate", "--verify", $verifyOut, "--manifest", '
            '$archiveManifest, "--out", $certDir)') in s10
    assert 'Record-Stage 10 "certify" "PASS"' in s10
    assert 'Record-Stage 10 "certify" "FAIL"' in s10
    assert 'Finish-Gate "certify"' in s10
    # no SKIP path and no certify_strategy.py / certify_config.json any more
    assert "certify_config.json" not in s10
    assert '"SKIP"' not in s10
    assert '(Join-Path $PSScriptRoot "certify_strategy.py")' not in PS1
