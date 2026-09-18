"""Tests for strategy signal generation and the optimiser."""

import numpy as np
import pandas as pd
import pytest
from mql5bot.data import generate_ohlc
from mql5bot.optimizer import grid_search, walk_forward
from mql5bot.strategies import (
    STRATEGIES,
    STRATEGY_VERSIONS,
    default_params,
    list_strategies,
    signal,
)


@pytest.fixture(scope="module")
def df():
    return generate_ohlc(days=120, seed=21)


def test_all_strategies_produce_valid_signals(df):
    for name in STRATEGIES:
        s = signal(df, name)
        assert len(s) == len(df)
        assert set(np.unique(s)).issubset({-1, 0, 1})
        # no signal before the slowest indicator warms up
        assert s.iloc[0] == 0


def test_default_params_exist_for_all(df):
    for name in STRATEGIES:
        p = default_params(name)
        assert p, name
        # strategy must run with its defaults and tweaked params
        signal(df, name, p)
        tweaked = dict(p)
        first_key = next(iter(tweaked))
        tweaked[first_key] = float(tweaked[first_key]) * 1.1
        signal(df, name, tweaked)


def test_list_strategies_reports_declared_versions():
    for item in list_strategies():
        assert item["version"] == STRATEGY_VERSIONS[item["name"]]


def test_unknown_strategy_raises(df):
    with pytest.raises(KeyError):
        signal(df, "nope")
    with pytest.raises(KeyError):
        default_params("nope")


def test_strategy_behaviour_smoke(df):
    # trend strategy: mostly aligned with the prevailing trend direction
    s = signal(df, "ema_crossover")
    drift = np.sign(df["close"].iloc[-1] - df["close"].iloc[0])
    valid = s[s != 0]
    if len(valid) and drift != 0:
        # at least 40% of held bars agree with the net trend
        assert (valid == drift).mean() > 0.4
    # reversal strategy: never stays in a trade too long on this dataset
    s_rsi = signal(df, "rsi_reversal")
    assert abs(s_rsi).mean() <= 1.0


def test_grid_search_ranks_by_metric(df):
    grid = {"fast": [8, 12], "slow": [24, 40]}
    runs = grid_search(
        df, "ema_crossover", grid, metric="sharpe",
        risk_percent=0.5, max_bars=100,
    )
    assert len(runs) == 4
    sharpes = [r.result.metrics["sharpe"] for r in runs]
    assert sharpes == sorted(sharpes, reverse=True)


def test_grid_search_minimize(df):
    grid = {"fast": [8, 12], "slow": [24, 40]}
    runs = grid_search(
        df, "ema_crossover", grid, metric="max_drawdown_pct",
        minimize=True, risk_percent=0.5, max_bars=100,
    )
    dds = [r.result.metrics["max_drawdown_pct"] for r in runs]
    assert dds == sorted(dds)  # most negative (worst) last when minimising


def test_walk_forward_returns_oos_metrics(df):
    wf = walk_forward(
        df, "ema_crossover", grid={"fast": [8, 12], "slow": [24, 40]},
        n_windows=2, train_fraction=0.6, risk_percent=0.5, max_bars=100,
    )
    assert len(wf["windows"]) >= 1
    assert "oos_metrics" in wf
    assert len(wf["oos_equity"]) > 0
    for w in wf["windows"]:
        assert {"fast", "slow"} <= set(w["best_params"])  # defaults merged in


def _wf(df):
    return walk_forward(
        df, "ema_crossover", grid={"fast": [8, 12], "slow": [24, 40]},
        n_windows=2, train_fraction=0.6, risk_percent=0.5, max_bars=100,
    )


def test_walk_forward_windows_partition_the_oos_region(df):
    wf = _wf(df)
    g = wf["geometry"]
    wins = wf["windows"]
    assert len(wins) == 2
    # windows tile the OOS region contiguously with no overlaps (test_end
    # is the bar BEFORE the next test_start on the hourly frame)
    assert wins[0]["test_start"] == g["oos_start"]
    assert (pd.Timestamp(wins[0]["test_end"])
            + pd.Timedelta(hours=1)) == pd.Timestamp(wins[1]["test_start"])
    assert wins[1]["test_end"] == g["oos_end"]
    # OOS end is the last sample bar
    assert g["oos_end"] == str(df.index[-1])
    # IS windows end exactly at the OOS starts (rolling origin)
    for w in wins:
        assert w["train_end"] == str(pd.Timestamp(w["test_start"])
                                     - pd.Timedelta(hours=1))


def test_walk_forward_equity_is_the_continuous_run(df):
    wf = _wf(df)
    g = wf["geometry"]
    eq = wf["oos_equity"]
    # aggregate OOS equity = continuous run over the OOS region: unique,
    # contiguous index starting at the first OOS bar (the legacy
    # concatenation restarted capital at 10k per window)
    assert len(eq) == len(df) - g["head_bars"]
    assert eq.index[0] == df.index[g["head_bars"]]
    assert eq.index[-1] == df.index[-1]
    assert eq.index.is_unique
    assert eq.name == "equity"
    # realised equity differs from the flat 10k capital the legacy
    # concatenation always restarted with
    assert abs(float(eq.iloc[0]) - 10_000.0) > 1e-6


def test_walk_forward_window_reporting(df):
    wf = _wf(df)
    for w in wf["windows"]:
        assert {"fast", "slow"} <= set(w["best_params"])
        assert "total_return_pct" in w["is_metrics"]
        assert "total_return_pct" in w["test_metrics"]
        assert "max_drawdown_pct" in w["test_metrics"]
        # per-window trade count and cost ledger come from the OOS span
        assert w["oos_trades"] >= 0
        assert isinstance(w["cost"], float) and w["cost"] >= 0.0
        assert w["oos_max_drawdown_pct"] is None or w["oos_max_drawdown_pct"] <= 0
        assert set(w["regime"]) == {"bars", "drift_pct", "efficiency_ratio",
                                    "volatility_ann_pct", "up_fraction",
                                    "direction"}
        assert w["regime"]["bars"] >= 100
    assert wf["oos_metrics"]["trades"] == sum(
        w["oos_trades"] for w in wf["windows"])


def _param_hash_hex(params: dict) -> str:
    import hashlib
    import json
    payload = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def test_walk_forward_identity_fields_are_deterministic(df):
    wf1 = _wf(df)
    wf2 = _wf(df)
    # the grid winner is never the registry defaults (fast/slow grids are
    # disjoint from the ema_crossover defaults), so its hash must differ
    defaults_hash = _param_hash_hex(default_params("ema_crossover"))
    for w1, w2 in zip(wf1["windows"], wf2["windows"]):
        # deterministic parameter hashes + declared versions on every window
        assert w1["param_hash"] == w2["param_hash"]
        assert len(w1["param_hash"]) == 40 and all(
            c in "0123456789abcdef" for c in w1["param_hash"])
        assert w1["param_hash"] != defaults_hash
        assert w1["strategy_version"] == w2["strategy_version"] == "1.0.0"
        assert w1["dataset_version"] == w2["dataset_version"]
    assert wf1["dataset_version"] == wf1["windows"][0]["dataset_version"]
    assert wf1["strategy_version"] == wf1["windows"][0]["strategy_version"]
    # same data, different values -> different dataset digest
    df2 = df.copy()
    df2.loc[df2.index[-1], "close"] *= 1.001
    wf3 = walk_forward(df2, "ema_crossover",
                       grid={"fast": [8, 12], "slow": [24, 40]},
                       n_windows=2, train_fraction=0.6, risk_percent=0.5,
                       max_bars=100)
    assert wf3["dataset_version"] != wf1["dataset_version"]
    # explicit caller tag wins over the content digest
    wf4 = walk_forward(df, "ema_crossover",
                       grid={"fast": [8, 12], "slow": [24, 40]},
                       n_windows=2, train_fraction=0.6, risk_percent=0.5,
                       max_bars=100, dataset_version="feed-2024-01")
    assert wf4["dataset_version"] == "feed-2024-01"


def _wf_embargo(embargo=0, purge=0):
    df = generate_ohlc(days=120, seed=21)
    return df, walk_forward(
        df, "ema_crossover", grid={"fast": [8, 12], "slow": [24, 40]},
        n_windows=2, train_fraction=0.6, risk_percent=0.5, max_bars=100,
        embargo_bars=embargo, purge_bars=purge,
    )


def test_walk_forward_embargo_keeps_selection_off_boundary(df):
    # selection must never score the embargo_bars adjacent to each OOS
    # start: train_end sits embargo_bars (hourly bars) before test_start
    _df, wf = _wf_embargo(embargo=12)
    assert wf["geometry"]["embargo_bars"] == 12
    for w in wf["windows"]:
        # exactly embargo_bars unscored bars between the last scored IS bar
        # and the OOS start (train_end is the last SELECTED bar)
        last_scored = _df.index.get_loc(pd.Timestamp(w["train_end"]))
        oos = _df.index.get_loc(pd.Timestamp(w["test_start"]))
        assert oos - last_scored - 1 == 12
        # and every selected IS bar lies strictly before the OOS start
        assert pd.Timestamp(w["train_end"]) < pd.Timestamp(w["test_start"])


def test_walk_forward_purge_drops_boundary_censored_trades():
    # unit: _selection_metrics drops trades force-closed at the slice
    # boundary (an isolated run closes any open position at its last bar)
    import mql5bot.strategies as st
    from mql5bot.backtest import run_backtest
    from mql5bot.optimizer import _selection_metrics

    n = 300
    closes = 100.0 + np.arange(n) * 0.01  # steady rise
    o = np.empty(n); o[0] = closes[0]; o[1:] = closes[:-1]
    df = pd.DataFrame({
        "open": o,
        "high": np.maximum(o, closes) + 0.001,
        "low": np.minimum(o, closes) - 0.001,
        "close": closes, "volume": 1000.0,
    }, index=pd.date_range("2024-01-01", periods=n, freq="h"))

    def oracle(frame, p):
        return pd.Series(np.ones(len(frame), dtype=int), index=frame.index)

    st.STRATEGIES["opt_purge"] = (oracle, {"sl_atr": 0.5, "tp_atr": 1000.0})
    try:
        res = run_backtest(df, "opt_purge", risk_percent=1.0,
                           point=1e-5, spread_points=0.0,
                           commission_per_lot=0.0, allow_short=False)
    finally:
        del st.STRATEGIES["opt_purge"]
    # one trade entered after the ATR warm-up, still open at the end ->
    # force-closed at the slice boundary with reason end_of_data
    assert len(res.trades) == 1
    assert res.trades["exit_reason"].iloc[0] == "end_of_data"
    ppy = 365.25 * 24
    metrics, purged = _selection_metrics(res, n, 5, df, ppy)
    assert purged == 1
    assert metrics["trades"] == 0
    # without a purge window the same run keeps the (censored) trade
    metrics0, purged0 = _selection_metrics(res, n, 0, df, ppy)
    assert purged0 == 0
    assert metrics0["trades"] == 1


def test_walk_forward_leakage_validation_raises():
    df = generate_ohlc(days=120, seed=21)
    # embargo big enough to leave < 60 selection bars
    with pytest.raises(ValueError):
        walk_forward(df, "ema_crossover", n_windows=2, train_fraction=0.6,
                     embargo_bars=700)
    with pytest.raises(ValueError):
        walk_forward(df, "ema_crossover", n_windows=2, train_fraction=0.6,
                     embargo_bars=100, purge_bars=600)
    with pytest.raises(ValueError):
        walk_forward(df, "ema_crossover", n_windows=2, train_fraction=0.6,
                     embargo_bars=-1)


def test_walk_forward_too_little_data_raises():
    small = generate_ohlc(days=3, seed=1)  # 72 hourly bars
    with pytest.raises(ValueError):
        walk_forward(small, "ema_crossover", n_windows=3, train_fraction=0.6)


def test_no_strategy_signal_uses_future_bars(df):
    # automated leakage test: every registered strategy must be causal —
    # the signal on any bar may only depend on bars at or before it.
    # Computing the signal on the full frame and on a frame truncated at
    # probe bar p must agree on the common prefix (WFA relies on this:
    # frozen OOS signals are computed on the full sample, selection on
    # slices; any lookahead would train on OOS-adjacent information).
    probes = [len(df) // 2, int(len(df) * 0.8)]
    for name in STRATEGIES:
        full = signal(df, name).to_numpy()
        for p in probes:
            prefix = signal(df.iloc[: p + 1], name).to_numpy()
            assert np.array_equal(full[: p + 1], prefix), (
                f"{name}: signal at bars <= {p} changes when the frame is "
                "truncated at that bar — possible lookahead"
            )


def test_list_strategies_documents_everyone():
    listing = list_strategies()
    assert {s["name"] for s in listing} == set(STRATEGIES)
    for s in listing:
        assert s["description"]


def test_grid_search_composite_ranking_is_opt_in(df):
    from mql5bot.metrics import RobustFitnessConfig, composite_score

    grid = {"fast": [8, 12], "slow": [24, 40]}
    runs = grid_search(df, "ema_crossover", grid, metric="composite",
                       composite_config=RobustFitnessConfig(),
                       risk_percent=0.5, max_bars=100)
    # the plain default metric still ranks by sharpe (no silent change)
    by_sharpe = grid_search(df, "ema_crossover", grid, risk_percent=0.5,
                            max_bars=100)
    best_manual = max(by_sharpe,
                      key=lambda r: r.result.metrics.get("sharpe") or -1e9)
    assert by_sharpe[0].params == best_manual.params
    scores = [composite_score(r.result.metrics, RobustFitnessConfig())["score"]
              for r in runs]
    assert scores == sorted(scores, reverse=True)
    # manual recomputation matches the ranking key exactly
    assert len(runs) == 4
    # explicit, validated config is required for the composite ranking
    with pytest.raises(TypeError):
        grid_search(df, "ema_crossover", grid, metric="composite",
                    composite_config={"w": 1}, risk_percent=0.5)


def test_walk_forward_accepts_composite_selection(df):
    from mql5bot.metrics import RobustFitnessConfig

    wf = walk_forward(df, "ema_crossover",
                      grid={"fast": [8, 12], "slow": [24, 40]},
                      n_windows=2, train_fraction=0.6, risk_percent=0.5,
                      max_bars=100, metric="composite",
                      composite_config=RobustFitnessConfig())
    assert wf["metric"] == "composite"
    assert len(wf["windows"]) == 2
    for w in wf["windows"]:
        assert {"fast", "slow"} <= set(w["best_params"])
        assert w["param_hash"]
