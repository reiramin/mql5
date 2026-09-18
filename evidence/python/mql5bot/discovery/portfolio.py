"""Portfolio assembly — correlation-aware, concentration-capped, with
legitimate zero exposure (mission §38-§40/§66).

Gross exposure is a TARGET (10-20% by default) — never a minimum; the
portfolio is allowed to hold 0% when nothing qualifies or safety
demands it.  Risk% (portfolio heat) and gross% are DIFFERENT
quantities and never conflated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CandidatePortfolioEntry:
    strategy_id: str
    symbol: str
    direction: str                     # long|short|both
    asset_class: str                   # fx|metal|index|crypto|other
    weight: float                      # normalized weight [0, 1]
    score: float                       # discovery score
    returns: tuple[float, ...] = ()    # aligned daily returns (or None)
    correlation_penalty: float = 0.0
    marginal_heat: float = 0.0


def _same_dir(a: str, b: str) -> bool:
    """Opposite pure directions never share direction heat."""
    if a == "short" or b == "short":
        return a == b
    return True


def correlation(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    if len(a) != len(b) or len(a) < 3:
        return 1.0                     # unknown → assume worst
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    da = [x - ma for x in a]
    db = [x - mb for x in b]
    num = sum(x * y for x, y in zip(da, db))
    den = math.sqrt(sum(x * x for x in da) * sum(y * y for y in db))
    if den <= 1e-12:
        return 1.0
    rho = num / den
    return max(-1.0, min(1.0, rho))


@dataclass
class ConcentrationLimits:
    max_per_strategy_pct: float = 30.0
    max_per_symbol_pct: float = 40.0
    max_per_direction_pct: float = 65.0
    max_per_asset_class_pct: float = 60.0
    max_corr_avg: float = 0.70          # avg pairwise correlation cap
    corr_penalty_strength: float = 0.5
    redundant_corr: float = 0.95        # hard near-duplicate threshold

    def validate(self) -> None:
        for v in (self.max_per_strategy_pct, self.max_per_symbol_pct,
                  self.max_per_direction_pct, self.max_per_asset_class_pct):
            if not 0 < v <= 100:
                raise ValueError("concentration caps must be in (0,100]")
        if not 0 <= self.max_corr_avg <= 1:
            raise ValueError("correlation cap must be within [0,1]")


def _corr_penalty(entry: CandidatePortfolioEntry,
                  selected: list[CandidatePortfolioEntry],
                  strength: float) -> float:
    if not selected or not entry.returns:
        return 0.0
    rhos = []
    for s in selected:
        if s.returns and len(s.returns) == len(entry.returns):
            rhos.append(abs(correlation(entry.returns, s.returns)))
    if not rhos:
        return 0.0
    return strength * (sum(rhos) / len(rhos))


def build_portfolio(candidates: list[dict], *,
                    capital_gross_target_pct: float = 15.0,
                    limits: ConcentrationLimits | None = None,
                    min_score: float = 0.45,
                    max_positions: int = 8) -> dict:
    """Greedy correlation-aware assembly (deterministic: sort by
    (score desc, strategy_id)).  Candidates must already be
    stage-eligible (§29); scores rank, they never authorize."""
    limits = limits or ConcentrationLimits()
    limits.validate()
    target_frac = max(0.0, min(1.0, capital_gross_target_pct / 100.0))
    ranked = sorted((c for c in candidates
                     if float(c.get("score", 0.0)) >= min_score),
                    key=lambda c: (-float(c.get("score", 0.0)),
                                   str(c.get("strategy_id", ""))))
    selected: list[CandidatePortfolioEntry] = []
    excluded: list[tuple[str, str]] = []
    total_w = 0.0
    for c in ranked:
        if len(selected) >= max_positions:
            break
        sid = str(c["strategy_id"])
        w = float(c.get("weight", 1.0))
        entry = CandidatePortfolioEntry(
            strategy_id=sid, symbol=str(c.get("symbol", "?")),
            direction=str(c.get("direction", "both")),
            asset_class=str(c.get("asset_class", "other")),
            weight=w, score=float(c.get("score", 0.0)),
            returns=tuple(c.get("returns", ())))
        pen = _corr_penalty(entry, selected, limits.corr_penalty_strength)
        # hard near-duplicate rule (§64): lower-ranked clone excluded
        if selected and entry.returns:
            rhos = [abs(correlation(entry.returns, s.returns))
                    for s in selected if s.returns
                    and len(s.returns) == len(entry.returns)]
            if rhos and max(rhos) >= limits.redundant_corr:
                excluded.append((sid, (f"redundant: corr "
                                       f"{max(rhos):.3f} >= "
                                       f"{limits.redundant_corr}")))
                continue
        adj = entry.score - pen
        if adj < min_score and selected:
            excluded.append((sid, (f"correlation penalty {pen:.3f} "
                                   f"dropped score to {adj:.3f}")))
            continue
        # concentration checks vs CURRENT selection — shares are the
        # SCALED exposure (% of capital after gross-target scaling)
        tentative = total_w + entry.weight
        if tentative <= 0:
            excluded.append((sid, "non-positive weight"))
            continue

        sym, direc, cls = entry.symbol, entry.direction, entry.asset_class

        def _pct(pred, *, sym=sym, direc=direc, cls=cls,
                 new_weight=entry.weight, tot=tentative):
            base = sum(e.weight for e in selected if pred(e))
            return (base + new_weight) / tot * target_frac * 100

        if _pct(lambda e, sym=sym: True) > limits.max_per_strategy_pct:
            excluded.append((sid, "per-strategy cap"))
            continue
        if _pct(lambda e, sym=sym: e.symbol == sym) > \
                limits.max_per_symbol_pct:
            excluded.append((sid, "per-symbol cap"))
            continue
        if _pct(lambda e, direc=direc: _same_dir(e.direction, direc)) > \
                limits.max_per_direction_pct:
            excluded.append((sid, "per-direction cap"))
            continue
        if _pct(lambda e, cls=cls: e.asset_class == cls) > \
                limits.max_per_asset_class_pct:
            excluded.append((sid, "per-asset-class cap"))
            continue
        selected.append(entry)
        total_w += entry.weight
    # normalize weights into the gross target
    target_frac = max(0.0, min(1.0, capital_gross_target_pct / 100.0))

    def _realized_ok(entries: list[CandidatePortfolioEntry]) -> bool:
        """§25: caps must hold on REALIZED exposure (% of capital),
        not only at admission time."""
        total = sum(e.weight for e in entries)
        if total <= 0:
            return True
        for cap, keyfn in (
                (limits.max_per_strategy_pct, lambda e: e.strategy_id),
                (limits.max_per_symbol_pct, lambda e: e.symbol),
                (limits.max_per_direction_pct,
                 lambda e: "short" if e.direction == "short"
                 else "netlong"),
                (limits.max_per_asset_class_pct,
                 lambda e: e.asset_class)):
            bucket: dict[str, float] = {}
            for e in entries:
                k = keyfn(e)
                bucket[k] = bucket.get(k, 0.0) + e.weight / total \
                    * target_frac * 100
            if any(v > cap + 1e-9 for v in bucket.values()):
                return False
        return True

    # drop lowest-score entries until realized caps hold (§25)
    while selected and not _realized_ok(selected):
        victim = min(selected, key=lambda e: e.score)
        selected.remove(victim)
        excluded.append((victim.strategy_id,
                         "realized concentration cap (post-scale)"))
    total_w = sum(e.weight for e in selected)
    scale = target_frac / total_w if total_w > 0 else 0.0
    portfolio = []
    for e in selected:
        portfolio.append({
            "strategy_id": e.strategy_id, "weight": round(e.weight, 6),
            "scaled_weight": round(e.weight * scale, 6),
            "score": round(e.score, 6),
            "correlation_penalty": round(
                _corr_penalty(e, [x for x in selected if x is not e],
                              limits.corr_penalty_strength), 6),
        })
    gross_pct = round(target_frac * 100 if total_w > 0 else 0.0, 4)
    heat = round(sum(p["scaled_weight"] * p["score"] for p in portfolio), 6)
    return {
        "gross_exposure_pct": gross_pct,   # §40: 0% is legitimate
        "portfolio_heat": heat,            # ≠ gross (§40)
        "positions": portfolio,
        "excluded": excluded,
        "zero_exposure": total_w == 0.0,
    }


def marginal_contribution(candidates: list[dict], new_candidate: dict,
                          *, base: dict | None = None) -> dict:
    """§39 marginal analysis: what does adding this candidate do to the
    portfolio (incremental score/heat/correlation)?"""
    base = base or build_portfolio(candidates)
    with_new = build_portfolio(
        candidates + [dict(new_candidate, strategy_id=new_candidate[
            "strategy_id"] + "__cand")],
        capital_gross_target_pct=base.get("gross_exposure_pct", 15.0))
    extra = [p for p in with_new["positions"]
             if str(p["strategy_id"]).endswith("__cand")]
    if not extra:
        return {"admitted": False, "reason": "did not survive portfolio "
                "assembly (score/correlation/caps)",
                "base_heat": base["portfolio_heat"]}
    return {"admitted": True,
            "delta_heat": round(with_new["portfolio_heat"]
                                - base["portfolio_heat"], 6),
            "base_heat": base["portfolio_heat"],
            "with_heat": with_new["portfolio_heat"],
            "avg_correlation": round(extra[0]["correlation_penalty"], 6)}


# ------------------------------------------------- §25/§26 concentration


def _hhi(shares: list[float]) -> float:
    """Herfindahl–Hirschman index of shares summing to <=1 (0 if empty)."""
    total = sum(shares)
    if total <= 0:
        return 0.0
    return round(sum((x / total) ** 2 for x in shares), 6)


def concentration_report(positions: list[dict]) -> dict:
    """§25: EXPLICIT concentration across every axis that matters.
    Each axis reports the max single share and the HHI; shares are
    fractions of total allocated weight.  An empty portfolio reports
    zeros (0% exposure has no concentration problem)."""
    axes = ("strategy_id", "symbol", "direction", "currency",
            "asset_class")
    out: dict = {"positions": len(positions)}
    for axis in axes:
        buckets: dict[str, float] = {}
        for p in positions:
            key = str(p.get(axis, "unknown"))
            buckets[key] = buckets.get(key, 0.0) +                 float(p.get("weight", 0.0))
        total = sum(buckets.values())
        shares = [v / total for v in buckets.values()] if total > 0 else []
        out[axis] = {"max_share": round(max(shares), 6) if shares else 0.0,
                     "hhi": _hhi(shares),
                     "buckets": len(buckets)}
    # §26 correlation concentration: mean |pairwise| over available
    # series; series without enough data are classified UNKNOWN and
    # EXCLUDED from the mean (never silently treated as uncorrelated)
    rhos: list[float] = []
    unknown_pairs = 0
    for i, a in enumerate(positions):
        for b in positions[i + 1:]:
            rho, band = classify_correlation(a.get("returns", ()),
                                             b.get("returns", ()))
            if band == "UNKNOWN":
                unknown_pairs += 1
            else:
                rhos.append(abs(rho))    # type: ignore[arg-type]
    out["correlation"] = {
        "mean_abs": round(sum(rhos) / len(rhos), 6) if rhos else 0.0,
        "max_abs": round(max(rhos), 6) if rhos else 0.0,
        "unknown_pairs": unknown_pairs,
        "n_pairs": len(positions) * (len(positions) - 1) // 2,
    }
    return out


def classify_correlation(a: tuple[float, ...], b: tuple[float, ...],
                         *, min_obs: int = 60) -> tuple[float | None, str]:
    """§26: correlation with honest evidence classification.

    Returns (rho | None, band).  UNKNOWN when history is missing,
    the sample is too short, or either series is constant — UNKNOWN is
    NEVER converted to zero (mission §26)."""
    if len(a) != len(b) or len(a) < min_obs:
        return None, "UNKNOWN"
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    da = [x - ma for x in a]
    db = [x - mb for x in b]
    sda = (sum(x * x for x in da)) ** 0.5
    sdb = (sum(y * y for y in db)) ** 0.5
    if sda <= 1e-12 or sdb <= 1e-12:
        return None, "UNKNOWN"            # constant series: no evidence
    num = sum(x * y for x, y in zip(da, db))
    rho = num / (sda * sdb)
    if not math.isfinite(rho):            # NaN inputs
        return None, "UNKNOWN"
    rho = max(-1.0, min(1.0, rho))
    mag = abs(rho)
    band = "LOW" if mag < 0.3 else ("MEDIUM" if mag < 0.7 else "HIGH")
    return rho, band
