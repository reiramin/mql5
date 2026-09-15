"""mql5bot.factory.gates — the versioned gate engine (mission §21).

Gates 0–9 evaluate RESEARCH evidence; Gates 10–12 (shadow, demo,
live-small) evaluate OBSERVATION evidence and are marked by run_type
with the same engine.

THRESHOLD POLICY (no invented numbers — mission §21): every threshold
comes from ``factory/gates.yaml`` whose defaults are the SPEC §10.4
Gate-1 numbers and DECISIONS §4.12 rules.  The policy file is hashed
into every run (config_hash) so results are reproducible against the
exact thresholds used.

The engine consumes ALREADY-MEASURED metrics (from the canonical
research tooling) and returns per-gate verdicts with the evidence it
used.  It never computes performance itself and never sees future
data — measurement happens in the pipeline, gating is a pure verdict.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

GATES_POLICY_PATH = Path(__file__).resolve().parents[3] / "factory" \
    / "gates.yaml"

GATE_VERSION = "gates-1.0.0"

# gate id → the metrics it consumes (documentation + validation)
GATE_IDS = ("gate0_schema", "gate1_semantic", "gate2_backtest",
            "gate3_costs", "gate4_robustness", "gate5_walk_forward",
            "gate6_cpcv_pbo", "gate7_monte_carlo", "gate8_regime",
            "gate9_portfolio")


def default_policy() -> dict:
    if GATES_POLICY_PATH.exists():
        return yaml.safe_load(GATES_POLICY_PATH.read_text())
    return {
        "policy_version": "spec-10.4-defaults",
        "gate2_backtest": {
            "min_trades": 200, "min_years": 3.0, "min_pf": 1.3,
            "max_dd_pct": 20.0, "max_top10_profit_share": 0.5,
            "min_positive_quarters_share": 0.6,
            "min_edge_to_cost": 3.0},
        "gate3_costs": {"stress_cost_multiplier": 2.0,
                        "require_profitable_under_stress": True},
        "gate4_robustness": {"max_param_sensitivity_dd_ratio": 2.0},
        "gate5_walk_forward": {"min_wfe": 0.0},
        "gate6_cpcv_pbo": {"max_pbo": 0.5, "min_dsr_p": 0.90},
        "gate7_monte_carlo": {"max_p05_dd_pct": 40.0},
        "gate8_regime": {"require_positive_in_expected_regime": True},
        "gate9_portfolio": {"max_correlation_with_book": 0.85,
                            "max_marginal_heat_add": 0.10},
        "gate10_shadow": {"min_weeks": 4, "min_trades": 30},
        "gate11_demo": {"min_weeks": 4, "min_trades": 30},
        "gate12_live_small": {"min_weeks": 8, "max_dd_since_start_pct": 10.0},
    }


def policy_hash(policy: dict) -> str:
    return hashlib.sha256(json.dumps(
        policy, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


@dataclass
class GateVerdict:
    gate: str
    status: str                     # PASS | FAIL | SKIP
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"gate": self.gate, "status": self.status,
                "reasons": self.reasons}


def _check(verdicts: list, gate: str, ok: bool, fail_reason: str,
           skip_reason: str | None = None) -> None:
    if skip_reason:
        verdicts.append(GateVerdict(gate, "SKIP", [skip_reason]))
    elif ok:
        verdicts.append(GateVerdict(gate, "PASS", []))
    else:
        verdicts.append(GateVerdict(gate, "FAIL", [fail_reason]))


def evaluate_gates(policy: dict, m: dict) -> list[GateVerdict]:
    """Verdicts for gates 0–9 from a measured-metrics dict ``m``.

    Expected keys (only those needed by enabled gates; missing input
    ⇒ SKIP with the reason, never an invented pass):
    schema_valid, semantic_ok, n_trades, years, pf, max_dd_pct,
    top10_profit_share, positive_quarters_share, edge_to_cost,
    pf_under_cost_stress, param_sensitivity_dd_ratio, wfe, pbo,
    dsr_p, mc_p05_dd_pct, positive_in_expected_regime,
    max_correlation_with_book, marginal_heat_add.
    """
    g2 = policy.get("gate2_backtest", {})
    g3 = policy.get("gate3_costs", {})
    g6 = policy.get("gate6_cpcv_pbo", {})
    g7 = policy.get("gate7_monte_carlo", {})
    g9 = policy.get("gate9_portfolio", {})
    out: list[GateVerdict] = []

    # Gate 0 — schema
    if "schema_valid" not in m:
        _check(out, "gate0_schema", False, "", "no schema result supplied")
    else:
        _check(out, "gate0_schema", bool(m["schema_valid"]),
               "DSL schema invalid")

    # Gate 1 — semantic lints (missing SL etc.)
    if "semantic_ok" not in m:
        _check(out, "gate1_semantic", False, "", "no lint result supplied")
    else:
        _check(out, "gate1_semantic", bool(m["semantic_ok"]),
               "semantic lints failed (e.g. missing SL)")

    # Gate 2 — backtest (SPEC §10.4 numbers)
    need2 = {"n_trades", "years", "pf", "max_dd_pct"}
    if not need2 <= set(m):
        _check(out, "gate2_backtest", False, "",
               f"missing measurements: {sorted(need2 - set(m))}")
    else:
        reasons = []
        if m["n_trades"] < g2.get("min_trades", 200):
            reasons.append(f"trades {m['n_trades']} < "
                           f"{g2.get('min_trades', 200)}")
        if m["years"] < g2.get("min_years", 3.0):
            reasons.append(f"history {m['years']}y < "
                           f"{g2.get('min_years', 3.0)}y")
        if m["pf"] < g2.get("min_pf", 1.3):
            reasons.append(f"PF {m['pf']} < {g2.get('min_pf', 1.3)}")
        if m["max_dd_pct"] > g2.get("max_dd_pct", 20.0):
            reasons.append(f"maxDD {m['max_dd_pct']}% > "
                           f"{g2.get('max_dd_pct', 20.0)}%")
        if "top10_profit_share" in m and \
                m["top10_profit_share"] > g2.get(
                    "max_top10_profit_share", 0.5):
            reasons.append("top-10% trades carry too much of the profit")
        if "positive_quarters_share" in m and \
                m["positive_quarters_share"] < g2.get(
                    "min_positive_quarters_share", 0.6):
            reasons.append("too few positive quarters")
        if "edge_to_cost" in m and \
                m["edge_to_cost"] < g2.get("min_edge_to_cost", 3.0):
            reasons.append("edge-to-cost below 3")
        _check(out, "gate2_backtest", not reasons, "; ".join(reasons))

    # Gate 3 — costs under stress
    if "pf_under_cost_stress" not in m:
        _check(out, "gate3_costs", False, "",
               "no cost-stress measurement supplied")
    else:
        mult = g3.get("stress_cost_multiplier", 2.0)
        ok = m["pf_under_cost_stress"] > 1.0
        _check(out, "gate3_costs", ok,
               f"not profitable under {mult}x costs")

    # Gate 4 — robustness (parameter perturbation)
    if "param_sensitivity_dd_ratio" not in m:
        _check(out, "gate4_robustness", False, "",
               "no perturbation measurement supplied")
    else:
        cap = policy.get("gate4_robustness", {}).get(
            "max_param_sensitivity_dd_ratio", 2.0)
        _check(out, "gate4_robustness",
               m["param_sensitivity_dd_ratio"] <= cap,
               f"perturbation DD ratio {m['param_sensitivity_dd_ratio']}"
               f" > {cap}")

    # Gate 5 — walk-forward efficiency
    if "wfe" not in m:
        _check(out, "gate5_walk_forward", False, "",
               "no WFA measurement supplied")
    else:
        min_wfe = policy.get("gate5_walk_forward", {}).get("min_wfe", 0.0)
        _check(out, "gate5_walk_forward", m["wfe"] > min_wfe,
               f"WFE {m['wfe']} <= {min_wfe}")

    # Gate 6 — CPCV/PBO/DSR
    if "pbo" not in m:
        _check(out, "gate6_cpcv_pbo", False, "",
               "no CPCV/PBO measurement supplied")
    else:
        reasons = []
        max_pbo = g6.get("max_pbo", 0.5)
        if m["pbo"] > max_pbo:
            reasons.append(f"PBO {m['pbo']} > {max_pbo}")
        if "dsr_p" in m and m["dsr_p"] < g6.get("min_dsr_p", 0.90):
            reasons.append(f"DSR p {m['dsr_p']} < "
                           f"{g6.get('min_dsr_p', 0.90)}")
        _check(out, "gate6_cpcv_pbo", not reasons, "; ".join(reasons))

    # Gate 7 — Monte Carlo
    if "mc_p05_dd_pct" not in m:
        _check(out, "gate7_monte_carlo", False, "",
               "no Monte-Carlo measurement supplied")
    else:
        cap = g7.get("max_p05_dd_pct", 40.0)
        _check(out, "gate7_monte_carlo", m["mc_p05_dd_pct"] <= cap,
               f"MC p05 DD {m['mc_p05_dd_pct']}% > {cap}%")

    # Gate 8 — regime
    if "positive_in_expected_regime" not in m:
        _check(out, "gate8_regime", False, "",
               "no regime-partition measurement supplied")
    else:
        need = policy.get("gate8_regime", {}).get(
            "require_positive_in_expected_regime", True)
        _check(out, "gate8_regime",
               bool(m["positive_in_expected_regime"]) or not need,
               "not positive in its declared expected regime")

    # Gate 9 — portfolio interaction
    reasons = []
    if "max_correlation_with_book" in m and \
            m["max_correlation_with_book"] > g9.get(
                "max_correlation_with_book", 0.85):
        reasons.append("duplicates the existing book")
    if "marginal_heat_add" in m and \
            m["marginal_heat_add"] > g9.get("max_marginal_heat_add",
                                            0.10):
        reasons.append("marginal portfolio heat too high")
    if not ("max_correlation_with_book" in m
            or "marginal_heat_add" in m):
        _check(out, "gate9_portfolio", False, "",
               "no portfolio-interaction measurement supplied")
    else:
        _check(out, "gate9_portfolio", not reasons, "; ".join(reasons))
    return out


def overall(verdicts: list[GateVerdict]) -> str:
    """PASS only when every gate passed; any FAIL blocks; SKIP blocks
    research-gate progression too (missing evidence is not a pass)."""
    statuses = {v.status for v in verdicts}
    if "FAIL" in statuses:
        return "FAIL"
    if "SKIP" in statuses:
        return "SKIP"
    return "PASS"
