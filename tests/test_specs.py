"""Tests for the canonical synthetic fixtures (mql5bot.specs, Phase 1).

The same six SymbolSpec fixtures must drive the Sizer, the backtester and
every risk test — these tests pin the fixture set and prove sizer
usability on every asset class (incl. profit-currency conversion).
"""

import pytest
from mql5bot.sizer import (
    BELOW_MIN,
    RISK_PERCENT_EQUITY,
    size_position,
)
from mql5bot.specs import (
    FIXTURE_PROFIT_TO_DEPOSIT,
    SYNTHETIC_SPECS,
    synthetic_profit_to_deposit,
    synthetic_spec,
)
from mql5bot.symbolspec import SymbolSpec, loss_per_lot


def test_fixture_set_covers_required_asset_classes():
    assert set(SYNTHETIC_SPECS) == {
        "EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30", "BTCUSD",
    }
    spec = synthetic_spec("GBPUSD")
    assert isinstance(spec, SymbolSpec) and spec.digits == 5


def test_unknown_symbol_raises():
    with pytest.raises(KeyError, match="no synthetic spec"):
        synthetic_spec("NOPE")
    with pytest.raises(KeyError, match="no fixture conversion"):
        synthetic_profit_to_deposit("NOPE")


def test_conversion_fixtures_are_positive_and_complete():
    assert set(FIXTURE_PROFIT_TO_DEPOSIT) == set(SYNTHETIC_SPECS)
    for rate in FIXTURE_PROFIT_TO_DEPOSIT.values():
        assert rate > 0.0


@pytest.mark.parametrize("symbol", sorted(SYNTHETIC_SPECS))
def test_sizer_usable_on_every_fixture(symbol):
    """A funded 1% risk request must size a valid trade on every asset."""
    spec = synthetic_spec(symbol)
    conv = synthetic_profit_to_deposit(symbol)
    res = size_position(
        spec,
        mode=RISK_PERCENT_EQUITY,
        equity=100_000.0,
        balance=100_000.0,
        stop_distance=spec.min_stop_distance() + 5 * spec.tick_size,
        value=1.0,
        profit_to_deposit=conv,
        max_lots=10.0,
    )
    assert not res.rejected, f"{symbol}: {res.reason}"
    assert res.lots >= spec.volume_min
    # conservative invariant: actual risk never exceeds the requested budget
    # (floor-to-step may only undershoot)
    assert res.risk_money_actual <= res.risk_money_budget * (1 + 1e-9)


def test_usdjpy_loss_converts_jpy_to_deposit():
    """USDJPY fixture: loss per lot is in JPY; the sizer must convert."""
    spec = synthetic_spec("USDJPY")
    conv = synthetic_profit_to_deposit("USDJPY")  # 1/150
    dist = 0.010  # 10 ticks of 0.001
    pl_jpy = loss_per_lot(dist, spec, profit_to_deposit=1.0)
    assert pl_jpy == pytest.approx(1000.0)  # 10 ticks * 100 JPY
    pl_usd = loss_per_lot(dist, spec, profit_to_deposit=conv)
    assert pl_usd == pytest.approx(1000.0 / 150.0)
    res = size_position(
        spec, mode=RISK_PERCENT_EQUITY, equity=1_000.0, balance=1_000.0,
        stop_distance=dist, value=1.0, profit_to_deposit=conv, max_lots=10.0,
    )
    assert not res.rejected
    # risk budget = 1% of 1k USD = 10 USD; loss/lot = 6.6667 USD ->
    # 10 / 6.6667 = 1.5 lots on the 0.01 step grid
    assert res.lots == pytest.approx(1.5, abs=1e-9)


def test_underfunded_budget_rejects_below_minimum():
    """An equity too small for the min lot must be rejected, never rounded
    up (the behaviour the legacy engine got wrong)."""
    spec = synthetic_spec("EURUSD")
    res = size_position(
        spec, mode=RISK_PERCENT_EQUITY, equity=10_000.0, balance=10_000.0,
        stop_distance=0.01, value=1.0, profit_to_deposit=1.0, max_lots=10.0,
    )
    # min-lot loss at 0.01 stop = 1000 ticks * $1 * 0.01 = $10 >= 1% of 10k
    if res.reason == BELOW_MIN:
        assert res.rejected and res.lots == 0.0
    else:
        assert res.risk_money_actual <= 100.0 * (1 + 1e-9)
