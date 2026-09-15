"""mql5bot.retryqueue — sleep-free bounded retry engine (SPEC §3.4/§8.A).

Release-A seed model for ``mql5/Include/Mql5Bot/RetryQueue.mqh``: retryable
trade-server failures are re-scheduled on the EA timer with exponential
backoff, refreshed prices and a hard attempt cap. There are NO blocking
retry loops anywhere in the trade path; the only immediate re-send permitted
is a single REQUOTE retry with refreshed prices (handled by the caller).

This mirror pins the parts that are pure and unit-testable:

* the backoff schedule ``500 ms * 2**attempt`` capped at 10 s;
* queue semantics: bounded slots, dedupe of the same logical operation
  (action+symbol+ticket+comment) that *refreshes the schedule without
  resetting the attempt counter*, earliest-due pop, deactivation on pop.

``now_ms`` is injected so tests need no wall clock.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- actions (match ENUM_RETRY_ACTION in RetryQueue.mqh) -------------------
RETRY_ACTION_NONE: int = 0
RETRY_ACTION_MARKET: int = 1
RETRY_ACTION_PENDING: int = 2
RETRY_ACTION_CLOSE: int = 3
RETRY_ACTION_MODIFY: int = 4
RETRY_ACTION_CANCEL: int = 5

# --- bounds (match RetryQueue.mqh defines) ---------------------------------
RETRY_MAX_ITEMS: int = 32
RETRY_DEFAULT_ATTEMPTS: int = 4
RETRY_BACKOFF_MS: float = 500.0  # attempt 0 -> 500 ms (next timer tick)
RETRY_BACKOFF_CAP_MS: float = 10000.0  # never wait longer than 10 s


def retry_backoff_ms(attempt: int) -> int:
    """Mirror ``RetryBackoffMs``: 500 * 2**max(0, attempt), capped at 10 s."""
    ms = RETRY_BACKOFF_MS * (2 ** max(0, attempt))
    return int(min(ms, RETRY_BACKOFF_CAP_MS))


@dataclass
class RetryItem:
    """One queued operation (mirror SRetryItem fields used for dedupe)."""

    action: int = RETRY_ACTION_NONE
    symbol: str = ""
    ticket: int = 0
    comment: str = ""
    attempt: int = 0
    max_attempts: int = RETRY_DEFAULT_ATTEMPTS
    due_ms: int = 0
    active: bool = True

    def key(self) -> tuple[int, str, int, str]:
        return (self.action, self.symbol, self.ticket, self.comment)


class RetryQueue:
    """Bounded earliest-due queue with same-op dedupe (mirror CRetryQueue)."""

    def __init__(self, max_items: int = RETRY_MAX_ITEMS) -> None:
        self._max_items = max_items
        self._items: list[RetryItem] = []
        self.dropped: int = 0  # items dropped because the queue was full

    def count_active(self) -> int:
        return sum(1 for it in self._items if it.active)

    def is_empty(self) -> bool:
        return self.count_active() == 0

    def add(self, item: RetryItem, attempted: int, now_ms: int) -> bool:
        """Enqueue, or refresh an identical entry keeping the attempt counter.

        Mirrors ``CRetryQueue::Add``: a re-request of the same logical
        operation re-schedules it but NEVER resets the cap.
        """
        for existing in self._items:
            if existing.active and existing.key() == item.key():
                existing.attempt = attempted
                existing.due_ms = now_ms + retry_backoff_ms(existing.attempt)
                return True
        if len(self._items) >= self._max_items:
            self.dropped += 1
            return False  # fail-safe: drop rather than resend unboundedly
        item.attempt = attempted
        item.due_ms = now_ms + retry_backoff_ms(attempted)
        item.active = True
        self._items.append(item)
        return True

    def pop_due(self, now_ms: int) -> RetryItem | None:
        """Remove and return the next due item (earliest due first)."""
        best: RetryItem | None = None
        for it in self._items:
            if not it.active or it.due_ms > now_ms:
                continue
            if best is None or it.due_ms < best.due_ms:
                best = it
        if best is None:
            return None
        best.active = False
        return best
