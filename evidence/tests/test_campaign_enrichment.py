"""Campaign engine enrichment tests (convergence mission §13–§17):
candidate lineage, deterministic seeds, search positions, complete
research manifests, trial accounting, and resume boundary refusals."""

from __future__ import annotations

import pytest
from mql5bot.discovery.candidates import (
    GENERATOR_VERSION,
    GenerationContext,
    generate_stage,
)
from mql5bot.discovery.orchestrator import DiscoveryOrchestrator
from mql5bot.discovery.score import compute_score

from tests.test_discovery import _full_measurements, _space


def _ctx() -> GenerationContext:
    return GenerationContext(campaign_id="camp_conv", hypothesis="h1",
                             seed=7, parent_strategy_id="parent_a",
                             parent_version=3)


def test_every_candidate_carries_lineage_and_search_position():
    docs = generate_stage("stage1_single_indicator", _space(),
                          budgets={"stage1_single_indicator": 4},
                          ctx=_ctx())
    assert len(docs) == 4
    for i, d in enumerate(docs):
        m = d["meta"]
        assert m["campaign_id"] == "camp_conv"
        assert m["search_position"] == {"stage": "stage1_single_indicator",
                                        "index": i}
        assert m["parent_strategy_id"] == "parent_a"
        assert m["parent_version"] == 3
        assert m["seed"] == 7
        assert m["candidate_id"] and len(m["candidate_id"]) == 16
        assert d["strategy_id"].startswith("gen_camp_conv_")


def test_generation_is_seed_deterministic_and_reproducible():
    a = generate_stage("stage2_two_factor", _space(),
                       budgets={"stage2_two_factor": 5}, ctx=_ctx())
    b = generate_stage("stage2_two_factor", _space(),
                       budgets={"stage2_two_factor": 5}, ctx=_ctx())
    assert [d["meta"]["candidate_id"] for d in a] == \
        [d["meta"]["candidate_id"] for d in b]
    other = generate_stage("stage2_two_factor", _space(),
                           budgets={"stage2_two_factor": 5},
                           ctx=GenerationContext(campaign_id="camp_other"))
    assert [d["meta"]["candidate_id"] for d in a] != \
        [d["meta"]["candidate_id"] for d in other]


def test_manifest_contains_all_required_fields_and_is_hashed():
    orch = DiscoveryOrchestrator(
        _space(), budgets={"stage1_single_indicator": 3,
                           "stage2_two_factor": 3},
        policy_hash="p" * 64, dataset_id="ds-2026-09",
        dataset_hash="d" * 64, data_horizon="2020-01..2026-01",
        cost_config={"spread": 1.0}, risk_config={"risk_per_trade": 0.01},
        gate_policy="gates-1.0", campaign_id="camp_conv",
        hypothesis="structural breakout persists", seed=7,
        strategy_parent="parent_a", oos_boundary="last_20pct")
    run, _ = _pipeline({})
    camp = orch.run_campaign({"campaign_id": "camp_conv", "progress": {},
                              "results": {}}, run)
    m = orch.manifest(camp)
    required = ["campaign_id", "strategy_parent", "hypothesis",
                "search_space", "candidate_count", "candidate_ids",
                "dataset_id", "dataset_hash", "data_horizon",
                "cost_config", "risk_config", "gate_policy",
                "score_policy", "DSL_version", "code_version",
                "generator_version", "random_seed", "OOS_boundary",
                "selected_candidates", "rejected_candidates"]
    for k in required:
        assert k in m, k
    assert m["generator_version"] == GENERATOR_VERSION
    assert m["DSL_version"] == "1.0"
    assert m["random_seed"] == 7
    assert m["OOS_boundary"] == "last_20pct"
    # manifest is self-hashed over its own content
    assert m["manifest_hash"] and len(m["manifest_hash"]) == 64
    from mql5bot.discovery.candidates import doc_hash
    body = {k: v for k, v in m.items() if k != "manifest_hash"}
    assert doc_hash(body) == m["manifest_hash"]


def _pipeline(states_by_stage: dict):
    def run_stage(stage, docs):
        out = []
        for i, d in enumerate(docs):
            st = states_by_stage.get(stage, "OOS_SURVIVOR") if i == 0 \
                else "BACKTESTED"
            out.append({"strategy_id": d["strategy_id"], "state": st})
        return out
    return run_stage, None


def test_trial_accounting_counts_every_alternative():
    orch = DiscoveryOrchestrator(
        _space(), budgets={"stage1_single_indicator": 3,
                           "stage2_two_factor": 2, "stage3_multi_factor": 2,
                           "stage5_mutations": 2},
        policy_hash="p" * 64)
    run, _ = _pipeline({})
    camp = orch.run_campaign({"campaign_id": "c", "progress": {},
                              "results": {}}, run)
    ta = orch.manifest(camp)["trial_accounting"]
    assert ta["total_candidates"] == 9
    assert len(ta["selected"]) == 4   # i==0 per executed stage
    assert len(ta["rejected"]) == 5
    assert ta["mutations"] == 2
    assert ta["strategy_families"] >= 1
    assert ta["parameter_trials"] >= ta["total_candidates"]


def test_resume_refuses_foreign_dataset_hash():
    orch = DiscoveryOrchestrator(_space(), policy_hash="a" * 64,
                                 dataset_hash="d1" * 32)
    camp = {"campaign_id": "c", "progress": {}, "results": {},
            "policy_hash": "a" * 64, "dataset_hash": "d2" * 32}
    with pytest.raises(ValueError, match="DIFFERENT dataset"):
        orch.run_campaign(camp, lambda stage, docs: [])


def test_ranking_uses_score_only_for_eligible_and_records_unavailable():
    orch = DiscoveryOrchestrator(
        _space(), budgets={"stage1_single_indicator": 2},
        policy_hash="p" * 64)
    run, _ = _pipeline({"stage1_single_indicator": "OOS_SURVIVOR"})
    camp = orch.run_campaign({"campaign_id": "c", "progress": {},
                              "results": {}}, run)
    ranked = orch.rank_candidates(camp, lambda item: compute_score(
        _full_measurements()))
    assert ranked[0]["score"] > 0
    assert isinstance(ranked[0]["unavailable"], list)
