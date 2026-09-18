"""AEGIS Phase 10 — execution stress scenarios.

Pins: every mandated dimension is exercised (mutators actually mutate),
every scenario is deterministic and preserves the accounting identity,
swap/gap-rejection scenarios produce NONZERO effects on the fixture (the
dimension is really stressed, not silently a no-op), the report marks
not-modelled live-path dimensions instead of inventing numbers, and no
universal degradation threshold exists anywhere in the module.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

from mql5bot.backtest import run_backtest
from mql5bot.data import generate_ohlc
from mql5bot.stress import (
    NOT_MODELLED,
    SCENARIOS,
    gaps,
    observed_table,
    render_report,
    spikes,
)

BASE_KWARGS = {"spread_points": 1.0, "commission_per_lot": 7.0}


@pytest.fixture(scope="module")
def df():
    return generate_ohlc(days=365, seed=5)


def test_all_mandated_dimensions_present():
    dims = {sc.dimension for sc in SCENARIOS}
    assert {"spread", "slippage", "commission", "swap", "spikes", "gaps",
            "gap_rejection", "combined", "baseline"} <= dims


def test_mutators_actually_mutate(df):
    spiked = spikes(df)
    gapped = gaps(df)
    assert not spiked["low"].equals(df["low"]) or \
        not spiked["high"].equals(df["high"])
    assert not gapped["open"].equals(df["open"])
    # OHLC consistency preserved by both mutators
    for m in (spiked, gapped):
        assert (m["high"] >= m[["open", "close"]].max(axis=1) - 1e-12).all()
        assert (m["low"] <= m[["open", "close"]].min(axis=1) + 1e-12).all()


def test_every_scenario_runs_and_preserves_accounting_identity(df):
    for sc in SCENARIOS:
        from mql5bot.stress import run_scenario
        res = run_scenario(df, sc, **BASE_KWARGS)
        assert len(res.equity) > 0
        total = res.trades["pnl"].sum()
        assert res.equity.iloc[-1] == pytest.approx(10000.0 + total, abs=1e-6)


def test_scenarios_are_deterministic(df):
    from mql5bot.stress import run_scenario
    for sc in SCENARIOS:
        r1 = run_scenario(df, sc, **BASE_KWARGS)
        r2 = run_scenario(df, sc, **BASE_KWARGS)
        assert r1.equity.equals(r2.equity)
        assert r1.trades.equals(r2.trades)


def test_cost_and_data_stresses_actually_bite(df):
    """The stress dimensions must NOT be silent no-ops on the fixture:
    swap charges on overnight carries, spikes trigger stops, gap-reject
    changes entry selection on gapped data."""
    rows = {r["scenario"]: r for r in observed_table(df, **BASE_KWARGS)}
    assert rows["SWAP_STRESS"]["delta_net"] != 0.0
    assert rows["SPIKES"]["delta_net"] < 0.0          # wicks hurt a reversal
    assert rows["SPIKES"]["trades"] != rows["BASE"]["trades"]
    assert rows["GAP_REJECT_1PCT"]["trades"] != rows["GAPS"]["trades"]


def test_degradation_can_be_improvement_for_some_strategy_classes(df):
    """Honest observation, pinned: gaps give a mean-reversion entry better
    prices — the table records ACTUAL deltas, which may be positive. This
    is exactly why no universal '30–50% worse' gate exists."""
    rows = {r["scenario"]: r for r in observed_table(df, **BASE_KWARGS)}
    assert rows["GAPS"]["delta_net"] > 0.0


def test_report_marks_not_modelled_and_has_no_threshold_gate():
    assert set(NOT_MODELLED) >= {"latency", "partial_fills", "rejections"}
    report = render_report(
        [{"scenario": "BASE", "dimension": "baseline", "description": "d",
          "net_profit": 1.0, "delta_net": 0.0, "profit_factor": 1.0,
          "sharpe": 0.0, "max_drawdown": -0.1, "trades": 1}])
    for dim in NOT_MODELLED:
        assert dim in report
    assert "never a gate" in report
    assert "no target, no" in report


def test_wrapper_validates_new_cost_kwargs(df):
    with pytest.raises(ValueError, match="max_gap_fraction"):
        run_backtest(df, "bollinger_reversal", {}, max_gap_fraction=0.0)
    with pytest.raises(ValueError, match="costs must be >= 0"):
        run_backtest(df, "bollinger_reversal", {}, commission_min=-1.0)


def test_gap_rejection_masks_only_large_gap_entries(df):
    g = gaps(df)
    base = run_backtest(g, "bollinger_reversal", {}, **BASE_KWARGS)
    rejected = run_backtest(g, "bollinger_reversal", {},
                            max_gap_fraction=0.01, **BASE_KWARGS)
    assert len(rejected.trades) <= len(base.trades)
    # entries in the rejected run never sit on a >1%-gap bar
    oc = g["open"] / g["close"].shift(1)
    for t in rejected.trades.itertuples():
        gap_frac = abs(float(oc.loc[t.entry_time]) - 1.0)
        assert gap_frac <= 0.01 + 1e-12
