"""Gate engine tests (mission §21): thresholds come from the policy
(SPEC defaults), missing evidence is SKIP (never a pass), and the
policy version is recorded."""

from __future__ import annotations

from mql5bot.factory.gates import (
    GATE_IDS,
    default_policy,
    evaluate_gates,
    overall,
    policy_hash,
)

GOOD = {
    "schema_valid": True, "semantic_ok": True, "n_trades": 250,
    "years": 3.2, "pf": 1.5, "max_dd_pct": 12.0,
    "top10_profit_share": 0.3, "positive_quarters_share": 0.7,
    "edge_to_cost": 4.0, "pf_under_cost_stress": 1.2,
    "param_sensitivity_dd_ratio": 1.1, "wfe": 0.4, "pbo": 0.2,
    "dsr_p": 0.95, "mc_p05_dd_pct": 25.0,
    "positive_in_expected_regime": True,
    "max_correlation_with_book": 0.4, "marginal_heat_add": 0.03,
}


def test_all_ten_research_gates_present():
    v = evaluate_gates(default_policy(), GOOD)
    assert {x.gate for x in v} == set(GATE_IDS)
    assert overall(v) == "PASS"


def test_spec_thresholds_enforced_not_watered():
    policy = default_policy()
    assert policy["gate2_backtest"]["min_trades"] == 200
    assert policy["gate2_backtest"]["min_pf"] == 1.3
    assert policy["gate2_backtest"]["max_dd_pct"] == 20.0
    # a candidate just under any threshold FAILs
    m = dict(GOOD, n_trades=199)
    v = {x.gate: x for x in evaluate_gates(policy, m)}
    assert v["gate2_backtest"].status == "FAIL"
    assert any("199" in r for r in v["gate2_backtest"].reasons)


def test_missing_evidence_is_skip_and_blocks():
    m = {k: v for k, v in GOOD.items() if k != "pbo"}
    verdicts = evaluate_gates(default_policy(), m)
    v = {x.gate: x for x in verdicts}
    assert v["gate6_cpcv_pbo"].status == "SKIP"
    assert "SKIP" in v["gate6_cpcv_pbo"].reasons[0] or \
        "CPCV" in v["gate6_cpcv_pbo"].reasons[0]
    assert overall(verdicts) == "SKIP"


def test_policy_hash_binds_thresholds_to_runs():
    p1 = default_policy()
    p2 = default_policy()
    assert policy_hash(p1) == policy_hash(p2)
    changed = default_policy()
    changed["gate2_backtest"]["min_pf"] = 9.9
    assert policy_hash(changed) != policy_hash(p1)


def test_cost_stress_and_mc_and_regime_gates_fire():
    policy = default_policy()
    v = {x.gate: x for x in evaluate_gates(
        policy, dict(GOOD, pf_under_cost_stress=0.9))}
    assert v["gate3_costs"].status == "FAIL"
    v = {x.gate: x for x in evaluate_gates(
        policy, dict(GOOD, mc_p05_dd_pct=55.0))}
    assert v["gate7_monte_carlo"].status == "FAIL"
    v = {x.gate: x for x in evaluate_gates(
        policy, dict(GOOD, positive_in_expected_regime=False))}
    assert v["gate8_regime"].status == "FAIL"
    v = {x.gate: x for x in evaluate_gates(
        policy, dict(GOOD, max_correlation_with_book=0.97))}
    assert v["gate9_portfolio"].status == "FAIL"
    assert any("duplicates" in r
               for r in v["gate9_portfolio"].reasons)


def test_no_gate_can_pass_on_no_data():
    v = evaluate_gates(default_policy(), {})
    assert all(x.status == "SKIP" for x in v)
    assert overall(v) == "SKIP"
