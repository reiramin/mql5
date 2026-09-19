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
RUN_BACKTEST = REPO / "tools" / "run_mt5_backtest.py"

# The exact tester-log lines measured from the MT5 build-6184 gate_run17 legs
# (STAGE 5 R5). BLOCKED: gold2 M1 ran clean but wrote no report file.
_BLOCKED_JOURNAL = (
    'Tester\tquality of analyzed history is 100%\n'
    'Core 1\tEURUSD.G2,M1: 11520 ticks, 2880 bars generated. '
    'Test passed in 0:00:03.561.\n'
    'Tester\tlast test passed with result "successfully finished" '
    'in 0:00:03.561\n')
# FIXTURE TOO SHORT: gold1's 120-bar H1 fixture cannot provide MT5's warm-up
# AND a test window, so 0 bars were generated.
_FIXTURE_SHORT_JOURNAL = (
    'Core 1\tEURUSD.G1: start time changed to 2024.01.06 00:00 to provide '
    'data at beginning\n'
    'Core 1\tEURUSD.G1,H1: 0 ticks, 0 bars generated.\n')


# ---------------------------------------------------------------------------
# model_int_from_text — canonical labels, longest-first precedence, bare int
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("1 minute OHLC", 1),
    ("Every tick", 0),
    ("Open prices only", 2),
    # STAGE 5 R5, DEFECT 1: config-file enum — 3 = math calculations,
    # 4 = every tick based on real ticks.
    ("Every tick based on real ticks", 4),  # must not shadow to 0
    ("Math calculations", 3),
    ("Modelling: Every tick based on real ticks (real)", 4),
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
    assert am["model"] == 4
    assert am["source"] == "report"
    assert any("report Model=" in e for e in am["evidence"])


def test_actual_model_falls_back_to_journal_when_report_silent():
    am = mt.read_actual_model({}, "…\nModelling: 1 minute OHLC\n…")
    assert am["model"] == 1 and am["source"] == "journal"
    assert any("journal:" in e for e in am["evidence"])


def test_actual_model_records_report_journal_disagreement():
    am = mt.read_actual_model({"model": "Every tick based on real ticks"},
                              "run used Every tick\n")
    assert am["report_model"] == 4 and am["journal_model"] == 0
    assert am["report_journal_agree"] is False
    # the report value wins the reported model, the disagreement is visible
    assert am["model"] == 4


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
    # model 4 = every tick based on real ticks (the only real-tick mode).
    cov = mt.classify_real_tick_coverage(
        {"history quality": "100%"},
        "some minute bars had no tick data: ticks are generated\n", 4)
    assert cov["coverage"] == mt.REAL_TICK_COVERAGE_PARTIAL
    assert any("generated" in e for e in cov["evidence"])


def test_coverage_partial_when_history_quality_below_100():
    cov = mt.classify_real_tick_coverage({"history quality": "97%"}, "", 4)
    assert cov["coverage"] == mt.REAL_TICK_COVERAGE_PARTIAL


def test_coverage_unknown_with_no_evidence_never_full():
    cov = mt.classify_real_tick_coverage({}, "", 4)
    assert cov["coverage"] == mt.REAL_TICK_COVERAGE_UNKNOWN
    assert cov["applicable"] is True


def test_coverage_not_applicable_for_math_calculations_model():
    # STAGE 5 R5, DEFECT 1: model 3 is math calculations, NOT a real-tick mode.
    cov = mt.classify_real_tick_coverage({"history quality": "100%"},
                                         "based on real ticks\n", 3)
    assert cov["coverage"] == mt.REAL_TICK_COVERAGE_UNKNOWN
    assert cov["applicable"] is False


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
    r = gs.tester_leg_evidence(sc, None, requested_model=4, symbol="EURUSD.G1")
    assert r["ok"]  # the model IS readable, it just differs
    assert r["model_matches_requested"] is False
    assert any("differs from the requested" in x for x in r["reasons"])


def test_tester_leg_evidence_uses_journal_for_coverage(tmp_path: Path):
    sc = _sidecar(tmp_path, {"model": "Every tick based on real ticks",
                             "history quality": "100%"})
    journal = tmp_path / "journal.txt"
    journal.write_text("real ticks used for the whole period\n",
                       encoding="utf-8")
    r = gs.tester_leg_evidence(sc, journal, requested_model=4,
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
    sc = _sidecar(tmp_path, {"model": "Every tick based on real ticks",
                             "history quality": "100%", "symbol": "EURUSD.G1"})
    journal = tmp_path / "j.txt"
    journal.write_text("based on real ticks\n", encoding="utf-8")
    cp = _decide("stage5-leg", "--report-json", str(sc),
                 "--journal", str(journal), "--requested-model", "4",
                 "--symbol", "EURUSD.G1", "--leg", "gold1_real_ticks")
    assert cp.returncode == 0, cp.stderr
    payload = json.loads(cp.stdout)
    assert payload["actual_model"]["label"] == "Every tick based on real ticks"
    assert payload["coverage"] == mt.REAL_TICK_COVERAGE_FULL


def test_cli_stage5_leg_fails_when_model_unreadable(tmp_path: Path):
    sc = _sidecar(tmp_path, {"period": "H1"})
    cp = _decide("stage5-leg", "--report-json", str(sc),
                 "--requested-model", "1")
    assert cp.returncode == 1
    payload = json.loads(cp.stdout)
    assert payload["ok"] is False


# ---------------------------------------------------------------------------
# classify_tester_leg_outcome — R6: a leg is judged by its OWN window only.
# BLOCKED is earned from scoped lines; zero bars is INSUFFICIENT_FIXTURE_
# HISTORY; anything unprovable is a plain FAIL. The poisoned-log tests below
# rebuild the EXACT shape that slipped through the R5 delivery run: gold1's
# zero-bar legs classified BLOCKED because gold2's successes were in the dump.
# ---------------------------------------------------------------------------

# a deliberately POISONED capture: this leg's own 0-bars lines PLUS another
# leg's successful lines (bars>0 + successfully finished) — the R5 defect shape
_POISONED_G1_WINDOW = (
    _FIXTURE_SHORT_JOURNAL
    + 'Core 1\tEURUSD.G2,M1: 11520 ticks, 2880 bars generated. '
      'Test passed in 0:00:03.561.\n'
      'Tester\tlast test passed with result "successfully finished" '
      'in 0:00:03.561\n')


def test_leg_outcome_blocked_owner_environment_is_earned_from_the_log():
    r = gs.classify_tester_leg_outcome(
        report_present=False, window_text=_BLOCKED_JOURNAL,
        symbol="EURUSD.G2", leg="gold2_m1_ohlc")
    assert r["outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV
    assert r["blocked"] is True and r["ok"] is False
    assert r["bars_generated"] == 2880 and r["test_finished"] is True
    # the reason QUOTES the scoped tester-log lines it rests on
    assert "successfully finished" in r["reason"]
    assert "2880 bars generated" in r["reason"]
    assert any("bars generated" in ln for ln in r["evidence_lines"])


def test_leg_outcome_blocked_needs_positive_bars_not_just_finished():
    # "successfully finished" WITHOUT a symbol-attributed bars>0 line can NOT
    # be BLOCKED — never inferred from the absence of a bars line.
    window = ('Tester\tlast test passed with result "successfully finished"\n')
    r = gs.classify_tester_leg_outcome(report_present=False,
                                       window_text=window,
                                       symbol="EURUSD.G1")
    assert r["outcome"] == gs.STAGE5_OUTCOME_FAIL
    assert r["blocked"] is False


def test_leg_outcome_zero_bars_is_insufficient_history_not_blocked():
    r = gs.classify_tester_leg_outcome(
        report_present=False, window_text=_FIXTURE_SHORT_JOURNAL,
        symbol="EURUSD.G1", leg="gold1_m1_ohlc")
    assert r["outcome"] == gs.STAGE5_OUTCOME_INSUFFICIENT_FIXTURE_HISTORY
    assert r["blocked"] is False and r["ok"] is False
    assert r["bars_generated"] == 0
    assert "INSUFFICIENT_FIXTURE_HISTORY" in r["reason"]
    assert "warm-up" in r["reason"]
    assert "0 bars generated" in r["reason"] or "start time changed" in r["reason"]


def test_leg_outcome_zero_bars_never_blocked_even_if_finished():
    # a leg that generated 0 bars is insufficient data even if a stray
    # "successfully finished" line is present — insufficient-history wins.
    window = _FIXTURE_SHORT_JOURNAL + \
        'Tester\tlast test passed with result "successfully finished"\n'
    r = gs.classify_tester_leg_outcome(report_present=False,
                                       window_text=window,
                                       symbol="EURUSD.G1")
    assert r["outcome"] == gs.STAGE5_OUTCOME_INSUFFICIENT_FIXTURE_HISTORY
    assert r["blocked"] is False


def test_leg_outcome_unprovable_is_plain_fail():
    r = gs.classify_tester_leg_outcome(
        report_present=False, symbol="EURUSD.G1",
        window_text="Core 1\tEURUSD.G1: some error after pass finished\n")
    assert r["outcome"] == gs.STAGE5_OUTCOME_FAIL
    assert r["blocked"] is False and r["ok"] is False


def test_leg_outcome_report_present_is_ok():
    r = gs.classify_tester_leg_outcome(report_present=True,
                                       window_text="", symbol="EURUSD.G1")
    assert r["outcome"] == gs.STAGE5_OUTCOME_OK and r["ok"] is True


# ---------------------------------------------------------------------------
# R6 scoping — the exact laundering shape that slipped through the delivery
# run, built on purpose: another leg's successes must never clear this leg.
# ---------------------------------------------------------------------------

def test_poisoned_window_zero_bars_leg_is_insufficient_never_blocked():
    """THE R6 regression: gold1's window shows 0 bars, and the same text ALSO
    carries gold2's successful lines (2880 bars + successfully finished).
    R5 classified this BLOCKED. It must be FAIL/INSUFFICIENT_FIXTURE_HISTORY —
    the other leg's bars>0 must not enter the decision OR the evidence."""
    r = gs.classify_tester_leg_outcome(
        report_present=False, window_text=_POISONED_G1_WINDOW,
        symbol="EURUSD.G1", leg="gold1_m1_ohlc")
    assert r["outcome"] == gs.STAGE5_OUTCOME_INSUFFICIENT_FIXTURE_HISTORY
    assert r["blocked"] is False
    assert r["bars_generated"] == 0
    # gold2's lines appear NOWHERE in this leg's evidence or reason
    assert all("EURUSD.G2" not in ln for ln in r["evidence_lines"])
    assert "EURUSD.G2" not in r["reason"]
    assert "2880" not in r["reason"]


def test_blocked_requires_bars_line_naming_this_legs_symbol():
    # only ANOTHER symbol's bars>0 + a finished line: not provable for THIS
    # leg -> plain FAIL, never BLOCKED (the bars line must name this symbol)
    window = ('Core 1\tEURUSD.G2,M1: 11520 ticks, 2880 bars generated.\n'
              'Tester\tlast test passed with result "successfully finished"\n')
    r = gs.classify_tester_leg_outcome(report_present=False,
                                       window_text=window,
                                       symbol="EURUSD.G1")
    assert r["outcome"] == gs.STAGE5_OUTCOME_FAIL
    assert r["blocked"] is False
    assert all("EURUSD.G2" not in ln for ln in r["evidence_lines"])


def test_no_symbol_means_no_attribution_and_never_blocked():
    # without a symbol no bars line can be ATTRIBUTED to the leg — even a
    # perfect blocked-shape text cannot prove BLOCKED (fail closed)
    r = gs.classify_tester_leg_outcome(report_present=False,
                                       window_text=_BLOCKED_JOURNAL,
                                       symbol=None)
    assert r["outcome"] == gs.STAGE5_OUTCOME_FAIL
    assert r["blocked"] is False


def test_two_legs_in_the_same_log_get_different_verdicts_by_window():
    """One physical tester log, two leg windows: gold1's window (its own
    appended lines) says 0 bars; gold2's says 2880 bars + finished. Scoped
    classification reaches DIFFERENT verdicts from the same source log."""
    full_log = (_FIXTURE_SHORT_JOURNAL + _BLOCKED_JOURNAL).splitlines()
    g1_window = "\n".join(full_log[:2])   # the lines appended during leg 1
    g2_window = "\n".join(full_log[2:])   # the lines appended during leg 2
    r1 = gs.classify_tester_leg_outcome(
        report_present=False, window_text=g1_window, symbol="EURUSD.G1")
    r2 = gs.classify_tester_leg_outcome(
        report_present=False, window_text=g2_window, symbol="EURUSD.G2")
    assert r1["outcome"] == gs.STAGE5_OUTCOME_INSUFFICIENT_FIXTURE_HISTORY
    assert r2["outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV
    # neither leg's evidence contains a line from outside its own window
    assert all(ln in g1_window.splitlines() for ln in
               (line.strip() for line in r1["evidence_lines"]))
    assert all(ln in [x.strip() for x in g2_window.splitlines()]
               for ln in r2["evidence_lines"])
    assert all("EURUSD.G2" not in ln for ln in r1["evidence_lines"])
    assert all("EURUSD.G1" not in ln for ln in r2["evidence_lines"])


def test_evidence_is_short_specific_and_deduped():
    # the day-wide dump is what hid the R5 defect: evidence must be the few
    # scoped lines that justify the verdict, deduplicated
    window = ('Core 1\tEURUSD.G1,H1: 0 ticks, 0 bars generated.\n' * 5
              + 'Core 1\tEURUSD.G1: start time changed to 2024.01.06 00:00 '
                'to provide data at beginning\n' * 3)
    r = gs.classify_tester_leg_outcome(report_present=False,
                                       window_text=window,
                                       symbol="EURUSD.G1")
    assert r["outcome"] == gs.STAGE5_OUTCOME_INSUFFICIENT_FIXTURE_HISTORY
    assert len(r["evidence_lines"]) <= 3
    assert len(set(r["evidence_lines"])) == len(r["evidence_lines"])


def test_cli_stage5_leg_outcome_blocked(tmp_path: Path):
    window = tmp_path / "window.txt"
    window.write_text(_BLOCKED_JOURNAL, encoding="utf-8")
    cp = _decide("stage5-leg-outcome", "--report-present", "false",
                 "--window", str(window), "--symbol", "EURUSD.G2",
                 "--leg", "gold2_m1_ohlc")
    # BLOCKED is not-ok (not a pass) -> exit 1
    assert cp.returncode == 1
    payload = json.loads(cp.stdout)
    assert payload["outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV
    assert payload["blocked"] is True
    assert "successfully finished" in payload["reason"]


def test_cli_stage5_leg_outcome_poisoned_window_is_insufficient(tmp_path: Path):
    # end-to-end through the CLI the .ps1 shells to, with the poisoned shape
    window = tmp_path / "window.txt"
    window.write_text(_POISONED_G1_WINDOW, encoding="utf-8")
    cp = _decide("stage5-leg-outcome", "--report-present", "false",
                 "--window", str(window), "--symbol", "EURUSD.G1",
                 "--leg", "gold1_m1_ohlc")
    assert cp.returncode == 1
    payload = json.loads(cp.stdout)
    assert payload["outcome"] == gs.STAGE5_OUTCOME_INSUFFICIENT_FIXTURE_HISTORY
    assert payload["blocked"] is False
    assert "2880" not in payload["reason"]


# ---------------------------------------------------------------------------
# run_mt5_backtest — DEFECT 2: [TesterInputs] populated from --defaults; an
# empty [TesterInputs] leg is REFUSED before launch.
# ---------------------------------------------------------------------------

def _run_backtest(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RUN_BACKTEST), *args],
                          capture_output=True, text=True, check=False)


def test_generate_ini_defaults_populates_tester_inputs():
    cp = _run_backtest("generate-ini", "--symbol", "EURUSD.G1",
                       "--timeframe", "H1", "--model", "1",
                       "--from", "2024.01.01", "--to", "2024.01.05",
                       "--report", "gold1_m1_ohlc", "--defaults")
    assert cp.returncode == 0, cp.stderr
    body = cp.stdout
    block = body[body.index("[TesterInputs]"):]
    assert "InpStrategy=0" in block and "InpFastEma=10" in block
    assert "InpSlowEma=30" in block


def test_generate_ini_without_defaults_has_empty_tester_inputs():
    cp = _run_backtest("generate-ini", "--symbol", "EURUSD.G1",
                       "--timeframe", "H1", "--model", "1",
                       "--from", "2024.01.01", "--to", "2024.01.05",
                       "--report", "gold1_m1_ohlc")
    assert cp.returncode == 0, cp.stderr
    block = cp.stdout[cp.stdout.index("[TesterInputs]"):]
    # the exact DEFECT-2 empty block: the header with no input lines under it
    assert block.strip() == "[TesterInputs]"


def test_run_refuses_empty_tester_inputs_before_launch():
    # No --defaults, no --input: the [TesterInputs] would be EMPTY, so the leg
    # is refused (exit 2, ValueError) BEFORE any terminal is launched.
    cp = _run_backtest("run", "--terminal-dir", "C:\\MT5",
                       "--data-folder", "C:\\MT5", "--symbol", "EURUSD.G1",
                       "--timeframe", "H1", "--model", "1",
                       "--from", "2024.01.01", "--to", "2024.01.05",
                       "--report", "gold1_m1_ohlc")
    assert cp.returncode == 2
    assert "EMPTY [TesterInputs]" in cp.stderr


def test_run_with_defaults_passes_inputs_guard_then_platform_guard():
    # With --defaults the inputs guard PASSES; on this non-Windows host the
    # only remaining stop is the platform guard (exit 3) — proving the empty-
    # inputs refusal is not what fired.
    cp = _run_backtest("run", "--terminal-dir", "C:\\MT5",
                       "--data-folder", "C:\\MT5", "--symbol", "EURUSD.G1",
                       "--timeframe", "H1", "--model", "4",
                       "--from", "2024.01.01", "--to", "2024.01.05",
                       "--report", "gold1_real_ticks", "--defaults")
    assert cp.returncode == 3
    assert "Windows-only" in cp.stderr
    assert "EMPTY [TesterInputs]" not in cp.stderr
