"""mql5bot.optimizer — parameter optimisation and walk-forward analysis."""

from __future__ import annotations

import hashlib
import itertools
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import BacktestResult, run_backtest
from .strategies import STRATEGY_VERSIONS, default_params


@dataclass
class Run:
    params: dict
    result: BacktestResult

    def summary(self) -> dict:
        return {"params": self.params, **{k: v for k, v in self.result.metrics.items()}}


def _expand(grid: dict) -> list[dict]:
    keys = list(grid)
    if not keys:
        return [{}]
    values = [v if isinstance(v, (list, tuple, range)) else [v] for v in grid.values()]
    combos = list(itertools.product(*values))
    return [dict(zip(keys, combo)) for combo in combos]


def grid_search(
    df: pd.DataFrame,
    strategy_name: str,
    grid: dict | None = None,
    *,
    metric: str = "sharpe",
    minimize: bool = False,
    n_jobs: int = 1,
    composite_config=None,
    **kwargs,
) -> list[Run]:
    """Run every parameter combination and return runs sorted by `metric`.

    ``grid`` maps parameter names to lists of candidate values. Parameters
    not present in the grid take their strategy defaults.

    ``metric="composite"`` is an OPT-IN robust-fitness ranking (Phase B):
    it requires/uses an explicit :class:`~mql5bot.metrics.RobustFitnessConfig`
    (``composite_config``, defaulted when None) and sorts by the composite
    score.  The default metric stays ``"sharpe"`` — selection behaviour
    never changes silently.
    """
    from .metrics import RobustFitnessConfig

    cfg = composite_config if composite_config is not None \
        else RobustFitnessConfig()
    if metric == "composite" and not isinstance(cfg, RobustFitnessConfig):
        raise TypeError("composite_config must be a RobustFitnessConfig")
    base = default_params(strategy_name)
    combos = _expand(grid or {})
    param_sets = [{**base, **combo} for combo in combos]

    if n_jobs > 1 and len(param_sets) > 1:
        with ProcessPoolExecutor(max_workers=n_jobs) as pool:
            futures = [
                pool.submit(run_backtest, df, strategy_name, ps, **kwargs)
                for ps in param_sets
            ]
            results = [f.result() for f in futures]
    else:
        results = [run_backtest(df, strategy_name, ps, **kwargs) for ps in param_sets]

    runs = [Run(ps, res) for ps, res in zip(param_sets, results)]
    runs.sort(
        key=lambda r: _selection_key(r, metric, cfg)[0],
        reverse=not minimize,
    )
    return runs


def _metric_value(value, minimize: bool):
    if value is None:
        return float("inf") if minimize else float("-inf")
    return float(value)


def _selection_key(run, metric: str,
                   composite_config) -> tuple[float, dict]:
    """Sort key for one run.  ``metric="composite"`` is the OPT-IN robust
    fitness ranking (explicit RobustFitnessConfig, never the default);
    any other metric is read straight off the run's metrics dict."""
    if metric == "composite":
        from .metrics import composite_score

        report = composite_score(run.result.metrics, composite_config)
        return float(report["score"]), report
    return _metric_value(run.result.metrics.get(metric), False), {}


def walk_forward(
    df: pd.DataFrame,
    strategy_name: str,
    grid: dict | None = None,
    *,
    train_fraction: float = 0.6,
    n_windows: int = 3,
    metric: str = "sharpe",
    warmup_bars: int = 200,
    embargo_bars: int = 0,
    purge_bars: int = 0,
    dataset_version: str | None = None,
    composite_config=None,
    **kwargs,
) -> dict:
    """Continuous walk-forward analysis on the canonical engine.

    One single scheduled-parameter engine run covers the full sample:
    capital, portfolio, costs and risk state are carried forward across
    segments (no per-window capital resets — the legacy concatenating
    walk-forward is gone).  Parameters are frozen per out-of-sample (OOS)
    segment via the engine's walk-forward ``schedule``; the aggregate OOS
    equity IS the continuous run's equity over the OOS region.

    Geometry (continuous walk-forward contract, see docs/WFA_CONTRACT.md):
      * ``n_windows`` OOS segments of ``L`` bars tile the sample from bar
        ``head = is_bars + warmup_bars`` (the last segment absorbs any
        remainder); ``is_bars = round(train_fraction * L)`` and
        ``L = (n - warmup_bars) / (n_windows + train_fraction)``.
      * The in-sample window of segment ``w`` is the ``is_bars`` bars
        immediately before its OOS start (rolling origin, disjoint from
        that segment's own OOS; earlier tested segments may feed later
        IS windows — released data).

    Leakage controls (Phase 7) — both act on SELECTION only (signals in
    the continuous run always use everything already released):
      * ``embargo_bars`` (default 0): the IS selection window ends
        ``embargo_bars`` bars before the OOS start, so parameter choice
        never scores the bars adjacent to the test boundary (their trades
        would be force-closed at the boundary in an isolated run).
      * ``purge_bars`` (default 0): trades of the selection run that exit
        within the last ``purge_bars`` bars of the (embargoed) IS window
        are dropped from the IS metrics together with those bars' equity
        tail (boundary-censored outcomes).  The count dropped is reported
        per window as ``is_trades_purged``.

      * Before the first OOS start the account is warmed by the strategy
        registry defaults (excluded from the OOS aggregates).
      * Each window's schedule entry starts at ``oos_start - 1`` so the
        frozen parameters govern entries from the OOS bar's open.

    ``metric="composite"`` is an OPT-IN robust-fitness ranking (Phase B)
    — pass the explicit selection metric AND (optionally) a
    :class:`~mql5bot.metrics.RobustFitnessConfig`; the default selection
    metric stays ``"sharpe"``.

    RESEARCH POLICY (documented, enforced by the research protocol):
    never optimise on the same OOS certification slice more than once per
    (dataset_version, strategy_version) — one look, recorded in the run
    manifest.  IS selection inside each window is exempt (it is
    re-fit per window on that window's train interval only).

    Per-window output (``windows``): IS/OOS date spans, selected params
    plus a deterministic ``param_hash``, the declared ``strategy_version``
    and ``dataset_version`` (content digest unless the caller passes an
    explicit tag), IS metrics (best grid run on the IS window), OOS
    metrics (the continuous equity slice of the OOS span, trades
    attributed to the window of their ENTRY bar), walk-forward
    efficiency, OOS trade count, OOS max drawdown, cost (row ``costs``
    ledger) and a price-regime breakdown of the OOS span.  The two
    version tags are also repeated at the top level for report rows.

    Returns a dict with ``windows``, the continuous ``oos_equity`` (index
    = the OOS region), aggregate ``oos_metrics`` and the ``geometry``.
    """
    n = len(df)
    strategy_version = STRATEGY_VERSIONS.get(strategy_name, "undeclared")
    dataset_digest = dataset_version if dataset_version is not None \
        else _dataset_digest(df)
    if n_windows < 1:
        raise ValueError("n_windows must be >= 1")
    if train_fraction <= 0.0:
        raise ValueError("train_fraction must be > 0")
    k = int(n_windows)
    f = float(train_fraction)
    if n - warmup_bars <= 0:
        raise ValueError("warmup_bars must leave bars for the walk-forward")
    if embargo_bars < 0 or purge_bars < 0:
        raise ValueError("embargo_bars and purge_bars must be >= 0")
    L = int((n - warmup_bars) / (k + f))
    is_len = max(1, round(f * L))
    if L < 120 or is_len < 60:
        raise ValueError(
            "not enough bars for walk-forward windows "
            f"(n={n}, n_windows={k}, train_fraction={f}) — reduce n_windows "
            "or train_fraction, or pass more data"
        )
    if embargo_bars >= is_len - 59 or embargo_bars + purge_bars >= is_len:
        raise ValueError(
            f"embargo/purge ({embargo_bars}/{purge_bars}) leave too few "
            f"selection bars (is_bars={is_len})"
        )
    head = warmup_bars + is_len  # first OOS start (b_0)
    starts = [head + w * L for w in range(k)]
    ends = [head + (w + 1) * L for w in range(k)]
    ends[-1] = n  # the last segment absorbs any remainder
    if starts[-1] >= n or starts[0] < 1:
        raise ValueError("not enough bars for walk-forward windows")

    ppy = _pph(df.index)

    # ---- per-window optimisation on the rolling IS windows ---------------
    schedule: list[tuple[int, dict]] = []
    windows = []
    for w in range(k):
        b0, b1 = starts[w], ends[w]
        sel_end = b0 - embargo_bars  # selection never scores the embargo
        train = df.iloc[b0 - is_len:sel_end]
        test = df.iloc[b0:b1]
        best = grid_search(train, strategy_name, grid, metric=metric,
                           composite_config=composite_config, **kwargs)[0]
        schedule.append((b0 - 1, dict(best.params)))
        if purge_bars:
            is_metrics, purged = _selection_metrics(
                best.result, sel_end, purge_bars, df, ppy)
        else:
            is_metrics, purged = dict(best.result.metrics), 0
        windows.append(
            {
                "window": w,
                "train_start": str(train.index[0]),
                "train_end": str(train.index[-1]),
                "test_start": str(test.index[0]),
                "test_end": str(test.index[-1]),
                "best_params": dict(best.params),
                "param_hash": _param_hash(dict(best.params)),
                "strategy_version": strategy_version,
                "dataset_version": dataset_digest,
                "train_metric": is_metrics.get(metric),
                "is_metrics": is_metrics,
                "is_trades": is_metrics.get("trades"),
                "is_trades_purged": purged,
            }
        )

    # ---- one continuous scheduled run over the full sample ----------------
    result = run_backtest(df, strategy_name, None,
                          schedule=tuple(schedule), **kwargs)
    eq = result.equity
    rows = result.trades
    bar_of = {str(t): i for i, t in enumerate(df.index)}

    def entry_bars(frame: pd.DataFrame) -> list[int]:
        return [bar_of[r["entry_time"]] for _, r in frame.iterrows()]

    from .metrics import compute_metrics

    row_bars = entry_bars(rows)
    oos_mask = [b >= head for b in row_bars]
    oos_equity = eq.iloc[head:]
    oos_rows = rows.loc[oos_mask] if len(rows) else rows

    agg_metrics = (
        compute_metrics(oos_equity, oos_rows, periods_per_year=ppy)
        if len(oos_equity) > 1
        else {}
    )

    # ---- per-window OOS metrics on the continuous equity slices -----------
    for w in range(k):
        b0, b1 = starts[w], ends[w]
        span = eq.iloc[b0:b1]
        span_rows = rows.loc[
            [b0 <= b < b1 for b in row_bars]] if len(rows) else rows
        oos_met = (
            compute_metrics(span, span_rows, periods_per_year=ppy)
            if len(span) > 1
            else {}
        )
        cost = float(span_rows["costs"].sum()) if len(span_rows) else 0.0
        is_ret = windows[w]["is_metrics"].get("total_return_pct")
        oos_ret = oos_met.get("total_return_pct")
        wfe = None
        if isinstance(is_ret, (int, float)) and isinstance(oos_ret, (int, float)):
            denom = is_ret / 100.0
            if denom > 0:
                wfe = (oos_ret / 100.0) / denom
        windows[w].update(
            {
                "test_metrics": oos_met,
                "oos_metrics": oos_met,
                "wfe": wfe,
                "oos_trades": len(span_rows),
                "oos_max_drawdown_pct": oos_met.get("max_drawdown_pct"),
                "cost": cost,
                "regime": _regime(df, b0, b1, ppy),
            }
        )

    return {
        "strategy": strategy_name,
        "strategy_version": strategy_version,
        "dataset_version": dataset_digest,
        "metric": metric,
        "train_fraction": f,
        "n_windows": k,
        "geometry": {
            "bars": n,
            "warmup_bars": warmup_bars,
            "is_bars": is_len,
            "segment_bars": L,
            "head_bars": head,
            "embargo_bars": int(embargo_bars),
            "purge_bars": int(purge_bars),
            "oos_start": str(df.index[head]),
            "oos_end": str(df.index[-1]),
        },
        "windows": windows,
        "oos_metrics": agg_metrics,
        "oos_equity": oos_equity,
    }


def _selection_metrics(result, sel_end: int, purge_bars: int,
                        df: pd.DataFrame, ppy: float) -> tuple[dict, int]:
    """IS selection metrics with boundary-censored trades purged.

    ``result`` is a selection backtest over the (embargoed) IS slice whose
    last bar is ``df.index[sel_end - 1]``.  Trades exiting within the last
    ``purge_bars`` bars are force-closed at the slice boundary by an
    isolated run, so their outcomes are censored: they are dropped from
    the metrics together with the equity tail that carries them.  Returns
    ``(metrics, purged_count)``.
    """
    from .metrics import compute_metrics

    if purge_bars <= 0:
        metrics = dict(result.metrics)
        return metrics, 0
    cut = sel_end - purge_bars
    eq = result.equity
    rows = result.trades
    if not len(rows):
        return {}, 0
    cut_time = str(df.index[cut])
    keep = rows[rows["exit_time"] < cut_time]
    purged = len(rows) - len(keep)
    eq_trunc = eq.iloc[: max(1, cut - (sel_end - len(eq)))]
    if len(eq_trunc) < 2:
        return {"trades": len(keep)}, purged
    metrics = compute_metrics(eq_trunc, keep, periods_per_year=ppy)
    # stable schema: compute_metrics omits trade keys for empty logs
    metrics["trades"] = len(keep)
    return metrics, int(purged)


def _regime(df: pd.DataFrame, b0: int, b1: int, ppy: float) -> dict:
    """Cheap deterministic price-regime features of a bar span."""
    c = df["close"].to_numpy(dtype=float)[b0:b1]
    out = {"bars": int(b1 - b0)}
    if len(c) < 3:
        return out
    drift = c[-1] / c[0] - 1.0
    out["drift_pct"] = round(float(drift * 100.0), 6)
    moves = np.abs(np.diff(c))
    denom = float(moves.sum())
    out["efficiency_ratio"] = round(float(abs(c[-1] - c[0]) / denom), 6) \
        if denom > 0 else None
    logrets = np.diff(np.log(c))
    std = float(logrets.std(ddof=0))
    out["volatility_ann_pct"] = round(std * np.sqrt(ppy) * 100.0, 6) \
        if std > 0 else None
    out["up_fraction"] = round(float((logrets > 0).mean()), 6)
    out["direction"] = "up" if drift > 1e-12 else ("down" if drift < -1e-12 else "flat")
    return out


def _param_hash(params: dict) -> str:
    """Deterministic sha-1 over a canonical parameter serialisation."""
    payload = json.dumps(
        params,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda v: float(v) if isinstance(v, (np.integer, np.floating))
        else repr(v),
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _dataset_digest(df: pd.DataFrame) -> str:
    """Content digest of a research frame (index + column values + dtypes).

    Deterministic for the numeric OHLCV frames this codebase produces; a
    caller may pass an explicit ``dataset_version`` instead when upstream
    data has a canonical version tag.
    """
    h = hashlib.sha1()
    h.update(str(df.dtypes.to_dict()).encode("utf-8"))
    h.update(np.ascontiguousarray(df.index.values).tobytes())
    for col in df.columns:
        arr = df[col].to_numpy()
        if arr.dtype.kind in "biufc":  # numeric: byte-stable
            h.update(np.ascontiguousarray(arr).tobytes())
        else:
            h.update(pd.util.hash_pandas_object(df[col]).values.tobytes())
    return h.hexdigest()


def _pph(index: pd.DatetimeIndex) -> float:
    if len(index) < 2:
        return 252.0
    delta = index.to_series().diff().dt.total_seconds().median()
    if pd.isna(delta) or delta <= 0:
        return 252.0
    return 365.25 * 24 * 3600 / delta


def runs_to_frame(runs: list[Run]) -> pd.DataFrame:
    """Flatten a list of optimisation runs into a table."""
    rows = []
    for r in runs:
        row = {f"p_{k}": v for k, v in r.params.items()}
        for k, v in r.result.metrics.items():
            row[f"m_{k}"] = v
        rows.append(row)
    return pd.DataFrame(rows)


def best(runs: list[Run]) -> Run:
    return runs[0]
