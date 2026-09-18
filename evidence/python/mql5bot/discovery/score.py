"""Discovery Score — transparent, multi-component, policy-weighted
(autonomous-discovery mission §27/§28/§29/§94).

SCORE ≠ PERMISSION (§28): the score answers "how attractive is this
qualified research candidate relative to others".  It NEVER answers
"may this strategy trade" — eligibility is lifecycle+gates, risk is
the Risk Engine.  There is no code path from a score to orders.

Every component row exposes: raw value, normalized value, weight,
evidence availability and contribution.  Missing evidence counts as
unavailable (never an invented neutral pass).  The score version and
policy hash persist with the result so historical decisions remain
reproducible (§98).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field

SCORE_VERSION = "discovery-1.0"

# 16 components (mission §27).  Normalizers map a raw measurement to
# [0, 1]; `higher_is_better` flips where needed.
COMPONENTS: tuple[str, ...] = (
    "oos_survival", "profit_factor", "drawdown_quality", "expectancy",
    "trade_count_confidence", "parameter_robustness", "wfa_survival",
    "cpcv_pbo_evidence", "monte_carlo_stability", "cost_robustness",
    "regime_stability", "drift_health", "execution_realism",
    "portfolio_diversification", "shadow_evidence", "live_evidence",
)


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))


DEFAULT_WEIGHTS: dict[str, float] = {
    "oos_survival": 0.12, "profit_factor": 0.08,
    "drawdown_quality": 0.08, "expectancy": 0.06,
    "trade_count_confidence": 0.06, "parameter_robustness": 0.07,
    "wfa_survival": 0.07, "cpcv_pbo_evidence": 0.07,
    "monte_carlo_stability": 0.06, "cost_robustness": 0.06,
    "regime_stability": 0.05, "drift_health": 0.05,
    "execution_realism": 0.05, "portfolio_diversification": 0.06,
    "shadow_evidence": 0.04, "live_evidence": 0.06,
}

DEFAULT_NORMALIZERS: dict[str, tuple] = {
    # component: (raw_lo, raw_hi, higher_is_better)
    "oos_survival": (0.0, 1.0, True),
    "profit_factor": (1.0, 2.0, True),
    "drawdown_quality": (30.0, 5.0, True),      # raw = maxDD%, lower better
    "expectancy": (0.0, 200.0, True),           # per-trade, account ccy
    "trade_count_confidence": (100.0, 1000.0, True),
    "parameter_robustness": (0.0, 1.0, True),   # 1 - dd_ratio/max allowed
    "wfa_survival": (0.0, 1.0, True),
    "cpcv_pbo_evidence": (0.5, 0.0, True),      # raw = PBO, lower better
    "monte_carlo_stability": (0.0, 1.0, True),  # e.g. p05/p50 DD ratio
    "cost_robustness": (0.0, 1.0, True),        # PF@2x / PF@1x clipped
    "regime_stability": (0.0, 1.0, True),
    "drift_health": (0.0, 1.0, True),           # 1 - drift_score
    "execution_realism": (0.0, 1.0, True),
    "portfolio_diversification": (0.0, 1.0, True),
    "shadow_evidence": (0.0, 1.0, True),
    "live_evidence": (0.0, 1.0, True),
}


def policy_hash(weights: dict[str, float],
                normalizers: dict[str, tuple]) -> str:
    return hashlib.sha256(json.dumps(
        {"w": weights, "n": {k: list(v) for k, v in normalizers.items()}},
        sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ScoreRow:
    component: str
    raw: float | None
    normalized: float
    weight: float
    available: bool
    contribution: float


@dataclass(frozen=True, slots=True)
class DiscoveryScore:
    score: float
    rows: tuple[ScoreRow, ...]
    score_version: str
    pol_hash: str
    unavailable: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"score": self.score, "score_version": self.score_version,
                "policy_hash": self.pol_hash,
                "unavailable": list(self.unavailable),
                "components": [asdict(r) for r in self.rows]}

    def explain(self) -> str:
        """Human-readable, auditable explanation (mission §93: no AI
        magic — every number traceable)."""
        lines = [(f"discovery score {self.score:.4f} "
                  f"({self.score_version}, policy "
                  f"{self.pol_hash[:12]})")]
        for r in self.rows:
            state = "ok" if r.available else "MISSING EVIDENCE"
            lines.append(f"  {r.component:<26} raw="
                         f"{'—' if r.raw is None else format(r.raw, '.4f')}"
                         f" norm={r.normalized:.3f} w={r.weight:.2f} "
                         f"contrib={r.contribution:.4f} [{state}]")
        return "\n".join(lines)


def compute_score(measured: dict[str, float | None], *,
                  weights: dict[str, float] | None = None,
                  normalizers: dict | None = None
                  ) -> DiscoveryScore:
    w = dict(DEFAULT_WEIGHTS if weights is None else weights)
    n = dict(DEFAULT_NORMALIZERS if normalizers is None else normalizers)
    missing = [k for k in COMPONENTS if k not in w or k not in n]
    if missing:
        raise ValueError(f"policy missing components: {missing}")
    total_w = sum(w[k] for k in COMPONENTS)
    rows: list[ScoreRow] = []
    score = 0.0
    unavailable: list[str] = []
    for comp in COMPONENTS:
        raw = measured.get(comp)
        lo, hi, higher = n[comp]
        if raw is None or (isinstance(raw, float)
                           and not math.isfinite(raw)):
            norm = 0.0
            available = False
            unavailable.append(comp)
        else:
            frac = (_clip01((float(raw) - lo) / (hi - lo))
                    if hi != lo else _clip01(float(raw)))
            norm = frac if higher else 1.0 - frac
            available = True
        contribution = w[comp] * norm
        score += contribution
        rows.append(ScoreRow(component=comp, raw=None if raw is None
                             else float(raw),
                             normalized=round(norm, 6),
                             weight=w[comp], available=available,
                             contribution=round(contribution, 6)))
    return DiscoveryScore(score=round(score / total_w, 6),
                          rows=tuple(rows), score_version=SCORE_VERSION,
                          pol_hash=policy_hash(w, n),
                          unavailable=tuple(unavailable))
