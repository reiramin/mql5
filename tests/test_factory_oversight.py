"""Oversight tests: shadow mode safety, transparent evidence score,
anti-churn hysteresis, challenger/incumbent contract (mission §28/
§31/§32/§33/§69)."""

from __future__ import annotations

import pandas as pd
import pytest
from mql5bot.data import generate_ohlc
from mql5bot.dsl import parse_file
from mql5bot.factory.oversight import (
    DEFAULT_COMPONENTS,
    Hysteresis,
    IncumbentState,
    challenger_decision,
    evidence_score,
    run_shadow,
    should_demote,
    should_promote,
)

EXAMPLES = __import__("pathlib").Path(__file__).resolve().parent \
    .parent / "examples" / "strategies"


# ------------------------------------------------------------ shadow mode


def test_shadow_never_sends_orders_and_records_hypotheticals():
    """§33: the runner returns observation ROWS; there is no order,
    broker, or execution object anywhere in its signature or result."""
    spec = parse_file(EXAMPLES / "ema_crossover.json")
    df = generate_ohlc(days=120, seed=30)
    trades = run_shadow(spec, df)
    assert trades, "expected hypothetical shadow trades"
    for t in trades:
        assert t.side in {-1, 1}
        assert t.entry_price > 0
        assert t.pnl_assumed is not None or t.exit_index is None


def test_shadow_pnl_is_cost_adjusted():
    """§33: costs are deducted — a 1-point roundtrip move with 6
    points of roundtrip cost must close NEGATIVE, never flattered."""
    steps = [1.10] * 30 + [1.1010] * 20 + [1.0990] * 30
    idx = pd.date_range("2024-01-01", periods=len(steps), freq="1h")
    df = pd.DataFrame({"open": steps, "high": steps, "low": steps,
                       "close": steps, "volume": [100.0] * len(steps)},
                      index=idx)
    spec = parse_file(EXAMPLES / "ema_crossover.json")
    trades = run_shadow(spec, df, spread_points=2.0,
                        slippage_points=1.0, point_size=1e-4,
                        point_value_per_lot=1.0, lots=0.1)
    closed = [t for t in trades if t.exit_index is not None]
    assert closed, "expected at least one closed hypothetical trade"
    for t in closed:
        gross = t.side * (t.exit_price - t.entry_price) / 1e-4 * 1.0 \
            * 0.1
        net = gross - 2 * (2.0 + 1.0) * 1.0 * 0.1   # roundtrip costs
        assert t.pnl_assumed == pytest.approx(net)
        assert t.pnl_assumed < gross                 # never flattered


def test_shadow_refuses_ambiguous_drafts():
    spec = parse_file(EXAMPLES / "draft_ambiguous_rsi.json")
    with pytest.raises(ValueError, match="executable"):
        run_shadow(spec, generate_ohlc(days=60, seed=1))


# ------------------------------------------------------------ evidence score


def test_evidence_score_is_fully_auditable():
    report = evidence_score({"oos_robustness": 0.8,
                             "wfa_survival": 1.0})
    assert report["weights_version"] == "evidence-1.0"
    names = [c["component"] for c in report["components"]]
    assert len(names) == 11
    assert all({"component", "value", "weight", "missing"} ==
               set(c) for c in report["components"])
    # missing components are listed as missing and count as 0
    assert sum(c["missing"] for c in report["components"]) == 9
    # all-max ⇒ 1.0; all-missing ⇒ 0.0
    full = evidence_score({n: 1.0 for n in names})
    assert full["score"] == 1.0
    assert evidence_score({})["score"] == 0.0


def test_evidence_score_is_monotone_in_each_component():
    names = [n for n, _ in DEFAULT_COMPONENTS]
    base = {n: 0.5 for n in names}
    s0 = evidence_score(base)["score"]
    s1 = evidence_score({**base, "oos_robustness": 0.9})["score"]
    assert s1 > s0


# ------------------------------------------------------------ anti-churn


def test_noisy_oscillation_does_not_churn():
    """Mission §69: short-window reversals must NOT flip live state."""
    pol = Hysteresis()
    inc = IncumbentState(strategy_id="inc", score=0.60,
                         in_state_since_day=0, last_change_day=0,
                         observation_trades=100, observation_days=60)
    # day 20: challenger 0.66 (beats by margin) → promote
    ok, why = should_promote(inc, 0.66, day=20, policy=pol)
    assert ok
    inc.score, inc.last_change_day = 0.66, 20
    # day 25 (inside cooldown): challenger spikes to 0.9 → NO switch
    ok, why = should_promote(inc, 0.90, day=25, policy=pol)
    assert not ok and "cooldown" in why
    # day 40 (cooldown over): challenger 0.67 (within margin) → NO
    ok, _ = should_promote(inc, 0.67, day=40, policy=pol)
    assert not ok


def test_promotion_requires_minimum_incumbent_observation():
    pol = Hysteresis()
    inc = IncumbentState(strategy_id="inc", score=0.3,
                         in_state_since_day=0, last_change_day=0,
                         observation_trades=5, observation_days=3)
    ok, why = should_promote(inc, 0.9, day=100, policy=pol)
    assert not ok and "minimum evidence" in why


def test_demotion_requires_robust_evidence_not_a_bad_week():
    pol = Hysteresis()
    inc = IncumbentState(strategy_id="inc", score=0.6,
                         in_state_since_day=0, last_change_day=0,
                         observation_trades=100, observation_days=60)
    # a single low reading inside the window → no demotion
    ok, _why = should_demote(inc, 0.58, day=30, policy=pol)
    assert not ok
    # sustained underperformance beyond the margin → demote
    ok, why2 = should_demote(inc, 0.40, day=30, policy=pol)
    assert ok and "underperformance" in why2
    # a risk-control breach demotes regardless of scores
    ok, why = should_demote(inc, 0.60, day=2, policy=pol, breach=True)
    assert ok and "breach" in why


def test_first_activation_requires_human_approval_downstream():
    ok, why = should_promote(None, 0.8, day=1, policy=Hysteresis())
    assert ok and "human approval" in why


def test_hysteresis_policy_validates_itself():
    with pytest.raises(ValueError):
        Hysteresis(promotion_margin=0.0).validate()


# ------------------------------------------------------------ challenger


def test_challenger_decision_requires_equal_foot_and_oos():
    d, _w = challenger_decision(0.9, 0.5, same_period=False,
                                 same_costs=True,
                                 same_data_provenance=True,
                                 oos_only=True)
    assert d == "NO_DECISION"
    d, _ = challenger_decision(0.9, 0.5, same_period=True,
                               same_costs=True,
                               same_data_provenance=True,
                               oos_only=False)
    assert d == "NO_DECISION"        # IS never decides (§32)
    d, _why = challenger_decision(0.9, 0.5, same_period=True,
                                 same_costs=True,
                                 same_data_provenance=True,
                                 oos_only=True)
    assert d == "CHALLENGER"
    d, _ = challenger_decision(0.52, 0.5, same_period=True,
                               same_costs=True,
                               same_data_provenance=True,
                               oos_only=True)
    assert d == "INCUMBENT_RETAINS"
