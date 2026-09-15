"""Discovery orchestrator — resumable staged campaigns (mission §7/§17/
§18/§63).

Stage plan (deterministic, budget-bounded, each stage persisted so a
crashed run RESUMES at the next unfinished stage):

  stage1_single_indicator   single canonical-indicator hypotheses
  stage2_two_factor         two-indicator compositions
  stage3_multi_factor       three-indicator compositions (≤ max_factors)
  stage4_portfolio_aware    diversifier slots for portfolio gaps
  stage5_mutations          bounded perturbations of survivors

Every candidate flows through the EXISTING pipeline (intake→parse→
validate→backtest→OOS→robustness).  The orchestrator NEVER bypasses a
gate (§104) and never tunes on the final OOS (§17): stage ranking uses
IS/CV metrics only; OOS is touched once, by the existing engine path.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .candidates import (
    DSL_VERSION,
    GENERATOR_VERSION,
    STAGES,
    GenerationContext,
    RedundancyFilter,
    ResearchSpace,
    doc_hash,
    generate_stage,
)
from .score import SCORE_VERSION, DiscoveryScore


@dataclass
class StageResult:
    stage: str
    generated: int
    kept: int
    dropped_redundant: int
    budget: int
    doc_hashes: list[str] = field(default_factory=list)
    ts: float = field(default_factory=time.time)


class DiscoveryOrchestrator:
    """Runs stage plans against injected functions (testable, no I/O
    hard-wired).  ``run_stage_fn(stage, docs) -> list[dict]`` executes
    the existing pipeline per candidate and returns result records
    (with metrics + lifecycle outcome).  Persist callbacks are
    injected by the application layer."""

    def __init__(self, space: ResearchSpace, *,
                 budgets: dict[str, int] | None = None,
                 redundancy: RedundancyFilter | None = None,
                 policy_hash: str = "",
                 dataset_hash: str = "",
                 dataset_id: str = "",
                 data_horizon: str = "",
                 cost_config: dict | None = None,
                 risk_config: dict | None = None,
                 gate_policy: str = "",
                 score_policy_hash: str = "",
                 campaign_id: str = "campaign",
                 hypothesis: str = "",
                 strategy_parent: str = "",
                 seed: int = 0,
                 oos_boundary: str = "",
                 max_factors: int = 3):
        self.space = space
        self.budgets = budgets or {}
        self.redundancy = redundancy or RedundancyFilter()
        self.policy_hash = policy_hash
        self.dataset_hash = dataset_hash
        self.dataset_id = dataset_id
        self.data_horizon = data_horizon
        self.cost_config = cost_config or {}
        self.risk_config = risk_config or {}
        self.gate_policy = gate_policy
        self.score_policy_hash = score_policy_hash or policy_hash
        self.campaign_id = campaign_id
        self.hypothesis = hypothesis
        self.strategy_parent = strategy_parent
        self.seed = seed
        self.oos_boundary = oos_boundary
        self.max_factors = max_factors
        self.stage_results: dict[str, StageResult] = {}
        self._last_docs: list[dict] = []

    def _gen_ctx(self) -> GenerationContext:
        return GenerationContext(
            campaign_id=self.campaign_id, hypothesis=self.hypothesis,
            seed=self.seed, parent_strategy_id=self.strategy_parent,
            parent_version=0)

    def plan(self) -> list[str]:
        """Which stages will run (fixed order)."""
        return list(STAGES)

    def completed_stages(self, campaign: dict) -> list[str]:
        prog = campaign.get("progress", {})
        return [s for s in STAGES if prog.get(s, {}).get("done")]

    def next_stage(self, campaign: dict) -> str | None:
        done = set(self.completed_stages(campaign))
        for s in STAGES:
            if s not in done:
                return s
        return None

    def build_docs(self, stage: str) -> list[dict]:
        docs = generate_stage(stage, self.space, budgets=self.budgets,
                              ctx=self._gen_ctx())
        self._last_docs = list(self._last_docs) + docs
        kept, dropped = self.redundancy.filter_docs(docs)
        res = StageResult(stage=stage, generated=len(docs), kept=len(kept),
                          dropped_redundant=len(dropped),
                          budget=self.budgets.get(stage, 12),
                          doc_hashes=[doc_hash(d) for d in kept])
        self.stage_results[stage] = res
        return kept

    def run_campaign(self, campaign: dict, run_stage_fn: Callable,
                     *, stop_after: str | None = None) -> dict:
        """Resume-or-start: skips completed stages, executes the rest,
        returns an updated campaign dict (progress + results).  Any
        exception leaves completed stages intact (resumability, §7)."""
        # §7/§18/§98: a campaign's progress is bound to the policy and
        # dataset it ran under.  A different policy hash means the
        # stored progress was earned elsewhere — refuse, never reuse.
        stored_policy = campaign.get("policy_hash", "")
        if stored_policy and stored_policy != self.policy_hash:
            raise ValueError(
                "campaign progress was earned under a different policy "
                f"hash ({stored_policy[:12]}); start a new campaign")
        stored_ds = campaign.get("dataset_hash", "")
        if stored_ds and self.dataset_hash and stored_ds != self.dataset_hash:
            raise ValueError(
                "campaign progress was earned on a DIFFERENT dataset "
                f"({stored_ds[:12]}); never continue research across a "
                "data boundary (mission §15)")
        progress = dict(campaign.get("progress", {}))
        results = dict(campaign.get("results", {}))
        for stage in STAGES:
            if progress.get(stage, {}).get("done"):
                continue
            if stop_after and stage > stop_after:
                break
            docs = self.build_docs(stage)
            stage_out = run_stage_fn(stage, docs) or []
            progress[stage] = {"done": True,
                               "generated": len(docs),
                               "candidates": len(stage_out),
                               "ts": time.time()}
            results[stage] = stage_out
            campaign["progress"] = progress
            campaign["results"] = results
            campaign["stage"] = stage
        campaign["status"] = "DONE" if self.next_stage(campaign) is None \
            else "PAUSED"
        campaign["policy_hash"] = self.policy_hash
        campaign["dataset_hash"] = self.dataset_hash
        campaign["manifest_hash"] = doc_hash({
            "budgets": self.budgets,
            "space": {"symbols": list(self.space.symbols),
                      "timeframe": self.space.timeframe,
                      "indicators": list(self.space.indicators),
                      "param_grid": self.space.param_grid},
            "policy": self.policy_hash})
        return campaign

    def rank_candidates(self, campaign: dict,
                        score_fn: Callable[[dict], DiscoveryScore]
                        ) -> list[dict]:
        """Rank stage-ELIGIBLE candidates only (§29): items whose
        lifecycle outcome is OOS_SURVIVOR or beyond.  Score ranks;
        never promotes (§28)."""
        rows = []
        for stage, items in campaign.get("results", {}).items():
            for item in items:
                state = item.get("state", "")
                if state not in ("OOS_SURVIVOR", "SHADOW", "DEMO",
                                 "LIVE_SMALL", "LIVE"):
                    continue
                sc = score_fn(item)
                rows.append({"strategy_id": item.get("strategy_id"),
                             "stage": stage, "state": state,
                             "score": sc.score,
                             "unavailable": list(sc.unavailable)})
        rows.sort(key=lambda r: (-r["score"], r["strategy_id"] or ""))
        return rows

    def trial_accounting(self, campaign: dict) -> dict:
        """§17: the system must know how many alternatives it tried —
        totals feed multiple-testing context (DSR/PBO), never a gate
        bypass."""
        results = campaign.get("results", {})
        total = kept = dropped = 0
        families: set[str] = set()
        mutations = 0
        selected: list[str] = []
        rejected: list[str] = []
        for stage, items in results.items():
            total += len(items)
            for item in items:
                state = item.get("state", "")
                sid = item.get("strategy_id", "")
                if state in ("OOS_SURVIVOR", "SHADOW", "DEMO",
                             "LIVE_SMALL", "LIVE"):
                    selected.append(sid)
                else:
                    rejected.append(sid)
            sr = self.stage_results.get(stage)
            if sr:
                kept += sr.kept
                dropped += sr.dropped_redundant
            if stage == "stage5_mutations":
                mutations = len(items)
        for doc in self._last_docs:
            families.add(",".join(sorted(
                i["kind"] for i in doc.get("indicators", []))))
        return {"total_candidates": total, "kept_after_redundancy": kept,
                "discarded_redundant": dropped,
                "parameter_trials": kept + dropped,
                "strategy_families": len(families),
                "mutations": mutations,
                "selected": sorted(selected),
                "rejected": sorted(rejected)}


    def manifest(self, campaign: dict) -> dict:
        """§16 research manifest — complete provenance, hashed."""
        accounting = self.trial_accounting(campaign)
        m = {
            "campaign_id": campaign.get("campaign_id", self.campaign_id),
            "strategy_parent": self.strategy_parent,
            "hypothesis": self.hypothesis,
            "search_space": {"symbols": list(self.space.symbols),
                             "timeframe": self.space.timeframe,
                             "indicators": list(self.space.indicators),
                             "param_grid": self.space.param_grid,
                             "max_factors": self.space.max_factors},
            "search_space_hash": doc_hash({
                "symbols": list(self.space.symbols),
                "timeframe": self.space.timeframe,
                "indicators": list(self.space.indicators),
                "param_grid": self.space.param_grid}),
            "candidate_count": accounting["total_candidates"],
            "candidate_ids": accounting["selected"]
            + accounting["rejected"],
            "dataset_id": self.dataset_id,
            "dataset_hash": self.dataset_hash,
            "data_horizon": self.data_horizon,
            "cost_config": self.cost_config,
            "risk_config": self.risk_config,
            "gate_policy": self.gate_policy,
            "score_policy": {"score_version": SCORE_VERSION,
                             "policy_hash": self.score_policy_hash},
            "DSL_version": DSL_VERSION,
            "code_version": self.policy_hash[:12] or "dev",
            "generator_version": GENERATOR_VERSION,
            "random_seed": self.seed,
            "OOS_boundary": self.oos_boundary,
            "selected_candidates": accounting["selected"],
            "rejected_candidates": accounting["rejected"],
            "stage_plan": self.plan(),
            "budgets": self.budgets,
            "policy_hash": self.policy_hash,
            "trial_accounting": accounting,
            "stage_results": {k: {"generated": v.generated,
                                  "kept": v.kept,
                                  "dropped_redundant":
                                  v.dropped_redundant,
                                  "budget": v.budget}
                              for k, v in self.stage_results.items()},
        }
        m["manifest_hash"] = doc_hash(
            {k: v for k, v in m.items() if k != "manifest_hash"})
        return m

    def to_json(self, campaign: dict) -> str:
        return json.dumps(self.manifest(campaign), sort_keys=True)
