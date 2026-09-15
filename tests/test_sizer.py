"""Tests for the canonical risk sizer (SPEC §8.C, DoD #9/#10).

Runs the exact same arithmetic on the five synthetic broker specs that the
MQL5 port must pass: EURUSD 5-digit, USDJPY, XAUUSD, US30-like index and
BTCUSD-like crypto — clamping, margin rejection, stop enforcement, floor-to-
step volume and risk-budget adherence.
"""

import pytest
from mql5bot.sizer import (
    BELOW_MIN,
    CLAMPED_TO_MAX,
    FIXED_LOT,
    FIXED_MONEY,
    KELLY_FRACTION,
    MARGIN_REDUCED,
    MARGIN_REJECTED,
    MISSING_STOP,
    NO_EDGE,
    OK,
    RISK_PERCENT_BALANCE,
    RISK_PERCENT_EQUITY,
    kelly_fraction,
    size_position,
)
from mql5bot.symbolspec import SymbolSpec
from test_symbolspec import make_specs


@pytest.fixture(scope="module")
def specs() -> dict[str, SymbolSpec]:
    return make_specs()


def _usdjpy_conv() -> float:
    """JPY -> USD conversion used by the USDJPY assertions."""
    return 1.0 / 150.0


# ---------------------------------------------------------------------------
# Hand-computed lot sizes on the five synthetic specs
# ---------------------------------------------------------------------------


def test_eurusd_five_digit_hand_calc(specs):
    """risk 1% of 10k = 100 USD; stop 0.0020 = 200 ticks x $1 = 200/lot ->
    0.50 lots exactly."""
    res = size_position(
        specs["EURUSD"], mode=RISK_PERCENT_EQUITY, equity=10_000.0,
        value=1.0, stop_distance=0.0020,
    )
    assert res.reason == OK and not res.rejected
    assert res.lots == pytest.approx(0.50)
    assert res.loss_per_lot_ccy == pytest.approx(200.0)
    assert res.risk_money_actual == pytest.approx(100.0)


def test_eurusd_floor_to_step_never_exceeds_budget(specs):
    """stop 0.0033 -> raw 0.3030... lots -> floored to 0.30; actual risk
    stays under the 100 USD budget."""
    res = size_position(
        specs["EURUSD"], equity=10_000.0, value=1.0, stop_distance=0.0033,
    )
    assert res.lots == pytest.approx(0.30)
    assert res.risk_money_actual <= res.risk_money_budget + 1e-9


def test_usdjpy_profit_currency_conversion(specs):
    """stop 0.300 JPY = 300 ticks x 100 JPY/tick = 30 000 JPY = 200 USD per
    lot at 1/150 -> 0.50 lots for a 100 USD budget."""
    res = size_position(
        specs["USDJPY"], equity=10_000.0, value=1.0, stop_distance=0.30,
        profit_to_deposit=_usdjpy_conv(),
    )
    assert res.reason == OK
    assert res.lots == pytest.approx(0.50)
    assert res.loss_per_lot_ccy == pytest.approx(200.0, rel=1e-9)


def test_usdjpy_requires_conversion(specs):
    """Forgetting the conversion factor is an error of 150x — the engine
    must not silently assume 1.0; the caller injects the rate."""
    with pytest.raises(ValueError):
        size_position(
            specs["USDJPY"], equity=10_000.0, value=1.0, stop_distance=0.30,
            profit_to_deposit=0.0,
        )


def test_xauusd_hand_calc(specs):
    """stop 5.00 = 500 ticks x $1 = 500/lot -> 0.20 lots."""
    res = size_position(
        specs["XAUUSD"], equity=10_000.0, value=1.0, stop_distance=5.0,
    )
    assert res.lots == pytest.approx(0.20)
    assert res.loss_per_lot_ccy == pytest.approx(500.0)


def test_us30_index_tick_grid_and_min_volume(specs):
    """stop 200.0 = 800 ticks (0.25) x $2.5 = 2000/lot; 1% of 200k = 2000 ->
    1.00 lot == exactly volume_min for the index grid."""
    res = size_position(
        specs["US30"], equity=200_000.0, value=1.0, stop_distance=200.0,
    )
    assert res.reason == OK
    assert res.lots == pytest.approx(1.0)


def test_us30_below_min_rejected(specs):
    """small account: raw size 0.04 < volume_min 1.0 -> rejected, never
    forced up to 1.0 (which would overshoot the 100 USD budget 25x)."""
    res = size_position(
        specs["US30"], equity=10_000.0, value=1.0, stop_distance=200.0,
    )
    assert res.rejected and res.reason == BELOW_MIN
    assert res.lots == 0.0


def test_btcusd_crypto_value_per_tick_decoupled(specs):
    """BTCUSD tick value (0.0105) is NOT tick_size*contract_size (0.01):
    sizing must use the injected tick value. stop 3000 = 300 000 ticks x
    0.0105 = 3150/lot -> 0.031746... -> floored to 0.031 lots."""
    res = size_position(
        specs["BTCUSD"], equity=10_000.0, value=1.0, stop_distance=3000.0,
    )
    assert res.reason == OK
    assert res.lots == pytest.approx(0.031)
    # risk stays below budget: 0.031 x 3150 = 97.65 <= 100
    assert res.risk_money_actual <= res.risk_money_budget


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def test_fixed_lot_mode(specs):
    res = size_position(
        specs["EURUSD"], mode=FIXED_LOT, equity=10_000.0, value=0.25,
        stop_distance=0.0020,
    )
    assert res.reason == OK
    assert res.lots == pytest.approx(0.25)
    # fixed lot ignores the equity budget: reported risk is 0.25 * 200 = 50
    assert res.risk_money_actual == pytest.approx(50.0)


def test_risk_percent_balance_mode(specs):
    res = size_position(
        specs["EURUSD"], mode=RISK_PERCENT_BALANCE, balance=20_000.0,
        equity=1.0, value=2.0, stop_distance=0.0020,
    )
    # 2% of 20 000 = 400 -> 2.00 lots (equity is irrelevant in this mode)
    assert res.lots == pytest.approx(2.0)
    assert res.risk_money_budget == pytest.approx(400.0)


def test_fixed_money_mode(specs):
    res = size_position(
        specs["EURUSD"], mode=FIXED_MONEY, value=500.0, stop_distance=0.0020,
    )
    assert res.lots == pytest.approx(2.5)
    assert res.risk_money_budget == pytest.approx(500.0)


def test_kelly_off_by_default(specs):
    res = size_position(
        specs["EURUSD"], mode=KELLY_FRACTION, equity=10_000.0, value=0.0,
        stop_distance=0.0020, win_rate=0.6, payoff_ratio=1.5,
    )
    assert res.rejected and res.reason == "invalid_args"


def test_kelly_capped_at_quarter(specs):
    """w=0.6, b=1.5 -> full Kelly 0.333 > cap 0.25 -> budget = 25% of 10k =
    2500; at 200 USD risk per lot that is 12.5 lots."""
    assert kelly_fraction(0.6, 1.5) == pytest.approx(1 / 3, rel=1e-9)
    res = size_position(
        specs["EURUSD"], mode=KELLY_FRACTION, equity=10_000.0, value=0.0,
        stop_distance=0.0020, win_rate=0.6, payoff_ratio=1.5,
        kelly_enabled=True, kelly_cap=0.25,
    )
    assert res.reason == OK
    assert res.lots == pytest.approx(12.5)
    assert res.risk_money_budget == pytest.approx(2500.0)


def test_kelly_no_edge_rejected(specs):
    res = size_position(
        specs["EURUSD"], mode=KELLY_FRACTION, equity=10_000.0, value=0.0,
        stop_distance=0.0020, win_rate=0.3, payoff_ratio=1.0,
        kelly_enabled=True,
    )
    assert res.rejected and res.reason == NO_EDGE


# ---------------------------------------------------------------------------
# Safety behaviour
# ---------------------------------------------------------------------------


def test_missing_stop_rejected(specs):
    res = size_position(specs["EURUSD"], equity=10_000.0, value=1.0,
                        stop_distance=0.0)
    assert res.rejected and res.reason == MISSING_STOP


def test_stops_level_enforced_inside_sizer(specs):
    """stop closer than the broker stops level is grown to the minimum
    before risk math: 10 points = 0.0001 = 10 ticks on EURUSD -> $10/lot ->
    100 USD budget buys 10 lots."""
    res = size_position(specs["EURUSD"], equity=10_000.0, value=1.0,
                        stop_distance=0.00005)
    assert res.reason == OK
    assert res.loss_per_lot_ccy == pytest.approx(10.0)
    assert res.lots == pytest.approx(10.0)


def test_max_lots_strategy_cap(specs):
    res = size_position(
        specs["EURUSD"], equity=10_000.0, value=1.0, stop_distance=0.00005,
        max_lots=2.0,
    )
    assert res.reason == CLAMPED_TO_MAX
    assert res.lots == pytest.approx(2.0)


def test_margin_reduction_step_by_step(specs):
    """XAUUSD margin = 2000/lot; free margin 300 fits 0.15 lots only; the
    requested 0.20 is reduced to 0.15 and flagged."""
    margin = lambda v: v * 2000.0
    res = size_position(
        specs["XAUUSD"], equity=10_000.0, value=1.0, stop_distance=5.0,
        margin_calc=margin, free_margin=300.0,
    )
    assert not res.rejected and res.reason == MARGIN_REDUCED
    assert res.lots == pytest.approx(0.15)


def test_margin_rejection_when_minimum_does_not_fit(specs):
    margin = lambda v: v * 2000.0
    res = size_position(
        specs["XAUUSD"], equity=10_000.0, value=1.0, stop_distance=5.0,
        margin_calc=margin, free_margin=10.0,
    )
    assert res.rejected and res.reason == MARGIN_REJECTED
    assert res.lots == 0.0


def test_margin_ok_unchanged(specs):
    margin = lambda v: v * 2000.0
    res = size_position(
        specs["XAUUSD"], equity=10_000.0, value=1.0, stop_distance=5.0,
        margin_calc=margin, free_margin=500.0,
    )
    assert res.reason == OK
    assert res.lots == pytest.approx(0.20)


def test_volume_limit_caps_like_broker(specs):
    """BTCUSD volume_limit = 50; a huge budget must still not exceed it."""
    res = size_position(
        specs["BTCUSD"], equity=100_000_000.0, value=1.0, stop_distance=3000.0,
    )
    assert res.reason == CLAMPED_TO_MAX
    assert res.lots == pytest.approx(50.0)


def test_invalid_args_rejected(specs):
    with pytest.raises(ValueError):
        # volume grid corrupted
        size_position(
            SymbolSpec(volume_step=0.0),  # overrides only the default spec
            equity=1000.0, value=1.0, stop_distance=0.01,
        )
    bad_mode = size_position(specs["EURUSD"], mode="lottery", equity=1000.0,
                             value=1.0, stop_distance=0.01)
    assert bad_mode.rejected


# ---------------------------------------------------------------------------
# Budget invariant sweep (deterministic)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("distance", [0.0021, 0.0047, 0.0099])
@pytest.mark.parametrize("equity", [5_000.0, 25_000.0])
def test_risk_never_exceeds_budget_across_grid(specs, distance, equity):
    for name, spec in specs.items():
        conv = _usdjpy_conv() if name == "USDJPY" else 1.0
        res = size_position(
            spec, equity=equity, value=1.0, stop_distance=distance,
            profit_to_deposit=conv,
        )
        if res.rejected:
            assert res.lots == 0.0
        else:
            assert res.lots > 0.0
            assert res.risk_money_actual <= res.risk_money_budget + 1e-6, name
