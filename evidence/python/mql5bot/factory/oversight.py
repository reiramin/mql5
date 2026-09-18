"""mql5bot.factory.oversight — shadow mode, evidence score, anti-churn
(mission §28/§31/§32/§33/§69).

Three cooperating pieces, all deterministic and auditable:

- :class:`ShadowRunner` — replays recent bars through a parsed DSL spec
  and records hypothetical entries/exits/PnL with EXPLICIT spread and
  slippage assumptions.  It never sends orders (structurally: it
  returns rows for ``shadow_observations``).
- :func:`evidence_score` — a transparent weighted average of named
  components (OOS robustness, WFA survival, …).  Every component and
  weight appears in the report — there is no hidden model.
- :class:`Hysteresis` — promotion/demotion margins, minimum evidence
  and cooldown so noisy short-window reversals cannot churn live
  strategies (§31/§69).  The incumbent keeps its seat unless a
  challenger beats it by the configured margin on OOS-only evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..dsl import StrategySpec, desired_positions

# ------------------------------------------------------------ shadow mode


@dataclass
class ShadowTrade:
    side: int
    entry_index: int
    exit_index: int | None
    entry_price: float
    exit_price: float | None
    pnl_assumed: float | None
    regime: str | None = None


def run_shadow(spec: StrategySpec, df: pd.DataFrame, *,
               spread_points: float = 2.0, slippage_points: float = 1.0,
               point_size: float = 1e-4,
               point_value_per_lot: float = 1.0, lots: float = 0.1,
               regime_series: np.ndarray | None = None,
               ) -> list[ShadowTrade]:
    """Hypothetical shadow replay over ``df`` (already-closed bars).

    Costs are DEDUCTED from the hypothetical PnL (spread + slippage on
    both sides) so shadow evidence is not flattered.  This is a
    research observation, never an order."""
    if not spec.executable:
        raise ValueError("shadow mode requires an executable spec")
    sig = desired_positions(spec, df, regime_series=regime_series)
    s = sig.to_numpy()
    o = df["open"].to_numpy(dtype=float)
    trades: list[ShadowTrade] = []
    pos = 0
    entry_i = -1
    for i in range(1, len(df)):
        want = int(s[i - 1])          # acts at bar i's open (engine rule)
        if want != 0 and pos == 0:
            pos, entry_i = want, i
        elif pos != 0 and want == -pos:
            trades.append(_close_shadow(pos, entry_i, i, o,
                                        spread_points, slippage_points,
                                        point_size, point_value_per_lot,
                                        lots, regime_series))
            pos, entry_i = want, i if want != 0 else -1
    if pos != 0:
        trades.append(_close_shadow(pos, entry_i, len(df) - 1, o,
                                    spread_points, slippage_points,
                                    point_size, point_value_per_lot,
                                    lots, regime_series, open_trade=True))
    return trades


def _close_shadow(pos, entry_i, exit_i, o, spread_points,
                  slippage_points, point_size, point_value_per_lot,
                  lots, regime_series, open_trade=False):
    entry_px = o[entry_i]
    exit_px = o[exit_i]
    cost_points = 2 * (spread_points + slippage_points)
    signed = pos * (exit_px - entry_px) / point_size
    # hypothetical PnL is COST-ADJUSTED: shadow evidence is never
    # flattered by ignoring spread/slippage (mission §33)
    pnl = (signed - cost_points) * point_value_per_lot * lots
    regime = None
    if regime_series is not None and entry_i < len(regime_series):
        regime = str(regime_series[entry_i])
    return ShadowTrade(
        side=pos, entry_index=entry_i,
        exit_index=None if open_trade else exit_i,
        entry_price=entry_px,
        exit_price=None if open_trade else exit_px,
        pnl_assumed=None if open_trade else pnl, regime=regime)


# ------------------------------------------------------------ evidence score


DEFAULT_COMPONENTS: tuple[tuple[str, float], ...] = (
    ("oos_robustness", 0.16),
    ("wfa_survival", 0.12),
    ("cpcv_quality", 0.10),
    ("monte_carlo_stability", 0.08),
    ("cost_robustness", 0.08),
    ("drawdown_quality", 0.10),
    ("trade_count_confidence", 0.08),
    ("regime_coverage", 0.06),
    ("correlation_benefit", 0.06),
    ("shadow_evidence", 0.10),
    ("live_execution_evidence", 0.06),
)


def evidence_score(components: dict[str, float], *,
                   weights: tuple[tuple[str, float], ...]
                   = DEFAULT_COMPONENTS) -> dict:
    """Transparent evidence score: every component (0..1) and weight is
    in the report; missing components count as 0 and are listed —
    nothing is hidden or invented (mission §28)."""
    total_w = sum(w for _, w in weights)
    details = []
    score = 0.0
    for name, w in weights:
        v = components.get(name)
        used = 0.0 if v is None else min(1.0, max(0.0, float(v)))
        score += w * used
        details.append({"component": name, "value": used,
                        "weight": w, "missing": v is None})
    return {"score": round(score / total_w, 4),
            "components": details,
            "weights_version": "evidence-1.0"}


# ------------------------------------------------------------ anti-churn


@dataclass
class Hysteresis:
    """Anti-churn policy (mission §31).  All bounds explicit."""

    min_observation_trades: int = 30
    min_observation_days: int = 28
    promotion_margin: float = 0.05      # challenger must beat by 5 pts
    demotion_margin: float = 0.05
    cooldown_days: int = 14
    stable_state_days: int = 7

    def validate(self) -> None:
        if self.min_observation_trades < 1 or \
                self.min_observation_days < 1 or \
                self.promotion_margin <= 0 or self.demotion_margin <= 0:
            raise ValueError("hysteresis margins and minimum evidence "
                             "must be positive (anti-churn invariant)")


@dataclass
class IncumbentState:
    strategy_id: str
    score: float
    in_state_since_day: int
    last_change_day: int = -10**9
    observation_trades: int = 0
    observation_days: int = 0


def should_promote(incumbent: IncumbentState | None,
                   challenger_score: float, *, day: int,
                   policy: Hysteresis) -> tuple[bool, str]:
    """Challenger promotion decision with full anti-churn logic
    (OOS-only decision data is the CALLER's contract — this function
    only enforces the evidence thresholds and margins)."""
    policy.validate()
    if challenger_score is None:
        return False, "no challenger evidence"
    if incumbent is None:
        if challenger_score >= 0.0:
            return True, ("no incumbent: first activation (human "
                          "approval still required, §51)")
        return False, "challenger score negative"
    if incumbent.observation_trades < policy.min_observation_trades or \
            incumbent.observation_days < policy.min_observation_days:
        return False, ("incumbent observation below minimum evidence "
                       f"({incumbent.observation_trades} trades / "
                       f"{incumbent.observation_days} days)")
    if day - incumbent.last_change_day < policy.cooldown_days:
        return False, "cooldown active"
    if day - incumbent.in_state_since_day < policy.stable_state_days:
        return False, "incumbent state not stable long enough"
    if challenger_score > incumbent.score + policy.promotion_margin:
        return True, (f"challenger {challenger_score:.3f} beats "
                      f"incumbent {incumbent.score:.3f} by the margin")
    return False, "challenger does not beat the incumbent by the margin"


def should_demote(incumbent: IncumbentState, score_now: float, *,
                  day: int, policy: Hysteresis,
                  breach: bool = False) -> tuple[bool, str]:
    """Demotion needs ROBUST evidence: a risk-control breach, or a
    sustained underperformance beyond the margin over the minimum
    observation window — never a single short window (§30/§31)."""
    policy.validate()
    if breach:
        return True, "risk-control breach (hard evidence)"
    if incumbent.observation_trades < policy.min_observation_trades or \
            incumbent.observation_days < policy.min_observation_days:
        return False, "insufficient observation to demote"
    if day - incumbent.last_change_day < policy.cooldown_days:
        return False, "cooldown active"
    if score_now < incumbent.score - policy.demotion_margin:
        return True, (f"sustained underperformance: {score_now:.3f} "
                      f"below incumbent {incumbent.score:.3f}")
    return False, "within hysteresis band"


def challenger_decision(challenger_score: float, incumbent_score: float,
                        *, same_period: bool, same_costs: bool,
                        same_data_provenance: bool, oos_only: bool
                        ) -> tuple[str, str]:
    """§32 comparison contract: a challenger verdict is only valid on
    equal footing; anything else is NO_DECISION, never a winner."""
    if not (same_period and same_costs and same_data_provenance):
        return "NO_DECISION", ("comparison not valid: evaluation "
                               "period/costs/data provenance differ")
    if not oos_only:
        return "NO_DECISION", ("in-sample comparisons never decide "
                               "(§32: no winner on IS performance)")
    if challenger_score > incumbent_score + 0.05:
        return "CHALLENGER", "beats incumbent beyond the margin (OOS)"
    return "INCUMBENT_RETAINS", "no meaningful OOS edge for the change"
