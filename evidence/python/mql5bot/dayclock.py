"""mql5bot.dayclock — server-time daily reset semantics (Phase 3).

The EA measures daily loss from equity at the *server-time* day boundary
(``TimeCurrent`` server time, persisted day key), not the researcher's wall
clock.  This module gives the engine the same semantics:

* bars may be labelled in UTC (tz-aware, or naive-UTC) while the server
  runs on another zone, or already in server-local naive time;
* the daily reset happens at a configurable local hour/minute
  (``reset_hour``/``reset_minute``, default 00:00 — the classic midnight
  rollover) of the server zone;
* DST transitions are handled with wall-clock subtraction in the server
  zone: the day id of a bar is the calendar date of
  ``server_local_wall_time - reset_delta``.  Only the date is read back,
  so nonexistent/ambiguous local times (spring-forward and autumn-repeat
  hours) cannot corrupt the result, and DST-compressed days keep the
  exact ``[reset(D), reset(D+1))`` convention.

Definition: server day ``D`` spans ``[reset(D), reset(D+1))`` in server
local time.  ``server_day_ids`` returns one integer id per bar
(``YYYYMMDD`` of the shifted local date — the same shape as the EA's
persisted day key), and ``day_starts`` returns the bar indexes at which a
new server day begins (bar 0 is always one).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_SERVER_TZ = "UTC"


@dataclass(frozen=True)
class DayClock:
    """Daily reset configuration.

    ``server_tz``: IANA zone name of the broker server.  None means the
    bar index is already server-local naive time (no conversion).
    ``reset_hour``/``reset_minute``: local server time of the daily reset.
    """

    reset_hour: int = 0
    reset_minute: int = 0
    server_tz: str | None = None

    def validate(self) -> None:
        if not 0 <= self.reset_hour <= 23 or not 0 <= self.reset_minute <= 59:
            raise ValueError(
                f"reset time must be HH:MM, got {self.reset_hour}:{self.reset_minute}")

    @property
    def reset_delta(self) -> pd.Timedelta:
        return pd.Timedelta(hours=self.reset_hour, minutes=self.reset_minute)


def _as_server_local(index: pd.DatetimeIndex, server_tz: str | None) -> pd.DatetimeIndex:
    """Return ``index`` projected into the server's local time.

    * naive index + server_tz=None -> unchanged (already server local);
    * naive index + server_tz      -> treated as UTC, converted;
    * tz-aware index + server_tz   -> converted;
    * tz-aware index + None        -> treated as server tz already.
    """
    if index.tz is None:
        if server_tz is None or server_tz == DEFAULT_SERVER_TZ:
            return index
        return index.tz_localize("UTC").tz_convert(server_tz)
    if server_tz is None:
        return index
    return index.tz_convert(server_tz)


def server_day_ids(
    index: pd.DatetimeIndex,
    clock: DayClock,
) -> np.ndarray:
    """Integer ``YYYYMMDD`` server-day id per bar (see module docstring).

    Implementation: project the index into server-local wall time, drop
    the tz offset (dates are DST-immune), subtract the reset delta as wall
    time, and read the resulting calendar date.  Wall-clock subtraction
    gives exactly the ``[reset(D), reset(D+1))`` convention on every day,
    including DST-compressed days; because only the *date* is read back,
    nonexistent/ambiguous local times (spring/autumn transitions) cannot
    corrupt the result.
    """
    clock.validate()
    local = _as_server_local(index, clock.server_tz)
    naive = local.tz_localize(None) if local.tz is not None else local
    shifted = naive - clock.reset_delta
    return np.asarray(
        [ts.year * 10_000 + ts.month * 100 + ts.day for ts in shifted],
        dtype=np.int64,
    )


def day_starts(
    index: pd.DatetimeIndex,
    clock: DayClock,
) -> tuple[np.ndarray, np.ndarray]:
    """Bar indexes where a new server day begins + their day ids.

    Bar 0 is always a day start.  ``day_starts`` is used by the engine to
    snapshot day-start equity and to charge swap at the boundary.
    """
    ids = server_day_ids(index, clock)
    starts = [0]
    prev = ids[0]
    for i in range(1, len(ids)):
        if ids[i] != prev:
            starts.append(i)
            prev = ids[i]
    return np.asarray(starts, dtype=np.int64), np.asarray([ids[i] for i in starts],
                                                          dtype=np.int64)
