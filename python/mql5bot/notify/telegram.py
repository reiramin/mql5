"""mql5bot.notify.telegram — a Telegram alert CHANNEL for the Watchdog.

This is a channel that satisfies the EXISTING contract in
``mql5bot.discovery.safety.Watchdog`` — ``channel: Callable[[dict], None]``.
It is NOT a second alerting system: it adds no monitoring, no alert logic, and
does not reimplement Watchdog's per-kind rate limiting. Watchdog calls it with
an alert dict; this channel formats and delivers it to Telegram.

Design constraints this module MUST honour (Feature Wave 2, commit 1):

  * Credentials come from the ENVIRONMENT ONLY — ``MQL5BOT_TELEGRAM_BOT_TOKEN``
    and ``MQL5BOT_TELEGRAM_CHAT_ID``. Never a CLI argument, config file,
    default, or literal. A missing variable fails construction naming the
    variable and NOT its value.
  * SECRET REDACTION is a hard requirement. The bot token is IN THE URL
    (``.../bot<TOKEN>/sendMessage``), so every urllib exception string carries
    it, and Watchdog stores channel-exception ``repr`` in ``_channel_errors``.
    Nothing leaving this module — a raised exception, a breadcrumb, a log line
    — may contain the token: it is scrubbed by VALUE (not by URL pattern,
    which the value can escape) and replaced with ``<redacted>``.
  * NEVER BLOCK the Watchdog. Watchdog's try/except guards against exceptions,
    not against a hang, so a blocking send would stop monitoring entirely.
    Every request carries a bounded timeout; on failure the channel gives up
    for that alert (no retry loop, no backoff sleep) and raises a SCRUBBED
    exception so Watchdog's breadcrumb path records it and keeps monitoring.
  * Telegram's own limits are respected with a minimum send interval enforced
    by SKIPPING (never sleeping) sends that arrive too soon. This is separate
    from Watchdog's per-kind rate limit and does not touch it.
  * The formatted message carries only the alert kind, equity, open positions
    and timestamp — never account numbers, balances, tokens, chat ids or file
    paths.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping

_LOG = logging.getLogger("mql5bot.notify.telegram")

ENV_BOT_TOKEN = "MQL5BOT_TELEGRAM_BOT_TOKEN"
ENV_CHAT_ID = "MQL5BOT_TELEGRAM_CHAT_ID"

# transport(url, data, timeout) -> None; delivers the POST or raises.
Transport = Callable[[str, bytes, float], None]


class TelegramConfigError(RuntimeError):
    """A required Telegram environment variable is missing. The message names
    the variable, NEVER its value."""


class TelegramSendError(RuntimeError):
    """A Telegram delivery failed. The message is ALWAYS token-scrubbed."""


def _scrub(text: str, secret: str) -> str:
    """Replace every occurrence of the secret VALUE with ``<redacted>``.

    Scrubbing by value (not by a URL regex) is deliberate: the token can turn
    up in text a URL pattern would not cover (a chained OS error, a proxy
    message, a partial echo). An empty secret is a no-op.
    """
    if not secret:
        return text
    return text.replace(secret, "<redacted>")


class TelegramChannel:
    """A Watchdog channel that delivers alerts to a Telegram chat.

    Construct it with the two environment variables set, then hand it to
    ``Watchdog(channel=TelegramChannel())``. ``__call__(alert)`` is the
    Watchdog contract.
    """

    def __init__(self, *,
                 env: Mapping[str, str] | None = None,
                 transport: Transport | None = None,
                 timeout: float = 5.0,
                 min_interval_seconds: float = 1.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        source = os.environ if env is None else env
        token = source.get(ENV_BOT_TOKEN)
        chat_id = source.get(ENV_CHAT_ID)
        # Fail closed naming the missing variable, NEVER its value.
        if not token:
            raise TelegramConfigError(
                f"{ENV_BOT_TOKEN} is not set — export it from the environment "
                "(never a CLI argument, config file, or literal)")
        if not chat_id:
            raise TelegramConfigError(
                f"{ENV_CHAT_ID} is not set — export it from the environment "
                "(never a CLI argument, config file, or literal)")
        self._token = token
        self._chat_id = chat_id
        # The token lives IN the URL — this string is never logged or raised
        # unscrubbed.
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._timeout = float(timeout)
        self._min_interval = float(min_interval_seconds)
        self._clock = clock
        self._transport: Transport = transport or self._default_transport
        self._last_send: float | None = None
        # scrubbed breadcrumbs of what this channel did / why a send failed
        self._log: list[str] = []

    # -- Watchdog contract --------------------------------------------------

    def __call__(self, alert: dict) -> None:
        # Minimum-interval enforcement WITHOUT blocking: a send that arrives
        # sooner than min_interval since the last attempt is skipped, never
        # slept on (a sleep here would freeze the Watchdog).
        now = self._clock()
        if self._last_send is not None and \
                (now - self._last_send) < self._min_interval:
            self._log.append(
                "skipped: min send interval not elapsed "
                f"({now - self._last_send:.3f}s < {self._min_interval:.3f}s)")
            return
        self._last_send = now
        text = self.format_alert(alert)
        data = urllib.parse.urlencode(
            {"chat_id": self._chat_id, "text": text}).encode("utf-8")
        try:
            self._transport(self._url, data, self._timeout)
        except Exception as exc:  # noqa: BLE001 — boundary: any failure, scrubbed
            scrubbed = _scrub(str(exc), self._token)
            breadcrumb = f"telegram send failed: {scrubbed}"
            self._log.append(breadcrumb)
            _LOG.warning("%s", breadcrumb)
            # Raise a fresh SCRUBBED exception with NO __cause__ chain, so the
            # token cannot leak via the original exception's repr/traceback.
            # Watchdog stores repr(exc) — of THIS scrubbed exception — as a
            # breadcrumb and keeps monitoring.
            raise TelegramSendError(breadcrumb) from None
        self._log.append(f"sent: {alert.get('watchdog_alert', 'alert')}")

    # -- message formatting -------------------------------------------------

    def format_alert(self, alert: Mapping[str, object]) -> str:
        """A short operator message. Carries ONLY alert kind, equity, open
        positions and timestamp — never account numbers, balances, tokens,
        chat ids or file paths."""
        kind = alert.get("watchdog_alert", "alert")
        equity = alert.get("equity")
        positions = alert.get("open_positions")
        ts = alert.get("ts")
        when = self._iso(ts)
        # Persian labels alongside the (Latin, copyable) values.
        lines = [
            "⚠️ Mql5Bot هشدار / watchdog alert",
            f"نوع (kind): {kind}",
            f"سرمایه (equity): {equity}",
            f"موقعیت‌ها (open positions): {positions}",
            f"زمان (time): {when}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _iso(ts: object) -> str:
        try:
            return _dt.datetime.fromtimestamp(
                float(ts), tz=_dt.timezone.utc).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            return str(ts)

    # -- default transport --------------------------------------------------

    def _default_transport(self, url: str, data: bytes, timeout: float) -> None:
        """POST to Telegram with a bounded timeout. Any urllib error (which
        embeds the token-bearing URL) is caught and SCRUBBED by ``__call__``;
        this method itself never logs the URL."""
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()


__all__ = [
    "ENV_BOT_TOKEN",
    "ENV_CHAT_ID",
    "TelegramChannel",
    "TelegramConfigError",
    "TelegramSendError",
]
