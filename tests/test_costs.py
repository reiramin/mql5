"""Tests for the explicit execution cost model (mql5bot.costs, Phase 2)."""

import pytest
from mql5bot.costs import (
    COST_PROFILES,
    CostConfig,
    commission_cash,
    cost_profile,
    entry_fill,
    exit_fill,
    gap_blocks,
    pending_trigger_fill,
    spread_price,
    stop_fill,
    swap_charge,
    tp_fill,
)

POINT = 1e-5


def test_spread_and_entry_fill_conventions():
    # buy pays +spread/2, sell pays -spread/2 (mid-price convention)
    assert spread_price(2.0, POINT) == pytest.approx(2e-5)
    buy = entry_fill(1.10000, +1, spread_points=2.0, slippage_points=1.0, point=POINT)
    sell = entry_fill(1.10000, -1, spread_points=2.0, slippage_points=1.0, point=POINT)
    # surcharge = spread/2 + slippage = 2 points = 2e-5
    assert buy == pytest.approx(1.10000 + 2e-5)
    assert sell == pytest.approx(1.10000 - 2e-5)
    # round trip pays the full spread + slippage on both legs
    exit_buy = exit_fill(1.10100, +1, spread_points=2.0, slippage_points=1.0,
                         point=POINT)
    assert exit_buy == pytest.approx(1.10100 - 2e-5)


def test_commission_side_vs_round_trip():
    cfg_side = CostConfig(commission_per_lot=7.0)
    assert commission_cash(0.5, cfg_side) == pytest.approx(3.5)
    cfg_rt = CostConfig(commission_per_lot=7.0, commission_per_round_trip=True)
    # half at entry, half at exit -> full round trip still 7.0 * lots
    assert commission_cash(0.5, cfg_rt) == pytest.approx(1.75)
    assert commission_cash(0.5, cfg_rt) + commission_cash(0.5, cfg_rt) == pytest.approx(3.5)
    cfg_min = CostConfig(commission_per_lot=0.0, commission_min=1.0)
    assert commission_cash(0.01, cfg_min) == pytest.approx(0.0)  # no per-lot rate
    cfg_min2 = CostConfig(commission_per_lot=1.0, commission_min=2.0)
    assert commission_cash(0.1, cfg_min2) == pytest.approx(2.0)  # floor at min


def test_swap_charge_sign_and_side():
    # rates are costs per lot per day (positive values)
    cfg = CostConfig(swap_long_per_lot_day=2.5, swap_short_per_lot_day=1.5)
    assert swap_charge(+1, 1.0, cfg) == pytest.approx(2.5)   # long pays 2.5/day
    assert swap_charge(-1, 1.0, cfg) == pytest.approx(1.5)
    assert swap_charge(+1, 0.5, cfg, days_held=3) == pytest.approx(3.75)


def test_gap_blocking():
    cfg_open = CostConfig(max_gap_fraction=0.01)
    assert not gap_blocks(1.1000, 1.1000, cfg_open)
    assert not gap_blocks(1.1005, 1.1000, cfg_open)
    assert gap_blocks(1.1120, 1.1000, cfg_open)
    cfg_off = CostConfig(max_gap_fraction=float("inf"))
    assert not gap_blocks(2.0, 1.0, cfg_off)


def test_stop_fill_worst_case():
    cfg = CostConfig(slippage_points=1.0)
    # long stop hit intrabar -> fill at stop minus slippage
    hit, price = stop_fill(1.1000, 1.0950, 1.1020, +1, 1.0960, cfg, POINT)
    assert hit and price == pytest.approx(1.0960 - POINT)
    # gap through the stop -> fill at the (worse) open
    hit, price = stop_fill(1.0940, 1.0935, 1.0941, +1, 1.0960, cfg, POINT)
    assert hit and price == pytest.approx(1.0940)
    # short stop mirror
    hit, price = stop_fill(1.1000, 1.0980, 1.1045, -1, 1.1030, cfg, POINT)
    assert hit and price == pytest.approx(1.1030 + POINT)
    # not touched
    hit, _ = stop_fill(1.1000, 1.0980, 1.1010, +1, 1.0960, cfg, POINT)
    assert not hit


def test_tp_fill_no_adverse_slippage():
    cfg = CostConfig(slippage_points=5.0)  # slippage must not hurt a limit
    hit, price = tp_fill(1.1000, 1.0960, 1.1050, +1, 1.1040, cfg, POINT)
    assert hit and price == pytest.approx(1.1040)
    # gap beyond TP -> fill at open (better), still recorded at open price
    hit, price = tp_fill(1.1060, 1.1055, 1.1062, +1, 1.1040, cfg, POINT)
    assert hit and price == pytest.approx(1.1060)
    hit, price = tp_fill(1.1000, 1.0950, 1.1010, -1, 1.0970, cfg, POINT)
    assert hit and price == pytest.approx(1.0970)


def test_pending_stop_entry():
    cfg = CostConfig(slippage_points=1.0)
    # buy stop triggered intrabar at 1.1050
    hit, price = pending_trigger_fill(1.1000, 1.0990, 1.1060, +1, 1.1050, cfg, POINT)
    assert hit and price == pytest.approx(1.1050 + POINT)
    # opens beyond trigger -> fill at open + slippage
    hit, price = pending_trigger_fill(1.1070, 1.1065, 1.1075, +1, 1.1050, cfg, POINT)
    assert hit and price == pytest.approx(1.1070 + POINT)
    # not triggered
    hit, _ = pending_trigger_fill(1.1000, 1.0990, 1.1040, +1, 1.1050, cfg, POINT)
    assert not hit


def test_validation_errors():
    with pytest.raises(ValueError, match="spread_mode"):
        CostConfig(spread_mode="quantum").validate()
    with pytest.raises(ValueError, match="spread_series"):
        CostConfig(spread_mode="variable").validate()
    with pytest.raises(ValueError, match="length"):
        CostConfig(spread_mode="variable", spread_series=[1.0, 2.0]).validate(n_bars=3)
    with pytest.raises(ValueError, match="entry_mode"):
        CostConfig(entry_mode="iceberg").validate()
    with pytest.raises(ValueError, match="max_gap"):
        CostConfig(max_gap_fraction=0.0).validate()


def test_variable_spread_series_and_reject_mask():
    cfg = CostConfig(spread_mode="variable", spread_series=[1.0, 2.0, 3.0],
                     reject_mask=[False, True, False])
    cfg.validate(n_bars=3)
    assert cfg.spread_at(0) == 1.0 and cfg.spread_at(2) == 3.0
    assert not cfg.rejects(0) and cfg.rejects(1)


# ---------------------------------------------------------------------------
# deterministic cost profiles ZERO / BASE / STRESSED / SEVERE / EXTREME
# ---------------------------------------------------------------------------


def test_cost_profile_validation_and_determinism():
    assert COST_PROFILES == ("ZERO", "BASE", "STRESSED", "SEVERE", "EXTREME")
    with pytest.raises(ValueError):
        cost_profile("NO_SUCH_PROFILE")
    # case-insensitive; identical calls return identical configs
    assert cost_profile("stressed") == cost_profile("STRESSED")
    # profiles validate as standalone configs
    for p in COST_PROFILES:
        cost_profile(p).validate()
    # overrides tune individual fields
    cfg = cost_profile("BASE", symbol="XAUUSD", spread_points=2.0)
    assert cfg.symbol == "XAUUSD" and cfg.spread_points == 2.0
    assert cfg.slippage_points == 0.25  # untouched fields keep the preset


def test_zero_profile_is_cost_free():
    z = cost_profile("ZERO")
    assert z.spread_points == 0.0
    assert z.slippage_points == 0.0
    assert z.commission_per_lot == 0.0 and z.commission_min == 0.0
    assert z.swap_long_per_lot_day == 0.0 and z.swap_short_per_lot_day == 0.0
    assert z.max_gap_fraction == float("inf")
    assert z.reject_mask is None and z.spread_mode == "fixed"


def test_profiles_escalate_field_by_field():
    """Each later profile is >= harsher on every cost dimension, so any
    identical trade path costs monotonically more (the engine integration
    test asserts that on the ledger)."""
    fields = (
        "spread_points", "slippage_points", "commission_per_lot",
        "commission_min", "swap_long_per_lot_day", "swap_short_per_lot_day",
    )
    prev = cost_profile("ZERO")
    for name in COST_PROFILES[1:]:
        cur = cost_profile(name)
        for f in fields:
            assert cur.__getattribute__(f) >= prev.__getattribute__(f), \
                f"{name}.{f} regressed below {COST_PROFILES[COST_PROFILES.index(name) - 1]}"
        # every preset raises the core three strictly over the previous one
        assert cur.spread_points > prev.spread_points
        assert cur.slippage_points > prev.slippage_points
        assert cur.commission_per_lot > prev.commission_per_lot
        # gap limit only ever tightens (inf -> finite -> smaller)
        assert cur.max_gap_fraction <= prev.max_gap_fraction
        prev = cur
