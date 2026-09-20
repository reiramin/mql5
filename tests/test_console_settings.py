"""Console v2 — settings & health checklist.

Environment variable NAMES are shown, never values; sources that are not
connected say so; the whole page reads top to bottom for a non-developer.
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient
from mql5bot.api.main import create_app
from mql5bot.factory.store import FactoryStore

SECRET_TOKEN = "super-secret-console-token"
SECRET_TG = "123456789:AAF-telegram-secret"


def _client(tmp_path, **kw):
    store = FactoryStore(tmp_path / "api.db")
    return store, TestClient(create_app(store, **kw))


def test_settings_shows_names_never_values(tmp_path):
    env = {
        "MQL5BOT_CONSOLE_TOKEN": SECRET_TOKEN,
        "MQL5BOT_TELEGRAM_BOT_TOKEN": SECRET_TG,
        "MQL5BOT_TELEGRAM_CHAT_ID": "987654321",
    }
    _, c = _client(tmp_path, console_env=env, console_token=SECRET_TOKEN)
    c.post("/login", data={"token": SECRET_TOKEN})
    page = c.get("/settings")
    assert page.status_code == 200
    # names present
    assert "MQL5BOT_CONSOLE_TOKEN" in page.text
    assert "MQL5BOT_TELEGRAM_BOT_TOKEN" in page.text
    # values ABSENT
    assert SECRET_TOKEN not in page.text
    assert SECRET_TG not in page.text
    assert "987654321" not in page.text
    # states named
    assert "SET" in page.text
    assert "both SET" in page.text            # telegram configured


def test_settings_honest_when_nothing_configured(tmp_path):
    _, c = _client(tmp_path, console_env={})
    page = c.get("/settings")
    assert "NOT SET" in page.text
    assert "not configured" in page.text      # telemetry + evidence dir
    assert "not connected" in page.text       # MT5 last seen
    assert "loopback-only mode" in page.text  # auth not configured


def test_settings_mt5_last_seen_from_heartbeat(tmp_path):
    log = tmp_path / "telemetry.jsonl"
    log.write_text(json.dumps({
        "event": "heartbeat", "received_at": time.time()}) + "\n",
        encoding="utf-8")
    _, c = _client(tmp_path,
                   console_env={"MQL5BOT_TELEMETRY_LOG": str(log)})
    page = c.get("/settings")
    assert "UTC" in page.text                 # a real last-seen timestamp


def test_settings_evidence_dir_missing_summary_is_flagged(tmp_path):
    ev = tmp_path / "ev"
    ev.mkdir()
    _, c = _client(tmp_path,
                   console_env={"MQL5BOT_EVIDENCE_DIR": str(ev)})
    page = c.get("/settings")
    assert "gate_summary.json MISSING" in page.text


def test_settings_renders_in_persian(tmp_path):
    _, c = _client(tmp_path, console_env={})
    fa = c.get("/settings?lang=fa")
    assert 'dir="rtl"' in fa.text
    assert "تنظیمات و سلامت" in fa.text