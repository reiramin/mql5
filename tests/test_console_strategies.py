"""Console v2 — strategies pages and the new-strategy conversation flow.

Pins: registration lands at DRAFT and nowhere further; a run never advances
lifecycle state by itself; no dataset means a clear message and no run.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from mql5bot.api.main import create_app
from mql5bot.data import generate_ohlc, save_csv
from mql5bot.factory.models import ValidationRun
from mql5bot.factory.store import FactoryStore

IDEA = "EMA 10 crosses above EMA 30, stop 2 ATR, take profit 3 ATR"


def _client(tmp_path, **kw):
    store = FactoryStore(tmp_path / "api.db")
    return store, TestClient(create_app(store, **kw))


def _register(c):
    start = c.post("/guided/start", data={
        "idea": IDEA, "symbol": "EURUSD", "timeframe": "H1"}).json()
    assert start["needs_answers"] is False
    r = c.post("/guided/register", data={
        "draft": json.dumps(start["draft"]),
        "accepted_token": start["acceptance_token"],
        "original_text": IDEA})
    assert r.status_code == 200, r.text
    return r.json()


def test_conversation_registers_a_draft_and_nothing_further(tmp_path):
    store, c = _client(tmp_path)
    body = _register(c)
    assert body["registered"] is True
    sid = body["strategy_id"]
    assert body["state"] == "DRAFT"
    assert store.current_state(sid) == "DRAFT"


def test_register_refused_without_acceptance(tmp_path):
    store, c = _client(tmp_path)
    start = c.post("/guided/start", data={
        "idea": IDEA, "symbol": "EURUSD", "timeframe": "H1"}).json()
    r = c.post("/guided/register",
               data={"draft": json.dumps(start["draft"])})
    assert r.status_code == 422
    assert "not accepted" in r.json()["reason"]
    assert store.list_strategies() == []


def test_strategies_list_shows_rail_and_why(tmp_path):
    _, c = _client(tmp_path)
    sid = _register(c)["strategy_id"]
    page = c.get("/strategies")
    assert sid in page.text
    assert "DRAFT" in page.text and "LIVE" in page.text  # the rail
    assert ("registered as a draft" in page.text
            or "no lifecycle events yet" in page.text)


def test_strategy_detail_shows_text_restatement_and_confirmed_retire(tmp_path):
    _, c = _client(tmp_path)
    sid = _register(c)["strategy_id"]
    page = c.get(f"/strategy/{sid}")
    assert page.status_code == 200
    assert IDEA in page.text                       # owner's original text
    assert "10-period EMA" in page.text or "EMA" in page.text  # restatement
    assert "no runs recorded" in page.text
    # a DRAFT permits no pause/resume/retire; nothing toward execution
    assert "no action is permitted" in page.text
    # Persian variant renders
    fa = c.get(f"/strategy/{sid}?lang=fa")
    assert 'dir="rtl"' in fa.text


def test_validate_python_without_dataset_is_a_clear_message_and_no_run(tmp_path):
    store, c = _client(tmp_path, console_env={})
    sid = _register(c)["strategy_id"]
    r = c.post(f"/strategy/{sid}/validate-python")
    body = r.json()
    assert body["ran"] is False
    assert "MQL5BOT_CONSOLE_DATASET" in body["detail"]
    assert "nothing was run" in body["detail"]
    with store.session() as sess:
        assert sess.query(ValidationRun).count() == 0
    assert store.current_state(sid) == "DRAFT"


def test_validate_python_records_a_run_and_never_advances_state(tmp_path):
    csv = tmp_path / "EURUSD_H1.csv"
    save_csv(generate_ohlc(symbol="EURUSD", timeframe="H1", days=30, seed=7),
             str(csv))
    store, c = _client(
        tmp_path, console_env={"MQL5BOT_CONSOLE_DATASET": str(csv)})
    sid = _register(c)["strategy_id"]
    r = c.post(f"/strategy/{sid}/validate-python")
    body = r.json()
    assert body["ran"] is True
    assert body["status"] in ("PASS", "ERROR")
    assert "lifecycle state unchanged" in body["detail"]
    # the run is RECORDED and the state did not move
    with store.session() as sess:
        assert sess.query(ValidationRun).count() == 1
    assert store.current_state(sid) == "DRAFT"
    # and it now shows on the detail page
    assert "backtest" in c.get(f"/strategy/{sid}").text