"""Tests for mql5bot.notify.telegram — the Watchdog Telegram alert channel.

These tests NEVER touch the network: the transport is injected, and every case
passes a fake. They pin the hard requirements of Feature Wave 2 commit 1:
env-only credentials, token redaction everywhere secrets could leak, a
non-blocking bounded send, minimum-interval enforcement, and that a failing
channel never stops the Watchdog from returning its alerts.
"""

from __future__ import annotations

import logging

import pytest
from mql5bot.discovery.safety import Watchdog, WatchdogObservation
from mql5bot.notify.telegram import (
    ENV_BOT_TOKEN,
    ENV_CHAT_ID,
    TelegramChannel,
    TelegramConfigError,
    TelegramSendError,
)

# A recognisable fake token; it must appear NOWHERE that leaves the module.
FAKE_TOKEN = "123456789:AAF-FAKE-TOKEN-do-not-leak-me"
FAKE_CHAT = "-1009876543210"
ENV = {ENV_BOT_TOKEN: FAKE_TOKEN, ENV_CHAT_ID: FAKE_CHAT}
ALERT = {"watchdog_alert": "daily DD 22.0%", "ts": 1_700_000_000.0,
         "equity": 9500.0, "open_positions": 2}


class _FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


# ---------------------------------------------------------------------------
# credentials come from the environment ONLY; missing var names itself, not
# its value
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing", [ENV_BOT_TOKEN, ENV_CHAT_ID])
def test_missing_env_var_fails_naming_the_variable_not_its_value(missing):
    env = dict(ENV)
    del env[missing]
    with pytest.raises(TelegramConfigError) as exc:
        TelegramChannel(env=env, transport=lambda *a: None)
    msg = str(exc.value)
    assert missing in msg              # the variable is named
    # the surviving credential's VALUE never appears in the error
    survivor = FAKE_CHAT if missing == ENV_BOT_TOKEN else FAKE_TOKEN
    assert survivor not in msg


def test_empty_env_var_is_treated_as_missing():
    env = {ENV_BOT_TOKEN: "", ENV_CHAT_ID: FAKE_CHAT}
    with pytest.raises(TelegramConfigError, match=ENV_BOT_TOKEN):
        TelegramChannel(env=env, transport=lambda *a: None)


# ---------------------------------------------------------------------------
# successful send
# ---------------------------------------------------------------------------

def test_successful_send_calls_transport_once_with_bounded_timeout():
    calls = []

    def transport(url, data, timeout):
        calls.append((url, data, timeout))

    ch = TelegramChannel(env=ENV, transport=transport, timeout=5.0)
    ch(ALERT)
    assert len(calls) == 1
    url, data, timeout = calls[0]
    assert url.endswith("/sendMessage") and FAKE_TOKEN in url  # internal only
    assert timeout == 5.0
    body = data.decode("utf-8")
    assert "chat_id=" in body and "text=" in body


def test_message_carries_only_permitted_fields():
    captured = {}

    def transport(url, data, timeout):
        captured["body"] = data.decode("utf-8")

    ch = TelegramChannel(env=ENV, transport=transport)
    text = ch.format_alert(ALERT)
    # permitted: kind, equity, open positions, timestamp
    assert "daily DD 22.0%" in text
    assert "9500.0" in text
    assert "open positions): 2" in text
    assert "2023-11-14" in text          # ISO timestamp of ts
    # forbidden: token, chat id, file paths
    assert FAKE_TOKEN not in text
    assert FAKE_CHAT not in text
    ch(ALERT)
    # the chat id travels ONLY as the urlencoded chat_id form field, never in
    # the human text
    assert "text=" in captured["body"]


# ---------------------------------------------------------------------------
# never block; on failure give up for this alert and raise SCRUBBED
# ---------------------------------------------------------------------------

def test_timeout_failure_is_scrubbed_and_raised():
    def transport(url, data, timeout):
        # urllib embeds the token-bearing URL in its error text
        raise TimeoutError(f"connection to {url} timed out")

    ch = TelegramChannel(env=ENV, transport=transport)
    with pytest.raises(TelegramSendError) as exc:
        ch(ALERT)
    assert FAKE_TOKEN not in str(exc.value)
    assert "<redacted>" in str(exc.value)


def test_http_error_failure_is_scrubbed_and_raised():
    def transport(url, data, timeout):
        raise OSError(f"HTTP Error 401: Unauthorized for {url}")

    ch = TelegramChannel(env=ENV, transport=transport)
    with pytest.raises(TelegramSendError) as exc:
        ch(ALERT)
    assert FAKE_TOKEN not in str(exc.value)


# ---------------------------------------------------------------------------
# THE required redaction test: the token appears in NONE of the raised
# message, the breadcrumb, or the log line. Removing the scrub breaks it.
# ---------------------------------------------------------------------------

def test_token_is_redacted_in_exception_breadcrumb_and_log(caplog):
    def transport(url, data, timeout):
        raise TimeoutError(f"failed talking to {url}")

    ch = TelegramChannel(env=ENV, transport=transport)
    with caplog.at_level(logging.WARNING, logger="mql5bot.notify.telegram"), \
            pytest.raises(TelegramSendError) as exc:
        ch(ALERT)

    # (1) the raised message
    assert FAKE_TOKEN not in str(exc.value)
    # (2) the channel breadcrumb
    assert FAKE_TOKEN not in "\n".join(ch._log)
    assert any("<redacted>" in line for line in ch._log)
    # (3) the log line
    assert FAKE_TOKEN not in caplog.text
    assert "<redacted>" in caplog.text
    # and the token does not leak via a chained cause's traceback either
    assert exc.value.__cause__ is None


def test_scrub_replaces_the_token_value_not_just_a_url_pattern():
    from mql5bot.notify.telegram import _scrub
    # the token can appear in text no URL regex would cover
    leaked = f"proxy rejected credential {FAKE_TOKEN} (bad auth)"
    scrubbed = _scrub(leaked, FAKE_TOKEN)
    assert FAKE_TOKEN not in scrubbed
    assert scrubbed == "proxy rejected credential <redacted> (bad auth)"


# ---------------------------------------------------------------------------
# minimum send interval — enforced by SKIPPING, never sleeping
# ---------------------------------------------------------------------------

def test_minimum_interval_skips_a_too_soon_send_without_blocking():
    clock = _FakeClock(100.0)
    calls = []
    ch = TelegramChannel(env=ENV, transport=lambda *a: calls.append(a),
                         min_interval_seconds=1.0, clock=clock)
    ch(ALERT)                    # t=100.0 -> sent
    assert len(calls) == 1
    clock.t = 100.5             # 0.5s later -> skipped (no sleep, no send)
    ch(ALERT)
    assert len(calls) == 1
    assert any("skipped" in line for line in ch._log)
    clock.t = 101.6             # 1.1s after the first send -> sent again
    ch(ALERT)
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# a failing channel must NEVER stop the Watchdog from returning its alerts,
# and the Watchdog breadcrumb it stores must also be token-free
# ---------------------------------------------------------------------------

def test_failing_channel_does_not_stop_watchdog_and_breadcrumb_is_scrubbed():
    def transport(url, data, timeout):
        raise TimeoutError(f"cannot reach {url}")

    ch = TelegramChannel(env=ENV, transport=transport)
    wd = Watchdog(channel=ch, max_dd_pct=20.0)
    obs = WatchdogObservation(equity=9500.0, daily_dd_pct=22.0,
                              open_positions=2, trades_last_hour=1,
                              heartbeat_age_seconds=1.0)
    alerts = wd.check(obs)
    # the Watchdog still produced its alert despite the channel raising
    assert any("daily DD" in a for a in alerts)
    # and it recorded the delivery failure as a breadcrumb...
    assert wd._channel_errors
    # ...whose stored repr(exc) carries NO token (the channel scrubbed it)
    assert FAKE_TOKEN not in repr(wd._channel_errors)


def test_working_channel_delivers_through_watchdog():
    sent = []
    ch = TelegramChannel(env=ENV, transport=lambda *a: sent.append(a))
    wd = Watchdog(channel=ch, max_dd_pct=20.0)
    obs = WatchdogObservation(equity=9500.0, daily_dd_pct=22.0,
                              open_positions=2, trades_last_hour=1,
                              heartbeat_age_seconds=1.0)
    wd.check(obs)
    assert len(sent) == 1
    assert not wd._channel_errors
