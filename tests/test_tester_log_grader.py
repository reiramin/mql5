"""Stage 5 log-based grading (PASS_FROM_LOG) — Mac-tested, no MT5 required.

MT5 build 6184 writes no [Tester] Report file, so a leg that ran a complete
backtest sits at BLOCKED_OWNER_ENVIRONMENT. ``tester_log_grader`` grades such a
leg from its OWN window capture. These tests pin the rule:

    PASS_FROM_LOG  <=>  "successfully finished" in the window
                        AND bars > 0 for this leg's symbol
                        AND history quality present
                        AND the model MT5 stated == the requested model

and that every other window keeps the R6 classifier's verdict.

Line provenance:
  * REAL CAPTURE — tests/data/owner_gate/tester_log_gate_runs_16_17.txt:
    the owner's gate runs 16/17 (2026-09-19, MT5 build 6184), verbatim:
    both model statements ("1 minutes OHLC ticks generating", "every tick
    generating"), "final balance", the gold2 bars line, history quality and
    "successfully finished". Also real: the DECISIONS.md lines for gold1's
    0-bars window, the math-calculations line and the every-tick bars line.
  * STILL UNCONFIRMED (never captured): the model-4 phrase "every tick based
    on real ticks", MT5's own "deal #N buy|sell" / "close #N" lines, and
    any EA "DEAL #" line with real values (its FORMAT is pinned to the EA
    source by a test below). Such lines are marked UNCONFIRMED where used.

The captured lines come from several legs of those runs; each test window
below is assembled from them, and only symbol-scoped attribution decides
which leg a line can speak for.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from mql5bot import gate_selfcheck as gs
from mql5bot import tester_log_grader as tlg

REPO = Path(__file__).resolve().parents[1]
DECIDE = REPO / "tools" / "owner_gate_decide.py"
CAPTURE = REPO / "tests" / "data" / "owner_gate" / "tester_log_gate_runs_16_17.txt"


def _lines(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _captured() -> list[str]:
    text = CAPTURE.read_text(encoding="utf-8")
    return [ln for ln in text.splitlines() if ln and not ln.startswith("#")]


# REAL CAPTURE (gate runs 16/17) — read from the fixture, never retyped.
(_G2_MODEL, _G1_MODEL_EVERY_TICK, _FINAL_BALANCE_REAL, _G2_BARS, _G2_QUALITY,
 _G2_FINISHED) = _captured()

# The real gold2 M1-OHLC window: every captured line except gold1's.
GOLD2_WINDOW = _lines(_G2_MODEL, _FINAL_BALANCE_REAL, _G2_BARS, _G2_QUALITY,
                      _G2_FINISHED)
# The same real lines with the model statement removed.
GOLD2_NO_MODEL_WINDOW = _lines(_FINAL_BALANCE_REAL, _G2_BARS, _G2_QUALITY,
                               _G2_FINISHED)

# REAL (docs/OWNER_DELIVERY.md stage-5 table): gold2 every-tick bars line.
_G2_EVERY_TICK_BARS = "EURUSD.G2,M1: 1894944 ticks, 2880 bars generated"
# REAL (docs/DECISIONS.md 2026-09-20, DEFECT 4): gold1's 0-bars window.
GOLD1_ZERO_BARS_WINDOW = (
    "Core 1\tEURUSD.G1: start time changed to 2024.01.06 00:00 to provide "
    "data at beginning\n"
    "Core 1\tEURUSD.G1,H1: 0 ticks, 0 bars generated.\n")
# REAL (docs/DECISIONS.md 2026-09-20, DEFECT 1): a real-tick leg sent
# Model=3 and MT5 ran math-calculations mode.
_G1_MATH_MODE = ("Core 1\tmath calculations test mode means no history and "
                 "no symbol info for EURUSD.G1")

# UNCONFIRMED: MT5's model-4 statement has never been captured; the phrase is
# the expected "every tick based on real ticks" in the captured line shape.
_G2_MODEL_REAL_TICKS = ("EURUSD.G2,M1 (MetaQuotes-Demo): every tick based on "
                        "real ticks generating")
# DERIVED, NOT A CAPTURE: gold1's real "every tick generating" line with the
# symbol changed to gold2 — used only to put two model statements in one
# gold2 window (the conflict test).
_G2_MODEL_EVERY_TICK = _G1_MODEL_EVERY_TICK.replace("EURUSD.G1,H1",
                                                    "EURUSD.G2,M1")

# UNCONFIRMED: the EA's DEAL line (format pinned to Mql5Bot.mq5 by a test; the
# values are invented) and MT5's own deal/request lines (never captured).
_EA_DEAL_OPEN = ("Core 1\t2024.01.02 10:00:00   [2024.01.02 10:00:00] [INFO] "
                 "DEAL #2 EURUSD.G2 vol=0.10 price=1.10010 pnl=0.00")
_EA_DEAL_CLOSE = ("Core 1\t2024.01.02 14:00:00   [2024.01.02 14:00:00] [INFO] "
                  "DEAL #3 EURUSD.G2 vol=0.10 price=1.10100 pnl=9.00")
_MT5_REQ_OPEN = ("Core 1\t2024.01.02 10:00:00   market buy 0.10 EURUSD.G2 "
                 "(1.10000 / 1.10010 / 1.10000)")
_MT5_DEAL_OPEN = ("Core 1\t2024.01.02 10:00:00   deal #2 buy 0.10 EURUSD.G2 "
                  "at 1.10010 done (based on order #2)")
_MT5_REQ_CLOSE = ("Core 1\t2024.01.02 14:00:00   market sell 0.10 EURUSD.G2, "
                  "close #2 buy 0.10 EURUSD.G2 1.10010 (1.10100 / 1.10110)")
_MT5_DEAL_CLOSE = ("Core 1\t2024.01.02 14:00:00   deal #3 sell 0.10 EURUSD.G2 "
                   "at 1.10100 done (based on order #3)")
# the captured "final balance" line shape with an invented value
_FINAL_BALANCE = "Core 1\tfinal balance 10009.00 USD"


def _grade(window: str, symbol: str = "EURUSD.G2", model: int = 1,
           leg: str = "gold2_m1_ohlc") -> dict:
    return tlg.grade_leg_from_log(window_text=window, symbol=symbol,
                                  requested_model=model, leg=leg)


# ---------------------------------------------------------------------------
# the capture itself
# ---------------------------------------------------------------------------

def test_capture_fixture_holds_the_six_owner_lines_verbatim():
    assert _captured() == [
        "EURUSD.G2,M1 (MetaQuotes-Demo): 1 minutes OHLC ticks generating",
        "EURUSD.G1,H1 (MetaQuotes-Demo): every tick generating",
        "final balance 10000.00 USD",
        ("EURUSD.G2,M1: 11520 ticks, 2880 bars generated. Environment "
         "synchronized in 0:00:00.039. Test passed in 0:00:03.561."),
        "Tester    quality of analyzed history is 100%",
        ('Tester    last test passed with result "successfully finished" '
         "in 0:00:03.561"),
    ]


# ---------------------------------------------------------------------------
# parsing — real captured text, every missing field None
# ---------------------------------------------------------------------------

def test_real_gold2_window_parses_every_field():
    p = tlg.parse_leg_window(GOLD2_WINDOW, "EURUSD.G2")
    assert p["finished_ok"] is True
    assert (p["bars"], p["ticks"]) == (2880, 11520)
    assert p["history_quality"] == 100.0
    assert (p["final_balance"], p["final_balance_currency"]) == \
        (10000.0, "USD")
    assert (p["actual_model"], p["actual_model_label"]) == \
        (1, "1 minute OHLC")
    assert p["deals"] == []  # no DEAL line: the EA made no trades
    assert p["lines"] == {
        "finished": [_G2_FINISHED], "bars": [_G2_BARS], "warmup": [],
        "history_quality": [_G2_QUALITY],
        "final_balance": [_FINAL_BALANCE_REAL], "model": [_G2_MODEL],
        "loaded_strategy": []}
    # runs 16/17 loaded no DSL bundle, so the EA logged no strategy line
    assert p["loaded_strategy"] is None


def test_real_every_tick_statement_is_model_0():
    p = tlg.parse_leg_window(_G1_MODEL_EVERY_TICK + "\n", "EURUSD.G1")
    assert (p["actual_model"], p["actual_model_label"]) == (0, "Every tick")


def test_model_statement_is_read_after_a_timestamp_column():
    # agent-log files prefix each message with time columns ("12:34:56.789")
    line = "CS\t0\t12:34:56.789\tCore 1\t" + _G2_MODEL
    assert tlg.parse_leg_window(line, "EURUSD.G2")["actual_model"] == 1


def test_unconfirmed_real_ticks_phrase_is_model_4_not_every_tick():
    # UNCONFIRMED phrase: must map to 4, never shadowed by "every tick" (0)
    p = tlg.parse_leg_window(_G2_MODEL_REAL_TICKS, "EURUSD.G2")
    assert p["actual_model"] == 4


def test_the_bars_line_is_not_a_model_statement():
    # "generated" is not "generating": the real bars line states no model
    assert tlg.parse_leg_window(_G2_BARS, "EURUSD.G2")["actual_model"] is None


def test_fields_absent_from_the_window_are_none_never_a_default():
    p = tlg.parse_leg_window(GOLD2_NO_MODEL_WINDOW, "EURUSD.G2")
    assert p["actual_model"] is None
    assert p["actual_model_label"] is None
    empty = tlg.parse_leg_window("", "EURUSD.G2")
    for field in ("finished_ok", "bars", "ticks", "history_quality",
                  "final_balance", "final_balance_currency", "actual_model",
                  "actual_model_label"):
        assert empty[field] is None, field
    assert empty["deals"] == []


def test_real_every_tick_bars_line_parses():
    p = tlg.parse_leg_window(_G2_EVERY_TICK_BARS + "\n", "EURUSD.G2")
    assert (p["ticks"], p["bars"]) == (1894944, 2880)


def test_real_math_mode_line_is_read_as_model_3():
    p = tlg.parse_leg_window(_G1_MATH_MODE + "\n", "EURUSD.G1")
    assert p["actual_model"] == 3
    assert p["actual_model_label"] == "Math calculations"
    assert p["lines"]["model"] == [_G1_MATH_MODE]


def test_parse_reuses_gate_selfcheck_leg_scoping(monkeypatch):
    # R6 scoping lives in ONE place; the grader must go through it, not a
    # copy. Poison it and the grader's finished/bars fields must follow.
    calls = []

    def fake(window_text, symbol):
        calls.append(symbol)
        return {"finished": [], "bars": [], "warmup": []}

    monkeypatch.setattr(gs, "_leg_scoped_lines", fake)
    p = tlg.parse_leg_window(GOLD2_WINDOW, "EURUSD.G2")
    assert calls == ["EURUSD.G2"]
    assert p["finished_ok"] is None and p["bars"] is None


# ---------------------------------------------------------------------------
# grading — PASS_FROM_LOG only when every condition holds
# ---------------------------------------------------------------------------

def test_real_gold2_window_grades_pass_from_log():
    r = _grade(GOLD2_WINDOW)
    assert r["outcome"] == tlg.STAGE5_OUTCOME_PASS_FROM_LOG == "PASS_FROM_LOG"
    assert r["ok"] is True
    assert r["evidence_class"] == "PASS_FROM_LOG"
    assert r["source"] == "tester agent log"
    assert r["report_present"] is False
    assert r["base_outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV
    assert r["failed_checks"] == []
    # the verdict quotes the exact captured lines it rests on
    assert r["evidence_lines"] == [_G2_FINISHED, _G2_BARS, _G2_QUALITY,
                                   _G2_MODEL]
    for line in r["evidence_lines"]:
        assert line in r["reason"]


def test_real_window_missing_the_model_line_stays_blocked():
    # the grader never infers the model (not even from 11520/2880 = 4 ticks
    # per M1 bar): no model statement -> no PASS_FROM_LOG
    r = _grade(GOLD2_NO_MODEL_WINDOW)
    assert r["outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV
    assert r["ok"] is False
    assert r["failed_checks"] == ["model_matches_requested"]
    assert "Not PASS_FROM_LOG" in r["reason"]


def test_gold1_model_line_cannot_speak_for_gold2():
    # gold1's real model statement in a gold2 window without its own
    window = GOLD2_NO_MODEL_WINDOW + _G1_MODEL_EVERY_TICK + "\n"
    r = _grade(window, model=0)
    assert r["parsed"]["actual_model"] is None
    assert r["outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV


def test_pass_from_log_is_never_the_report_based_pass():
    r = _grade(GOLD2_WINDOW)
    assert r["outcome"] != gs.STAGE5_OUTCOME_OK
    assert r["outcome"] != "PASS"
    assert "distinct from the report-based PASS" in r["reason"]


def test_real_gold1_zero_bars_window_stays_insufficient_history():
    r = _grade(GOLD1_ZERO_BARS_WINDOW, symbol="EURUSD.G1", leg="gold1_m1_ohlc")
    assert r["outcome"] == gs.STAGE5_OUTCOME_INSUFFICIENT_FIXTURE_HISTORY
    assert r["ok"] is False
    assert r["parsed"]["bars"] == 0
    assert "bars_positive" in r["failed_checks"]


def test_zero_bars_is_never_graded_up_even_with_every_other_line_present():
    # gold1's real 0-bars lines + its real "every tick generating" statement
    # + a real quality/finished line, requested every tick (0)
    window = (GOLD1_ZERO_BARS_WINDOW + _G1_MODEL_EVERY_TICK + "\n"
              + _G2_QUALITY + "\n" + _G2_FINISHED + "\n")
    r = _grade(window, symbol="EURUSD.G1", model=0, leg="gold1_every_tick")
    assert r["parsed"]["actual_model"] == 0
    assert r["outcome"] == gs.STAGE5_OUTCOME_INSUFFICIENT_FIXTURE_HISTORY
    assert r["ok"] is False


def test_another_symbols_success_lines_do_not_pass_this_leg():
    # gold2's real window, judged as the gold1 leg
    r = _grade(GOLD2_WINDOW, symbol="EURUSD.G1", leg="gold1_m1_ohlc")
    assert r["outcome"] != tlg.STAGE5_OUTCOME_PASS_FROM_LOG
    assert r["ok"] is False
    assert r["parsed"]["bars"] is None
    assert r["parsed"]["actual_model"] is None
    assert "2880" not in " ".join(r["evidence_lines"])


def test_gold1_window_poisoned_with_gold2_success_stays_insufficient():
    r = _grade(GOLD1_ZERO_BARS_WINDOW + GOLD2_WINDOW, symbol="EURUSD.G1",
               leg="gold1_m1_ohlc")
    assert r["outcome"] == gs.STAGE5_OUTCOME_INSUFFICIENT_FIXTURE_HISTORY


def test_model_mismatch_fails():
    # real lines only: the window states 1 minutes OHLC; every tick requested
    r = _grade(GOLD2_WINDOW, model=0, leg="gold2_every_tick")
    assert r["outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV
    assert r["ok"] is False
    assert r["failed_checks"] == ["model_matches_requested"]
    assert "MT5 stated 1 minute OHLC" in r["reason"]


def test_real_math_mode_leg_requested_real_ticks_does_not_pass():
    # the measured DEFECT-1 shape: Model=4 requested, MT5 ran math calculations
    r = _grade(_G1_MATH_MODE + "\n", symbol="EURUSD.G1", model=4,
               leg="gold1_real_ticks")
    assert r["ok"] is False
    assert r["parsed"]["actual_model"] == 3
    assert "model_matches_requested" in r["failed_checks"]


def test_two_different_models_for_the_symbol_is_a_conflict_not_a_pick():
    r = _grade(GOLD2_WINDOW + _G2_MODEL_EVERY_TICK + "\n", model=1)
    assert r["parsed"]["actual_model"] is None
    assert r["parsed"]["model_conflict"] is True
    assert r["ok"] is False


def test_missing_history_quality_fails():
    window = _lines(_G2_MODEL, _G2_BARS, _G2_FINISHED)
    r = _grade(window)
    assert r["parsed"]["history_quality"] is None
    assert r["failed_checks"] == ["history_quality_present"]
    assert r["outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV


def test_missing_successfully_finished_fails():
    window = _lines(_G2_MODEL, _G2_QUALITY, _G2_BARS)
    r = _grade(window)
    assert r["parsed"]["finished_ok"] is None
    assert "successfully_finished" in r["failed_checks"]
    assert r["outcome"] == gs.STAGE5_OUTCOME_FAIL


# ---------------------------------------------------------------------------
# deals + final balance (FORMAT lines; the EA format is pinned to its source)
# ---------------------------------------------------------------------------

def test_ea_deal_format_matches_the_ea_source():
    src = (REPO / "mql5" / "Experts" / "Mql5Bot" / "Mql5Bot.mq5").read_text(
        encoding="utf-8", errors="replace")
    assert '"DEAL #%I64u %s vol=%.2f price=%.5f pnl=%.2f"' in src
    logger = (REPO / "mql5" / "Include" / "Mql5Bot" / "Logger.mqh").read_text(
        encoding="utf-8", errors="replace")
    assert 'StringFormat("[%s] [%s] %s"' in logger


def test_deals_parse_from_the_ea_lines_with_side_and_entry_from_mt5():
    window = _lines(_MT5_REQ_OPEN, _MT5_DEAL_OPEN, _EA_DEAL_OPEN,
                        _MT5_REQ_CLOSE, _MT5_DEAL_CLOSE, _EA_DEAL_CLOSE,
                        _FINAL_BALANCE)
    p = tlg.parse_leg_window(window, "EURUSD.G2")
    assert [d["ticket"] for d in p["deals"]] == [2, 3]
    opened, closed = p["deals"]
    assert opened == {
        "ticket": 2, "time": "2024.01.02 10:00:00", "symbol": "EURUSD.G2",
        "side": "buy", "entry": "open", "volume": 0.10, "price": 1.10010,
        "pnl": 0.0, "lines": [_EA_DEAL_OPEN, _MT5_DEAL_OPEN]}
    assert (closed["side"], closed["entry"], closed["pnl"]) == \
        ("sell", "close", 9.0)
    assert p["final_balance"] == 10009.0
    assert p["final_balance_currency"] == "USD"


def test_side_and_entry_are_none_without_mt5_lines():
    p = tlg.parse_leg_window(_EA_DEAL_CLOSE + "\n", "EURUSD.G2")
    (deal,) = p["deals"]
    # the EA line does not state them and pnl != 0 is never read as "close"
    assert deal["side"] is None
    assert deal["entry"] is None
    assert deal["pnl"] == 9.0


def test_deals_for_another_symbol_are_not_this_legs_deals():
    p = tlg.parse_leg_window(_EA_DEAL_OPEN + "\n" + _MT5_DEAL_OPEN + "\n",
                             "EURUSD.G1")
    assert p["deals"] == []


# ---------------------------------------------------------------------------
# stage-8 trade input
# ---------------------------------------------------------------------------

def test_log_trade_list_is_flagged_and_invents_no_metrics():
    window = GOLD2_WINDOW + _EA_DEAL_OPEN + "\n"
    raw = window.encode("utf-8")
    doc = tlg.log_trade_list(_grade(window), raw)
    assert doc["from_log"] is True
    assert doc["report_present"] is False
    assert doc["evidence_class"] == "PASS_FROM_LOG"
    assert doc["source"] == "tester agent log"
    assert doc["window_sha256"] == hashlib.sha256(raw).hexdigest()
    assert doc["metrics"] == {} and doc["fields"] == {}
    assert doc["settings"] == {"symbol": "EURUSD.G2", "model": "1 minute OHLC",
                               "history quality": "100%"}
    assert [d["ticket"] for d in doc["deals"]] == [2]
    assert doc["final_balance"] == 10000.0


def test_real_window_trade_list_has_zero_deals_and_is_valid():
    # the captured gold2 run made no trades (final balance = the 10000 start):
    # an empty deal list is an honest observation, not a missing one
    raw = GOLD2_WINDOW.encode("utf-8")
    doc = tlg.log_trade_list(_grade(GOLD2_WINDOW), raw)
    assert doc is not None
    assert doc["deals"] == []
    assert (doc["final_balance"], doc["final_balance_currency"]) == \
        (10000.0, "USD")
    assert doc["settings"]["model"] == "1 minute OHLC"


def test_no_trade_list_for_a_leg_that_did_not_pass_from_log():
    assert tlg.log_trade_list(_grade(GOLD2_NO_MODEL_WINDOW), b"") is None
    assert tlg.log_trade_list(
        _grade(GOLD1_ZERO_BARS_WINDOW, symbol="EURUSD.G1"), b"") is None


# ---------------------------------------------------------------------------
# CLI the .ps1 shells to: owner_gate_decide.py stage5-leg --window
# ---------------------------------------------------------------------------

def _decide(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(DECIDE), "--repo", str(REPO),
                           *args], capture_output=True, text=True, check=False)


def test_cli_stage5_leg_grades_pass_from_log_and_writes_trades(tmp_path):
    window = tmp_path / "tester_gold2_m1_ohlc_window.txt"
    window.write_text(GOLD2_WINDOW + _EA_DEAL_OPEN + "\n", encoding="utf-8")
    trades = tmp_path / "tester_gold2_m1_ohlc_log_trades.json"
    cp = _decide("stage5-leg", "--window", str(window), "--requested-model",
                 "1", "--symbol", "EURUSD.G2", "--leg", "gold2_m1_ohlc",
                 "--trades-out", str(trades))
    assert cp.returncode == 0, cp.stderr
    payload = json.loads(cp.stdout)
    assert payload["outcome"] == "PASS_FROM_LOG"
    doc = json.loads(trades.read_text(encoding="utf-8"))
    assert doc["from_log"] is True
    assert doc["window_sha256"] == hashlib.sha256(
        window.read_bytes()).hexdigest()


def test_cli_stage5_leg_keeps_blocked_on_the_real_window(tmp_path):
    window = tmp_path / "w.txt"
    window.write_text(GOLD2_NO_MODEL_WINDOW, encoding="utf-8")
    trades = tmp_path / "t.json"
    cp = _decide("stage5-leg", "--window", str(window), "--requested-model",
                 "1", "--symbol", "EURUSD.G2", "--trades-out", str(trades))
    assert cp.returncode == 1
    assert json.loads(cp.stdout)["outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV
    assert not trades.exists()


@pytest.mark.parametrize("extra", [[], ["--report-json", "/nonexistent.json"]])
def test_cli_stage5_leg_without_report_or_window_fails_closed(extra):
    cp = _decide("stage5-leg", "--requested-model", "1", "--symbol",
                 "EURUSD.G2", *extra)
    assert cp.returncode == 1
    assert json.loads(cp.stdout)["ok"] is False
