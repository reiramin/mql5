"""Staged screening pipeline (plan Phase D) — manifests, purge/embargo
CPCV, cost stress, one-look OOS registry, cache, Optuna guard."""

import json

import numpy as np
import pandas as pd
import pytest
from mql5bot.data import generate_ohlc
from mql5bot.pipeline import (
    OosOneLookViolation,
    OosRegistry,
    RunManifest,
    _block_edges,
    _entry_index_map,
    _pnl_per_bar,
    cost_stress_stage,
    dataset_version_of,
    mt5_stage,
    oos_stage,
    optuna_optimize,
    purged_cv_stage,
    run_stages,
    screen_stage,
)


@pytest.fixture
def df_small():
    return generate_ohlc(days=20, seed=5)  # 480 hourly bars


def _trend_frame(seed: int, n: int, drift: float = 0.00012) -> pd.DataFrame:
    """Slowly trending random walk (trend-following strategies survive)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    px = 1.08 * np.exp(np.cumsum(rng.normal(drift, 0.0011, n)))
    o = px * (1 + rng.normal(0, 2e-5, n))
    c = px * (1 + rng.normal(0, 2e-5, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 2e-5, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 2e-5, n)))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c},
                        index=idx)


# --------------------------------------------------------------------------
# Manifests
# --------------------------------------------------------------------------


def test_manifest_digest_deterministic_and_created_free():
    a = RunManifest(stage="screen", strategy="ema_crossover",
                    params={"fast": 8, "slow": 24}, engine="fast",
                    dataset_version="abc", seed=3)
    b = RunManifest(stage="screen", strategy="ema_crossover",
                    params={"fast": 8, "slow": 24}, engine="fast",
                    dataset_version="abc", seed=3)
    assert a.manifest_id == b.manifest_id
    assert a.manifest_id == a.digest()
    # wall-clock created is excluded from the id
    c = RunManifest(stage="screen", strategy="ema_crossover",
                    params={"fast": 8, "slow": 24}, engine="fast",
                    dataset_version="abc", seed=3,
                    created="1999-01-01T00:00:00+00:00")
    assert c.manifest_id == a.manifest_id
    # any content change changes the id
    d = RunManifest(stage="screen", strategy="ema_crossover",
                    params={"fast": 9, "slow": 24}, engine="fast",
                    dataset_version="abc", seed=3)
    assert d.manifest_id != a.manifest_id
    # round trip survives (asdict/from_dict) with a stable id
    again = RunManifest.from_dict(a.to_dict())
    assert again.manifest_id == a.manifest_id


def test_dataset_version_tag_or_digest():
    df = generate_ohlc(days=10, seed=1)
    assert dataset_version_of(df, "v7") == "v7"
    d1 = dataset_version_of(df)
    assert isinstance(d1, str) and len(d1) == 40
    df2 = df.copy()
    df2.iloc[5, df2.columns.get_loc("close")] += 1e-9
    assert dataset_version_of(df2) != d1


# --------------------------------------------------------------------------
# S1 — screen
# --------------------------------------------------------------------------


def test_screen_stage_ranks_and_marks_fast(df_small):
    out = screen_stage(df_small, "ema_crossover",
                       grid={"fast": [8, 12], "slow": [24, 40]},
                       top_k=2, risk_percent=0.5, max_bars=100)
    ms = out["manifests"]
    assert len(ms) == 2
    assert all(m.engine == "fast" for m in ms)
    assert all(m.status == "ok" for m in ms)
    vals = [m.metrics["sharpe"] for m in ms]
    assert vals == sorted(vals, reverse=True)
    # manifests carry the effective params (defaults merged)
    assert ms[0].params["sl_atr"] == 2.5
    # deterministic across calls
    out2 = screen_stage(df_small, "ema_crossover",
                        grid={"fast": [8, 12], "slow": [24, 40]},
                        top_k=2, risk_percent=0.5, max_bars=100)
    assert [m.manifest_id for m in out2["manifests"]] == \
        [m.manifest_id for m in ms]


def test_screen_stage_gates(df_small):
    with pytest.raises(ValueError):
        screen_stage(df_small, "ema_crossover", {}, top_k=1)
    with pytest.raises(ValueError):
        screen_stage(df_small, "ema_crossover", {"fast": [8]}, top_k=0)
    with pytest.raises(ValueError):
        screen_stage(df_small, "ema_crossover", {"fast": [8]}, engine="x")
    with pytest.raises(KeyError):
        screen_stage(df_small, "no_such", {"fast": [8]}, top_k=1)


# --------------------------------------------------------------------------
# S2 — cost stress
# --------------------------------------------------------------------------


def test_cost_stress_doubles_costs_and_gates(df_small):
    params = {"fast": 10, "slow": 30}
    out = cost_stress_stage(df_small, "ema_crossover", [params],
                            min_trades=5, risk_percent=0.5,
                            commission_per_lot=7.0, spread_points=1.0,
                            slippage_points=0.0)
    m = out["manifests"][0]
    assert m.artifacts["factor"] == 2.0
    assert m.cost_config["commission_per_lot"] == pytest.approx(14.0)
    assert m.cost_config["spread_points"] == pytest.approx(2.0)
    # strictly higher costs on identical fills -> strictly lower end equity
    assert m.artifacts["stressed_end_equity"] < \
        m.artifacts["base_end_equity"]


def test_cost_stress_gate_drops_below_min_trades(df_small):
    out = cost_stress_stage(df_small, "ema_crossover",
                            [{"fast": 10, "slow": 30}],
                            min_trades=10**6, risk_percent=0.5)
    assert out["manifests"][0].status == "dropped"


# --------------------------------------------------------------------------
# S3 — trade-level purged CPCV
# --------------------------------------------------------------------------


def test_block_edges_and_pnl_helpers():
    edges = _block_edges(100, 4)
    assert edges == [(0, 25), (25, 50), (50, 75), (75, 100)]
    edges = _block_edges(103, 4)
    assert edges[-1] == (75, 103)  # remainder absorbed by the last block
    with pytest.raises(ValueError):
        _block_edges(3, 4)

    idx = pd.date_range("2024-01-01", periods=5, freq="h")
    pos = _entry_index_map(idx)
    assert pos["2024-01-01 03:00:00"] == 3
    trades = pd.DataFrame({
        "entry_time": ["2024-01-01 00:00:00", "2024-01-01 02:00:00",
                       "2024-01-01 00:00:00"],
        "pnl": [1.0, -2.0, 3.0],  # duplicate entry bar -> summed
    })
    pnl = _pnl_per_bar(trades, pos, 5)
    assert list(pnl) == [4.0, 0.0, -2.0, 0.0, 0.0]
    assert list(_pnl_per_bar(pd.DataFrame(), pos, 5)) == [0.0] * 5


class _FakeRun:
    def __init__(self, trades):
        self.trades = trades
        self.metrics = {"trades": len(trades)}


def _trades_at(ts, starts, end_delta, pnl_base):
    """Trades entering at ``starts``, exiting ``end_delta`` bars later,
    with strictly increasing pnl (so any >=3-trade sample has variance)."""
    rows = []
    for k, entry in enumerate(starts):
        rows.append({
            "entry_time": ts[entry],
            "exit_time": ts[min(entry + end_delta, len(ts) - 1)],
            "pnl": float(pnl_base + k),
        })
    return pd.DataFrame(rows)


def test_purged_cv_isolated_spans_purge_and_warmup(df_small, monkeypatch):
    """The CPCV stage must score every span on its OWN isolated simulation
    (state never crosses spans) with boundary-censoring purge and a
    price-only warmup that never reaches a raw test-block interior.

    Proven with a slice-aware fake runner on a 480-bar frame, n_splits=6
    (blocks of 80 bars):

    * ``fat`` config: one +5000 trade per span entered early, exiting at
      the span's LAST bar (boundary-censored outcome);
    * ``thin`` config: three +1 trades fully inside the span.

    purge_bars=0: the fat config's IS includes its boundary trade and it
    is selected everywhere.  purge_bars=20: the boundary trade is
    censored in every train span, the fat edge vanishes and ``thin`` is
    selected everywhere.  Warmup: with warmup_bars=50 only spans whose
    preceding bars are outside every raw test interior receive warmup
    (values in {0, 50}); with warmup_bars=0 every span runs with 0.
    """
    import mql5bot.pipeline as pl

    calls: list[tuple[int, int]] = []

    def fake_runner(sub, strategy, params, warmup_bars=0, **kw):
        calls.append((len(sub), int(warmup_bars)))
        ts = [str(t) for t in sub.index]
        if params.get("fast") == 99:
            trades = [{"entry_time": ts[b], "exit_time": ts[-1],
                       "pnl": 5000.0} for b in (10, 20, 30)]
        else:
            trades = [{"entry_time": ts[10 + k], "exit_time": ts[30 + k],
                       "pnl": 1.0 + k} for k in range(3)]
        return _FakeRun(pd.DataFrame(trades))

    monkeypatch.setattr(pl, "run_fast", fake_runner)
    cfgs = [{"fast": 99, "slow": 1}, {"fast": 8, "slow": 2}]

    out0 = purged_cv_stage(df_small, "ema_crossover", cfgs, n_splits=6,
                           embargo_bars=0, purge_bars=0, warmup_bars=0,
                           engine="fast", risk_percent=0.5)
    h = [c["param_hash"] for c in out0["manifest"].artifacts["configs"]]
    fat_hash, thin_hash = h[0], h[1]
    assert {f["selected"] for f in out0["manifest"].artifacts["folds"]} \
        == {fat_hash}

    outp = purged_cv_stage(df_small, "ema_crossover", cfgs, n_splits=6,
                           embargo_bars=0, purge_bars=20, warmup_bars=0,
                           engine="fast", risk_percent=0.5)
    assert {f["selected"] for f in outp["manifest"].artifacts["folds"]} \
        == {thin_hash}
    assert outp["manifest"].artifacts["purge_bars"] == 20
    # every span is scored on its own small isolated simulation: no run
    # ever sees the full frame (a full-sample backtest would need 480)
    assert calls and max(ln for ln, _ in calls) < len(df_small)

    calls.clear()
    purged_cv_stage(df_small, "ema_crossover", cfgs, n_splits=6,
                    embargo_bars=0, purge_bars=0, warmup_bars=50,
                    engine="fast", risk_percent=0.5)
    warms = {w for _, w in calls}
    assert warms == {0, 50}  # truncation: spans after a test block get 0

    # deterministic rerun (purge variant)
    outp2 = purged_cv_stage(df_small, "ema_crossover", cfgs, n_splits=6,
                            embargo_bars=0, purge_bars=20, warmup_bars=0,
                            engine="fast", risk_percent=0.5)
    assert outp2["manifest"].manifest_id == outp["manifest"].manifest_id


def test_purged_cv_validation(df_small):
    with pytest.raises(ValueError):
        purged_cv_stage(df_small, "ema_crossover", [{"a": 1}], n_splits=5)
    with pytest.raises(ValueError):
        purged_cv_stage(df_small, "ema_crossover", [], n_splits=4)
    with pytest.raises(ValueError):
        purged_cv_stage(df_small, "ema_crossover", [{"a": 1}], n_splits=4,
                        engine="nope")


# --------------------------------------------------------------------------
# S4 — MT5 stage honesty
# --------------------------------------------------------------------------


def test_mt5_stage_skips_without_terminal():
    m = mt5_stage()
    assert m.status == "skipped"
    assert "terminal host" in m.artifacts["reason"]
    assert m.engine == "mt5tester"
    # never a fake "ok"
    assert m.status != "ok"


# --------------------------------------------------------------------------
# S5 — OOS one-look registry
# --------------------------------------------------------------------------


def test_oos_registry_one_look(tmp_path):
    reg = OosRegistry(tmp_path / "oos.json")
    params = {"fast": 8, "slow": 24}
    e1 = reg.certify("ema_crossover", "DATA-v1", params)
    assert reg.has_look("ema_crossover", "DATA-v1")
    assert e1.status == "ok" and e1.stage == "oos"
    with pytest.raises(OosOneLookViolation):
        reg.certify("ema_crossover", "DATA-v1", {"fast": 12, "slow": 40})
    # different strategy or dataset version is a fresh slice
    reg.certify("ema_crossover", "DATA-v2", params)
    reg.certify("rsi_reversal", "DATA-v1", {})
    # persistence across instances
    reg2 = OosRegistry(tmp_path / "oos.json")
    assert reg2.has_look("ema_crossover", "DATA-v1")
    assert not reg2.has_look("ema_crossover", "DATA-v3")


def test_oos_stage_refuses_second_look_and_records(df_small, tmp_path):
    reg = OosRegistry(tmp_path / "oos.json")
    oos_df = generate_ohlc(days=30, seed=9, start="2024-07-01")
    out = oos_stage(oos_df, "ema_crossover", {"fast": 8, "slow": 24},
                    registry=reg, dataset_tag="OOS-2024H2",
                    risk_percent=0.5)
    m = out["manifest"]
    assert m.status == "ok"
    assert m.dataset_version == "OOS-2024H2"
    assert m.metrics["trades"] > 0
    # manifest params = effective (defaults merged) params
    assert m.params["sl_atr"] == 2.5
    # second look refused BEFORE any run
    with pytest.raises(OosOneLookViolation):
        oos_stage(oos_df, "ema_crossover", {"fast": 9, "slow": 30},
                  registry=reg, dataset_tag="OOS-2024H2",
                  risk_percent=0.5)
    # fast engine is not a certification path
    with pytest.raises(ValueError):
        oos_stage(oos_df, "ema_crossover", {"fast": 8, "slow": 24},
                  registry=OosRegistry(tmp_path / "o2.json"),
                  engine="fast", dataset_tag="OOS-x")


# --------------------------------------------------------------------------
# Orchestration, cache, optuna guard
# --------------------------------------------------------------------------


def test_run_stages_end_to_end_and_cache(df_small, tmp_path):
    oos_df = generate_ohlc(days=30, seed=12, start="2024-07-01")
    reg = OosRegistry(tmp_path / "oos.json")
    out = run_stages(df_small, "ema_crossover",
                     grid={"fast": [8, 12], "slow": [24, 40]},
                     top_k=2, n_splits=4,
                     risk_percent=0.5, max_bars=100,
                     oos_df=oos_df, oos_registry=reg,
                     cache_dir=str(tmp_path / "cache"))
    assert set(out["stages"]) == {"screen", "cost_stress", "purged_cv",
                                  "oos"}
    pcv_id = out["stages"]["purged_cv"]["manifest_id"]
    # cache replay is identical and does not need the registry again
    out2 = run_stages(df_small, "ema_crossover",
                      grid={"fast": [8, 12], "slow": [24, 40]},
                      top_k=2, n_splits=4,
                      risk_percent=0.5, max_bars=100,
                      cache_dir=str(tmp_path / "cache"))
    assert out2["stages"]["purged_cv"]["manifest_id"] == pcv_id
    # cached files exist and are JSON (s1+s2 always; s3 when survivors)
    files = list((tmp_path / "cache").glob("*.json"))
    assert 2 <= len(files) <= 3
    json.loads(files[0].read_text())
    # when the x2-cost gate drops everyone, the funnel reports it loudly
    if out["stages"]["purged_cv"]["status"] == "skipped":
        assert "no cost-stress survivors" in \
            out["stages"]["purged_cv"]["artifacts"]["reason"]


def test_run_stages_full_path_with_survivors(tmp_path):
    """On data where the strategy survives the x2-cost gate, every stage
    runs to completion: S1 (fast) -> S2 (truth, ok) -> S3 (purged CV,
    ok) -> S5 (OOS certify of the CV-selected params, one look)."""
    dev = _trend_frame(1, 720)
    oos = _trend_frame(7, 360)
    reg = OosRegistry(tmp_path / "oos2.json")
    out = run_stages(dev, "ema_crossover",
                     grid={"fast": [8, 12], "slow": [24, 40]},
                     top_k=2, n_splits=4, risk_percent=1.0,
                     oos_df=oos, oos_registry=reg)
    assert all(m["status"] == "ok"
               for m in out["stages"]["cost_stress"]["manifests"])
    pcv = out["stages"]["purged_cv"]
    assert pcv["status"] == "ok"
    assert pcv["artifacts"]["n_folds"] == 6
    assert out["stages"]["oos"]["metrics"]["end_equity"] > 0
    # OOS ran the CV-selected parameter set (manifest params = effective)
    assert out["oos_params"]["fast"] in (8, 12)


def test_run_stages_requires_registry_for_oos(df_small, tmp_path):
    oos_df = generate_ohlc(days=30, seed=13, start="2024-07-01")
    with pytest.raises(ValueError):
        run_stages(df_small, "ema_crossover",
                   grid={"fast": [8, 12], "slow": [24, 40]},
                   top_k=1, n_splits=4, risk_percent=0.5,
                   oos_df=oos_df, oos_registry=None)


def test_optuna_is_optional_extra_only():
    """Without optuna installed the stage fails loudly with guidance —
    it is never a core dependency."""
    try:
        import optuna  # noqa: F401

        pytest.skip("optuna present in this environment")
    except ImportError:
        pass
    df = generate_ohlc(days=20, seed=1)
    with pytest.raises(ImportError, match="optimize"):
        optuna_optimize(df, "ema_crossover",
                        {"fast": {"type": "int", "low": 6, "high": 12}},
                        n_trials=2)


# --------------------------------------------------------------------------
# Certification semantics: NO VALID SURVIVOR never certifies (Blocker 5)
# and the status model is explicit (Blocker 7)
# --------------------------------------------------------------------------


def test_run_stages_zero_survivors_block_certification(df_small, tmp_path):
    """S1 survivors > 0, S2 survivors = 0: S3 = skipped, S5 = BLOCKED
    with reason NO_VALID_SURVIVOR; the one-look registry is NOT consumed
    and the screen leader is diagnostics-only."""
    oos_df = generate_ohlc(days=30, seed=21, start="2024-07-01")
    reg = OosRegistry(tmp_path / "oos.json")
    out = run_stages(df_small, "ema_crossover",
                     grid={"fast": [8, 12], "slow": [24, 40]},
                     top_k=2, n_splits=4, risk_percent=0.5,
                     spread_points=500.0, commission_per_lot=50.0,
                     oos_df=oos_df, oos_registry=reg)
    stages = out["stages"]
    assert len(stages["screen"]["manifests"]) > 0          # S1 ran
    assert all(m["status"] == "dropped"
               for m in stages["cost_stress"]["manifests"])  # S2: zero
    assert stages["purged_cv"]["status"] == "skipped"      # S3 skipped
    assert "mt5" not in stages                             # S4 not invoked
    assert stages["oos"]["status"] == "blocked"            # S5 BLOCKED
    reason = stages["oos"]["artifacts"]["reason"]
    assert "NO_VALID_SURVIVOR" in reason
    # the screen leader is present for diagnostics but NOT certified
    assert out["oos_params"] is None
    # the one-look registry was never consulted: nothing written
    assert not (tmp_path / "oos.json").exists()
    # explicit certification status
    assert out["certification"]["status"] == "NOT_ELIGIBLE"
    assert out["certification"]["reason"] == "NO_VALID_SURVIVOR"


def test_run_stages_certification_status_full_path(tmp_path):
    """With survivors and a used one-look OOS: status is
    EMPIRICAL_VALIDATION_PENDING and MT5 stays NOT VERIFIED — a sandbox
    pipeline can never claim VERIFIED."""
    from mql5bot.status import (
        EMPIRICAL_VALIDATION_PENDING,
        MT5_NOT_VERIFIED,
    )

    dev = _trend_frame(1, 720)
    oos = _trend_frame(7, 360)
    reg = OosRegistry(tmp_path / "oos2.json")
    out = run_stages(dev, "ema_crossover",
                     grid={"fast": [8, 12], "slow": [24, 40]},
                     top_k=2, n_splits=4, risk_percent=1.0,
                     oos_df=oos, oos_registry=reg)
    cert = out["certification"]
    assert cert["status"] == EMPIRICAL_VALIDATION_PENDING
    assert cert["mt5_status"] == MT5_NOT_VERIFIED
    assert cert["software_status"] == "SOFTWARE_PASS"
    assert cert["status"] != "VERIFIED"
    # the registry record itself carries the honest statuses
    data = json.loads((tmp_path / "oos2.json").read_text())
    entry = data["entries"][0]
    assert entry["certification_status"] == EMPIRICAL_VALIDATION_PENDING
    assert entry["mt5_status"] == MT5_NOT_VERIFIED
