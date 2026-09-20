"""Tests for the Telegram operator surface (mql5bot.notify.telegram_ops).

Every test injects the transport and the clock — nothing here touches the
network. The load-bearing test is the asymmetric-friction one: no inbound
message can re-enable a stopped system.
"""

from __future__ import annotations

import datetime as _dt
import inspect
import urllib.parse

import pytest
from mql5bot.discovery.safety import KillSwitch, KillSwitchState
from mql5bot.notify import telegram_ops
from mql5bot.notify.telegram import ENV_BOT_TOKEN, ENV_CHAT_ID, TelegramChannel
from mql5bot.notify.telegram_ops import (
    COMMANDS,
    ENV_ALLOWED_CHATS,
    OpenPosition,
    OpsState,
    TelegramOperator,
)

FAKE_TOKEN = "123456789:AAF-FAKE-TOKEN-do-not-leak-me"
FAKE_CHAT = "555000555"
ALLOWED_CHAT = "111222333"
CHAN_ENV = {ENV_BOT_TOKEN: FAKE_TOKEN, ENV_CHAT_ID: FAKE_CHAT}
UTC = _dt.timezone.utc


def _capturing_channel():
    """A real TelegramChannel with an injected transport that records the
    decoded message text. min_interval 0 so every send goes through."""
    sent: list[str] = []

    def transport(url, data, timeout):
        fields = urllib.parse.parse_qs(data.decode("utf-8"))
        sent.append(fields["text"][0])

    channel = TelegramChannel(
        env=CHAN_ENV, transport=transport, min_interval_seconds=0.0)
    return channel, sent


def _state(**kw) -> OpsState:
    base = {
        "alive": True,
        "trades_today": 3,
        "realised_pnl_today": 12.5,
        "open_positions": (OpenPosition("EURUSD", "buy", 0.10),),
        "drawdown_limit_pct": 6.0,
        "drawdown_used_pct": 1.5,
    }
    base.update(kw)
    return OpsState(**base)


def _operator(channel, *, state=None, per_trade=True, allow=ALLOWED_CHAT):
    state = state if state is not None else _state()
    ks = KillSwitch()
    op = TelegramOperator(
        channel=channel,
        kill_switch=ks,
        state_provider=lambda: state,
        env={ENV_ALLOWED_CHATS: allow},
        per_trade=per_trade,
    )
    return op, ks


def test_per_trade_notification_sent_when_enabled():
    channel, sent = _capturing_channel()
    op, _ks = _operator(channel, per_trade=True)
    assert op.on_trade_event(
        {"event": "trade", "action": "open", "symbol": "EURUSD",
         "lots": 0.10, "pnl": None}) is True
    assert len(sent) == 1
    assert "EURUSD" in sent[0]
    assert "open" in sent[0]


def test_per_trade_off_suppresses_trade_but_alerts_still_flow():
    channel, sent = _capturing_channel()
    op, _ks = _operator(channel, per_trade=False)
    assert op.on_trade_event(
        {"event": "trade", "action": "close", "symbol": "EURUSD",
         "lots": 0.10}) is False
    assert sent == []
    # The underlying alert channel is untouched and still delivers.
    channel({"watchdog_alert": "heartbeat stale", "equity": 1000,
             "open_positions": 1, "ts": 0})
    assert len(sent) == 1
    assert "watchdog" in sent[0].lower()


def test_status_command_reads_state():
    channel, sent = _capturing_channel()
    op, _ks = _operator(channel)
    reply = op.on_command(ALLOWED_CHAT, "status")
    assert reply is not None
    assert len(sent) == 1
    # distance = 6.0 - 1.5 = 4.5
    assert "4.5" in reply


def test_positions_command_lists_open_positions():
    channel, _sent = _capturing_channel()
    op, _ks = _operator(channel)
    reply = op.on_command(ALLOWED_CHAT, "positions")
    assert "EURUSD" in reply
    assert "0.1" in reply


def test_report_command_matches_digest():
    channel, _sent = _capturing_channel()
    op, _ks = _operator(channel)
    reply = op.on_command(ALLOWED_CHAT, "report")
    assert "12.5" in reply  # realised P&L today
    assert reply == op.digest_text()


def test_stop_trips_killswitch_immediately_and_blocks_new_trades():
    channel, _sent = _capturing_channel()
    op, ks = _operator(channel)
    assert ks.may_open_new_trades() is True
    reply = op.on_command(ALLOWED_CHAT, "stop")
    assert reply is not None
    assert ks.state is KillSwitchState.EMERGENCY_HALT
    assert ks.may_open_new_trades() is False


def test_unauthorised_chat_is_ignored_without_echo(caplog):
    channel, sent = _capturing_channel()
    op, ks = _operator(channel)
    secret_text = "stop please SUPERSECRETPAYLOAD"
    with caplog.at_level("WARNING"):
        reply = op.on_command("999888777", secret_text)
    assert reply is None
    assert sent == []          # nothing delivered
    # neither the message content nor the chat id is echoed into the log
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "SUPERSECRETPAYLOAD" not in joined
    assert "999888777" not in joined
    # and the kill switch was NOT affected by an outsider's "stop"
    assert ks.may_open_new_trades() is True


def test_no_inbound_message_can_re_enable_a_stopped_system():
    channel, _sent = _capturing_channel()
    op, ks = _operator(channel)
    op.on_command(ALLOWED_CHAT, "stop")
    assert ks.state is KillSwitchState.EMERGENCY_HALT
    # Try every re-enabling word we can think of, from the allow-listed chat.
    for attempt in ("start", "resume", "go", "run", "enable", "on", "status"):
        op.on_command(ALLOWED_CHAT, attempt)
        assert ks.state is KillSwitchState.EMERGENCY_HALT
        assert ks.may_open_new_trades() is False
    # There is no resume/start command, and the code never resets the switch
    # (a reset is a console action, off the phone). These patterns match CALLS,
    # not the docstring's prose mention of the concept.
    assert "resume" not in COMMANDS
    assert "start" not in COMMANDS
    src = inspect.getsource(telegram_ops)
    assert "explicit_reset(" not in src
    assert "KillSwitchState" not in src
    assert "manual_start" not in src


def test_no_message_contains_secrets():
    channel, sent = _capturing_channel()
    op, _ks = _operator(channel)
    op.on_command(ALLOWED_CHAT, "status")
    op.on_command(ALLOWED_CHAT, "positions")
    op.on_command(ALLOWED_CHAT, "report")
    op.on_command(ALLOWED_CHAT, "stop")
    op.on_trade_event({"event": "trade", "action": "open", "symbol": "EURUSD",
                       "lots": 0.1})
    for msg in sent:
        assert FAKE_TOKEN not in msg
        assert FAKE_CHAT not in msg
        assert ALLOWED_CHAT not in msg
        assert "/Users/" not in msg
        assert "/home/" not in msg


def test_digest_sent_once_per_local_day_at_configured_time():
    channel, sent = _capturing_channel()
    op, _ks = _operator(channel)
    op._digest_h, op._digest_m = 22, 0
    # before the configured time: nothing
    assert op.maybe_send_digest(_dt.datetime(2026, 9, 20, 21, 59, tzinfo=UTC)) is False
    assert sent == []
    # at/after: one send
    assert op.maybe_send_digest(_dt.datetime(2026, 9, 20, 22, 0, tzinfo=UTC)) is True
    assert len(sent) == 1
    # same day again: no duplicate
    assert op.maybe_send_digest(_dt.datetime(2026, 9, 20, 23, 30, tzinfo=UTC)) is False
    assert len(sent) == 1
    # next day: one more
    assert op.maybe_send_digest(_dt.datetime(2026, 9, 21, 22, 5, tzinfo=UTC)) is True
    assert len(sent) == 2


def test_commands_are_read_or_stop_only():
    # The surface exposes exactly the four documented commands, none of which
    # can start trading.
    assert set(COMMANDS) == {"status", "positions", "report", "stop"}


@pytest.mark.parametrize("word", ["start", "resume"])
def test_start_and_resume_are_not_commands(word):
    assert word not in COMMANDS
