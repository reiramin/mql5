"""mql5bot.notify.telegram_ops — the Telegram OPERATOR surface.

Phase 1 of ``docs/ROADMAP_UX.md``: turn the existing alert channel into the
owner's primary interface. This module adds, on top of the EXISTING
``TelegramChannel`` (which it reuses for delivery — same bounded timeout, same
minimum-send interval, same by-value token scrubbing; NO second notifier and NO
duplicated rate limiting):

  * per-trade open/close notifications, toggleable, so the digest can stand
    alone while alerts keep flowing;
  * a daily digest at a configured local time — alive/not, trades today,
    realised P&L today, open positions, and the distance to the drawdown limit;
  * the four read-or-stop commands ``status``, ``positions``, ``report`` and
    ``stop``, each reading injected state and never inventing it.

ASYMMETRIC FRICTION — the binding rule (``docs/ROADMAP_UX.md`` Phase 1):
stopping is immediate and unconfirmed; **there is no resume**. No inbound
Telegram message — not ``start``, not ``resume``, not any word — has a code
path that can re-enable a stopped system. This module never calls
``KillSwitch.explicit_reset`` and never sets ``NORMAL``; leaving a halt is a
console action, off the phone entirely. A lost, unlocked phone can only ever
STOP the bot.

Privacy: no account number, token, chat id, or file path appears in any
message this module sends. An inbound message from a chat id that is not on the
allow-list is ignored and logged WITHOUT echoing its content.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from ..discovery.safety import KillSwitch
from .telegram import TelegramChannel

_LOG = logging.getLogger("mql5bot.notify.telegram_ops")

# comma-separated allow-list of chat ids permitted to send commands
ENV_ALLOWED_CHATS = "MQL5BOT_TELEGRAM_ALLOWED_CHAT_IDS"
# "1"/"true"/"on" enable per-trade notifications; anything else disables them
ENV_PER_TRADE = "MQL5BOT_TELEGRAM_PER_TRADE"
# local time of day for the daily digest, "HH:MM" (24h); default 22:00
ENV_DIGEST_TIME = "MQL5BOT_TELEGRAM_DIGEST_TIME"

# The commands this surface accepts. There is deliberately NO "start"/"resume":
# see the asymmetric-friction rule in the module docstring.
COMMANDS = ("status", "positions", "report", "stop")

_TRUEISH = frozenset({"1", "true", "on", "yes"})


@dataclass(frozen=True)
class OpenPosition:
    """A single open position as shown to the owner. Carries ONLY the symbol,
    side and lot size — never a ticket, account number or price."""

    symbol: str
    side: str
    lots: float


@dataclass(frozen=True)
class OpsState:
    """A snapshot the commands and the digest READ. Every field is measured
    upstream and injected here; this module never fabricates a value.

    ``drawdown_limit_pct`` is the configured daily-loss limit; ``drawdown_used_pct``
    is how much of it today has already consumed. The distance to the limit is
    ``drawdown_limit_pct - drawdown_used_pct``.
    """

    alive: bool
    trades_today: int
    realised_pnl_today: float
    open_positions: Sequence[OpenPosition] = field(default_factory=tuple)
    drawdown_limit_pct: float = 0.0
    drawdown_used_pct: float = 0.0

    @property
    def drawdown_distance_pct(self) -> float:
        return self.drawdown_limit_pct - self.drawdown_used_pct


def _parse_allow_list(raw: str | None) -> frozenset[str]:
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _digest_time(raw: str | None) -> tuple[int, int]:
    """Parse ``HH:MM`` into (hour, minute); default 22:00 on missing/invalid."""
    if raw:
        try:
            hh, mm = raw.split(":", 1)
            h, m = int(hh), int(mm)
            if 0 <= h < 24 and 0 <= m < 60:
                return h, m
        except (ValueError, TypeError):
            pass
    return 22, 0


def _distance_line(s: OpsState) -> str:
    return (
        f"فاصله تا حد ضرر (distance to loss limit): "
        f"{s.drawdown_distance_pct} pct "
        f"({s.drawdown_used_pct} / {s.drawdown_limit_pct})"
    )


class TelegramOperator:
    """Owner-facing Telegram surface built on an existing ``TelegramChannel``.

    ``channel`` is reused verbatim for delivery — do not pass a second notifier.
    ``kill_switch`` is the safety veto the ``stop`` command trips. ``state_provider``
    returns a fresh :class:`OpsState` each time it is read.
    """

    def __init__(self, *,
                 channel: TelegramChannel,
                 kill_switch: KillSwitch,
                 state_provider: Callable[[], OpsState],
                 env: Mapping[str, str] | None = None,
                 per_trade: bool | None = None,
                 actor: str = "telegram-owner") -> None:
        source = os.environ if env is None else env
        self._channel = channel
        self._kill = kill_switch
        self._state_provider = state_provider
        self._actor = actor
        self._allow = _parse_allow_list(source.get(ENV_ALLOWED_CHATS))
        if per_trade is None:
            per_trade = str(source.get(ENV_PER_TRADE, "")).strip().lower() in _TRUEISH
        self._per_trade = bool(per_trade)
        self._digest_h, self._digest_m = _digest_time(source.get(ENV_DIGEST_TIME))
        self._last_digest_date: _dt.date | None = None

    # -- per-trade notifications -------------------------------------------

    def on_trade_event(self, event: Mapping[str, object]) -> bool:
        """Deliver an open/close notification for a telemetry ``trade`` event.

        Returns True if a message was sent. Does nothing (returns False) when
        per-trade notifications are off or the event is not a trade — watchdog
        alerts are unaffected and keep flowing through ``channel`` directly.
        """
        if not self._per_trade:
            return False
        if str(event.get("event", "")) != "trade":
            return False
        self._channel.send_text(self._format_trade(event))
        return True

    @staticmethod
    def _format_trade(event: Mapping[str, object]) -> str:
        action = str(event.get("action", "")) or "trade"
        symbol = str(event.get("symbol", "")) or "?"
        lots = event.get("lots")
        pnl = event.get("pnl")
        lines = [
            f"📈 معامله / trade: {action}",
            f"نماد (symbol): {symbol}",
            f"حجم (lots): {lots}",
        ]
        if pnl is not None:
            lines.append(f"سود/زیان (pnl): {pnl}")
        return "\n".join(lines)

    # -- daily digest -------------------------------------------------------

    def digest_text(self, state: OpsState | None = None) -> str:
        s = state if state is not None else self._state_provider()
        alive = "بله / yes" if s.alive else "خیر / no"
        pos_lines = [
            f"  · {p.symbol} {p.side} {p.lots}" for p in s.open_positions
        ] or ["  · (none)"]
        lines = [
            "📊 گزارش روزانه / daily digest",
            f"زنده (alive): {alive}",
            f"معاملات امروز (trades today): {s.trades_today}",
            f"سود/زیان امروز (realised P&L today): {s.realised_pnl_today}",
            "موقعیت‌های باز (open positions):",
            *pos_lines,
            _distance_line(s),
        ]
        return "\n".join(lines)

    def maybe_send_digest(self, now: _dt.datetime) -> bool:
        """Send the digest at most once per local day, at/after the configured
        time. ``now`` is the caller's local wall clock (inject it in tests)."""
        target = now.replace(
            hour=self._digest_h, minute=self._digest_m, second=0, microsecond=0)
        if now < target:
            return False
        if self._last_digest_date == now.date():
            return False
        self._last_digest_date = now.date()
        self._channel.send_text(self.digest_text())
        return True

    # -- inbound commands ---------------------------------------------------

    def on_command(self, chat_id: object, text: str) -> str | None:
        """Handle one inbound message. Returns the reply text that was sent, or
        None when the message was ignored (unauthorised chat or unknown word).

        Authorisation is by allow-list. A message from any other chat is
        dropped and logged WITHOUT its content or the chat id.
        """
        if str(chat_id) not in self._allow:
            _LOG.warning("ignored inbound message from a non-allowlisted chat")
            return None
        word = (text or "").strip().lstrip("/").split() or [""]
        cmd = word[0].lower()
        if cmd == "status":
            reply = self._status_text()
        elif cmd == "positions":
            reply = self._positions_text()
        elif cmd == "report":
            reply = self.digest_text()
        elif cmd == "stop":
            reply = self._do_stop()
        else:
            # Unknown word — including anything resembling start/resume. There
            # is no code path from here that re-enables trading.
            _LOG.info("ignored an unrecognised command from an allowlisted chat")
            return None
        self._channel.send_text(reply)
        return reply

    def _status_text(self) -> str:
        s = self._state_provider()
        alive = "بله / yes" if s.alive else "خیر / no"
        halted = not self._kill.may_open_new_trades()
        engine = self._kill.state.value  # a protected term, shown verbatim
        return "\n".join([
            "ℹ️ وضعیت / status",
            f"زنده (alive): {alive}",
            f"موتور (engine): {engine}",
            "معاملات جدید مجاز (new trades allowed): "
            + ("no" if halted else "yes"),
            f"فاصله تا حد ضرر (distance to loss limit): {s.drawdown_distance_pct} pct",
        ])

    def _positions_text(self) -> str:
        s = self._state_provider()
        if not s.open_positions:
            return "موقعیت باز نیست / no open positions"
        lines = ["📂 موقعیت‌ها / positions"]
        lines += [f"  · {p.symbol} {p.side} {p.lots}" for p in s.open_positions]
        return "\n".join(lines)

    def _do_stop(self) -> str:
        """Trip the kill switch immediately, no confirmation. There is no
        inverse command on this surface."""
        self._kill.manual_stop(self._actor, "owner stop via Telegram")
        return "\n".join([
            "🛑 توقف اضطراری / emergency stop",
            f"موتور (engine): {self._kill.state.value}",
            "برای ازسرگیری از کنسول استفاده کنید / resume only from the console",
        ])


__all__ = [
    "COMMANDS",
    "ENV_ALLOWED_CHATS",
    "ENV_DIGEST_TIME",
    "ENV_PER_TRADE",
    "OpenPosition",
    "OpsState",
    "TelegramOperator",
]
