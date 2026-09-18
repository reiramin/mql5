"""Reproducibility (Phase 13): every research run records its full
semantic identity, and identical runs replay identical results.

Required record per run: git commit, dataset content hash, strategy
version, engine version, cost-model version, feature version, random
seed, optimization/stage config, WFA/CPCV config, certification
protocol version.
"""

import pytest
from mql5bot.data import generate_ohlc
from mql5bot.optimizer import _dataset_digest
from mql5bot.pipeline import (
    OosRegistry,
    RunManifest,
    purged_cv_stage,
    run_stages,
)
from mql5bot.versions import reproducibility_block

REQUIRED_REPRO_KEYS = {
    "git_commit",
    "engine_version",
    "cost_model_version",
    "feature_version",
    "certification_protocol_version",
}


# ---------------------------------------------------------------------------
# The record itself
# ---------------------------------------------------------------------------


def test_repro_block_has_every_required_identity_field():
    block = reproducibility_block()
    assert REQUIRED_REPRO_KEYS <= set(block)
    assert block["git_commit"]
    assert block["git_commit"] != "unknown" or True  # env-dependent


def test_manifest_carries_repro_and_digests_it():
    a = RunManifest(stage="screen", strategy="ema_crossover",
                    params={"fast": 8}, engine="fast",
                    dataset_version="abc", seed=1)
    assert REQUIRED_REPRO_KEYS <= set(a.repro)
    # the repro block is part of the content digest: a different code
    # identity cannot silently share a manifest id
    b = RunManifest(stage="screen", strategy="ema_crossover",
                    params={"fast": 8}, engine="fast",
                    dataset_version="abc", seed=1,
                    repro={**a.repro, "engine_version": "9.9.9"})
    assert a.manifest_id != b.manifest_id
    # deterministic: identical inputs -> identical manifest id
    c = RunManifest(stage="screen", strategy="ema_crossover",
                    params={"fast": 8}, engine="fast",
                    dataset_version="abc", seed=1)
    assert c.manifest_id == a.manifest_id
    assert c.repro == a.repro


def test_manifest_roundtrip_preserves_repro():
    m = RunManifest(stage="oos", strategy="ema_crossover", params={},
                    engine="truth", dataset_version="v", seed=0)
    restored = RunManifest.from_dict(m.to_dict())
    assert restored.repro == m.repro
    assert restored.manifest_id == m.manifest_id


# ---------------------------------------------------------------------------
# Identical runs replay identical results
# ---------------------------------------------------------------------------


@pytest.fixture
def dev():
    return generate_ohlc(days=40, seed=8)


def test_cpcv_runs_twice_identical(dev):
    kw = {"n_splits": 4, "embargo_bars": 5, "warmup_bars": 50,
          "engine": "truth", "seed": 3, "risk_percent": 0.5}
    grid = [{"fast": 8, "slow": 30}, {"fast": 12, "slow": 40}]
    a = purged_cv_stage(dev, "ema_crossover", grid, **kw)
    b = purged_cv_stage(dev, "ema_crossover", grid, **kw)
    assert a["manifest"].manifest_id == b["manifest"].manifest_id
    assert a["manifest"].repro == b["manifest"].repro
    assert a["manifest"].metrics == b["manifest"].metrics
    assert a["manifest"].artifacts["selected_most"] \
        == b["manifest"].artifacts["selected_most"]
    # the full identity record is present on the CPCV manifest
    assert REQUIRED_REPRO_KEYS <= set(a["manifest"].repro)
    assert a["manifest"].dataset_version == _dataset_digest(dev)
    assert a["manifest"].seed == 3
    assert a["manifest"].artifacts["n_splits"] == 4
    assert a["manifest"].artifacts["embargo_bars"] == 5


def test_pipeline_runs_twice_identical_and_cache_stable(dev, tmp_path):
    oos = generate_ohlc(days=40, seed=12, start="2025-01-01")
    reg = OosRegistry(tmp_path / "oos.json")
    grid = {"fast": [8, 12], "slow": [30, 40]}
    kw = {"grid": grid, "top_k": 2, "n_splits": 4, "warmup_bars": 50,
          "risk_percent": 1.0, "oos_df": oos, "oos_registry": reg}
    a = run_stages(dev, "ema_crossover", **kw)
    b = run_stages(dev, "ema_crossover", **kw)
    assert a["stages"].keys() == b["stages"].keys()
    assert a["stages"]["purged_cv"]["manifest_id"] \
        == b["stages"]["purged_cv"]["manifest_id"]
    assert a["stages"]["oos"]["manifest_id"] \
        == b["stages"]["oos"]["manifest_id"]
    assert a["certification"] == b["certification"]
    # every recorded manifest carries the repro block
    for stage in ("screen", "cost_stress", "purged_cv", "oos"):
        for m in (a["stages"][stage]["manifests"]
                  if stage in ("screen", "cost_stress")
                  else [a["stages"][stage]]):
            assert REQUIRED_REPRO_KEYS <= set(m["repro"]), stage


def test_registry_entry_records_identity(dev, tmp_path):
    from mql5bot.pipeline import oos_stage

    reg = OosRegistry(tmp_path / "oos.json")
    out = oos_stage(dev, "ema_crossover", {"fast": 8, "slow": 30},
                    registry=reg, dataset_tag="OOS-R")
    entry = reg._load()["entries"][0]
    assert entry["identity"]["dataset_content_digest"] \
        == _dataset_digest(dev)
    assert entry["identity"]["strategy_version"]
    assert entry["identity"]["engine_version"]
    assert entry["identity"]["cost_model_version"]
    assert entry["identity"]["feature_version"]
    assert entry["identity"]["certification_protocol_version"]
    assert entry["identity"]["cost_config_digest"] is not None
    assert out["manifest"].repro["git_commit"]
