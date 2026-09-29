"""Stage 5 log-based grading (PASS_FROM_LOG) — Mac-tested, no MT5 required.

MT5 build 6184 writes no [Tester] Report file, so a leg that ran a complete
backtest sits at BLOCKED_OWNER_ENVIRONMENT. ``tester_log_grader`` grades such a
leg from its OWN window capture. These tests pin the rule:

    PASS_FROM_LOG  <=>  "successfully finished" in the window
                        AND bars > 0 for this leg's symbol
                        AND history quality present
                        AND the model MT5 stated == the requested model

and that every other window keeps the R6 classifier's verdict.

Line provenance, stated per constant: MEASURED lines are copied byte-for-byte
from the gate_run17 / delivery-run excerpts recorded in docs/DECISIONS.md and
docs/OWNER_DELIVERY.md. Lines marked FORMAT are NOT captured output — they
follow the EA source (mql5/Experts/Mql5Bot/Mql5Bot.mq5) or MT5's tester
journal format, and are used only where no captured line exists.
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


def _lines(*lines: str) -> str:
    return "\n".join(lines) + "\n"


DECIDE = REPO / "tools" / "owner_gate_decide.py"

# MEASURED (docs/DECISIONS.md 2026-09-20, DEFECT 3): the gold2 M1 leg's lines.
_G2_QUALITY = "Tester\tquality of analyzed history is 100%"
_G2_BARS = ("Core 1\tEURUSD.G2,M1: 11520 ticks, 2880 bars generated. "
            "Test passed in 0:00:03.561.")
_G2_FINISHED = ('Tester\tlast test passed with result "successfully finished" '
                "in 0:00:03.561")
GOLD2_WINDOW = _lines(_G2_QUALITY, _G2_BARS, _G2_FINISHED)
# MEASURED (docs/OWNER_DELIVERY.md stage-5 table): gold2 every-tick bars line.
_G2_EVERY_TICK_BARS = "EURUSD.G2,M1: 1894944 ticks, 2880 bars generated"

# MEASURED (docs/DECISIONS.md 2026-09-20, DEFECT 4): gold1's 0-bars window.
GOLD1_ZERO_BARS_WINDOW = (
    "Core 1\tEURUSD.G1: start time changed to 2024.01.06 00:00 to provide "
    "data at beginning\n"
    "Core 1\tEURUSD.G1,H1: 0 ticks, 0 bars generated.\n")

# MEASURED (docs/DECISIONS.md 2026-09-20, DEFECT 1): MT5 stating that a
# real-tick leg sent Model=3 actually ran math-calculations mode.
_G1_MATH_MODE = ("Core 1\tmath calculations test mode means no history and "
                 "no symbol info for EURUSD.G1")

# FORMAT, NOT CAPTURED: a model statement naming the canonical
# "1 minute OHLC" label and the leg's symbol. No captured window in this repo
# contains a model line for gold2 — see test_real_gold2_window_alone_*.
_G2_MODEL_M1_OHLC = ("Core 1\tEURUSD.G2,M1 (MetaQuotes-Demo): 1 minute OHLC "
                     "ticks generating")
_G2_MODEL_EVERY_TICK = ("Core 1\tEURUSD.G2,M1 (MetaQuotes-Demo): every tick "
                        "generating")

# FORMAT, NOT CAPTURED: the EA's DEAL line (Mql5Bot.mq5 OnTradeTransaction →
# Logger.Write "[%s] [%s] %s") and MT5's own deal/request lines.
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
_FINAL_BALANCE = "Core 1\tfinal balance 10009.00 USD"

GRADEABLE_GOLD2 = GOLD2_WINDOW + _G2_MODEL_M1_OHLC + "\n"


def _grade(window: str, symbol: str = "EURUSD.G2", model: int = 1,
           leg: str = "gold2_m1_ohlc") -> dict:
    return tlg.grade_leg_from_log(window_text=window, symbol=symbol,
                                  requested_model=model, leg=leg)


# ---------------------------------------------------------------------------
# parsing — real captured text, every missing field None
# ---------------------------------------------------------------------------

def test_real_gold2_window_parses_the_measured_fields():
    p = tlg.parse_leg_window(GOLD2_WINDOW, "EURUSD.G2")
    assert p["finished_ok"] is True
    assert p["bars"] == 2880
    assert p["ticks"] == 11520
    assert p["history_quality"] == 100.0
    assert p["lines"]["finished"] == [_G2_FINISHED]
    assert p["lines"]["bars"] == [_G2_BARS]
    assert p["lines"]["history_quality"] == [_G2_QUALITY]


def test_fields_absent_from_the_window_are_none_never_a_default():
    p = tlg.parse_leg_window(GOLD2_WINDOW, "EURUSD.G2")
    # the captured excerpt states no balance, no deals and no model
    assert p["final_balance"] is None
    assert p["final_balance_currency"] is None
    assert p["actual_model"] is None
    assert p["actual_model_label"] is None
    assert p["deals"] == []
    empty = tlg.parse_leg_window("", "EURUSD.G2")
    for field in ("finished_ok", "bars", "ticks", "history_quality",
                  "final_balance", "final_balance_currency", "actual_model",
                  "actual_model_label"):
        assert empty[field] is None, field


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

def test_real_gold2_window_alone_is_not_pass_because_no_model_is_stated():
    # The honest result on the captured excerpt: MT5's model statement is not
    # in it, so the requested model cannot be confirmed and the leg keeps its
    # R6 verdict. The grader does not infer the model from the tick count.
    r = _grade(GOLD2_WINDOW)
    assert r["outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV
    assert r["ok"] is False
    assert r["failed_checks"] == ["model_matches_requested"]
    assert "Not PASS_FROM_LOG" in r["reason"]


def test_gold2_window_with_a_model_statement_grades_pass_from_log():
    r = _grade(GRADEABLE_GOLD2)
    assert r["outcome"] == tlg.STAGE5_OUTCOME_PASS_FROM_LOG == "PASS_FROM_LOG"
    assert r["ok"] is True
    assert r["evidence_class"] == "PASS_FROM_LOG"
    assert r["source"] == "tester agent log"
    assert r["report_present"] is False
    assert r["base_outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV
    assert r["failed_checks"] == []
    # the verdict quotes the exact window lines it rests on
    assert r["evidence_lines"] == [_G2_FINISHED, _G2_BARS, _G2_QUALITY,
                                   _G2_MODEL_M1_OHLC]
    for line in r["evidence_lines"]:
        assert line in r["reason"]


def test_pass_from_log_is_never_the_report_based_pass():
    r = _grade(GRADEABLE_GOLD2)
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
    window = (GOLD1_ZERO_BARS_WINDOW + _G2_QUALITY + "\n" + _G2_FINISHED
              + "\nCore 1\tEURUSD.G1,H1 (MetaQuotes-Demo): 1 minute OHLC "
              "ticks generating\n")
    r = _grade(window, symbol="EURUSD.G1", leg="gold1_m1_ohlc")
    assert r["outcome"] == gs.STAGE5_OUTCOME_INSUFFICIENT_FIXTURE_HISTORY
    assert r["ok"] is False


def test_another_symbols_success_lines_do_not_pass_this_leg():
    # gold2's real success lines + a gold2 model line, judged as the gold1 leg
    r = _grade(GRADEABLE_GOLD2, symbol="EURUSD.G1", leg="gold1_m1_ohlc")
    assert r["outcome"] != tlg.STAGE5_OUTCOME_PASS_FROM_LOG
    assert r["ok"] is False
    assert r["parsed"]["bars"] is None
    assert r["parsed"]["actual_model"] is None
    assert "2880" not in " ".join(r["evidence_lines"])


def test_gold1_window_poisoned_with_gold2_success_stays_insufficient():
    r = _grade(GOLD1_ZERO_BARS_WINDOW + GRADEABLE_GOLD2, symbol="EURUSD.G1",
               leg="gold1_m1_ohlc")
    assert r["outcome"] == gs.STAGE5_OUTCOME_INSUFFICIENT_FIXTURE_HISTORY


def test_model_mismatch_fails():
    # requested 1 minute OHLC; the window states every tick
    r = _grade(GOLD2_WINDOW + _G2_MODEL_EVERY_TICK + "\n", model=1)
    assert r["outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV
    assert r["ok"] is False
    assert r["failed_checks"] == ["model_matches_requested"]
    assert "MT5 stated Every tick" in r["reason"]


def test_real_math_mode_leg_requested_real_ticks_does_not_pass():
    # the measured DEFECT-1 shape: Model=4 requested, MT5 ran math calculations
    r = _grade(_G1_MATH_MODE + "\n", symbol="EURUSD.G1", model=4,
               leg="gold1_real_ticks")
    assert r["ok"] is False
    assert r["parsed"]["actual_model"] == 3
    assert "model_matches_requested" in r["failed_checks"]


def test_two_different_models_for_the_symbol_is_a_conflict_not_a_pick():
    window = GOLD2_WINDOW + _G2_MODEL_M1_OHLC + "\n" + _G2_MODEL_EVERY_TICK
    r = _grade(window, model=1)
    assert r["parsed"]["actual_model"] is None
    assert r["parsed"]["model_conflict"] is True
    assert r["ok"] is False


def test_missing_history_quality_fails():
    window = _lines(_G2_BARS, _G2_FINISHED, _G2_MODEL_M1_OHLC)
    r = _grade(window)
    assert r["parsed"]["history_quality"] is None
    assert r["failed_checks"] == ["history_quality_present"]
    assert r["outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV


def test_missing_successfully_finished_fails():
    window = _lines(_G2_QUALITY, _G2_BARS, _G2_MODEL_M1_OHLC)
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
    window = GRADEABLE_GOLD2 + _EA_DEAL_OPEN + "\n"
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
    assert doc["final_balance"] is None


def test_no_trade_list_for_a_leg_that_did_not_pass_from_log():
    assert tlg.log_trade_list(_grade(GOLD2_WINDOW), b"") is None
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
    window.write_text(GRADEABLE_GOLD2 + _EA_DEAL_OPEN + "\n", encoding="utf-8")
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
    window.write_text(GOLD2_WINDOW, encoding="utf-8")
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
