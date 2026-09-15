"""Meta Layer OOS validation + equal-weight baseline (Phases 14-15)."""

import pytest
from mql5bot.data import generate_ohlc
from mql5bot.meta_layer import MetaConfig, MetaPolicy
from mql5bot.meta_oos import (
    META_POLICY_ID,
    StrategySpec,
    dev_fold_table,
    policy_weights,
    run_meta_oos,
    verify_frozen,
)

SPECS = [StrategySpec("ema_crossover", {"fast": 8, "slow": 30}),
         StrategySpec("donchian_breakout", {"lookback": 20})]


@pytest.fixture(scope="module")
def dev():
    return generate_ohlc(days=120, seed=8)


@pytest.fixture(scope="module")
def oos():
    return generate_ohlc(days=40, seed=12, start="2025-01-01")


# ---- Phase 14: equal-weight baseline is first-class ------------------------


def test_equal_weight_baseline_differs_only_in_weighting(dev):
    stats = {"donchian_breakout": (0.01, 200), "ema_crossover": (-0.005, 90)}
    w_meta = policy_weights(MetaConfig(), SPECS, stats)
    w_eq = policy_weights(MetaConfig(policy=MetaPolicy.EQUAL_WEIGHT),
                          SPECS, stats)
    # same eligibility, same support, only the weighting policy differs
    assert set(w_meta) == set(w_eq) == {"donchian_breakout", "ema_crossover"}
    assert sum(w_eq.values()) == pytest.approx(sum(w_meta.values()), abs=1e-9)
    assert w_eq["donchian_breakout"] == pytest.approx(0.5, abs=1e-9)
    assert w_meta["donchian_breakout"] > w_eq["donchian_breakout"]
    # identical stats -> meta converges to equal weights (no hidden boost)
    same = {"donchian_breakout": (0.0, 100), "ema_crossover": (0.0, 100)}
    w1 = policy_weights(MetaConfig(), SPECS, same)
    assert w1["donchian_breakout"] == pytest.approx(0.5, abs=1e-9)


def test_fold_diagnostics_run_both_policies(dev):
    rows = dev_fold_table(dev, SPECS, MetaConfig(), n_folds=3)
    assert rows, "folds must be non-empty on a 120-day frame"
    for row in rows:
        assert set(row["meta"]) == set(row["equal_weight"])
        assert "sharpe" in row["meta"] and "max_dd" in row["equal_weight"]


# ---- Phase 15: one-look OOS discipline --------------------------------------


def test_oos_one_look_recorded_and_refused_afterwards(dev, oos, tmp_path):
    from mql5bot.pipeline import OosOneLookViolation, OosRegistry

    reg = OosRegistry(tmp_path / "oos.json")
    cfg = MetaConfig()
    out = run_meta_oos(dev, oos, SPECS, cfg, registry=reg)
    # the full identity block is recorded
    assert set(out["identity"]) == {
        "meta_config_version", "meta_parameter_hash", "dataset_digest",
        "strategy_versions", "engine_version", "cost_version",
        "regime_version"}
    assert out["identity"]["meta_parameter_hash"] == cfg.config_hash
    assert reg.has_look(META_POLICY_ID, out["identity"]["dataset_digest"])
    # a SECOND look is refused EVEN WITH A DIFFERENT CONFIG: the OOS
    # slice can never become a tuning loop
    with pytest.raises(OosOneLookViolation):
        run_meta_oos(dev, oos, SPECS, MetaConfig(max_strategy_weight=0.9),
                     registry=reg)


def test_no_oos_tuning_frozen_hash_binds_the_record(dev, oos):
    out = run_meta_oos(dev, oos, SPECS, MetaConfig())
    assert verify_frozen(out["identity"]["meta_parameter_hash"],
                         MetaConfig())
    assert not verify_frozen(out["identity"]["meta_parameter_hash"],
                             MetaConfig(vote_threshold=0.8))


def test_no_optuna_anywhere_in_meta_modules():
    import sys
    for mod in ("mql5bot.meta_layer", "mql5bot.meta_oos"):
        assert mod not in sys.modules or not hasattr(
            sys.modules.get(mod), "optuna")
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    src_layer = (root / "python/mql5bot/meta_layer.py").read_text()
    src_oos = (root / "python/mql5bot/meta_oos.py").read_text()
    assert "optuna" not in src_layer.lower()
    assert "optuna" not in src_oos.lower()
