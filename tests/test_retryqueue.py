"""Tests for the sleep-free retry queue mirror (SPEC §3.4/§8.A, DoD on
no-Sleep execution): bounded slots, exponential backoff with a hard cap,
same-operation dedupe that never resets the attempt cap, earliest-due pop.

Mirrors ``mql5/Include/Mql5Bot/RetryQueue.mqh`` and the constants the
``CTradeManager`` retry path relies on.
"""

from mql5bot.retryqueue import (
    RETRY_ACTION_CANCEL,
    RETRY_ACTION_CLOSE,
    RETRY_ACTION_MARKET,
    RETRY_ACTION_MODIFY,
    RETRY_ACTION_NONE,
    RETRY_ACTION_PENDING,
    RETRY_BACKOFF_CAP_MS,
    RETRY_BACKOFF_MS,
    RETRY_MAX_ITEMS,
    RetryItem,
    RetryQueue,
    retry_backoff_ms,
)


# ---------------------------------------------------------------------------
# Backoff schedule
# ---------------------------------------------------------------------------
def test_backoff_schedule_exponential():
    assert retry_backoff_ms(0) == 500
    assert retry_backoff_ms(1) == 1000
    assert retry_backoff_ms(2) == 2000
    assert retry_backoff_ms(3) == 4000
    assert retry_backoff_ms(4) == 8000


def test_backoff_caps_at_ten_seconds():
    assert retry_backoff_ms(5) == 10000
    assert retry_backoff_ms(10) == 10000
    assert retry_backoff_ms(99) == 10000
    assert RETRY_BACKOFF_CAP_MS == 10000.0


def test_backoff_negative_attempt_uses_attempt_zero():
    assert retry_backoff_ms(-3) == retry_backoff_ms(0)
    assert RETRY_BACKOFF_MS == 500.0


def test_action_ids_are_stable():
    # persisted/reviewed ids — never renumber between releases
    assert RETRY_ACTION_NONE == 0
    assert RETRY_ACTION_MARKET == 1
    assert RETRY_ACTION_PENDING == 2
    assert RETRY_ACTION_CLOSE == 3
    assert RETRY_ACTION_MODIFY == 4
    assert RETRY_ACTION_CANCEL == 5
    assert RETRY_MAX_ITEMS == 32


# ---------------------------------------------------------------------------
# Queue semantics
# ---------------------------------------------------------------------------
def _item(action=RETRY_ACTION_CLOSE, ticket=7, comment="mql5bot-close-1"):
    return RetryItem(action=action, symbol="EURUSD", ticket=ticket, comment=comment)


def test_add_then_pop_earliest_due():
    q = RetryQueue()
    now = 1_000_000
    assert q.add(_item(), 0, now)            # due now + 500
    late = _item(ticket=8)
    assert q.add(late, 0, now)
    late.due_ms = now + 5000                 # schedule the later item farther out
    first = q.pop_due(now + 1000)            # both due; earliest wins
    assert first is not None and first.ticket == 7
    assert q.count_active() == 1
    # item popped, later item still scheduled but not due yet
    assert q.pop_due(now + 2000) is None
    second = q.pop_due(now + 6000)
    assert second is not None and second.ticket == 8
    assert q.is_empty()


def test_pop_nothing_when_nothing_due():
    q = RetryQueue()
    q.add(_item(), 0, 1_000)
    assert q.pop_due(999) is None
    assert q.count_active() == 1


def test_pop_deactivates():
    q = RetryQueue()
    q.add(_item(), 0, 1_000)
    item = q.pop_due(2_000)
    assert item is not None
    assert q.count_active() == 0
    assert q.is_empty()
    assert q.pop_due(9_999) is None


def test_dedupe_refreshes_schedule_but_keeps_attempt_counter():
    q = RetryQueue()
    now = 1_000
    q.add(_item(), 0, now)          # attempt 0 -> due now + 500
    q.add(_item(), 1, now)          # same logical op re-queued after attempt 1
    assert q.count_active() == 1    # not duplicated
    item = q.pop_due(now + 10_000)  # wait past any backoff
    assert item is not None
    assert item.attempt == 1        # cap was NOT reset by the re-request


def test_different_operations_are_not_deduplicated():
    q = RetryQueue()
    now = 0
    q.add(_item(action=RETRY_ACTION_CLOSE, ticket=7), 0, now)
    q.add(_item(action=RETRY_ACTION_MODIFY, ticket=7), 0, now)
    q.add(_item(action=RETRY_ACTION_CLOSE, ticket=8), 0, now)
    q.add(_item(action=RETRY_ACTION_CLOSE, ticket=7, comment="other"), 0, now)
    assert q.count_active() == 4


def test_queue_is_bounded_and_drops_without_resending():
    q = RetryQueue(max_items=4)
    now = 0
    for i in range(6):
        q.add(_item(ticket=i, comment=f"c{i}"), 0, now)
    assert q.count_active() == 4
    assert q.dropped == 2  # fail-safe: drop rather than resend unboundedly


def test_default_attempt_cap_is_four():
    assert RetryItem().max_attempts == 4
    item = _item()
    item.max_attempts = 3
    assert item.max_attempts == 3
