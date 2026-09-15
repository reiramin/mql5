"""Staged candidate generation and redundancy filtering (mission
§16/§17/§63/§64).

Deterministic, budget-bounded generation of DSL strategy documents
from a DECLARED research-space config — never invented ranges.  The
generator composes canonical DSL indicators (from the §8 universe)
into staged hypotheses; a redundancy filter (correlation of indicator
output streams) suppresses near-duplicates so compute is spent on
genuinely different ideas.  The filter is a research-EFFICIENCY device
(§64): it never short-circuits correctness gates downstream.
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass, field

import numpy as np

from ..indicator_universe.registry import ALL_KINDS, contract

STAGES = ("stage1_single_indicator", "stage2_two_factor",
          "stage3_multi_factor", "stage4_portfolio_aware",
          "stage5_mutations")

DSL_VERSION = "1.0"
GENERATOR_VERSION = "aegis-gen-1.0"


@dataclass(frozen=True)
class GenerationContext:
    """§13: every candidate carries its lineage — campaign, hypothesis,
    deterministic seed, parent strategy/version — and its search
    position, so any candidate is reproducible from the manifest."""

    campaign_id: str = "adhoc"
    hypothesis: str = ""
    seed: int = 0
    parent_strategy_id: str = ""
    parent_version: int = 0


def _sid(campaign_id: str, stage: str, index: int) -> str:
    raw = f"gen_{campaign_id}_{stage}_{index:03d}"
    out = "".join(ch if (ch.isalnum() and ch.isascii()) else "_"
                  for ch in raw.lower())
    return out[:64]


def candidate_id(campaign_id: str, stage: str, index: int,
                 doc: dict) -> str:
    return doc_hash({"campaign_id": campaign_id, "stage": stage,
                     "index": index, "doc": doc})[:16]


@dataclass(frozen=True)
class ResearchSpace:
    """Declared search space (mission §16): every range below comes
    from a versioned config, never from an LLM's imagination."""

    symbols: tuple[str, ...] = ("EURUSD",)
    timeframe: str = "H1"
    indicators: tuple[str, ...] = ()
    param_grid: dict[str, dict] = field(default_factory=dict)
    entry_styles: tuple[str, ...] = ("breakout", "reversion")
    max_factors: int = 3

    def validate(self) -> None:
        bad = [k for k in self.indicators if k not in ALL_KINDS]
        if bad:
            raise ValueError(f"research space references unknown kinds: "
                             f"{bad}")
        for kind, grid in self.param_grid.items():
            contract(kind)  # raises if unknown
            for name in grid:
                params = {p.name: p for p in contract(kind).params}
                if name not in params:
                    raise ValueError(
                        f"grid param {name!r} not declared for {kind}")

    def variant_count(self, kind: str) -> int:
        grid = self.param_grid.get(kind, {})
        if not grid:
            return 1
        combos = itertools.product(*[v if isinstance(v, (list, tuple))
                                     else [v] for v in grid.values()])
        return sum(1 for _ in combos)


def doc_hash(doc: dict) -> str:
    import json
    return hashlib.sha256(json.dumps(
        doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _grid_values(kind: str, space: ResearchSpace,
                 max_variants: int) -> list[dict]:
    grid = space.param_grid.get(kind, {})
    if not grid:
        return [{}]
    names = sorted(grid)
    series = [grid[n] if isinstance(grid[n], (list, tuple)) else [grid[n]]
              for n in names]
    out = []
    for combo in itertools.product(*series):
        out.append(dict(zip(names, combo)))
        if len(out) >= max_variants:
            break
    return out


def generate_stage(stage: str, space: ResearchSpace, *,
                   budgets: dict[str, int] | None = None,
                   ctx: GenerationContext | None = None) -> list[dict]:
    """Deterministically enumerate candidate DSL documents for a stage
    within the stage budget.  Multi-output kinds expose named refs."""
    budgets = budgets or {}
    ctx = ctx or GenerationContext()
    space.validate()
    kinds = [k for k in space.indicators if k in ALL_KINDS]
    kinds = sorted(kinds)
    docs: list[dict] = []
    budget = budgets.get(stage, 12)
    base_meta = {"symbol": space.symbols[0], "timeframe": space.timeframe}

    def add(ind_specs: list[dict], style: str, tag: str) -> None:
        nonlocal n
        sid = _sid(ctx.campaign_id, stage, n)
        doc = {
            "strategy_id": sid,
            "market": base_meta,
            "entry": {"long": {"and": [
                {"gt": [{"ind_ref": ind_specs[0]["id"]},
                        {"price": "close"}]}]},
                "short": {"or": []}},
            "risk": {"stop_atr_mult": 2.0, "risk_per_trade": 0.01},
            "indicators": ind_specs,
            "meta": {"origin": "aegis_discovery", "stage": stage,
                     "style": style,
                     "campaign_id": ctx.campaign_id,
                     "candidate_id": candidate_id(ctx.campaign_id, stage,
                                                  n, {}),
                     "search_position": {"stage": stage, "index": n},
                     "parent_strategy_id": ctx.parent_strategy_id,
                     "parent_version": ctx.parent_version,
                     "seed": ctx.seed,
                     "hypothesis": ctx.hypothesis},
        }
        doc["meta"]["candidate_id"] = candidate_id(ctx.campaign_id, stage,
                                                   n, doc)
        docs.append(doc)
        n += 1

    n = 0
    if stage == "stage1_single_indicator":
        for kind in kinds:
            for params in _grid_values(kind, space, 5):
                if n >= budget:
                    break
                tag = f"s1_{kind.lower()}_{n}"
                add([{"id": f"i{kind.lower()}", "kind": kind,
                      **({"params": params} if params else {})}],
                   space.entry_styles[0], tag)
    elif stage == "stage2_two_factor":
        for a, b in itertools.combinations(kinds, 2):
            if n >= budget:
                break
            add([{"id": f"ia{a.lower()}", "kind": a},
                 {"id": f"ib{b.lower()}", "kind": b}],
                space.entry_styles[0], f"s2_{a.lower()}_{b.lower()}")
    elif stage == "stage3_multi_factor":
        for combo in itertools.combinations(kinds, min(3,
                max(1, space.max_factors))):
            if n >= budget:
                break
            specs = [{"id": f"m{j}{k.lower()}", "kind": k}
                     for j, k in enumerate(combo)]
            add(specs, space.entry_styles[0],
                "s3_" + "_".join(k.lower() for k in combo))
    elif stage == "stage4_portfolio_aware":
        # diversifier slots: single-indicator hypotheses on the OTHER
        # covered symbols (portfolio gaps, mission §38-§40); with a
        # single symbol the stage legitimately generates nothing.
        for kind in kinds:
            for sym in space.symbols[1:]:
                if n >= budget:
                    break
                sid = _sid(ctx.campaign_id, stage, n)
                doc = {
                    "strategy_id": sid,
                    "market": {"symbol": sym,
                               "timeframe": space.timeframe},
                    "entry": {"long": {"and": [
                        {"gt": [{"ind_ref": f"d{kind.lower()}"},
                                {"price": "close"}]}]},
                        "short": {"or": []}},
                    "risk": {"stop_atr_mult": 2.0,
                             "risk_per_trade": 0.01},
                    "indicators": [{"id": f"d{kind.lower()}",
                                    "kind": kind}],
                    "meta": {"origin": "aegis_discovery", "stage": stage,
                             "style": "diversifier",
                             "campaign_id": ctx.campaign_id,
                             "search_position": {"stage": stage,
                                                 "index": n},
                             "parent_strategy_id": ctx.parent_strategy_id,
                             "parent_version": ctx.parent_version,
                             "seed": ctx.seed,
                             "hypothesis": ctx.hypothesis},
                }
                doc["meta"]["candidate_id"] = candidate_id(
                    ctx.campaign_id, stage, n, doc)
                docs.append(doc)
                n += 1
    elif stage == "stage5_mutations":
        # small perturbations of single-indicator docs (budget-bounded)
        for kind in kinds:
            for params in _grid_values(kind, space, 3):
                if n >= budget:
                    break
                add([{"id": f"m{kind.lower()}", "kind": kind,
                      **({"params": params} if params else {}), "shift": 1}],
                   space.entry_styles[-1], f"s5_{kind.lower()}_{n}")
    else:
        raise ValueError(f"stage {stage} requires portfolio context or "
                         "is generated by the orchestrator")
    return docs


class RedundancyFilter:
    """§64: correlation-of-outputs duplicate suppression — research
    efficiency only."""

    def __init__(self, threshold: float = 0.98,
                 sample_bars: int = 1500):
        if not 0.5 <= threshold <= 1.0:
            raise ValueError("redundancy threshold must be in [0.5, 1]")
        self.threshold = threshold
        self.sample_bars = sample_bars

    def key(self, doc: dict) -> str:
        """Structural fingerprint: kinds + sorted params + stage."""
        kinds = sorted(i["kind"] + ":" + ",".join(
            f"{k}={v}" for k, v in sorted(
                i.get("params", {}).items()))
            for i in doc.get("indicators", []))
        return doc_hash({"kinds": kinds,
                         "stage": doc.get("meta", {}).get("stage")})

    def filter_docs(self, docs: list[dict],
                    series_fn=None) -> tuple[list[dict], list[dict]]:
        """Returns (kept, dropped).  ``series_fn(doc) -> list[ndarray]``
        optionally supplies output series for correlation dedupe."""
        seen_struct: set[str] = set()
        accepted: list[tuple[dict, list[np.ndarray]]] = []
        kept, dropped = [], []
        for doc in docs:
            k = self.key(doc)
            if k in seen_struct:
                dropped.append(doc)
                continue
            series = list(series_fn(doc)) if series_fn else []
            dup = False
            if series and accepted:
                for _, acc_series in accepted:
                    for a in series:
                        for b in acc_series:
                            if len(a) == len(b) and len(a) > 10:
                                c = _corr(a, b)
                                if c is not None and c > self.threshold:
                                    dup = True
                                    break
                        if dup:
                            break
                    if dup:
                        break
            if dup:
                dropped.append(doc)
                continue
            seen_struct.add(k)
            accepted.append((doc, series))
            kept.append(doc)
        return kept, dropped


def _corr(a: np.ndarray, b: np.ndarray) -> float | None:
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 10:
        return None
    x, y = a[m], b[m]
    if x.std() < 1e-12 or y.std() < 1e-12:
        return None
    return float(abs(np.corrcoef(x, y)[0, 1]))
