"""Stage 5 (tester legs) decision layer — Mac-tested, no MT5 required.

owner_gate.ps1's stage 5 launches the six tester legs on the Windows owner's
box, but every DECISION it makes there lives in committed Python and is tested
here:

  * the tester period + timeframe are DERIVED from the committed manifest +
    fixture — a setting the gate cannot derive FAILS the stage naming that
    input, never a guess (task #4);
  * per leg, the ACTUAL modelling model is read from the report Model line +
    journal (never the requested one) and the real-tick coverage is classified
    FULL/PARTIAL/UNKNOWN with the evidence it rests on (task #3).

These are VERIFIER self-tests. No leg result is fabricated: the classifiers
read only what a real report/journal states and record UNKNOWN when the
evidence is absent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from mql5bot import gate_selfcheck as gs
from mql5bot import mt5tester as mt

REPO = Path(__file__).resolve().parents[1]
DECIDE = REPO / "tools" / "owner_gate_decide.py"


# ---------------------------------------------------------------------------
# model_int_from_text — canonical labels, longest-first precedence, bare int
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("1 minute OHLC", 1),
    ("Every tick", 0),
    ("Open prices only", 2),
    ("Every tick based on real ticks", 3),  # must not shadow to 0/4
    ("Real ticks", 4),
    ("Modelling: Every tick based on real ticks (real)", 3),
    ("Model 3", 3),  # bare-int fallback
    ("no model stated here", None),
])
def test_model_int_from_text(text, expected):
    assert mt.model_int_from_text(text) == expected


# ---------------------------------------------------------------------------
# read_actual_model — from the report, the journal, disagreement, unknown
# ---------------------------------------------------------------------------

def test_actual_model_from_report_setting():
    am = mt.read_actual_model({"model": "Every tick based on real ticks"})
    assert am["model"] == 3
    assert am["source"] == "report"
    assert any("report Model=" in e for e in am["evidence"])


def test_actual_model_falls_back_to_journal_when_report_silent():
    am = mt.read_actual_model({}, "…\nModelling: 1 minute OHLC\n…")
    assert am["model"] == 1 and am["source"] == "journal"
    assert any("journal:" in e for e in am["evidence"])


def test_actual_model_records_report_journal_disagreement():
    am = mt.read_actual_model({"model": "Every tick based on real ticks"},
                              "run used Every tick\n")
    assert am["report_model"] == 3 and am["journal_model"] == 0
    assert am["report_journal_agree"] is False
    # the report value wins the reported model, the disagreement is visible
    assert am["model"] == 3


def test_actual_model_unknown_is_recorded_not_guessed():
    am = mt.read_actual_model({}, "nothing about the model here")
    assert am["model"] is None and am["source"] == "unknown"
    assert am["label"] is None


# ---------------------------------------------------------------------------
# classify_real_tick_coverage — never inferred from mode selection
# ---------------------------------------------------------------------------

def test_coverage_not_applicable_for_non_real_tick_model():
    cov = mt.classify_real_tick_coverage({"history quality": "100%"}, "", 1)
    assert cov["coverage"] == mt.REAL_TICK_COVERAGE_UNKNOWN
    assert cov["applicable"] is False
    assert any("not a real-tick mode" in e for e in cov["evidence"])


def test_coverage_full_requires_positive_evidence():
    cov = mt.classify_real_tick_coverage(
        {"history quality": "100%"},
        "ticks: based on real ticks for the whole period\n", 4)
    assert cov["coverage"] == mt.REAL_TICK_COVERAGE_FULL


def test_coverage_partial_when_ticks_generated():
    cov = mt.classify_real_tick_coverage(
        {"history quality": "100%"},
        "some minute bars had no tick data: ticks are generated\n", 3)
    assert cov["coverage"] == mt.REAL_TICK_COVERAGE_PARTIAL
    assert any("generated" in e for e in cov["evidence"])


def test_coverage_partial_when_history_quality_below_100():
    cov = mt.classify_real_tick_coverage({"history quality": "97%"}, "", 3)
    assert cov["coverage"] == mt.REAL_TICK_COVERAGE_PARTIAL


def test_coverage_unknown_with_no_evidence_never_full():
    cov = mt.classify_real_tick_coverage({}, "", 3)
    assert cov["coverage"] == mt.REAL_TICK_COVERAGE_UNKNOWN
    assert cov["applicable"] is True


# ---------------------------------------------------------------------------
# fixture_date_range — the tester period is DERIVED, never guessed
# ---------------------------------------------------------------------------

def test_fixture_date_range_reads_the_real_golds():
    d1 = mt.fixture_date_range(REPO / "artifacts/gold/gold_fixture.csv")
    assert d1 == ("2024.01.01", "2024.01.05")
    d2 = mt.fixture_date_range(REPO / "artifacts/gold_2/gold2_fixture.csv")
    assert d2 == ("2024.01.01", "2024.01.04")


def test_fixture_date_range_raises_when_no_time_column(tmp_path: Path):
    csv = tmp_path / "bad.csv"
    csv.write_text("open,high,low,close\n1,2,0,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be derived"):
        mt.fixture_date_range(csv)


# ---------------------------------------------------------------------------
# derive_tester_inputs — real golds pass; underivable input fails BY NAME
# ---------------------------------------------------------------------------

def test_derive_tester_inputs_from_real_gold1():
    r = gs.derive_tester_inputs(REPO / "artifacts/gold/manifest.json",
                                REPO / "artifacts/gold/gold_fixture.csv")
    assert r["ok"], r["reasons"]
    assert r["timeframe"] == "H1"
    assert r["date_from"] == "2024.01.01" and r["date_to"] == "2024.01.05"


def test_derive_tester_inputs_from_real_gold2():
    r = gs.derive_tester_inputs(REPO / "artifacts/gold_2/manifest.json",
                                REPO / "artifacts/gold_2/gold2_fixture.csv")
    assert r["ok"], r["reasons"]
    assert r["timeframe"] == "M1"


def test_derive_tester_inputs_fails_naming_missing_timeframe(tmp_path: Path):
    man = tmp_path / "manifest.json"
    man.write_text(json.dumps({"symbol": "EURUSD"}), encoding="utf-8")
    fx = tmp_path / "f.csv"
    fx.write_text("time,open\n2024-01-01 00:00:00,1.1\n", encoding="utf-8")
    r = gs.derive_tester_inputs(man, fx)
    assert not r["ok"]
    assert r["missing"] == "timeframe"
    assert any("timeframe" in x for x in r["reasons"])


def test_derive_tester_inputs_fails_naming_missing_period(tmp_path: Path):
    man = tmp_path / "manifest.json"
    man.write_text(json.dumps({"symbol": "EURUSD", "timeframe": "H1"}),
                   encoding="utf-8")
    fx = tmp_path / "f.csv"
    fx.write_text("open,high\n1.1,1.2\n", encoding="utf-8")  # no time column
    r = gs.derive_tester_inputs(man, fx)
    assert not r["ok"]
    assert r["missing"] == "date_from/date_to"


# ---------------------------------------------------------------------------
# tester_leg_evidence — ACTUAL model + coverage from the leg's own report
# ---------------------------------------------------------------------------

def _sidecar(tmp_path: Path, settings: dict) -> Path:
    p = tmp_path / "report.json"
    p.write_text(json.dumps({"tables": 2, "settings": settings,
                             "fields": {}, "metrics": {}}), encoding="utf-8")
    return p


def test_tester_leg_evidence_reads_actual_model_and_coverage(tmp_path: Path):
    sc = _sidecar(tmp_path, {"model": "1 minute OHLC", "period": "H1",
                             "symbol": "EURUSD.G1"})
    r = gs.tester_leg_evidence(sc, None, requested_model=1,
                               symbol="EURUSD.G1", leg="gold1_m1_ohlc")
    assert r["ok"], r["reasons"]
    assert r["actual_model"]["label"] == "1 minute OHLC"
    assert r["model_matches_requested"] is True
    assert r["coverage"] == mt.REAL_TICK_COVERAGE_UNKNOWN  # not a real-tick leg
    rec = r["coverage_record"]
    assert rec["actual_model_from_report"] == "1 minute OHLC"
    assert rec["symbol"] == "EURUSD.G1"


def test_tester_leg_evidence_fails_when_actual_model_unreadable(tmp_path: Path):
    sc = _sidecar(tmp_path, {"period": "H1"})  # no model row, no journal
    r = gs.tester_leg_evidence(sc, None, requested_model=1)
    assert not r["ok"]
    assert any("ACTUAL tester model" in x for x in r["reasons"])


def test_tester_leg_evidence_records_silent_model_fallback(tmp_path: Path):
    # requested real_ticks (3) but the report says Every tick -> recorded, and
    # NOT a real-tick FULL claim
    sc = _sidecar(tmp_path, {"model": "Every tick", "history quality": "100%"})
    r = gs.tester_leg_evidence(sc, None, requested_model=3, symbol="EURUSD.G1")
    assert r["ok"]  # the model IS readable, it just differs
    assert r["model_matches_requested"] is False
    assert any("differs from the requested" in x for x in r["reasons"])


def test_tester_leg_evidence_uses_journal_for_coverage(tmp_path: Path):
    sc = _sidecar(tmp_path, {"model": "Every tick based on real ticks",
                             "history quality": "100%"})
    journal = tmp_path / "journal.txt"
    journal.write_text("real ticks used for the whole period\n",
                       encoding="utf-8")
    r = gs.tester_leg_evidence(sc, journal, requested_model=3,
                               symbol="EURUSD.G1")
    assert r["coverage"] == mt.REAL_TICK_COVERAGE_FULL


# ---------------------------------------------------------------------------
# owner_gate_decide.py CLI — the exact path the .ps1 shells to
# ---------------------------------------------------------------------------

def _decide(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(DECIDE), "--repo", str(REPO),
                           *args], capture_output=True, text=True, check=False)


def test_cli_tester_inputs_ok_for_real_gold():
    cp = _decide("tester-inputs",
                 "--manifest", str(REPO / "artifacts/gold/manifest.json"),
                 "--fixture", str(REPO / "artifacts/gold/gold_fixture.csv"))
    assert cp.returncode == 0, cp.stderr
    payload = json.loads(cp.stdout)
    assert payload["ok"] and payload["timeframe"] == "H1"
    assert payload["date_to"] == "2024.01.05"


def test_cli_tester_inputs_fails_closed_naming_input(tmp_path: Path):
    man = tmp_path / "m.json"
    man.write_text(json.dumps({"symbol": "EURUSD"}), encoding="utf-8")
    fx = tmp_path / "f.csv"
    fx.write_text("time,open\n2024-01-01 00:00:00,1.1\n", encoding="utf-8")
    cp = _decide("tester-inputs", "--manifest", str(man), "--fixture", str(fx))
    assert cp.returncode == 1
    payload = json.loads(cp.stdout)
    assert payload["missing"] == "timeframe"


def test_cli_stage5_leg_reads_actual_model(tmp_path: Path):
    sc = _sidecar(tmp_path, {"model": "Real ticks", "history quality": "100%",
                             "symbol": "EURUSD.G1"})
    journal = tmp_path / "j.txt"
    journal.write_text("based on real ticks\n", encoding="utf-8")
    cp = _decide("stage5-leg", "--report-json", str(sc),
                 "--journal", str(journal), "--requested-model", "4",
                 "--symbol", "EURUSD.G1", "--leg", "gold1_real_ticks")
    assert cp.returncode == 0, cp.stderr
    payload = json.loads(cp.stdout)
    assert payload["actual_model"]["label"] == "Real ticks"
    assert payload["coverage"] == mt.REAL_TICK_COVERAGE_FULL


def test_cli_stage5_leg_fails_when_model_unreadable(tmp_path: Path):
    sc = _sidecar(tmp_path, {"period": "H1"})
    cp = _decide("stage5-leg", "--report-json", str(sc),
                 "--requested-model", "1")
    assert cp.returncode == 1
    payload = json.loads(cp.stdout)
    assert payload["ok"] is False
