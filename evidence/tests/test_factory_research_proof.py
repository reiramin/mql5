"""AEGIS INTEGRATION GATE — reproducibility, immutability, manifest
and multiple-testing proofs (mission §6/§7/§8/§9, §29.5).

Companion to tests/test_factory_e2e.py (the lifecycle journey).  Here
the proofs are about IDENTITY and RESEARCH ACCOUNTING:

- any logic change ⇒ new spec_hash ⇒ new version; old evidence stays
  bound to the old version (§6);
- identical inputs reproduce identical artifacts, exactly (§7);
- campaigns persist complete manifests with the search context, and
  the selected candidate can never masquerade as the only trial (§8/§9).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from mql5bot.backtest import run_backtest
from mql5bot.data import generate_ohlc
from mql5bot.dsl import desired_positions, parse_spec
from mql5bot.factory import lifecycle as lc
from mql5bot.factory.research import Campaign
from mql5bot.factory.store import FactoryStore, StoreError

from tests.test_factory_e2e import (
    DAYS,
    FIXTURE_POLICY,
    PARAMS,
    RISK,
    SEED,
    fixture_document,
)

ROOT = Path(__file__).resolve().parent.parent


def _df():
    return generate_ohlc(days=DAYS, seed=SEED, annual_vol=0.10,
                         drift=0.30)


# ---------------------------------------------------------------- §6


def test_version_immutability_across_every_modification(tmp_path):
    """Any logic change ⇒ different spec_hash ⇒ new version; history
    stays bound to the old version (§6)."""
    store = FactoryStore(tmp_path / "factory.db")
    base = fixture_document(version=1)
    s1 = parse_spec(base)
    store.register_strategy(s1, created_by="t")
    rid1 = store.record_run(s1.strategy_id, 1, run_type="parse",
                            status="PASS", spec_hash=s1.spec_hash)
    mods = {
        "entry": lambda d: d.update(
            {"entry": {**d["entry"],
                       "long": d["entry"]["long"]["and"][0]}}),
        "exit": lambda d: d["exit"]["sl"].__setitem__("mult", 2.0),
        "indicator_param": lambda d: d["indicators"][0].__setitem__(
            "period", 25),
        "timeframe": lambda d: d["market"].__setitem__("timeframe", "D1"),
        "symbol": lambda d: d["market"].__setitem__("symbol", "GBPUSD"),
        "stop": lambda d: d["exit"]["sl"].__setitem__("mult", 2.5),
        "target": lambda d: d["exit"]["tp"].__setitem__("mult", 4.0),
        "filter": lambda d: d["entry"]["long"]["and"].append(
            {"left": {"ind": "rsi_m"}, "cmp": "LT",
             "right": {"const": 70.0}}),
    }
    hashes = {}
    for i, (name, mutate) in enumerate(sorted(mods.items()), start=2):
        doc = json.loads(json.dumps(base))
        mutate(doc)
        doc["version"] = i
        s = parse_spec(doc)
        assert s.spec_hash != s1.spec_hash, name
        assert len({s.spec_hash, *hashes.values()}) == len(hashes) + 1
        hashes[name] = s.spec_hash
        store.register_strategy(s, created_by="t",
                                parent=(s1.strategy_id, 1))
        # historical run v1 is NOT evidence for the new version
        with pytest.raises(StoreError, match="not evidence"):
            store.transition(s.strategy_id, i, lc.PARSED,
                             evidence_refs=(rid1,), actor="t")
        rid = store.record_run(s.strategy_id, i, run_type="parse",
                               status="PASS", spec_hash=s.spec_hash)
        store.transition(s.strategy_id, i, lc.PARSED,
                         evidence_refs=(rid,), actor="t")
    # v1 history untouched by all the v2..v9 registrations
    with store.session() as sess:
        from mql5bot.factory.models import ValidationRun
        from sqlalchemy import select
        runs1 = list(sess.scalars(select(ValidationRun).where(
            ValidationRun.strategy_id == s1.strategy_id,
            ValidationRun.version == 1)))
    assert len(runs1) == 1 and runs1[0].spec_hash == s1.spec_hash


# ---------------------------------------------------------------- §7


def test_reproducibility_same_inputs_same_results():
    df = generate_ohlc(days=DAYS, seed=SEED, annual_vol=0.10, drift=0.30)
    spec = parse_spec(fixture_document())
    sig = desired_positions(spec, df)
    a = run_backtest(df, "dsl:rep", PARAMS, signal=sig, risk_percent=RISK)
    b = run_backtest(df, "dsl:rep", PARAMS, signal=sig, risk_percent=RISK)
    # deterministic engine: EXACT float equality (documented tolerance:
    # 0.0 — same code version, same data, same seed, same platform)
    assert a.metrics == b.metrics
    pd.testing.assert_frame_equal(a.trades, b.trades)
    pd.testing.assert_series_equal(a.equity, b.equity)


def test_campaign_replay_reproduces_manifest():
    """§7/§29.5: replaying the same campaign reproduces the manifest
    hash (same seeds, same data hash, same code identity)."""
    df = _df()
    parent = parse_spec(fixture_document())
    camp_a = Campaign(campaign_id="camp-repro",
                      parent_strategy_id=parent.strategy_id,
                      parent_version=1,
                      search_space={"max_candidates": 2,
                                    "grid": {"period": [20, 25]}},
                      data_version=f"synthetic-{SEED}",
                      data_timestamps=str(df.index[0]) + ".."
                      + str(df.index[-1]),
                      cost_model="spread=1.0,slippage=0",
                      broker_assumptions="fixture",
                      methodology="deterministic fixture replay",
                      gate_versions=[FIXTURE_POLICY["policy_version"]],
                      code_commit="fixture", dsl_version="1.0",
                      random_seed=SEED,
                      created_at="2026-09-06T00:00:00+00:00")
    camp_b = Campaign(campaign_id="camp-repro",
                      parent_strategy_id=parent.strategy_id,
                      parent_version=1,
                      search_space={"max_candidates": 2,
                                    "grid": {"period": [20, 25]}},
                      data_version=f"synthetic-{SEED}",
                      data_timestamps=str(df.index[0]) + ".."
                      + str(df.index[-1]),
                      cost_model="spread=1.0,slippage=0",
                      broker_assumptions="fixture",
                      methodology="deterministic fixture replay",
                      gate_versions=[FIXTURE_POLICY["policy_version"]],
                      code_commit="fixture", dsl_version="1.0",
                      random_seed=SEED,
                      created_at="2026-09-06T00:00:00+00:00")
    for period in (20, 25):
        doc = json.loads(json.dumps(parent.document))
        doc["indicators"][0]["period"] = period
        doc["strategy_id"] = f"cand_{period}"
        doc["version"] = 1
        note = f"period={period}"
        camp_a.register_candidate(parse_spec(doc), mutation_note=note)
        camp_b.register_candidate(parse_spec(doc), mutation_note=note)
    assert camp_a.manifest_hash() == camp_b.manifest_hash()
    man = camp_a.manifest()
    assert man["candidate_count"] == 2 and man["n_trials_for_dsr"] == 2
    assert "research_selection_bias_warning" in man


# ---------------------------------------------------------------- §8/§9


def test_manifest_completeness_and_multiple_testing():
    """§8: every required manifest field present; §9: the whole search
    context (budget, rejects with reasons, selection + warning)."""
    df = _df()
    parent = parse_spec(fixture_document())
    camp = Campaign(campaign_id="camp-mt",
                    parent_strategy_id=parent.strategy_id,
                    parent_version=1,
                    search_space={"max_candidates": 3,
                                  "grid": {"period": [18, 20, 25]}},
                    data_version=f"synthetic-{SEED}",
                    data_timestamps=str(df.index[0]) + ".."
                    + str(df.index[-1]),
                    cost_model="spread=1.0,slippage=0",
                    broker_assumptions="fixture",
                    methodology="single-axis parameter scan",
                    gate_versions=[FIXTURE_POLICY["policy_version"]],
                    code_commit="fixture", dsl_version="1.0",
                    random_seed=SEED)
    results = {}
    for period in (18, 20, 25):
        doc = json.loads(json.dumps(parent.document))
        doc["indicators"][0]["period"] = period
        doc["strategy_id"] = f"cand_{period}"
        doc["version"] = 1
        spec = parse_spec(doc)
        camp.register_candidate(spec, mutation_note=f"period={period}")
        sig = desired_positions(spec, df.iloc[: int(len(df) * 0.7)])
        r = run_backtest(df.iloc[: int(len(df) * 0.7)], "dsl:scan",
                         PARAMS, signal=sig, risk_percent=RISK)
        results[period] = float(r.metrics["profit_factor"])
    ranked = sorted(results, key=lambda p: results[p], reverse=True)
    best = ranked[0]
    for period in ranked[1:]:
        camp.reject(f"cand_{period}",
                    f"IS PF {results[period]:.4f} < best "
                    f"{results[best]:.4f}")
    camp.select(f"cand_{best}",
                f"highest IS PF {results[best]:.4f} within budget")
    man = camp.manifest()
    for key in ("campaign_id", "parent", "candidate_count",
                "mutation_count", "search_space", "data_version",
                "data_timestamps", "cost_model", "broker_assumptions",
                "test_methodology", "gate_versions", "code_version",
                "dsl_version", "random_seed", "selected_candidate",
                "rejected_candidates", "candidates",
                "research_selection_bias_warning", "n_trials_for_dsr"):
        assert key in man, key
    assert man["candidate_count"] == 3
    assert man["search_space"]["max_candidates"] == 3   # declared first
    assert len(man["rejected_candidates"]) == 2
    assert man["selected_candidate"]["strategy_id"] == f"cand_{best}"
    assert man["n_trials_for_dsr"] == 3
    # the selection can never masquerade as the only trial (§9)
    assert "3 candidates were tried" in \
        man["research_selection_bias_warning"]
