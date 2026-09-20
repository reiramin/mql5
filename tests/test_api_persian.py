"""Tests for the Persian/RTL operator status page (opt-in) on the console.

English stays the default; Persian is reached with ``?lang=fa`` exactly as
the console i18n layer selects language elsewhere.  The English board now
renders on the shared offline base.html shell (the legacy CDN template was
retired), so these tests pin the shell's English defaults rather than the
pre-shell bytes.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from mql5bot.api.main import create_app
from mql5bot.factory.store import FactoryStore
from mql5bot.notify.telegram_ops import OpenPosition, OpsState


def _client(tmp_path, **kw):
    store = FactoryStore(tmp_path / "api.db")
    return store, TestClient(create_app(store, **kw))


def test_english_default_renders_ltr_kanban(tmp_path):
    # Deliberate change with the CDN removal: the English board moved onto
    # the base.html shell, so the html tag now carries dir="ltr" explicitly.
    _, c = _client(tmp_path)
    r = c.get("/")
    assert r.status_code == 200
    assert '<html lang="en" dir="ltr">' in r.text
    assert 'dir="rtl"' not in r.text
    assert "SHADOW" in r.text                 # English kanban still rendered
    assert "هنوز اثبات‌نشده" not in r.text     # no Persian leaks into default


def test_persian_board_is_rtl_and_answers_three_questions(tmp_path):
    _, c = _client(tmp_path)
    r = c.get("/?lang=fa")
    assert r.status_code == 200
    assert 'dir="rtl"' in r.text
    assert 'lang="fa"' in r.text
    assert "زنده است؟" in r.text        # alive?
    assert "فعالیت امروز" in r.text      # today's activity
    assert "فاصله تا حد ضرر" in r.text   # distance to loss limit


def test_kill_switch_control_is_on_the_page(tmp_path):
    _, c = _client(tmp_path)
    r = c.get("/?lang=fa")
    assert 'action="/safety/killswitch/reset"' in r.text


def test_unproven_line_sourced_from_status_model(tmp_path):
    _, c = _client(tmp_path)
    r = c.get("/?lang=fa")
    # the certification term is shown VERBATIM, never translated away
    assert "EMPIRICAL_VALIDATION_PENDING" in r.text
    assert "NOT VERIFIED" in r.text


def test_latin_identifiers_are_bidi_isolated(tmp_path):
    _, c = _client(tmp_path)
    r = c.get("/?lang=fa")
    assert "\u2066" in r.text  # LRI — Latin runs isolated via i18n.isolate_ltr


def test_no_live_state_is_reported_honestly_not_faked(tmp_path):
    _, c = _client(tmp_path)
    r = c.get("/?lang=fa")
    assert "not connected" in r.text  # honest when no telemetry is wired


def test_live_state_answers_when_connected(tmp_path):
    state = OpsState(
        alive=True, trades_today=2, realised_pnl_today=5.0,
        open_positions=(OpenPosition("EURUSD", "buy", 0.1),),
        drawdown_limit_pct=6.0, drawdown_used_pct=2.0)
    _, c = _client(tmp_path, live_state=lambda: state)
    r = c.get("/?lang=fa")
    assert "4.0" in r.text          # distance = 6.0 - 2.0, shown as Latin digits
    assert "not connected" not in r.text
