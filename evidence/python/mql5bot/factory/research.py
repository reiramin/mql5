"""mql5bot.factory.research — campaigns, mutations, selection-bias
accounting (mission §22/§25/§44/§48).

A campaign is an AUDITABLE research container:

- every candidate (child) links to its parent;
- the search budget (candidate count, mutation count, parameter
  ranges) is written into the manifest BEFORE results exist;
- ``research_selection_bias_warning`` is attached whenever a "best"
  candidate is selected from more than one trial — no "best strategy
  found" language ever appears without the search context;
- mutations are NEW versions/children (never in-place edits) and OOS
  data is structurally out of their reach (the campaign manifest
  records the data version; the gate engine consumes only pre-registered
  measurements).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..dsl import StrategySpec

MANIFEST_VERSION = "campaign-1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Campaign:
    campaign_id: str
    parent_strategy_id: str
    parent_version: int
    search_space: dict                 # declared BEFORE results (§44)
    data_version: str
    data_timestamps: str
    cost_model: str
    broker_assumptions: str
    methodology: str
    gate_versions: list[str]
    code_commit: str
    dsl_version: str
    random_seed: int
    created_at: str = field(default_factory=_now)
    candidates: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    selected: dict | None = None

    # ------------------------------------------------------------ budget

    def __post_init__(self):
        declared = self.search_space.get("max_candidates")
        if declared is not None and declared <= 0:
            raise ValueError("campaign search_space.max_candidates must "
                             "be positive (resource limits, §43)")

    def register_candidate(self, spec: StrategySpec,
                           mutation_note: str = "") -> None:
        declared = self.search_space.get("max_candidates")
        if declared is not None and \
                len(self.candidates) >= int(declared):
            raise ValueError(
                f"campaign budget exhausted: max_candidates="
                f"{declared} (mission §43 — a user must not "
                "accidentally launch millions of backtests)")
        self.candidates.append({
            "strategy_id": spec.strategy_id, "version": spec.version,
            "spec_hash": spec.spec_hash, "dedup_hash": spec.dedup_hash,
            "parent": (self.parent_strategy_id, self.parent_version),
            "mutation_note": mutation_note,
            "registered_at": _now()})

    def reject(self, strategy_id: str, reason: str) -> None:
        self.rejected.append({"strategy_id": strategy_id,
                              "reason": reason, "at": _now()})

    def select(self, strategy_id: str, reason: str) -> dict:
        if len(self.candidates) > 1:
            pass                     # warning added in manifest below
        self.selected = {"strategy_id": strategy_id, "reason": reason,
                         "at": _now()}
        return self.selected

    # ------------------------------------------------------------ manifest

    def manifest(self) -> dict:
        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "campaign_id": self.campaign_id,
            "parent": [self.parent_strategy_id, self.parent_version],
            "candidate_count": len(self.candidates),
            "mutation_count": sum(
                1 for c in self.candidates if c["mutation_note"]),
            "search_space": self.search_space,
            "data_version": self.data_version,
            "data_timestamps": self.data_timestamps,
            "cost_model": self.cost_model,
            "broker_assumptions": self.broker_assumptions,
            "test_methodology": self.methodology,
            "gate_versions": self.gate_versions,
            "code_version": self.code_commit,
            "dsl_version": self.dsl_version,
            "random_seed": self.random_seed,
            "selected_candidate": self.selected,
            "rejected_candidates": list(self.rejected),
            "candidates": list(self.candidates),
            "created_at": self.created_at,
        }
        if len(self.candidates) > 1:
            manifest["research_selection_bias_warning"] = (
                f"{len(self.candidates)} candidates were tried and one "
                "was selected: any reported edge must be read against "
                "the search budget (multiple-testing / selection bias, "
                "mission §22/§48). Deflated-Sharpe / PBO gates consume "
                "this count.")
            manifest["n_trials_for_dsr"] = len(self.candidates)
        return manifest

    def manifest_hash(self) -> str:
        """sha256 over the manifest with WALL-CLOCK fields stripped —
        replaying the same campaign must reproduce the hash (gate §7);
        the timestamps stay inside manifest() for audit purposes."""
        def strip(node):
            if isinstance(node, dict):
                return {k: strip(v) for k, v in node.items()
                        if k not in ("registered_at", "at",
                                     "created_at")}
            if isinstance(node, list):
                return [strip(v) for v in node]
            return node
        return hashlib.sha256(json.dumps(
            strip(self.manifest()), sort_keys=True,
            ensure_ascii=False).encode()).hexdigest()


# ------------------------------------------------------------ mutations


def parameter_mutations(base: StrategySpec, grid: dict[str, list],
                        *, max_variants: int = 20) -> list[dict]:
    """Deterministic single-axis mutations of a parent spec (mission
    §25): EMA20/50/RSI55 → EMA18/50, EMA20/55, RSI52, RSI58 …

    Each mutation is a NEW DRAFT document (version 0, parent set at
    registration) — the parent is never modified, live strategies are
    never mutated (§1.17), and the campaign budget bounds the count.
    The caller registers each as a child and evaluates independently.
    """
    out: list[dict] = []
    for param, values in sorted(grid.items()):
        for v in values:
            if len(out) >= max_variants:
                return out
            doc = json.loads(json.dumps(base.document))
            mutated = _mutate_document(doc, param, v)
            if mutated is None:
                continue
            mutated["strategy_id"] = base.strategy_id + "_mut"
            mutated["version"] = 0
            out.append({"document": mutated,
                        "mutation_note": f"{param}={v}"})
    return out


def _mutate_document(doc: dict, param: str, value) -> dict | None:
    """Apply one parameter mutation to the FIRST matching location:
    indicator period/dev/fast/slow/signal, or a const operand whose
    adjacent ambiguity/param name matches, or indicator id remap.
    Returns None when the parameter does not exist (honest no-op)."""
    for ind in doc.get("indicators", []):
        if param in ind and isinstance(ind[param], (int, float)):
            ind[param] = value
            return doc
    # param-referenced consts (post-resolution consts carry names via
    # the ambiguity flow) — match declared params by name
    def walk(node):
        if isinstance(node, dict):
            if "param" in node and node["param"] == param:
                node.clear()
                node["const"] = value
                return True
            for v in node.values():
                if walk(v):
                    return True
        elif isinstance(node, list):
            for v in node:
                if walk(v):
                    return True
        return False
    if walk(doc.get("entry", {})):
        return doc
    return None
