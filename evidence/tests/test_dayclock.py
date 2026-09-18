"""Tests for server-time daily resets (mql5bot.dayclock, Phase 3)."""

import numpy as np
import pandas as pd
import pytest
from mql5bot.dayclock import DayClock, day_starts, server_day_ids


def _index(start: str, periods: int, freq: str = "h",
           tz: str | None = None) -> pd.DatetimeIndex:
    idx = pd.date_range(start, periods=periods, freq=freq)
    if tz is not None:
        idx = idx.tz_localize(tz)
    return idx


def test_midnight_reset_naive():
    idx = _index("2024-01-01 18:00", periods=48)  # 2 days of hourly bars
    clock = DayClock(reset_hour=0, reset_minute=0)  # naive = server local
    ids = server_day_ids(idx, clock)
    assert ids[0] == 20240101
    assert (ids[:6] == 20240101).all()          # 18:00..23:00 day 1
    assert ids[6] == 20240102 and ids[-1] == 20240103
    starts, _ = day_starts(idx, clock)
    assert list(starts) == [0, 6, 30]


def test_non_midnight_reset():
    # 17:00 reset: the bar at 17:00 local starts a new server day
    idx = _index("2024-06-01 15:00", periods=6)
    clock = DayClock(reset_hour=17, reset_minute=0)
    ids = server_day_ids(idx, clock)
    # 15:00/16:00 belong to the day that started 17:00 the previous day
    assert ids[0] == 20240531 and ids[1] == 20240531
    assert ids[2] == 20240601 and ids[3] == 20240601
    starts, start_ids = day_starts(idx, clock)
    assert list(starts) == [0, 2]
    assert list(start_ids) == [20240531, 20240601]


def test_weekend_gap_still_rolls_days():
    # Friday 2024-06-07 hourly until Monday 2024-06-10 with NO weekend bars:
    # build Fri(24) + Mon(24) contiguous
    fri = _index("2024-06-07 00:00", periods=24)
    mon = _index("2024-06-10 00:00", periods=24)
    idx2 = fri.append(mon)
    clock = DayClock()  # midnight reset
    ids = server_day_ids(idx2, clock)
    assert ids[0] == 20240607 and ids[23] == 20240607
    assert ids[24] == 20240610  # no Sat/Sun bars -> straight to Monday
    starts, _ = day_starts(idx2, clock)
    assert list(starts) == [0, 24]


def test_dst_spring_forward_us_eastern():
    """2024-03-10 02:00 EST -> 03:00 EDT (jump at 07:00 UTC).

    Reset at 17:00 server local (after the jump).  Hand-derived ids:
    the bar's id is the local date of (bar - 17h), i.e. the day whose
    17:00 reset opened the current server day.
    """
    utc = pd.DatetimeIndex([
        "2024-03-09 20:00",  # 15:00 EST -> day started Mar 8 17:00
        "2024-03-09 22:00",  # 17:00 EST -> first bar of day 20240309
        "2024-03-10 06:00",  # 01:00 EST (pre-jump)
        "2024-03-10 07:00",  # 03:00 EDT (post-jump; 02:00 never existed)
        "2024-03-10 21:00",  # 17:00 EDT -> first bar of day 20240310
        "2024-03-10 22:00",  # 18:00 EDT
    ], tz="UTC")
    clock = DayClock(reset_hour=17, reset_minute=0, server_tz="America/New_York")
    ids = server_day_ids(utc, clock)
    assert list(ids) == [20240308, 20240309, 20240309, 20240309, 20240310, 20240310]
    starts, start_ids = day_starts(utc, clock)
    assert list(starts) == [0, 1, 4]
    assert list(start_ids) == [20240308, 20240309, 20240310]
    local_hours = [ts.hour for ts in utc.tz_convert("America/New_York")]
    assert local_hours == [15, 17, 1, 3, 17, 18]  # jump visible: no 02:00


def test_dst_fall_back_us_eastern():
    """2024-11-03 02:00 EDT -> 01:00 EST (fall back at 06:00 UTC).

    Reset at 02:30 server local.  The ambiguous 01:00-01:59 hour occurs
    twice on the wall clock but once on the timeline; epoch-shift ids must
    stay monotonic and unambiguous.
    """
    utc = pd.DatetimeIndex([
        "2024-11-02 22:00",  # 18:00 EDT Nov 2 -> 20241102
        "2024-11-03 05:00",  # 01:00 EDT (first occurrence)
        "2024-11-03 06:00",  # 01:00 EST (second occurrence)
        "2024-11-03 07:00",  # 02:00 EST
        "2024-11-03 08:00",  # 03:00 EST -> 03:00 - 02:30 = 00:30 Nov 3
        "2024-11-03 09:00",  # 04:00 EST
    ], tz="UTC")
    clock = DayClock(reset_hour=2, reset_minute=30, server_tz="America/New_York")
    ids = server_day_ids(utc, clock)
    assert list(ids) == [20241102, 20241102, 20241102, 20241102, 20241103, 20241103]
    assert (np.diff(ids) >= 0).all()
    starts, _ = day_starts(utc, clock)
    assert list(starts) == [0, 4]


def test_dayclock_validation():
    with pytest.raises(ValueError, match="HH:MM"):
        DayClock(reset_hour=24).validate()
    with pytest.raises(ValueError, match="HH:MM"):
        DayClock(reset_minute=99).validate()
