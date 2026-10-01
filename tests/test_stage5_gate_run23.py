"""gate_run23: the stage-5 leg verdict names the cause its own window states.

Lines are the owner's gate_run23 lines, copied verbatim into
tests/data/owner_gate/tester_log_gate_run23.txt:

  * the EA refused the DSL bundle at OnInit (both error strings empty) and
    the tester stopped because OnInit returned non-zero -> FAIL whose reason
    says "EA refused the DSL bundle at OnInit";
  * the real_ticks leg (Model=4) stopped with "no history data, stop
    testing" -> the named FAIL_NO_TICK_HISTORY (never BLOCKED, never a pass).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from mql5bot import gate_selfcheck as gs
from mql5bot import tester_log_grader as tlg

REPO = Path(__file__).resolve().parents[1]
DECIDE = REPO / "tools" / "owner_gate_decide.py"
CAPTURE = REPO / "tests" / "data" / "owner_gate" / "tester_log_gate_run23.txt"
SYMBOL = "EURUSD.G2"
REFUSED_LINE = "[mql5bot] DSL bundle refused:  "
ONINIT_LINE = "tester stopped because OnInit returns non-zero code 1"
NO_HISTORY_LINE = "no history data, stop testing"
BEGINS_LINE = "EURUSD.G2: history data begins from 2024.01.01 00:00"


def _section(name: str) -> str:
    """The captured lines under ``# [section] <name>`` (verbatim bytes)."""
    out, on = [], False
    for ln in CAPTURE.read_text(encoding="utf-8").splitlines():
        if ln.startswith("# [section] "):
            on = ln.startswith(f"# [section] {name} ")
            continue
        if on and not ln.startswith("#"):
            out.append(ln)
    return "\n".join(out) + "\n"


def test_capture_holds_the_gate_run23_lines_verbatim():
    lines = CAPTURE.read_text(encoding="utf-8").splitlines()
    for want in (REFUSED_LINE, ONINIT_LINE, NO_HISTORY_LINE, BEGINS_LINE):
        assert want in lines
    assert REFUSED_LINE in _section("refused").splitlines()
    assert NO_HISTORY_LINE in _section("real_ticks").splitlines()


def test_refused_bundle_window_fails_naming_the_oninit_refusal():
    v = gs.classify_tester_leg_outcome(
        report_present=False, window_text=_section("refused"),
        symbol=SYMBOL, leg="gold2_m1_ohlc")
    assert v["outcome"] == gs.STAGE5_OUTCOME_FAIL
    assert v["ok"] is False and v["blocked"] is False
    assert "EA refused the DSL bundle at OnInit" in v["reason"]
    assert "both error strings empty" in v["reason"]
    assert ONINIT_LINE in v["reason"]
    assert REFUSED_LINE.strip() in v["evidence_lines"]
    assert ONINIT_LINE in v["evidence_lines"]


def test_oninit_nonzero_alone_is_named():
    v = gs.classify_tester_leg_outcome(
        report_present=False, window_text=ONINIT_LINE + "\n",
        symbol=SYMBOL, leg="gold2_m1_ohlc")
    assert v["outcome"] == gs.STAGE5_OUTCOME_FAIL
    assert "OnInit returned non-zero" in v["reason"]
    assert ONINIT_LINE in v["reason"]


def test_refusal_is_never_blocked_even_beside_a_clean_looking_run():
    window = (_section("refused")
              + "EURUSD.G2,M1: 11520 ticks, 2880 bars generated.\n"
              + 'last test passed with result "successfully finished"\n')
    v = gs.classify_tester_leg_outcome(
        report_present=False, window_text=window, symbol=SYMBOL,
        leg="gold2_m1_ohlc")
    assert v["outcome"] == gs.STAGE5_OUTCOME_FAIL
    assert v["blocked"] is False
    assert "EA refused the DSL bundle at OnInit" in v["reason"]


def test_real_ticks_window_is_the_named_no_tick_history_fail():
    v = gs.classify_tester_leg_outcome(
        report_present=False, window_text=_section("real_ticks"),
        symbol=SYMBOL, leg="gold2_real_ticks")
    assert v["outcome"] == gs.STAGE5_OUTCOME_NO_TICK_HISTORY
    assert v["outcome"] == "FAIL_NO_TICK_HISTORY"
    assert v["ok"] is False and v["blocked"] is False
    assert NO_HISTORY_LINE in v["reason"]
    assert v["evidence_lines"] == [BEGINS_LINE, NO_HISTORY_LINE]


def test_history_begins_line_of_another_symbol_is_not_quoted():
    window = _section("real_ticks").replace("EURUSD.G2", "EURUSD.G1")
    v = gs.classify_tester_leg_outcome(
        report_present=False, window_text=window, symbol=SYMBOL,
        leg="gold2_real_ticks")
    assert v["outcome"] == gs.STAGE5_OUTCOME_NO_TICK_HISTORY
    assert v["evidence_lines"] == [NO_HISTORY_LINE]


def test_log_grader_keeps_both_named_fails():
    for section, model, outcome in (
            ("refused", 1, gs.STAGE5_OUTCOME_FAIL),
            ("real_ticks", 4, gs.STAGE5_OUTCOME_NO_TICK_HISTORY)):
        g = tlg.grade_leg_from_log(
            window_text=_section(section), symbol=SYMBOL,
            requested_model=model, leg=f"gold2_{section}",
            expected_strategy="gold2_multifactor")
        assert g["outcome"] == outcome
        assert g["ok"] is False and g["blocked"] is False
    g = tlg.grade_leg_from_log(
        window_text=_section("refused"), symbol=SYMBOL, requested_model=1,
        expected_strategy="gold2_multifactor")
    assert "EA refused the DSL bundle at OnInit" in g["reason"]


def test_cli_stage5_leg_reports_the_named_cause(tmp_path):
    for section, model, outcome, phrase in (
            ("refused", 1, "FAIL", "EA refused the DSL bundle at OnInit"),
            ("real_ticks", 4, "FAIL_NO_TICK_HISTORY", NO_HISTORY_LINE)):
        window = tmp_path / f"{section}.txt"
        window.write_bytes(_section(section).encode("utf-8"))
        cp = subprocess.run(
            [sys.executable, str(DECIDE), "--repo", str(REPO), "stage5-leg",
             "--window", str(window), "--requested-model", str(model),
             "--symbol", SYMBOL, "--leg", f"gold2_{section}",
             "--trades-out", str(tmp_path / f"{section}_trades.json"),
             "--expected-strategy", "gold2_multifactor"],
            capture_output=True, text=True, check=False)
        assert cp.returncode == 1, cp.stdout + cp.stderr
        out = json.loads(cp.stdout)
        assert out["outcome"] == outcome
        assert phrase in out["reason"]
        assert not (tmp_path / f"{section}_trades.json").exists()
