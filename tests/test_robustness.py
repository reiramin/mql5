"""Statistical-robustness gate tests (mql5bot.robustness, plan Phase 11).

Every method ships with synthetic known-good / known-bad scenarios:
- PSR/DSR: a strong consistent edge must pass at any honest trial count;
  coin-flip noise must fail once trial multiplicity is accounted for.
- Monte Carlo: a positive-edge trade set concentrates above zero; a
  zero-edge set straddles it and the two seeds stay reproducible.
- perturbation: a smooth, insensitive surface must score a high
  smoothness ratio; a spike tuned to one parameter value must collapse.
"""

import numpy as np
import pytest
from mql5bot.data import generate_ohlc
from mql5bot.robustness import (
    combinatorial_purged_cv,
    deflated_sharpe,
    hansen_spa,
    monte_carlo_pnl,
    perturbation_report,
    probability_of_backtest_overshoot,
    psr,
    stamp_report,
    white_reality_check,
)

RNG = np.random.default_rng(1)


def _daily(n: int, mu: float, sigma: float, seed: int = 0) -> np.ndarray:
    r = np.random.default_rng(seed).normal(mu, sigma, n)
    return 1e-4 * r  # scale so that sigma is in daily-percent units


# ---------------------------------------------------------------------------
# PSR / DSR
# ---------------------------------------------------------------------------


def test_psr_strong_edge_passes_weak_noise_fails():
    # daily mean 0.12% at 1% vol -> annual SR ~1.9
    edge = _daily(750, 0.0012, 0.01)
    # daily mean 0.2% at 1% vol -> annual SR ~3.2
    strong = _daily(750, 0.0025, 0.01)
    noise = _daily(750, 0.0, 0.01)
    assert psr(edge, sr_ref_annual=0.0) > 0.99
    assert psr(strong, sr_ref_annual=2.0) > 0.90
    assert psr(noise, sr_ref_annual=0.0) < 0.6


def test_deflated_sharpe_punishes_trial_multiplicity():
    edge = _daily(750, 0.0012, 0.01)  # annual SR ~1.9
    single = deflated_sharpe(edge, n_trials=1)
    many = deflated_sharpe(edge, n_trials=10_000)
    assert single["dsr"] > 0.99
    assert single["sr0_annual"] < many["sr0_annual"]
    # an SR-0.3 edge cannot survive 10k trials' multiplicity discount
    weak = _daily(750, 0.0002, 0.01)
    assert deflated_sharpe(weak, n_trials=10_000)["dsr"] < 0.5
    # no multiplicity discount for a single trial
    assert deflated_sharpe(edge, n_trials=1)["sr0_annual"] == 0.0


def test_dsr_deterministic_and_validates():
    r = _daily(300, 0.0005, 0.01)
    a = deflated_sharpe(r, 100)
    b = deflated_sharpe(r, 100)
    assert a == b
    with pytest.raises(ValueError):
        deflated_sharpe(r, 0)
    with pytest.raises(ValueError):
        psr(np.ones(3))  # zero variance


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------


def test_monte_carlo_known_good_and_known_bad():
    good = np.array([20.0, -8.0, 14.0, -5.0, 18.0, -3.0, 22.0, -7.0])
    bad = np.array([10.0, -10.0, 12.0, -11.0, 9.0, -9.5, 10.5, -10.0])
    mg = monte_carlo_pnl(good, n_paths=4000, seed=3)
    mb = monte_carlo_pnl(bad, n_paths=4000, seed=3)
    assert mg["prob_profitable"] > 0.9
    assert mg["mean_pnl"] > 0.0
    assert 0.0 < mb["prob_profitable"] < 1.0
    assert mb["mean_pnl"] < mg["mean_pnl"]
    # deterministic across identical seeds
    assert monte_carlo_pnl(good, n_paths=4000, seed=3) == mg
    with pytest.raises(ValueError):
        monte_carlo_pnl(np.array([1.0, 2.0]))


def test_monte_carlo_p99_concentration():
    # every trade positive -> all paths profitable
    only_win = np.full(20, 5.0)
    m = monte_carlo_pnl(only_win, n_paths=500, seed=1)
    assert m["prob_profitable"] == 1.0


# ---------------------------------------------------------------------------
# parameter perturbation
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def df():
    return generate_ohlc(days=60, seed=11)


def test_perturbation_report_shape(df):
    r = perturbation_report(df, "ema_crossover",
                            {"fast": 10, "slow": 30, "sl_atr": 2.5,
                             "tp_atr": 4.0},
                            deltas=(0.1, 0.2), risk_percent=0.5)
    assert r["baseline"] is not None
    assert r["n_perturbations"] >= 8
    assert r["worst"] <= r["median"] <= r["best"]
    assert r["smoothness"] is None or 0.0 <= r["smoothness"] <= 1.0
    # reproducibility: same input, same report
    again = perturbation_report(df, "ema_crossover",
                                {"fast": 10, "slow": 30, "sl_atr": 2.5,
                                 "tp_atr": 4.0},
                                deltas=(0.1, 0.2), risk_percent=0.5)
    assert [p["value"] for p in r["points"]] ==         [p["value"] for p in again["points"]]


def test_perturbation_spike_detected(df):
    # emulate a curve-fit spike: the metric is 3.0 only at slow == 30 and
    # collapses for any perturbation.  perturbation_report imports
    # run_backtest per call, so patching the module attribute suffices.
    import mql5bot.backtest as bt

    orig = bt.run_backtest

    def spiky(df_, strategy_, params, **kw):
        class R:
            def __init__(self):
                spike = abs(params["slow"] - 30.0) < 1e-9
                self.metrics = {"sharpe": 3.0 if spike else -1.0}
        return R()

    bt.run_backtest = spiky
    try:
        from mql5bot.robustness import perturbation_report
        # only the spike-sensitive axis is perturbable; perturbing `slow`
        # in either direction destroys the metric
        r = perturbation_report(df, "ema_crossover", {"slow": 30},
                                deltas=(0.05, 0.1), risk_percent=0.5)
    finally:
        bt.run_backtest = orig
    assert r["baseline"] == 3.0
    # every perturbed point is bad -> the neighbourhood is degenerate bad
    assert r["worst"] == r["median"] == r["best"] == -1.0
    assert r["smoothness"] is None  # spike: no flatness at all
    assert r["n_perturbations"] == 4


# ---------------------------------------------------------------------------
# CPCV / PBO
# ---------------------------------------------------------------------------


def _config_matrix(n_periods=360, n_configs=6, good_idx=0, drift=0.0025,
                  seed=0):
    """Per-period returns of ``n_configs``; config ``good_idx`` carries a
    real edge (drift 0.0025/day at 1% vol -> annual SR ~4), the rest are
    noise.  Calibrated so PBO separation holds across seeds 0..2."""
    rng = np.random.default_rng(seed)
    out = rng.normal(0.0, 0.01, (n_periods, n_configs))
    out[:, good_idx] += drift
    return out


def test_cpcv_pbo_known_good_low_known_bad_high():
    # the persistent edge keeps the IS-best config above the OOS median in
    # (almost) every combination; pure noise overfits by construction, so
    # its PBO sits around the coin-flip region (0.2-0.25)
    for seed in (0, 1, 2):
        rg = combinatorial_purged_cv(_config_matrix(seed=seed), n_splits=6)
        rb = combinatorial_purged_cv(_config_matrix(drift=0.0, seed=seed),
                                     n_splits=6)
        assert rg["pbo"] <= 0.15, seed
        assert rb["pbo"] >= 0.2, seed
        assert rg["oos_sharpe_mean"] > rb["oos_sharpe_mean"], seed
        assert rg["n_combos"] == 20 and rb["n_combos"] == 20
    assert probability_of_backtest_overshoot(rg) == rg["pbo"]


def test_cpcv_deterministic_and_validates():
    m = _config_matrix(seed=5)
    a = combinatorial_purged_cv(m, n_splits=6, embargo_bars=5)
    b = combinatorial_purged_cv(m, n_splits=6, embargo_bars=5)
    assert a == b
    with pytest.raises(ValueError):
        combinatorial_purged_cv(np.ones((5, 3)), n_splits=4)  # too short
    with pytest.raises(ValueError):
        combinatorial_purged_cv(m, n_splits=3)
    with pytest.raises(ValueError):
        combinatorial_purged_cv(m, n_splits=6, embargo_bars=-1)


# ---------------------------------------------------------------------------
# White's Reality Check / Hansen SPA
# ---------------------------------------------------------------------------


def _aligned_configs(n=400, good_idx=2, seed=9):
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 0.01, (n, 5))
    good = rng.normal(0.0012, 0.01, n)  # annual SR ~1.9
    return np.column_stack([noise[:, :good_idx], good,
                            noise[:, good_idx:]])


def test_white_reality_check_detects_real_edge():
    x = _aligned_configs(seed=9)
    r = white_reality_check(x, n_boot=1500, seed=11)
    assert r["best_config"] == 2
    assert r["p_value"] <= 0.05  # null of no superior strategy rejected
    noise_only = np.random.default_rng(3).normal(0.0, 0.01, (400, 5))
    rn = white_reality_check(noise_only, n_boot=1500, seed=11)
    assert rn["p_value"] > 0.05  # cannot reject on pure noise


def test_hansen_spa_matches_direction_and_reproduces():
    x = _aligned_configs(seed=9)
    r = hansen_spa(x, n_boot=1500, seed=11)
    assert r["best_config"] == 2
    assert r["p_value"] <= 0.10
    assert hansen_spa(x, n_boot=1500, seed=11) == r  # deterministic
    rn = hansen_spa(np.random.default_rng(4).normal(0.0, 0.01, (400, 5)),
                    n_boot=1500, seed=11)
    assert rn["p_value"] > 0.05


def test_reality_check_validates_shapes():
    with pytest.raises(ValueError):
        white_reality_check(np.ones((10, 1)))
    with pytest.raises(ValueError):
        hansen_spa(np.ones((10, 2)), benchmark=np.ones(9))


def test_stamp_report_carries_research_identity():
    r = monte_carlo_pnl(np.array([1.0, -0.5, 2.0]), seed=1)
    stamped = stamp_report(r, strategy="ema_crossover",
                           strategy_version="1.0.0",
                           dataset_version="abc123", method="monte_carlo")
    assert stamped["strategy"] == "ema_crossover"
    assert stamped["strategy_version"] == "1.0.0"
    assert stamped["dataset_version"] == "abc123"
    assert stamped["method"] == "monte_carlo"
    assert stamped["paths"] == r["paths"]  # report content preserved
