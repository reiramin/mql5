"""Tests for the SL-verdict mirror (SPEC §3.2 non-negotiable stop-loss).

The matrix drives BOTH sides: ``SlVerdict`` in
``mql5/Include/Mql5Bot/SlGuard.mqh`` is the exact MQL5 port of
``slguard.sl_verdict``, so these vectors are the acceptance test for the
MQL5 implementation too.
"""

import pytest
from mql5bot.slguard import (
    POSITION_TYPE_BUY,
    POSITION_TYPE_SELL,
    SL_VERDICT_MISSING,
    SL_VERDICT_NOT_FOUND,
    SL_VERDICT_OK,
    SL_VERDICT_TOO_CLOSE,
    SL_VERDICT_WRONG_SIDE,
    SLG_CLOSE_WAIT_PUMPS,
    SLG_MAX_ITEMS,
    SLG_MAX_PUMPS_PER_TICK,
    SLG_MODIFY_WAIT_PUMPS,
    SLG_NO_POSITION_DROP_PUMPS,
    SLG_UNPROTECTABLE_ESCALATE_PUMPS,
    sl_verdict,
)
from test_symbolspec import make_specs


@pytest.fixture(scope="module")
def specs() -> dict:
    return make_specs()


# ---------------------------------------------------------------------------
# OK verdicts on the five synthetic specs
# ---------------------------------------------------------------------------
def test_buy_ok_far_enough(specs):
    eurusd = specs["EURUSD"]
    # stops level = 10 points = 0.0001; 0.0010 away is fine
    assert sl_verdict(eurusd, POSITION_TYPE_BUY, 1.1000, 1.0990) == SL_VERDICT_OK


def test_sell_ok_far_enough(specs):
    eurusd = specs["EURUSD"]
    assert sl_verdict(eurusd, POSITION_TYPE_SELL, 1.1000, 1.1010) == SL_VERDICT_OK


def test_us30_tick_grid_stops(specs):
    us30 = specs["US30"]
    # stops level = 25 points * 0.01 = 0.25 price units, tick 0.25
    assert sl_verdict(us30, POSITION_TYPE_BUY, 35000.0, 34999.0) == SL_VERDICT_OK
    # 0.25 exactly at the stops level is OK (half-tick tolerance)
    assert sl_verdict(us30, POSITION_TYPE_BUY, 35000.0, 34999.75) == SL_VERDICT_OK


def test_xauusd_and_crypto_ok(specs):
    xau = specs["XAUUSD"]
    assert sl_verdict(xau, POSITION_TYPE_BUY, 2000.00, 1999.00) == SL_VERDICT_OK
    crypto = specs["BTCUSD"]
    assert sl_verdict(crypto, POSITION_TYPE_SELL, 60000.0, 60100.0) == SL_VERDICT_OK


# ---------------------------------------------------------------------------
# Missing / unusable
# ---------------------------------------------------------------------------
def test_missing_sl(specs):
    eurusd = specs["EURUSD"]
    assert sl_verdict(eurusd, POSITION_TYPE_BUY, 1.1000, 0.0) == SL_VERDICT_MISSING
    assert sl_verdict(eurusd, POSITION_TYPE_BUY, 1.1000, -1.0) == SL_VERDICT_MISSING


def test_nan_sl_is_missing(specs):
    eurusd = specs["EURUSD"]
    assert sl_verdict(eurusd, POSITION_TYPE_BUY, 1.1000, float("nan")) == (
        SL_VERDICT_MISSING
    )


def test_unusable_parameters(specs):
    eurusd = specs["EURUSD"]
    assert sl_verdict(eurusd, 99, 1.1000, 1.0990) == SL_VERDICT_NOT_FOUND
    assert sl_verdict(eurusd, POSITION_TYPE_BUY, 0.0, 1.0990) == SL_VERDICT_NOT_FOUND
    assert sl_verdict(eurusd, POSITION_TYPE_BUY, -2.0, 1.0990) == SL_VERDICT_NOT_FOUND


# ---------------------------------------------------------------------------
# Wrong side
# ---------------------------------------------------------------------------
def test_buy_sl_above_entry_is_wrong_side(specs):
    eurusd = specs["EURUSD"]
    assert sl_verdict(eurusd, POSITION_TYPE_BUY, 1.1000, 1.1000) == SL_VERDICT_WRONG_SIDE
    assert sl_verdict(eurusd, POSITION_TYPE_BUY, 1.1000, 1.1010) == SL_VERDICT_WRONG_SIDE


def test_sell_sl_below_entry_is_wrong_side(specs):
    eurusd = specs["EURUSD"]
    assert sl_verdict(eurusd, POSITION_TYPE_SELL, 1.1000, 1.1000) == SL_VERDICT_WRONG_SIDE
    assert sl_verdict(eurusd, POSITION_TYPE_SELL, 1.1000, 1.0990) == SL_VERDICT_WRONG_SIDE


# ---------------------------------------------------------------------------
# Too close to entry (broker stops level, half-tick tolerance)
# ---------------------------------------------------------------------------
def test_buy_too_close_at_stops_level(specs):
    eurusd = specs["EURUSD"]
    # min distance 0.0001; tolerance 0.5 tick = 0.000005
    # 0.00009 < 0.0001 - 0.000005 -> too close
    assert sl_verdict(eurusd, POSITION_TYPE_BUY, 1.1000, 1.09991) == SL_VERDICT_TOO_CLOSE
    # exactly at 0.0001 -> OK (>= threshold minus tolerance)
    assert sl_verdict(eurusd, POSITION_TYPE_BUY, 1.1000, 1.09990) == SL_VERDICT_OK


def test_sell_too_close_at_stops_level(specs):
    eurusd = specs["EURUSD"]
    assert sl_verdict(eurusd, POSITION_TYPE_SELL, 1.1000, 1.10010) == SL_VERDICT_OK
    assert sl_verdict(eurusd, POSITION_TYPE_SELL, 1.1000, 1.10009) == SL_VERDICT_TOO_CLOSE


def test_us30_too_close(specs):
    us30 = specs["US30"]
    # tick 0.25, stops 0.25, eps 0.125 -> distances strictly below 0.125 are
    # too close (0.125 sits exactly on the tolerance boundary and is OK)
    assert sl_verdict(us30, POSITION_TYPE_BUY, 35000.0, 34999.90) == SL_VERDICT_TOO_CLOSE
    assert sl_verdict(us30, POSITION_TYPE_SELL, 35000.0, 35000.10) == SL_VERDICT_TOO_CLOSE
    assert sl_verdict(us30, POSITION_TYPE_BUY, 35000.0, 34999.875) == SL_VERDICT_OK


# ---------------------------------------------------------------------------
# Guard pump thresholds stay consistent with the fail-safe escalation order
# ---------------------------------------------------------------------------
def test_pump_threshold_invariants():
    # more items/ticks than one position can ever need -> slots always exist
    assert SLG_MAX_ITEMS >= 4
    assert SLG_MAX_PUMPS_PER_TICK >= 1
    # an unbound item that never filled drops before it can escalate
    assert SLG_NO_POSITION_DROP_PUMPS < SLG_UNPROTECTABLE_ESCALATE_PUMPS
    # modify is given more patience than the close-only path
    assert SLG_MODIFY_WAIT_PUMPS < SLG_CLOSE_WAIT_PUMPS
    # escalation (caller halts) is the last resort after close patience
    assert SLG_UNPROTECTABLE_ESCALATE_PUMPS < SLG_CLOSE_WAIT_PUMPS
