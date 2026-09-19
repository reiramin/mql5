"""mql5bot.notify — operator notification channels.

Channels satisfy the EXISTING alert contract in
``mql5bot.discovery.safety.Watchdog`` (``channel: Callable[[dict], None]``):
they receive an alert dict and deliver it. They add no monitoring logic and
do not reimplement Watchdog's per-kind rate limiting.
"""

from __future__ import annotations

from .telegram import (
    TelegramChannel,
    TelegramConfigError,
    TelegramSendError,
)

__all__ = [
    "TelegramChannel",
    "TelegramConfigError",
    "TelegramSendError",
]
