"""Console v2 — trades page (telemetry JSONL) and the certification rail.

The certification page is read-only and renders the gate's own files
(gate_summary.json + per-leg outcome JSONs) — never an invented status.
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient
from mql5bot.api.main import create_app
from mql5bot.factory.store import FactoryStore
from mql5bot.notify.telegram_ops import OpenPosition, OpsState


def _client(tmp_path, **kw):
    store = FactoryStore(tmp_path / "api.db")
    return store, TestClient(create_app(store, **kw))


def _write_jsonl(path, events):
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(e) + "\n" for e in events)


def test_trades_history_pages_from_the_jsonl(tmp_path):
    log = tmp_path / "telemetry.jsonl"
    now = time.time()
    events = [{"event": "trade", "symbol": "EURUSD", "action": "close",
               "lots": 0.1, "pnl": i, "received_at": now - i * 60}
              for i in range(60)]
    _write_jsonl(log, events)
    _, c = _client(tmp_path,
                   console_env={"MQL5BOT_TELEMETRY_LOG": str(log)})
    page0 = c.get("/trades")
    assert "EURUSD" in page0.text
    assert "older" in page0.text          # more than one page of history
    page1 = c.get("/trades?page=1")
    assert page1.status_code == 200
    assert "newer" in page1.text


def test_trades_today_section_and_distance_beside_pnl(tmp_path):
    log = tmp_path / "telemetry.jsonl"
    _write_jsonl(log, [{"event": "trade", "symbol": "EURUSD",
                        "action": "close", "lots": 0.1, "pnl": 2.5,
                        "received_at": time.time()}])
    state = OpsState(alive=True, trades_today=1, realised_pnl_today=2.5,
                     open_positions=(OpenPosition("EURUSD", "buy", 0.1),),
                     drawdown_limit_pct=6.0, drawdown_used_pct=1.0)
    _, c = _client(tmp_path,
                   console_env={"MQL5BOT_TELEMETRY_LOG": str(log)},
                   live_state=lambda: state)
    page = c.get("/trades")
    # P&L never without the distance to the loss limit beside it
    assert "2.5" in page.text
    assert "5.0 pct" in page.text          # 6.0 - 1.0
    assert "distance to loss limit" in page.text


def test_trades_empty_when_log_not_configured(tmp_path):
    _, c = _client(tmp_path, console_env={})
    page = c.get("/trades")
    assert "not connected" in page.text or "not configured" in page.text


def _fake_evidence(tmp_path):
    ev = tmp_path / "gate"
    ev.mkdir()
    stages = [
        {"stage": 0, "name": "self_protection", "status": "PASS",
         "reason": "anchor ok", "artifacts": []},
        {"stage": 5, "name": "tester_legs", "status": "FAIL",
         "reason": "gold1_m1_ohlc: exit 2; FAIL_INSUFFICIENT_FIXTURE_HISTORY",
         "artifacts": [{"sha256": "ab" * 32, "path": "tester_x.txt"}]},
    ]
    (ev / "gate_summary.json").write_text(json.dumps({
        "gate": "owner_mt5_certification", "gate_result": "tester_legs",
        "first_blocking": "tester_legs", "stages": stages}), encoding="utf-8")
    # a per-leg outcome JSON exactly as gate_selfcheck writes it
    (ev / "leg_outcome_gold1_m1_ohlc.json").write_text(json.dumps({
        "outcome": "FAIL_INSUFFICIENT_FIXTURE_HISTORY", "ok": False,
        "blocked": False, "bars_generated": 0, "test_finished": False,
        "evidence_lines": [
            "EURUSD.G1,H1: 0 ticks, 0 bars generated"],
        "reason": "FAIL_INSUFFICIENT_FIXTURE_HISTORY — zero bars",
        "leg": "gold1_m1_ohlc"}), encoding="utf-8")
    (ev / "leg_outcome_gold2_m1_ohlc.json").write_text(json.dumps({
        "outcome": "BLOCKED_OWNER_ENVIRONMENT", "ok": False, "blocked": True,
        "bars_generated": 2880, "test_finished": True,
        "evidence_lines": [
            "EURUSD.G2,M1: 11520 ticks, 2880 bars generated"],
        "reason": "BLOCKED_OWNER_ENVIRONMENT — NOT a pass",
        "leg": "gold2_m1_ohlc"}), encoding="utf-8")
    return ev


def test_certification_rail_renders_stages_legs_and_not_run(tmp_path):
    ev = _fake_evidence(tmp_path)
    _, c = _client(tmp_path,
                   console_env={"MQL5BOT_EVIDENCE_DIR": str(ev)})
    page = c.get("/certification")
    assert page.status_code == 200
    # gate verdict + recorded stages
    assert "GATE_RESULT=tester_legs" in page.text
    assert "self_protection" in page.text and "PASS" in page.text
    assert "tester_legs" in page.text and "FAIL" in page.text
    # stages the gate never reached are shown NOT RUN, never blank
    assert "NOT RUN" in page.text
    assert "reconciliation" in page.text and "certify" in page.text
    # per-leg verdicts with their quoted log lines
    assert "gold1_m1_ohlc" in page.text
    assert "FAIL_INSUFFICIENT_FIXTURE_HISTORY" in page.text
    assert "0 ticks, 0 bars generated" in page.text
    assert "BLOCKED_OWNER_ENVIRONMENT" in page.text
    assert "2880 bars generated" in page.text
    # artifact hash surfaced
    assert "ab" * 32 in page.text
    # read-only, and says so
    assert "READ-ONLY" in page.text


def test_certification_persian_keeps_terms_verbatim(tmp_path):
    ev = _fake_evidence(tmp_path)
    _, c = _client(tmp_path,
                   console_env={"MQL5BOT_EVIDENCE_DIR": str(ev)})
    fa = c.get("/certification?lang=fa")
    assert "BLOCKED_OWNER_ENVIRONMENT" in fa.text   # verbatim, never replaced
    assert 'dir="rtl"' in fa.text


def test_certification_missing_summary_is_an_error_not_a_guess(tmp_path):
    ev = tmp_path / "empty"
    ev.mkdir()
    _, c = _client(tmp_path,
                   console_env={"MQL5BOT_EVIDENCE_DIR": str(ev)})
    page = c.get("/certification")
    assert "gate_summary.json not found" in page.text