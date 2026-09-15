"""mql5bot.robustness — statistical validation gates (plan Phase 11).

Research gates, not cosmetic report fields: every method below is a
deterministic function over per-period returns (or a backtest result) with
a seeded RNG, and every method ships with synthetic known-good /
known-bad tests in ``tests/test_robustness.py``.

Implemented in this module:

* :func:`psr` / :func:`deflated_sharpe` — probabilistic and deflated
  Sharpe (Bailey & López de Prado); DSR accounts for the number of trials
  behind the observed Sharpe.
* :func:`monte_carlo_pnl` — trade-level Monte Carlo (sampling with
  replacement of the per-trade PnL, deterministic seed): net-profit
  distribution, probability of a profitable outcome, percentile bands.
* :func:`perturbation_report` — parameter perturbation (systematic
  parameter permutation): the strategy's metric over a neighbourhood of
  its parameter vector, reported as worst / median / best and as a
  smoothness ratio, so curve-fit spikes are visible.
* :func:`combinatorial_purged_cv` / :func:`probability_of_backtest_overshoot`
  — CPCV with purging support and the PBO estimate (Bailey et al.):
  probability that the in-sample-best configuration lands below the OOS
  median across configurations.
* :func:`white_reality_check` / :func:`hansen_spa` — multiple-testing
  reality checks over candidate strategy returns with a seeded stationary
  bootstrap.

All random methods accept an explicit ``seed``; the same seed reproduces
the same numbers exactly.
"""

from __future__ import annotations

import math
from itertools import combinations
from statistics import NormalDist

import numpy as np

# ---------------------------------------------------------------------------
# sharpe helpers
# ---------------------------------------------------------------------------


def _annual_factor(periods_per_year: float) -> float:
    return math.sqrt(max(periods_per_year, 1.0))


def _per_period_stats(returns: np.ndarray) -> dict:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3:
        raise ValueError("need at least 3 finite per-period returns")
    mean = float(r.mean())
    std = float(r.std(ddof=1))
    if std <= 0.0:
        raise ValueError("returns have zero variance")
    # population skewness / kurtosis (Bailey-LdP convention)
    z = (r - mean) / float(r.std(ddof=0))
    skew = float(np.mean(z**3))
    kurt = float(np.mean(z**4))
    return {"n": n, "mean": mean, "std": std, "skew": skew, "kurt": kurt,
            "sharpe_pp": mean / std}


def psr(returns, sr_ref_annual: float = 0.0, *,
        periods_per_year: float = 252.0) -> float:
    """Probabilistic Sharpe ratio: P( true Sharpe > ``sr_ref_annual`` )."""
    st = _per_period_stats(returns)
    sr_ref_pp = sr_ref_annual / _annual_factor(periods_per_year)
    sr = st["sharpe_pp"]
    denom = 1.0 - st["skew"] * sr + (st["kurt"] - 1.0) / 4.0 * sr**2
    if denom <= 0.0:
        return 0.0
    z = (sr - sr_ref_pp) * math.sqrt(st["n"] - 1.0) / math.sqrt(denom)
    return float(NormalDist().cdf(z))


def _sr_std(sharpe_pp: float, n: int, skew: float, kurt: float) -> float:
    # standard error of the per-period Sharpe estimate
    var = (1.0 - skew * sharpe_pp
           + (kurt - 1.0) / 4.0 * sharpe_pp**2) / (n - 1.0)
    return math.sqrt(max(var, 0.0))


def deflated_sharpe(returns, n_trials: int, *,
                    periods_per_year: float = 252.0) -> dict:
    """Deflated Sharpe ratio for ``n_trials`` independent trials.

    The deflated benchmark is the expected maximum Sharpe of ``n_trials``
    under the null of a zero-Sharpe strategy family; DSR is PSR at that
    benchmark.  ``n_trials`` should be the honest number of configurations
    the optimisation actually tried (grid size), never 1 for a searched
    result.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    st = _per_period_stats(returns)
    sr = st["sharpe_pp"]
    se = _sr_std(sr, st["n"], st["skew"], st["kurt"])
    euler = 0.5772156649015328606
    nd = NormalDist()
    # expected max of n iid normals (approximately), then per-period SR0;
    # a single trial has expected max 0 (no multiplicity discount)
    if n_trials == 1:
        z_max = 0.0
    else:
        z_max = ((1.0 - euler) * nd.inv_cdf(1.0 - 1.0 / n_trials)
                 + euler * nd.inv_cdf(1.0 - 1.0 / (n_trials * math.e)))
    sr0_pp = se * z_max
    sr0_annual = sr0_pp * _annual_factor(periods_per_year)
    return {
        "dsr": psr(returns, sr0_annual, periods_per_year=periods_per_year),
        "sr0_annual": round(float(sr0_annual), 6),
        "sr_annual": round(float(sr * _annual_factor(periods_per_year)), 6),
        "n_trials": int(n_trials),
    }


# ---------------------------------------------------------------------------
# trade-level Monte Carlo
# ---------------------------------------------------------------------------


def monte_carlo_pnl(trade_pnl, n_paths: int = 2000, *,
                    seed: int = 0) -> dict:
    """Resample the per-trade PnL with replacement (deterministic seed).

    Returns the distribution of cumulative net profit over ``n_paths``
    synthetic trade sequences of the same length: mean, 5th/50th/95th
    percentiles and the probability of a profitable path.
    """
    pnl = np.asarray(trade_pnl, dtype=float)
    pnl = pnl[np.isfinite(pnl)]
    if len(pnl) < 3:
        raise ValueError("need at least 3 trades for Monte Carlo")
    if n_paths < 1:
        raise ValueError("n_paths must be >= 1")
    rng = np.random.default_rng(seed)
    draws = rng.choice(pnl, size=(n_paths, len(pnl)), replace=True)
    totals = draws.sum(axis=1)
    return {
        "paths": int(n_paths),
        "trades": len(pnl),
        "mean_pnl": round(float(totals.mean()), 6),
        "p5_pnl": round(float(np.percentile(totals, 5)), 6),
        "median_pnl": round(float(np.percentile(totals, 50)), 6),
        "p95_pnl": round(float(np.percentile(totals, 95)), 6),
        "prob_profitable": round(float((totals > 0).mean()), 6),
        "seed": int(seed),
    }


# ---------------------------------------------------------------------------
# parameter perturbation / systematic parameter permutation
# ---------------------------------------------------------------------------


def perturbation_report(df, strategy: str, params: dict, *,
                        metric: str = "sharpe",
                        deltas: tuple[float, ...] = (0.05, 0.1, 0.2),
                        risk_percent: float = 0.5) -> dict:
    """Metric over the neighbourhood of ``params`` (one axis perturbed at a
    time, both signs, per ``deltas``), plus the intact baseline.

    ``worst/median/best`` describe the perturbed neighbourhood only; the
    ``smoothness`` ratio (median - worst) / (best - worst) is a
    location-free flatness measure in [0, 1]: values near 1 mean the
    neighbourhood performs almost as well as the peak (robust), values
    near 0 mean the edge exists only at the exact parameter point
    (curve-fit spike).  ``None`` when the neighbourhood is degenerate.
    """
    from .backtest import run_backtest

    if not params:
        raise ValueError("params must not be empty")

    def metric_of(p: dict) -> float | None:
        res = run_backtest(df, strategy, p, risk_percent=risk_percent)
        value = res.metrics.get(metric)
        return float(value) if value is not None else None

    base = metric_of(dict(params))
    points = []
    for key, val in sorted(params.items()):
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        if val == 0.0:
            continue
        for delta in deltas:
            for sign in (-1.0, 1.0):
                moved = dict(params)
                moved[key] = round(float(val) * (1.0 + sign * delta), 10)
                m = metric_of(moved)
                if m is not None:
                    points.append({"param": key, "delta": sign * delta,
                                   "value": m})
    vals = sorted(p["value"] for p in points)
    if not vals:
        raise ValueError("no numeric perturbable parameters")
    median = vals[len(vals) // 2]
    return {
        "metric": metric,
        "baseline": base,
        "n_perturbations": len(points),
        "worst": vals[0],
        "median": median,
        "best": vals[-1],
        "smoothness": (round((median - vals[0]) / (vals[-1] - vals[0]), 4)
                       if vals[-1] > vals[0] else None),
        "points": points,
    }


# ---------------------------------------------------------------------------
# combinatorial purged CV (CPCV) / PBO
# ---------------------------------------------------------------------------


def _matrix(returns_matrix) -> tuple[np.ndarray, int]:
    """Normalise a (T, M) returns input; return the array and config count."""
    a = np.asarray(returns_matrix, dtype=float)
    if a.ndim != 2:
        raise ValueError("returns_matrix must be 2-D (periods x configs)")
    if a.shape[0] < 8 or a.shape[1] < 2:
        raise ValueError("need at least 8 periods and 2 configurations")
    return a, a.shape[1]


def _sharpe_of(values: np.ndarray, ddof: int = 1) -> float:
    vals = values[np.isfinite(values)]
    if len(vals) < 3:
        return 0.0
    std = vals.std(ddof=ddof)
    if std <= 0.0:
        return 0.0
    return float(vals.mean() / std)


def combinatorial_purged_cv(returns_matrix, n_splits: int = 6, *,
                            embargo_bars: int = 0,
                            seed: int = 0) -> dict:
    """Combinatorial purged cross-validation over configurations.

    ``returns_matrix`` is (period, configuration) aligned per-period
    returns of the configurations under comparison (e.g. the top grid
    runs of one strategy version on one dataset).  The period axis is cut
    into ``n_splits`` contiguous blocks; for every combination of
    ``n_splits // 2`` training blocks the remaining blocks are the test
    set, and ``embargo_bars`` of training observations adjacent to each
    test block are dropped (leakage control, default 0).

    Returns the out-of-sample Sharpe distribution over all combinations
    (CPCV result) and the probability of backtest overfitting (PBO): the
    share of combinations in which the in-sample-best configuration ends
    up below the OOS median.  ``seed`` is accepted for interface symmetry;
    the computation itself is deterministic (no RNG).
    """
    a, m = _matrix(returns_matrix)
    t = a.shape[0]
    if n_splits < 4 or n_splits > t:
        raise ValueError("n_splits must be in [4, n_periods]")
    if embargo_bars < 0:
        raise ValueError("embargo_bars must be >= 0")
    blocks = [np.arange(i, min(t, i + t // n_splits + (1 if i < t % n_splits else 0)))
              for i in range(0, t, t // n_splits)]
    blocks = [b for b in blocks if len(b) > 0]
    s = len(blocks)
    if s < 4:
        raise ValueError("n_splits leaves too few non-empty blocks")
    train_size = s // 2
    best_oos_sharpes = []
    below_median = 0
    combos = 0
    for train_blocks in combinations(range(s), train_size):
        test_blocks = [b for b in range(s) if b not in train_blocks]
        train_idx = np.concatenate([blocks[b] for b in train_blocks])
        # embargo: drop training observations right before each test block
        keep = np.ones(len(train_idx), dtype=bool)
        for b in test_blocks:
            cut_start = blocks[b][0]
            if embargo_bars and cut_start > 0:
                drop = (train_idx >= max(0, cut_start - embargo_bars)) & \
                       (train_idx < cut_start)
                keep &= ~drop
        train_idx = train_idx[keep]
        test_idx = np.concatenate([blocks[b] for b in test_blocks])
        if len(train_idx) < 3 or len(test_idx) < 3:
            continue
        is_sr = np.array([_sharpe_of(a[train_idx, c]) for c in range(m)])
        oos_sr = np.array([_sharpe_of(a[test_idx, c]) for c in range(m)])
        if len(oos_sr) < 2 or not np.isfinite(oos_sr).all():
            continue
        best_is = int(np.argmax(is_sr))
        combos += 1
        best_oos_sharpes.append(float(oos_sr[best_is]))
        if oos_sr[best_is] <= float(np.median(oos_sr)):
            below_median += 1
    if combos == 0:
        raise RuntimeError("no valid CPCV combinations")
    arr = np.asarray(best_oos_sharpes)
    return {
        "n_splits": s,
        "n_combos": combos,
        "embargo_bars": int(embargo_bars),
        "pbo": round(below_median / combos, 6),
        "oos_sharpe_mean": round(float(arr.mean()), 6),
        "oos_sharpe_std": round(float(arr.std(ddof=1)), 6),
        "oos_sharpe_p5": round(float(np.percentile(arr, 5)), 6),
        "oos_sharpe_p95": round(float(np.percentile(arr, 95)), 6),
    }


def probability_of_backtest_overshoot(result: dict) -> float:
    """Read the PBO estimate out of a :func:`combinatorial_purged_cv` report."""
    return float(result["pbo"])


# ---------------------------------------------------------------------------
# multiple-testing reality checks (White RC / Hansen SPA)
# ---------------------------------------------------------------------------


def _stationary_bootstrap_indices(t: int, block_mean: float,
                                  n_boot: int, seed: int) -> np.ndarray:
    """(n_boot, t) circular stationary-bootstrap (Politis-Romano) indices."""
    rng = np.random.default_rng(seed)
    p = 1.0 / max(block_mean, 1.0)
    out = np.empty((n_boot, t), dtype=int)
    for i in range(n_boot):
        idx = np.empty(t, dtype=int)
        j = 0
        while j < t:
            # fresh uniform origin per block (overlapping blocks allowed,
            # so the resample has genuine variance)
            pos = int(rng.integers(0, t))
            length = 0
            while length == 0:
                length = int(rng.geometric(p))
            take = min(length, t - j)
            idx[j:j + take] = (pos + np.arange(take)) % t
            j += take
        out[i] = idx
    return out


def white_reality_check(returns_matrix, benchmark=None, *,
                        block_mean: float = 10.0, n_boot: int = 2000,
                        seed: int = 0) -> dict:
    """White's Reality Check over candidate configurations.

    Null hypothesis: the best configuration's mean excess return over the
    benchmark (default zero) is not positive.  The p-value comes from the
    maximum over configurations of the stationary-bootstrap mean, centred
    under the null.  Small p -> the best configuration is unlikely to be
    pure data mining.
    """
    a, m = _matrix(returns_matrix)
    bench = np.zeros(a.shape[0]) if benchmark is None \
        else np.asarray(benchmark, dtype=float)
    if bench.shape != (a.shape[0],):
        raise ValueError("benchmark must be one value per period")
    d = a - bench[:, None]  # (T, M)
    means = d.mean(axis=0)
    t = d.shape[0]
    idx = _stationary_bootstrap_indices(t, block_mean, n_boot, seed)
    boot_means = d[idx].mean(axis=1)  # (n_boot, M)
    centred = boot_means - means[None, :]  # null: zero mean excess
    stat = float(means.max() * np.sqrt(t))
    boot_max = centred.max(axis=1) * np.sqrt(t)
    p = float((boot_max >= stat).mean())
    return {
        "p_value": round(p, 6),
        "statistic": round(stat, 6),
        "best_config": int(np.argmax(means)),
        "n_configs": m,
        "n_periods": t,
        "n_boot": int(n_boot),
        "block_mean": float(block_mean),
        "seed": int(seed),
    }


def hansen_spa(returns_matrix, benchmark=None, *,
               block_mean: float = 10.0, n_boot: int = 2000,
               seed: int = 0) -> dict:
    """Hansen's Superior Predictive Ability test (studentised variant).

    Like :func:`white_reality_check` but with studentised statistics
    (t-values over bootstrap standard errors), which gives the test more
    power when configuration variances differ.  Implementation note: the
    null-recentering threshold of the original SPA is replaced by full
    recentering under the null — a documented simplification; direction
    and rejection behaviour are pinned by synthetic tests.
    """
    a, m = _matrix(returns_matrix)
    bench = np.zeros(a.shape[0]) if benchmark is None \
        else np.asarray(benchmark, dtype=float)
    d = a - bench[:, None]
    means = d.mean(axis=0)
    t = d.shape[0]
    idx = _stationary_bootstrap_indices(t, block_mean, n_boot, seed)
    boot_means = d[idx].mean(axis=1)
    se = boot_means.std(axis=0, ddof=0)
    se = np.where(se > 0.0, se, 1.0)
    tstat = means / se
    centred = (boot_means - means[None, :]) / se[None, :]
    stat = float(tstat.max())
    boot_max = centred.max(axis=1)
    p = float((boot_max >= stat).mean())
    return {
        "p_value": round(p, 6),
        "statistic": round(stat, 6),
        "best_config": int(np.argmax(means)),
        "n_configs": m,
        "n_periods": t,
        "n_boot": int(n_boot),
        "block_mean": float(block_mean),
        "seed": int(seed),
    }


# ---------------------------------------------------------------------------
# report identity stamping
# ---------------------------------------------------------------------------


def stamp_report(report: dict, *, strategy: str, strategy_version: str,
                 dataset_version: str, method: str) -> dict:
    """Attach research identity to a robustness report (plan exit gate:
    every validation report identifies dataset and strategy version)."""
    if not isinstance(report, dict):
        raise TypeError("report must be a dict")
    return {
        "method": method,
        "strategy": strategy,
        "strategy_version": strategy_version,
        "dataset_version": dataset_version,
        **report,
    }
