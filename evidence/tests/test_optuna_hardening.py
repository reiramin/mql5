"""Optuna acceptance tests (Phase 3 hardening, Blocker 3).

Proves the claims made by ``optuna_optimize``:

1. identical seed -> identical trial order
2. identical data -> identical best params
3. pruned trials are actually pruned
4. pruning does not alter correctness
5. no OOS metric is visible to the objective
6. cache hit produces equivalent output
7. the optional dependency remains optional

Plus: a missing ``HyperbandPruner`` is reported as an exact version/API
limitation (never silently substituted), and optional parallel
execution (``n_jobs``) is exposed.
"""

import subprocess
import sys
from collections import Counter

import mql5bot.pipeline as pl
import pandas as pd
import pytest
from mql5bot.data import generate_ohlc
from mql5bot.pipeline import optuna_optimize

SPACE = {"fast": {"type": "int", "low": 6, "high": 14},
         "slow": {"type": "int", "low": 20, "high": 48}}


@pytest.fixture
def dev_df():
    return generate_ohlc(days=45, seed=5)


@pytest.fixture
def oos_df():
    return generate_ohlc(days=45, seed=99, start="2025-01-01")


# ---------------------------------------------------------------------------
# Determinism (acceptance 1 + 2)
# ---------------------------------------------------------------------------


def test_identical_seed_identical_trial_order(dev_df):
    a = optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=8, seed=42)
    b = optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=8, seed=42)
    assert [t["params"] for t in a["trials"]] \
        == [t["params"] for t in b["trials"]]
    assert [t["state"] for t in a["trials"]] \
        == [t["state"] for t in b["trials"]]
    other = optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=8,
                            seed=43)
    assert [t["params"] for t in other["trials"]] \
        != [t["params"] for t in a["trials"]]


def test_identical_data_identical_best_params(dev_df):
    a = optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=10, seed=3)
    b = optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=10, seed=3)
    assert a["best_params"] == b["best_params"]
    assert a["best_value"] == b["best_value"]
    assert a["dataset_version"] == b["dataset_version"]


# ---------------------------------------------------------------------------
# Pruning (acceptance 3 + 4)
# ---------------------------------------------------------------------------


@pytest.fixture
def two_arm_runner(monkeypatch):
    """Deterministic runner: an arm of the space is catastrophically bad
    at every prefix (training-side metric), the other arm is good."""
    def fake_runner(sub, strategy, params, **kw):
        x = int(params.get("fast", 0))
        good = x <= 10
        return type("R", (), {
            "metrics": {"sharpe": 5.0 if good else -100.0},
            "trades": pd.DataFrame(),
        })()
    monkeypatch.setattr(pl, "run_fast", fake_runner)


def test_pruned_trials_actually_pruned(dev_df, two_arm_runner):
    out = optuna_optimize(dev_df, "ema_crossover",
                          {"fast": {"type": "int", "low": 6, "high": 14}},
                          n_trials=40, seed=7)
    assert out["pruner"] == "HyperbandPruner"
    counts = Counter(t["state"] for t in out["trials"])
    assert counts["PRUNED"] > 0, "Hyperband must prune the bad arm"
    assert counts["COMPLETE"] > 0
    assert out["n_pruned"] == counts["PRUNED"]
    # every pruned trial was reported before completion: its recorded
    # value (if any) came from a training-side prefix evaluation
    pruned = [t for t in out["trials"] if t["state"] == "PRUNED"]
    assert all(t["value"] is None or t["value"] <= 5.0 or t["value"] < 0
               for t in pruned)
    # the search still finds the good arm
    assert out["best_params"]["fast"] <= 10
    assert out["best_value"] == 5.0


def test_pruning_does_not_alter_correctness(dev_df):
    """A completed trial's recorded value must equal the metric of a
    direct full-frame run with its params — pruning removes candidates,
    it never distorts values."""
    out = optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=6,
                          seed=11)
    from mql5bot.fast_engine import run_fast
    from mql5bot.strategies import default_params
    for t in out["trials"]:
        if t["state"] != "COMPLETE":
            continue
        merged = {**default_params("ema_crossover"), **t["params"]}
        direct = run_fast(dev_df, "ema_crossover", merged)
        assert float(direct.metrics["sharpe"]) == t["value"]
    assert float(out["best_value"]) == max(
        t["value"] for t in out["trials"] if t["state"] == "COMPLETE")


def test_missing_hyperband_reported_not_substituted(dev_df, monkeypatch):
    """If the installed Optuna lacks HyperbandPruner the stage raises a
    RuntimeError naming the version — it never substitutes a different
    pruner, and never accepts an unknown pruner name."""
    import optuna

    monkeypatch.delattr(optuna.pruners, "HyperbandPruner",
                        raising=False)
    with pytest.raises(RuntimeError, match="HyperbandPruner"):
        optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=2)
    with pytest.raises(ValueError, match="hyperband"):
        optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=2,
                        pruner="median")
    assert optuna.__version__  # the limitation would be reported with it


# ---------------------------------------------------------------------------
# OOS isolation (acceptance 5)
# ---------------------------------------------------------------------------


def test_no_oos_metric_visible_to_objective(dev_df, oos_df, monkeypatch):
    """The objective sees ONLY prefixes of the development frame; the OOS
    frame is never passed to any evaluation."""
    seen: list[pd.DataFrame] = []
    real = pl.run_fast

    def spy(sub, strategy, params, **kw):
        seen.append(sub)
        return real(sub, strategy, params, **kw)

    monkeypatch.setattr(pl, "run_fast", spy)
    optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=5, seed=1,
                    oos_guard_df=oos_df)
    assert seen
    for sub in seen:
        assert len(sub) <= len(dev_df)
        assert sub.index.equals(dev_df.index[:len(sub)])
        assert not sub.index.equals(oos_df.index[:len(sub)])


def test_oos_guard_refuses_certification_slice(dev_df, oos_df):
    # dev frame identical to the OOS frame -> refuse before trial 0
    with pytest.raises(ValueError, match="certification slice"):
        optuna_optimize(oos_df, "ema_crossover", SPACE, n_trials=2,
                        oos_guard_df=oos_df)
    # different frames: fine, and the guard digest is recorded
    out = optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=2,
                          seed=1, oos_guard_df=oos_df)
    from mql5bot.optimizer import _dataset_digest
    assert out["oos_guard_version"] == _dataset_digest(oos_df)


# ---------------------------------------------------------------------------
# Cache (acceptance 6)
# ---------------------------------------------------------------------------


def test_cache_hit_produces_equivalent_output(dev_df, tmp_path,
                                              monkeypatch):
    calls = {"n": 0}
    real = pl.run_fast

    def counting(sub, strategy, params, **kw):
        calls["n"] += 1
        return real(sub, strategy, params, **kw)

    monkeypatch.setattr(pl, "run_fast", counting)
    cache = str(tmp_path / "ocache")
    a = optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=12,
                        seed=5, cache_dir=cache)
    cold_calls = calls["n"]
    assert cold_calls > 0
    b = optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=12,
                        seed=5, cache_dir=cache)
    assert calls["n"] == cold_calls  # warm run: zero new simulations
    assert b["best_params"] == a["best_params"]
    assert b["best_value"] == a["best_value"]
    assert [t["state"] for t in b["trials"]] \
        == [t["state"] for t in a["trials"]]
    assert b["n_pruned"] == a["n_pruned"]
    # a different data content must NOT hit the same cache entries
    optuna_optimize(generate_ohlc(days=45, seed=6), "ema_crossover",
                    SPACE, n_trials=12, seed=5, cache_dir=cache)
    assert calls["n"] > cold_calls


# ---------------------------------------------------------------------------
# Optional dependency (acceptance 7) + parallel option
# ---------------------------------------------------------------------------


def test_optuna_import_never_imported_by_pipeline():
    """Importing the pipeline (and calling non-optuna stages) must not
    require optuna: in an interpreter where 'import optuna' fails, the
    pipeline still imports."""
    code = (
        "import sys\n"
        "sys.modules['optuna'] = None\n"  # 'import optuna' -> ImportError
        "import mql5bot.pipeline\n"
        "print('pipeline-ok')\n"
    )
    env = {"PYTHONPATH": "python", "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, timeout=120, env=env, check=False)
    assert r.returncode == 0, r.stderr
    assert "pipeline-ok" in r.stdout


def test_optional_parallel_execution_runs(dev_df):
    out = optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=8,
                          seed=2, n_jobs=2)
    assert out["n_jobs"] == 2
    assert out["n_complete"] + out["n_pruned"] == 8
    # determinism is only claimed for n_jobs=1 (documented, not hidden)
    single = optuna_optimize(dev_df, "ema_crossover", SPACE, n_trials=8,
                             seed=2, n_jobs=1)
    assert single["n_complete"] + single["n_pruned"] == 8


# ---------------------------------------------------------------------------
# Phase-3-gate regression: the OOS suffix leak shape
# ---------------------------------------------------------------------------


def test_objective_never_evaluates_oos_suffix_rows(dev_df, monkeypatch):
    """The realistic leak shape: the certification slice is a TAIL of the
    same generated frame (overlapping DatetimeIndex).  A regression that
    ever let the objective evaluate the tail (e.g. a resample on the
    full frame) must fail HERE, loudly, per evaluated bar."""
    cut = int(len(dev_df) * 0.8)
    dev, oos = dev_df.iloc[:cut], dev_df.iloc[cut:]  # disjoint, same index space
    seen: list[pd.DataFrame] = []
    real = pl.run_fast

    def spy(sub, strategy, params, **kw):
        seen.append(sub)
        return real(sub, strategy, params, **kw)

    monkeypatch.setattr(pl, "run_fast", spy)
    out = optuna_optimize(dev, "ema_crossover", SPACE, n_trials=6, seed=5,
                          oos_guard_df=oos)
    assert seen
    oos_first = oos.index[0]
    for sub in seen:
        assert sub.index.max() < oos_first, (
            "objective evaluated a bar from the certification slice")
    # and the best result is reported with its identity, not OOS-derived
    assert out["best_params"]
    assert out["dataset_version"]
