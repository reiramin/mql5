"""discovery/journal.py — structured event journal (convergence §72/§73).

Application/infrastructure layer: an injectable sink receives typed
event dicts (JSON-serializable).  The default sink keeps an in-memory
bounded ring; hosts may persist to their own store.  The journal is
OBSERVATION ONLY: no component reads it back to make decisions, so a
broken sink can never alter behavior.

Event vocabulary (§72 minimum) is enforced as a closed set — unknown
names are refused, so telemetry cannot drift silently.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

EVENTS = frozenset({
    "strategy_received", "strategy_parsed", "candidate_created",
    "campaign_started", "campaign_resumed", "candidate_selected",
    "oos_completed", "score_computed", "shadow_started",
    "degradation_detected", "promotion_requested", "promotion_approved",
    "promotion_rejected", "allocation_changed", "allocation_frozen",
    "kill_switch_triggered", "kill_switch_reset", "watchdog_alert",
    "trade_intent_created", "trade_executed", "trade_reconciled",
    "sl_verified", "sl_failure", "lifecycle_advanced",
    "campaign_completed", "research_outcome",
})


class EventJournal:
    def __init__(self, sink: Callable[[dict], None] | None = None,
                 *, capacity: int = 5000,
                 clock: Callable[[], float] = time.time):
        self._sink = sink or (lambda e: None)
        self._ring: deque[dict] = deque(maxlen=capacity)
        self._clock = clock

    def emit(self, event: str, **fields) -> dict:
        if event not in EVENTS:
            raise ValueError(f"unknown journal event {event!r}; "
                             f"known: {sorted(EVENTS)}")
        for k, v in fields.items():
            if isinstance(v, str) and len(v) > 10_000:
                raise ValueError(f"journal field {k!r} exceeds 10k chars")
        record = {"event": event, "ts": self._clock(), **fields}
        try:
            self._sink(record)
        except Exception:  # noqa: BLE001,S110 — a dead sink must never
            pass           # abort the research chain it only observes
        self._ring.append(record)
        return record

    def tail(self, n: int = 50) -> list[dict]:
        return list(self._ring)[-n:]

    def by_strategy(self, strategy_id: str, version: int | None = None
                    ) -> list[dict]:
        rows = [r for r in self._ring
                if r.get("strategy_id") == strategy_id
                and (version is None or r.get("version") == version)]
        return rows
