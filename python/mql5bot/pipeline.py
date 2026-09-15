"""mql5bot.pipeline — staged screening pipeline (performance & selection
hardening, Phase D).

The certified research funnel, stage by stage:

    S1 screen      — cheap sweep over the parameter grid on the DEV data
                     (FAST engine by default; the TRUTH engine may be
                     forced).  Keeps ``top_k`` by an explicit rank metric.
    S2 cost stress — every survivor re-run at cost x1 and cost x2
                     (spread AND commission doubled) on the TRUTH engine;
                     survivors of the documented gate keep their place.
    S3 purged CV   — own trade-level purge + embargo combinatorial
                     cross-validation over the survivors (conceptually
                     after López de Prado's purged k-fold / CPCV; own
                     implementation, see ``purged_cv_stage``).
    S4 MT5 tester  — headless MetaTrader 5 Strategy Tester execution of
                     the survivors on tick data.  THIS SANDBOX HAS NO MT5
                     TERMINAL: without an explicit ``TesterConfig`` the
                     stage records a manifest with status ``skipped`` and
                     an honest reason — a certification is never faked.
    S5 OOS certify — ONE final TRUTH-engine run on never-touched OOS
                     data, gated by the one-look registry
                     (:class:`OosRegistry`): the same dataset version can
                     never be optimised/certified twice, enforced in
                     code, not just documented.

Every stage emits a :class:`RunManifest` whose digest (``manifest_id``)
is a deterministic function of params, window, data digest, cost config,
seed and stage — so certified results are reproducible from the manifest
alone.  FAST results appearing in manifests are always marked
``engine="fast"`` and are screening signals only — never final, never a
profit claim.  The only certification path is the TRUTH engine
(``mql5bot.backtest``/``mql5bot.engine``) plus the real MT5 tester.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import run_backtest
from .fast_engine import run_fast
from .metrics import RobustFitnessConfig
from .optimizer import STRATEGY_VERSIONS, _dataset_digest, _param_hash
from .strategies import default_params

# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------


def _clean(value):
    """Normalise a manifest value to plain JSON-safe Python types."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _canonical(params: dict) -> dict:
    """Deterministic canonical parameter serialisation (json-able)."""
    return _clean(dict(params))


@dataclass
class RunManifest:
    """Reproducibility record of one pipeline stage execution.

    ``manifest_id`` is a deterministic sha-1 over every field except
    ``created`` (wall-clock) and ``artifacts`` entries that are
    non-deterministic by nature (``skipped`` reasons etc. are included).
    """

    stage: str
    strategy: str
    params: dict
    engine: str
    dataset_version: str
    seed: int = 0
    dataset_bars: int = 0
    strategy_version: str = "undeclared"
    cost_config: dict = field(default_factory=dict)
    window: dict | None = None
    status: str = "ok"
    metrics: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
    created: str = ""
    repro: dict = field(default_factory=dict)  # Phase 13: run identity
    manifest_id: str = ""

    def __post_init__(self):
        self.params = _canonical(self.params)
        self.cost_config = _clean(self.cost_config)
        self.metrics = _clean(self.metrics)
        self.artifacts = _clean(self.artifacts)
        if not self.repro:
            from .versions import reproducibility_block

            self.repro = reproducibility_block()
        self.created = self.created or datetime.now(
            timezone.utc).isoformat(timespec="seconds")
        self.strategy_version = self.strategy_version \
            or STRATEGY_VERSIONS.get(self.strategy, "undeclared")
        self.manifest_id = self.digest()

    def digest(self) -> str:
        """Deterministic content id (excludes the wall-clock ``created``)."""
        payload = {
            "stage": self.stage,
            "strategy": self.strategy,
            "params": self.params,
            "engine": self.engine,
            "dataset_version": self.dataset_version,
            "seed": int(self.seed),
            "dataset_bars": int(self.dataset_bars),
            "strategy_version": self.strategy_version,
            "cost_config": self.cost_config,
            "window": self.window,
            "status": self.status,
            "metrics": self.metrics,
            "artifacts": self.artifacts,
            "repro": self.repro,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                          default=repr)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RunManifest:
        obj = cls(**{k: v for k, v in data.items()
                     if k in cls.__dataclass_fields__})
        return obj


# ---------------------------------------------------------------------------
# Data versions
# ---------------------------------------------------------------------------


def dataset_version_of(df: pd.DataFrame, tag: str | None = None) -> str:
    """Data version: an explicit tag when given, else the content digest."""
    return tag if tag else _dataset_digest(df)


# ---------------------------------------------------------------------------
# S1 — screen
# ---------------------------------------------------------------------------


def _rank_of(result, metric: str, composite_config=None) -> float:
    if metric == "composite":
        from .metrics import composite_score

        return float(composite_score(result.metrics, composite_config)["score"])
    value = result.metrics.get(metric)
    return float(value) if value is not None else float("-inf")


def screen_stage(df: pd.DataFrame, strategy: str, grid: dict, *,
                 top_k: int = 5,
                 rank_metric: str = "sharpe",
                 engine: str = "fast",
                 dataset_tag: str | None = None,
                 seed: int = 0,
                 composite_config=None,
                 **run_kwargs) -> dict:
    """S1: cheap screen over the grid; returns ranked manifests + params.

    ``engine`` is ``"fast"`` (default; screening signals only) or
    ``"truth"`` (wrapper engine — slower, still not a certification).
    Unknown strategies and empty grids raise like the canonical entry
    points.  Deterministic: same inputs -> same ranking and manifests.
    """

    if engine not in ("fast", "truth"):
        raise ValueError("engine must be 'fast' or 'truth'")
    if not grid:
        raise ValueError("grid must not be empty")
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    cfg_metric = composite_config if composite_config is not None \
        else RobustFitnessConfig()
    if rank_metric == "composite" and not isinstance(cfg_metric,
                                                     RobustFitnessConfig):
        raise TypeError("composite_config must be a RobustFitnessConfig")

    base = default_params(strategy)  # KeyError: unknown strategy
    keys = sorted(grid)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(
        *(grid[k] for k in keys))]
    runner = run_fast if engine == "fast" else run_backtest
    runs = []
    for combo in combos:
        params = {**base, **combo}
        result = runner(df, strategy, params, **run_kwargs)
        runs.append((params, result))
    runs.sort(key=lambda pr: _rank_of(pr[1], rank_metric, cfg_metric),
              reverse=True)

    version = dataset_version_of(df, dataset_tag)
    manifests = []
    for params, result in runs[:top_k]:
        m = RunManifest(
            stage="screen", strategy=strategy, params=params,
            engine=engine, dataset_version=version, seed=seed,
            dataset_bars=len(df),
            cost_config=_clean(run_kwargs),
            metrics=_clean(result.metrics),
            artifacts={"rank_metric": rank_metric},
        )
        manifests.append(m)
    return {
        "stage": "screen",
        "manifests": manifests,
        "top_params": [m.params for m in manifests],
        "rank_metric": rank_metric,
        "dataset_version": version,
    }


# ---------------------------------------------------------------------------
# S2 — cost stress (x2)
# ---------------------------------------------------------------------------

_COST_KEYS = ("spread_points", "slippage_points", "commission_per_lot")


def _stressed_costs(run_kwargs: dict, factor: float) -> dict:
    kwargs = dict(run_kwargs)
    for key in _COST_KEYS:
        kwargs[key] = float(kwargs.get(key, 0.0)) * factor
    return kwargs


def cost_stress_stage(df: pd.DataFrame, strategy: str,
                      params_list: list[dict], *,
                      factor: float = 2.0,
                      min_trades: int = 10,
                      engine: str = "truth",
                      dataset_tag: str | None = None,
                      seed: int = 0,
                      **run_kwargs) -> dict:
    """S2: TRUTH-engine robustness of every survivor at cost x ``factor``.

    Survival gate (documented, conservative): the stressed run must end
    above initial capital AND keep at least ``min_trades`` trades AND
    its max drawdown must not more than double the unstressed run's.
    The gate is a screening filter — surviving is NOT a profit promise.
    """
    if engine not in ("fast", "truth"):
        raise ValueError("engine must be 'fast' or 'truth'")
    if factor <= 1.0:
        raise ValueError("stress factor must be > 1.0")
    runner = run_backtest if engine == "truth" else run_fast
    version = dataset_version_of(df, dataset_tag)
    manifests = []
    for params in params_list:
        base = runner(df, strategy, params, **run_kwargs)
        stressed = runner(df, strategy, params,
                          **_stressed_costs(run_kwargs, factor))
        bm, sm = base.metrics, stressed.metrics
        trades_s = int(sm.get("trades", 0))
        dd_b = float(bm.get("max_drawdown_pct", 0.0))
        dd_s = float(sm.get("max_drawdown_pct", 0.0))
        end_b = float(bm.get("end_equity", 0.0))
        end_s = float(sm.get("end_equity", 0.0))
        dd_ok = dd_s >= 2.0 * min(dd_b, 0.0)  # never more than doubled
        survived = (end_s > float(run_kwargs.get("initial_capital", 10_000.0))
                    and trades_s >= min_trades
                    and dd_ok)
        manifests.append(RunManifest(
            stage="cost_stress", strategy=strategy, params=params,
            engine=engine, dataset_version=version, seed=seed,
            dataset_bars=len(df),
            cost_config=_clean(_stressed_costs(run_kwargs, factor)),
            status="ok" if survived else "dropped",
            metrics=_clean(sm),
            artifacts={
                "factor": float(factor),
                "base_end_equity": end_b,
                "stressed_end_equity": end_s,
                "stressed_trades": trades_s,
                "base_max_drawdown_pct": dd_b,
                "stressed_max_drawdown_pct": dd_s,
                "min_trades": min_trades,
            },
        ))
    return {"stage": "cost_stress", "manifests": manifests}


# ---------------------------------------------------------------------------
# S3 — trade-level purged CPCV (own implementation)
# ---------------------------------------------------------------------------


def _entry_index_map(index: pd.DatetimeIndex) -> dict[str, int]:
    return {str(t): i for i, t in enumerate(index)}


def _block_edges(n: int, n_splits: int) -> list[tuple[int, int]]:
    """Contiguous bar blocks; the last absorbs the remainder."""
    size = n // n_splits
    if size < 1:
        raise ValueError("n_splits too large for the frame")
    edges = []
    start = 0
    for s in range(n_splits):
        end = n if s == n_splits - 1 else start + size
        edges.append((start, end))
        start = end
    return edges


def _pnl_per_bar(trades: pd.DataFrame, pos: dict[str, int],
                 n: int) -> np.ndarray:
    """Realised net pnl per bar, attributed to the ENTRY bar (the same
    attribution the walk-forward contract uses for window accounting)."""
    out = np.zeros(n)
    if trades is None or trades.empty:
        return out
    for entry, pnl in zip(trades["entry_time"], trades["pnl"]):
        i = pos.get(entry)
        if i is not None:
            out[i] += float(pnl)
    return out


def _sharpe_of_pnl(pnl: np.ndarray) -> float:
    vals = pnl[np.isfinite(pnl)]
    if vals.size < 3:
        return 0.0
    std = vals.std(ddof=1)
    if std <= 0.0:
        return 0.0
    return float(vals.mean() / std)


# ---------------------------------------------------------------------------
# Fold geometry (CPCV, fold-isolated state model)
# ---------------------------------------------------------------------------


def _embargoed_test_spans(edges: list[tuple[int, int]],
                          test_blocks: tuple[int, ...], n: int,
                          embargo_bars: int) -> list[tuple[int, int]]:
    """Test blocks expanded by ``embargo_bars`` on both sides, merged into
    maximal spans.  The embargo margin belongs to the TEST side of the
    fold (it is simulated under fold-allowed data only) and is excluded
    from every TRAIN span."""
    raw = sorted(
        (max(0, edges[b][0] - embargo_bars), min(n, edges[b][1] + embargo_bars))
        for b in test_blocks)
    merged: list[list[int]] = [list(raw[0])]
    for lo, hi in raw[1:]:
        if lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(lo, hi) for lo, hi in merged]


def _complement_spans(n: int,
                      spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Maximal contiguous runs of ``range(n)`` not covered by ``spans``."""
    out: list[tuple[int, int]] = []
    cursor = 0
    for lo, hi in sorted(spans):
        if lo > cursor:
            out.append((cursor, lo))
        cursor = max(cursor, hi)
    if cursor < n:
        out.append((cursor, n))
    return out


def _test_interior_mask(edges: list[tuple[int, int]],
                        test_blocks: tuple[int, ...], n: int) -> np.ndarray:
    """Bars inside the raw (un-embargoed) test blocks.  Price-only warmup
    windows may never reach these bars — otherwise a fold's training
    indicators would be functions of another span's test data."""
    mask = np.zeros(n, dtype=bool)
    for b in test_blocks:
        lo, hi = edges[b]
        mask[lo:hi] = True
    return mask


def _warmup_allowed(span_start: int, warmup_bars: int,
                    test_interior: np.ndarray) -> int:
    """How many of the ``warmup_bars`` bars before ``span_start`` may be
    used as price-only indicator warmup: the contiguous run of
    immediately-preceding bars that stays clear of every raw test-block
    interior of the fold."""
    w = 0
    while w < warmup_bars:
        bar = span_start - w - 1
        if bar < 0 or test_interior[bar]:
            break
        w += 1
    return w


def purged_cv_stage(df: pd.DataFrame, strategy: str,
                    params_list: list[dict], *,
                    n_splits: int = 6,
                    embargo_bars: int = 0,
                    purge_bars: int = 0,
                    warmup_bars: int = 100,
                    engine: str = "truth",
                    dataset_tag: str | None = None,
                    seed: int = 0,
                    **run_kwargs) -> dict:
    """S3: fold-isolated purged combinatorial CV (CPCV-style, own impl).

    STATE MODEL (formal; see ``docs/CV_STATE_CONTRACT.md``): the previous
    implementation ran ONE full-sample simulation per configuration and
    filtered its trades per fold.  For stateful engines (equity-based
    sizing, daily-loss halts, permanent drawdown halts, open-position
    carry) a fold's TRAIN scores were then functions of state created on
    bars outside the fold's train region — DATA filtering cannot undo
    STATE contamination.  This implementation therefore scores every span
    on its own ISOLATED simulation:

    * Geometry — the bar axis is cut into ``n_splits`` contiguous blocks;
      every combination of ``n_splits // 2`` test blocks is one fold.
      Test spans are the test blocks expanded by ``embargo_bars`` on both
      sides (merged); train spans are the maximal contiguous complements.
    * Isolated evaluation — each scored span (train or test) is simulated
      by a FRESH engine run over the contiguous slice
      ``df[span_start - warm : span_end]`` with cold-start state:
      initial capital, flat, no halts, no realized cash, no drawdown
      peak, no daily-loss state.  Nothing from any other span's
      simulation can influence it.
    * Warmup — the first ``warm`` bars of the slice compute signals but
      open no positions (engine ``warmup_bars``); they provide indicator
      history only.  ``warm`` is truncated so warmup PRICES never reach
      into any raw test-block interior of the fold.  No outcomes, state
      or fitted artifacts cross a span boundary — prices from
      non-test bars immediately before the span are the only shared
      context, and only as indicator inputs.
    * Purge — trades entered in a TRAIN span whose exit falls within the
      last ``purge_bars`` bars of the span are boundary-censored (they
      would be force-closed at an isolated run's boundary) and are
      dropped from the train score.  Under span isolation a trade can
      never overlap a test block at all.
    * Scores — selection (IS) score per configuration: Sharpe of the
      entry-bar-attributed realised pnl over the fold's train bars.
      Each fold selects the best IS configuration (ties -> smallest
      parameter hash) and scores it on its own test spans (same
      attribution).  The reported OOS-Sharpe distribution is a
      DEVELOPMENT-data ranking diagnostic — it never touches the
      certification dataset and never replaces S5.

    A fold is skipped (recorded in ``artifacts['skipped_folds']``) when
    its train region is empty; a scored span slice smaller than the
    engines' minimum raises loudly.
    """
    if n_splits < 4 or n_splits % 2 != 0:
        raise ValueError("n_splits must be an even integer >= 4")
    if embargo_bars < 0:
        raise ValueError("embargo_bars must be >= 0")
    if purge_bars < 0:
        raise ValueError("purge_bars must be >= 0")
    if warmup_bars < 0:
        raise ValueError("warmup_bars must be >= 0")
    if not params_list:
        raise ValueError("params_list must not be empty")
    if engine not in ("fast", "truth"):
        raise ValueError("engine must be 'fast' or 'truth'")
    runner = run_backtest if engine == "truth" else run_fast
    version = dataset_version_of(df, dataset_tag)
    n = len(df)
    edges = _block_edges(n, n_splits)
    n_test = n_splits // 2

    state_model = {
        "mode": "isolated_span_cold_start",
        "engine_init": "fresh engine per scored span; no cross-span engine "
                       "state, no full-sample stateful backtest",
        "capital_state": "initial_capital at every span start; realized "
                         "cash never crosses spans",
        "position_state": "flat at every span start; no open-position "
                          "carry (WFA carry is a different, documented "
                          "policy)",
        "daily_loss_state": "day-start equity resets per span-local server "
                            "day; no halt state crosses spans",
        "drawdown_state": "drawdown peak = initial_capital at every span "
                          "start; the kill switch is span-local",
        "strategy_state": "signals computed on the span slice plus its "
                          "price-only warmup; no strategy state crosses "
                          "spans",
        "parameter_state": "fixed candidate parameters for the whole "
                           "span; no fitting, calibration or selection "
                           "inside a scored span",
        "warmup_policy": "price-only, entries blocked, never reaches a "
                         "raw test-block interior of the fold",
    }

    slice_pos_cache: dict[tuple[int, int], dict[str, int]] = {}

    def _slice_pos(a: int, hi: int) -> dict[str, int]:
        key = (a, hi)
        if key not in slice_pos_cache:
            slice_pos_cache[key] = {
                str(t): i for i, t in enumerate(df.index[a:hi])
            }
        return slice_pos_cache[key]

    def _span_trades(params: dict, lo: int, hi: int, warm: int,
                     drop_after: int | None) -> list[tuple[int, int, float]]:
        """Run the isolated simulation for ``[lo, hi)`` and return
        ``(global_entry, global_exit, pnl)`` for trades entered within the
        span, with boundary-censoring applied when ``drop_after`` is set
        (trades exiting at/after that bar are purged)."""
        a = lo - warm
        sub = df.iloc[a:hi]
        if len(sub) < 4:
            raise ValueError(
                f"scored span slice too small ({len(sub)} bars at "
                f"[{lo}, {hi})) — more bars or a smaller n_splits needed")
        res = runner(sub, strategy, params, warmup_bars=warm, **run_kwargs)
        pos = _slice_pos(a, hi)
        out: list[tuple[int, int, float]] = []
        trades = res.trades
        if trades is not None and len(trades):
            for entry, exit_t, pnl in zip(trades["entry_time"],
                                          trades["exit_time"],
                                          trades["pnl"]):
                le = pos.get(entry)
                lx = pos.get(exit_t)
                if le is None or lx is None:
                    continue  # not on this slice's grid: cannot happen for
                    # engine-produced rows; defensive only
                if le < warm:
                    continue  # warmup entries are structurally blocked
                ge, gx = a + le, a + lx
                if drop_after is not None and gx >= drop_after:
                    continue  # boundary-censored (purge)
                out.append((ge, gx, float(pnl)))
        return out

    cfg_ids = [_param_hash(p) for p in params_list]
    trade_counts = [0] * len(params_list)
    fold_scores: list[float] = []
    selected_hashes: list[str] = []
    fold_log: list[dict] = []
    skipped_folds: list[dict] = []

    for test_blocks in itertools.combinations(range(n_splits), n_test):
        test_spans = _embargoed_test_spans(edges, test_blocks, n,
                                           embargo_bars)
        train_spans = _complement_spans(n, test_spans)
        if not train_spans:
            skipped_folds.append({"test_blocks": sorted(test_blocks),
                                  "reason": "no train bars after embargo"})
            continue
        train_bars = np.zeros(n, dtype=bool)
        for lo, hi in train_spans:
            train_bars[lo:hi] = True
        test_bars = np.zeros(n, dtype=bool)
        for lo, hi in test_spans:
            test_bars[lo:hi] = True
        test_interior = _test_interior_mask(edges, test_blocks, n)

        # ---- in-sample scores: isolated runs over every train span -------
        is_scores: list[float] = []
        for ci, params in enumerate(params_list):
            pooled = np.zeros(n)
            for lo, hi in train_spans:
                warm = _warmup_allowed(lo, warmup_bars, test_interior)
                drop_after = (hi - purge_bars) if purge_bars > 0 else None
                for ge, _gx, pnl in _span_trades(params, lo, hi, warm,
                                                 drop_after):
                    pooled[ge] += pnl
                    trade_counts[ci] += 1
            is_scores.append(_sharpe_of_pnl(pooled[train_bars]))

        # deterministic argmax: best IS; ties -> smallest param hash
        best = max(range(len(params_list)),
                   key=lambda i: (is_scores[i], -int(cfg_ids[i], 16)))
        chosen_params = params_list[best]

        # ---- test scores: isolated runs over the chosen config's spans ---
        pooled_test = np.zeros(n)
        for lo, hi in test_spans:
            warm = _warmup_allowed(lo, warmup_bars, test_interior)
            for ge, _gx, pnl in _span_trades(chosen_params, lo, hi, warm,
                                             None):
                pooled_test[ge] += pnl
                trade_counts[best] += 1
        fold_scores.append(_sharpe_of_pnl(pooled_test[test_bars]))
        selected_hashes.append(cfg_ids[best])
        fold_log.append({
            "test_blocks": sorted(test_blocks),
            "test_spans": [list(s) for s in test_spans],
            "train_spans": [list(s) for s in train_spans],
            "selected": cfg_ids[best],
            "is_scores": [float(s) for s in is_scores],
            "oos_sharpe": fold_scores[-1],
        })

    if not fold_scores:
        raise ValueError(
            "no evaluable folds — every fold's train region was empty "
            "(embargo too large for the frame)")
    arr = np.asarray(fold_scores, dtype=float)
    manif = RunManifest(
        stage="purged_cv", strategy=strategy,
        params=dict(params_list[0]), engine=engine,
        dataset_version=version, seed=seed, dataset_bars=n,
        cost_config=_clean(run_kwargs),
        metrics={"oos_sharpe_mean": float(arr.mean()),
                 "oos_sharpe_worst": float(arr.min()),
                 "oos_sharpe_p10": float(np.percentile(arr, 10)),
                 "oos_sharpe_median": float(np.median(arr))},
        artifacts={
            "n_splits": n_splits,
            "embargo_bars": embargo_bars,
            "purge_bars": purge_bars,
            "warmup_bars": warmup_bars,
            "n_folds": len(fold_scores),
            "skipped_folds": skipped_folds,
            "state_model": state_model,
            "configs": [
                {"param_hash": h, "params": c, "n_trades": int(t)}
                for h, c, t in zip(cfg_ids, params_list, trade_counts)
            ],
            "selected_most": max(set(selected_hashes),
                                 key=selected_hashes.count),
            "per_fold_oos_sharpe": [float(x) for x in fold_scores],
            "folds": fold_log,
        },
    )
    return {"stage": "purged_cv", "manifest": manif}


# ---------------------------------------------------------------------------
# S4 — headless MT5 tester (certification path, terminal host only)
# ---------------------------------------------------------------------------


def mt5_stage(tester_config=None, run_settings=None) -> RunManifest:
    """S4: headless MetaTrader 5 Strategy Tester ticks.

    Requires a real terminal host: pass an ``mt5tester.TesterConfig`` and
    ``RunSettings``.  Without them the stage returns a manifest with
    status ``skipped`` and an explicit reason — results are never faked
    and never guessed.
    """
    if tester_config is None or run_settings is None:
        return RunManifest(
            stage="mt5", strategy="", params={}, engine="mt5tester",
            dataset_version="", status="skipped",
            artifacts={"reason": "headless MT5 tester requires a terminal "
                       "host; no TesterConfig provided (certification "
                       "runs on a terminal machine)"},
        )
    from .mt5tester import _config_snapshot, run_backtest

    outcome = run_backtest(tester_config, run_settings)
    return RunManifest(
        stage="mt5", strategy=getattr(tester_config, "ea", "") or "",
        params={}, engine="mt5tester",
        dataset_version="",
        status="ok" if outcome.ok else "failed",
        metrics=_clean(outcome.to_dict().get("metrics") or {}),
        artifacts={"snapshot": _config_snapshot(tester_config),
                   "run_id": outcome.run_id,
                   "error": outcome.error},
    )


# ---------------------------------------------------------------------------
# S5 — OOS certification with the one-look registry
# ---------------------------------------------------------------------------


class OosOneLookViolation(ValueError):
    """The OOS certification slice was already used."""


def _cost_config_digest(run_kwargs: dict) -> str:
    """Content digest of the cost-relevant run kwargs (the cost MODEL
    version is semantic; the cost CONFIG is content-addressed here so a
    different spread/commission regime can never silently share a
    certification identity)."""
    cost = {k: _clean(v) for k, v in sorted(run_kwargs.items())
            if any(part in k for part in
                   ("spread", "slippage", "commission", "point",
                    "contract_size", "swap"))}
    blob = json.dumps(cost, sort_keys=True, separators=(",", ":"),
                      default=repr)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


@dataclass
class OosIdentity:
    """Exact certification identity (Blocker 6).

    A certification look is unique to ALL of these fields together; the
    registry additionally refuses ANY new entry on the same
    (dataset content, strategy) pair, so changing a version field can
    never be used to mint a fresh look on the same data.
    """

    dataset_content_digest: str          # _dataset_digest(df) — always
    strategy: str
    strategy_version: str
    engine: str                          # "truth" only is a certification
    engine_version: str
    cost_model_version: str
    cost_config_digest: str
    feature_version: str
    certification_protocol_version: str
    dataset_tag: str = ""                # optional human tag (never the
    #                                      identity anchor — content is)

    def canonical(self) -> dict:
        return {
            "dataset_content_digest": self.dataset_content_digest,
            "dataset_tag": self.dataset_tag,
            "strategy": self.strategy,
            "strategy_version": self.strategy_version,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "cost_model_version": self.cost_model_version,
            "cost_config_digest": self.cost_config_digest,
            "feature_version": self.feature_version,
            "certification_protocol_version":
                self.certification_protocol_version,
        }

    def identity_id(self) -> str:
        blob = json.dumps(self.canonical(), sort_keys=True,
                          separators=(",", ":"), default=repr)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()

    def differ(self, other: OosIdentity) -> list[str]:
        return [k for k in self.canonical()
                if self.canonical()[k] != other.canonical().get(k)]


@dataclass
class OosRegistry:
    """Persistent one-look enforcement for OOS certification slices.

    POLICY (Blocker 6): one certification per exact identity
    (:class:`OosIdentity`), anchored on the DATASET CONTENT DIGEST — an
    explicit ``dataset_tag`` never weakens the identity.  Beyond the
    exact-identity check the registry refuses any entry with the same
    (dataset content, strategy) pair even when strategy version, cost
    model, feature version or protocol version differ: a researcher
    cannot bump a version and accidentally reuse the same certification
    slice — the attempt raises ``OosOneLookViolation`` naming exactly
    which identity fields changed.  One look, recorded, forever.

    File schema v2 (``_schema``); v1 files (flat
    ``"dataset_version::strategy"`` keys) are migrated on load and keep
    their enforcement.
    """

    path: str | Path

    # -- storage -----------------------------------------------------------

    def _load(self) -> dict:
        p = Path(self.path)
        if not p.exists():
            return {"_schema": 2, "entries": [], "legacy": {}}
        raw = json.loads(p.read_text(encoding="utf-8"))
        if "_schema" not in raw:  # v1 migration (persisted immediately)
            raw = {"_schema": 2, "entries": [],
                   "legacy": {k: v for k, v in raw.items()
                              if not k.startswith("_")}}
            self._save(raw)
        raw.setdefault("entries", [])
        raw.setdefault("legacy", {})
        return raw

    def _save(self, data: dict) -> None:
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, sort_keys=True),
                     encoding="utf-8")

    # -- lookups -----------------------------------------------------------

    def _matching_entries(self, strategy: str,
                          dataset_content_digest: str) -> list[dict]:
        return [e for e in self._load()["entries"]
                if e["identity"]["strategy"] == strategy
                and e["identity"]["dataset_content_digest"]
                == dataset_content_digest]

    def has_look(self, strategy: str, dataset_version: str) -> bool:
        """Legacy check: (dataset-version-or-tag, strategy).  Matches
        v2 identities too (tag or content digest)."""
        data = self._load()
        if f"{dataset_version}::{strategy}" in data["legacy"]:
            return True
        return any(
            e["identity"]["strategy"] == strategy
            and dataset_version in (e["identity"]["dataset_tag"],
                                    e["identity"]
                                    ["dataset_content_digest"])
            for e in data["entries"])

    def check_identity(self, identity: OosIdentity) -> None:
        """Refuse when this slice+strategy was already certified — under
        ANY identity version (Blocker 6: version changes cannot mint a
        second look)."""
        prior = self._matching_entries(identity.strategy,
                                       identity.dataset_content_digest)
        if not prior:
            return
        prev = OosIdentity(**{k: v for k, v in prior[0]["identity"].items()
                              if k in OosIdentity.__dataclass_fields__})
        changed = identity.differ(prev)
        raise OosOneLookViolation(
            f"OOS certification slice already used for "
            f"{identity.strategy!r} on dataset content "
            f"{identity.dataset_content_digest[:12]!r} (one-look policy; "
            f"prior identity {prior[0]['identity_id'][:12]!r}, certified "
            f"{prior[0].get('certified')}).  Changed identity fields: "
            f"{changed or 'none (exact same identity)'}.  A fresh, "
            "never-touched dataset is required for any further "
            "certification — changing versions does not grant a new "
            "look.")

    # -- certification -----------------------------------------------------

    def certify_identity(self, identity: OosIdentity, params: dict,
                         strategy_version: str = "undeclared",
                         metrics: dict | None = None,
                         cost_config: dict | None = None,
                         dataset_bars: int = 0) -> RunManifest:
        """Record one certification look under the exact identity; raise
        if the slice+strategy was already used under any identity."""
        if identity.engine != "truth":
            raise ValueError("OOS certification requires the TRUTH engine")
        self.check_identity(identity)
        entry = RunManifest(
            stage="oos", strategy=identity.strategy, params=params,
            engine=identity.engine,
            dataset_version=(identity.dataset_tag
                             or identity.dataset_content_digest),
            dataset_bars=dataset_bars,
            cost_config=_clean(cost_config or {}),
            metrics=_clean(metrics or {}),
            status="ok",
            artifacts={
                "policy": "one-look-per-dataset-content",
                "identity": identity.canonical(),
                "identity_id": identity.identity_id(),
                # Blocker 7: development-funnel empirical pass — never a
                # verified-strategy claim until the MT5 ladder ran.
                "certification_status": "EMPIRICAL_VALIDATION_PENDING",
                "mt5_status": "NOT VERIFIED",
            },
        )
        data = self._load()
        data["entries"].append({
            "identity_id": identity.identity_id(),
            "identity": identity.canonical(),
            "params": entry.params,
            "manifest_id": entry.manifest_id,
            "strategy_version": strategy_version,
            "engine": identity.engine,
            "metrics": entry.metrics,
            "cost_config": entry.cost_config,
            "certification_status": "EMPIRICAL_VALIDATION_PENDING",
            "mt5_status": "NOT VERIFIED",
            "certified": entry.created,
        })
        self._save(data)
        return entry

    def certify(self, strategy: str, dataset_version: str,
                params: dict, strategy_version: str = "undeclared",
                strategy_engine: str = "truth",
                metrics: dict | None = None,
                cost_config: dict | None = None,
                dataset_bars: int = 0) -> RunManifest:
        """LEGACY entry point (pre-identity callers and tests): records
        under an identity whose anchor is the given dataset version
        string.  One look per (dataset version, strategy) — enforced
        against v2 entries as well."""
        from . import __version__ as engine_version
        from .versions import (
            CERTIFICATION_PROTOCOL_VERSION,
            COST_MODEL_VERSION,
            FEATURE_VERSION,
        )

        data = self._load()
        legacy_key = f"{dataset_version}::{strategy}"
        if legacy_key in data["legacy"]:
            raise OosOneLookViolation(
                f"OOS certification slice already used for {strategy!r} "
                f"on dataset version {dataset_version!r} (one-look "
                f"policy; prior params "
                f"{data['legacy'][legacy_key]['params']!r}). A fresh, "
                "never-touched dataset version is required for any "
                "further certification.")
        identity = OosIdentity(
            dataset_content_digest=dataset_version,
            dataset_tag=dataset_version,
            strategy=strategy,
            strategy_version=strategy_version,
            engine=strategy_engine,
            engine_version=engine_version,
            cost_model_version=COST_MODEL_VERSION,
            cost_config_digest="",
            feature_version=FEATURE_VERSION,
            certification_protocol_version=CERTIFICATION_PROTOCOL_VERSION,
        )
        prior = self._matching_entries(strategy, dataset_version)
        if prior:
            self.check_identity(identity)  # raises with the diff
        entry = RunManifest(
            stage="oos", strategy=strategy, params=params,
            engine=strategy_engine, dataset_version=dataset_version,
            dataset_bars=dataset_bars,
            cost_config=_clean(cost_config or {}),
            metrics=_clean(metrics or {}),
            status="ok",
            artifacts={
                "policy": "one-look-per-dataset-version",
                "identity_id": identity.identity_id(),
                "certification_status": "EMPIRICAL_VALIDATION_PENDING",
                "mt5_status": "NOT VERIFIED",
            },
        )
        data["legacy"][legacy_key] = {
            "params": entry.params,
            "manifest_id": entry.manifest_id,
            "strategy_version": strategy_version,
            "engine": strategy_engine,
            "metrics": entry.metrics,
            "cost_config": entry.cost_config,
            "certification_status": "EMPIRICAL_VALIDATION_PENDING",
            "mt5_status": "NOT VERIFIED",
            "certified": entry.created,
        }
        self._save(data)
        return entry


def oos_identity(df: pd.DataFrame, strategy: str, *,
                 dataset_tag: str | None = None,
                 strategy_version: str | None = None,
                 engine: str = "truth",
                 **run_kwargs) -> OosIdentity:
    """Exact certification identity of an S5 look (Blocker 6).

    The anchor is the DATASET CONTENT digest — an explicit
    ``dataset_tag`` is carried but never weakens the identity.  Strategy
    version, engine version, cost-model version, cost-config digest,
    feature version and certification protocol version all participate;
    the registry refuses a second look on the same (content, strategy)
    pair under ANY identity.
    """
    from . import __version__ as pkg_version
    from .versions import (
        CERTIFICATION_PROTOCOL_VERSION,
        COST_MODEL_VERSION,
        ENGINE_VERSION,
        FEATURE_VERSION,
    )

    return OosIdentity(
        dataset_content_digest=_dataset_digest(df),
        dataset_tag=dataset_tag or "",
        strategy=strategy,
        strategy_version=strategy_version
        or STRATEGY_VERSIONS.get(strategy, "undeclared"),
        engine=engine,
        engine_version=ENGINE_VERSION or pkg_version,
        cost_model_version=COST_MODEL_VERSION,
        cost_config_digest=_cost_config_digest(run_kwargs),
        feature_version=FEATURE_VERSION,
        certification_protocol_version=CERTIFICATION_PROTOCOL_VERSION,
    )


def oos_stage(df: pd.DataFrame, strategy: str, params: dict, *,
              registry: OosRegistry,
              dataset_tag: str | None = None,
              strategy_version: str | None = None,
              engine: str = "truth",
              **run_kwargs) -> dict:
    """S5: ONE final TRUTH-engine run on never-touched OOS data.

    The registry refuses a second look on the same (dataset content,
    strategy) pair under ANY certification identity
    (``OosOneLookViolation``) — checked BEFORE the run.  The recorded
    entry carries the full ``OosIdentity`` (content digest, strategy /
    engine / cost-model / feature / protocol versions, cost-config
    digest) plus the parameter hash and the full cost configuration —
    enough to reproduce and to audit the certified run exactly.
    """
    if engine != "truth":
        raise ValueError("OOS certification requires engine='truth'")
    merged = {**default_params(strategy), **params}
    identity = oos_identity(df, strategy, dataset_tag=dataset_tag,
                            strategy_version=strategy_version,
                            engine=engine, **run_kwargs)
    # fast fail BEFORE the run: a second look on this content is refused
    registry.check_identity(identity)
    result = run_backtest(df, strategy, params, **run_kwargs)
    entry = registry.certify_identity(
        identity, merged, strategy_version=identity.strategy_version,
        metrics=_clean(result.metrics), cost_config=_clean(run_kwargs),
        dataset_bars=len(df))
    return {"stage": "oos", "manifest": entry, "result": result}


# ---------------------------------------------------------------------------
# Orchestration + cache + optional Optuna
# ---------------------------------------------------------------------------


def _cache_key(stage: str, inputs: dict) -> str:
    blob = json.dumps(_clean(inputs), sort_keys=True, separators=(",", ":"),
                      default=repr)
    return hashlib.sha1(f"{stage}|{blob}".encode()).hexdigest()


def _cache_load(cache_dir: str | None, key: str):
    if not cache_dir:
        return None
    p = Path(cache_dir) / f"{key}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _cache_save(cache_dir: str | None, key: str, data) -> None:
    if not cache_dir:
        return
    p = Path(cache_dir)
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{key}.json").write_text(
        json.dumps(_clean(data), indent=2, sort_keys=True),
        encoding="utf-8")



def research_identity() -> dict:
    """§54: identity of everything the research code carries into a
    cache key — engine, cost model, feature set, DSL schema.  Any bump
    invalidates every stage cache deterministically."""
    from . import versions as _versions
    from .dsl.schema import SCHEMA_VERSION as _DSL_VERSION
    return {"engine_version": _versions.ENGINE_VERSION,
            "cost_model_version": _versions.COST_MODEL_VERSION,
            "feature_version": _versions.FEATURE_VERSION,
            "dsl_schema_version": _DSL_VERSION}


def run_stages(df: pd.DataFrame, strategy: str, grid: dict, *,
               top_k: int = 5,
               n_splits: int = 6,
               embargo_bars: int = 0,
               purge_bars: int = 0,
               warmup_bars: int = 100,
               dataset_tag: str | None = None,
               oos_df: pd.DataFrame | None = None,
               oos_registry: OosRegistry | None = None,
               cache_dir: str | None = None,
               seed: int = 0,
               **run_kwargs) -> dict:
    """Run S1->S3 (-> S5 when an OOS frame + registry are supplied).

    Certification semantics (Blockers 5 + 7): ``NO VALID SURVIVOR`` is
    never an OOS candidate.  When S2 leaves zero survivors, S3 stays
    skipped and S5 is BLOCKED with reason ``NO_VALID_SURVIVOR`` — the
    registry is not consulted and nothing is certified.  A fallback
    candidate exists for DIAGNOSTICS only.  The result always carries an
    explicit ``certification`` status section
    (:mod:`mql5bot.status`): ``NOT_ELIGIBLE`` /
    ``EMPIRICAL_VALIDATION_PENDING`` / ``FAILED`` — MT5 is ``NOT
    VERIFIED`` here because ``run_stages`` never runs MT5.

    Deterministic and cacheable: stage outputs are cached under
    ``cache_dir`` keyed by the stage inputs (content digests, params,
    cost config, seed) and replayed verbatim on a cache hit.  S4 (MT5)
    is never invoked here — certification ticks belong to a terminal
    host and are driven by ``mt5_stage`` explicitly.
    """
    version = dataset_version_of(df, dataset_tag)
    out = {"dataset_version": version, "stages": {}}
    # §54 cache safety: the research identity binds code/DSL/policy
    # versions so incompatible evidence can never be reused
    identity = research_identity()

    key = _cache_key("s1", {"strategy": strategy, "grid": grid,
                            "version": version, "top_k": top_k,
                            "seed": seed, "run_kwargs": run_kwargs,
                            "identity": identity})
    cached = _cache_load(cache_dir, key)
    if cached is not None:
        out["stages"]["screen"] = cached
    else:
        s1 = screen_stage(df, strategy, grid, top_k=top_k,
                          dataset_tag=dataset_tag, seed=seed, **run_kwargs)
        out["stages"]["screen"] = {
            "manifests": [m.to_dict() for m in s1["manifests"]],
        }
        _cache_save(cache_dir, key, out["stages"]["screen"])

    survivors = [m["params"] for m in out["stages"]["screen"]["manifests"]]
    key2 = _cache_key("s2", {"strategy": strategy, "params": survivors,
                             "version": version, "seed": seed,
                             "run_kwargs": run_kwargs,
                             "identity": identity})
    cached = _cache_load(cache_dir, key2)
    if cached is not None:
        out["stages"]["cost_stress"] = cached
    else:
        s2 = cost_stress_stage(df, strategy, survivors, seed=seed,
                               dataset_tag=dataset_tag, **run_kwargs)
        out["stages"]["cost_stress"] = {
            "manifests": [m.to_dict() for m in s2["manifests"]],
        }
        _cache_save(cache_dir, key2, out["stages"]["cost_stress"])
    survivors = [m["params"] for m in out["stages"]["cost_stress"]
                 ["manifests"] if m["status"] == "ok"]

    if survivors:
        key3 = _cache_key("s3", {"strategy": strategy, "params": survivors,
                                 "version": version, "n_splits": n_splits,
                                 "embargo_bars": embargo_bars,
                                 "purge_bars": purge_bars,
                                 "warmup_bars": warmup_bars,
                                 "seed": seed,
                                 "run_kwargs": run_kwargs,
                                 "identity": identity})
        cached = _cache_load(cache_dir, key3)
        if cached is not None:
            out["stages"]["purged_cv"] = cached
        else:
            s3 = purged_cv_stage(df, strategy, survivors,
                                 n_splits=n_splits,
                                 embargo_bars=embargo_bars,
                                 purge_bars=purge_bars,
                                 warmup_bars=warmup_bars, seed=seed,
                                 dataset_tag=dataset_tag, **run_kwargs)
            out["stages"]["purged_cv"] = s3["manifest"].to_dict()
            _cache_save(cache_dir, key3, out["stages"]["purged_cv"])
    else:
        # loud, documented: the funnel stops here unless OOS data is
        # provided, in which case S5 falls back to the screen leader
        out["stages"]["purged_cv"] = RunManifest(
            stage="purged_cv", strategy=strategy, params={},
            engine="fast", dataset_version=version, seed=seed,
            dataset_bars=len(df), status="skipped",
            artifacts={"reason": "no cost-stress survivors (gate: x2-cost "
                       "end-equity, min trades, drawdown bound)"},
        ).to_dict()

    if oos_df is not None:
        if oos_registry is None:
            raise ValueError("oos_stage requires an OosRegistry")
        pcv = out["stages"]["purged_cv"]
        if pcv.get("status") == "ok":
            chosen = pcv.get("artifacts", {}).get("selected_most")
            params = next((p for p in survivors
                           if _param_hash(p) == chosen), survivors[0])
            oos = oos_stage(oos_df, strategy, params,
                            registry=oos_registry,
                            dataset_tag=dataset_tag, **run_kwargs)
            out["stages"]["oos"] = oos["manifest"].to_dict()
            out["oos_params"] = params
        else:
            # BLOCKER 5 semantics: NO VALID SURVIVOR must never become an
            # OOS candidate.  S5 is BLOCKED (diagnostic record only): the
            # one-look registry is not consulted, no run happens, no
            # certification is written.
            out["stages"]["oos"] = RunManifest(
                stage="oos", strategy=strategy, params={},
                engine="truth",
                dataset_version=dataset_version_of(oos_df, dataset_tag),
                seed=seed, dataset_bars=len(oos_df), status="blocked",
                artifacts={"reason": "NO_VALID_SURVIVOR: no S2 "
                           "cost-stress survivor — certification is "
                           "blocked; the screen leader is recorded for "
                           "diagnostics only and is NOT certified"},
            ).to_dict()
            out["oos_params"] = None

    # ---- certification status model (Blockers 5 + 7) ----------------------
    from .status import MT5_NOT_VERIFIED, pipeline_certification_status

    out["certification"] = pipeline_certification_status(
        s2_survivors=len(survivors),
        cv_status=out["stages"]["purged_cv"].get("status", "skipped"),
        oos_ran=(out["stages"].get("oos") or {}).get("status") == "ok",
        oos_status=(out["stages"].get("oos") or {}).get(
            "status", "not_requested"),
        mt5_status=MT5_NOT_VERIFIED,  # run_stages never runs MT5
    )
    return out


def optuna_optimize(df: pd.DataFrame, strategy: str, space: dict, *,
                    n_trials: int = 50,
                    dataset_tag: str | None = None,
                    seed: int = 0,
                    metric: str = "sharpe",
                    n_jobs: int = 1,
                    report_fractions: tuple[float, ...] = (0.25, 0.5, 1.0),
                    min_prefix_bars: int = 150,
                    pruner: str = "hyperband",
                    cache_dir: str | None = None,
                    oos_guard_df: pd.DataFrame | None = None,
                    **run_kwargs) -> dict:
    """OPTIONAL stage: Optuna TPE + Hyperband search over ``space``.

    Never a core dependency: importing this function does not import
    Optuna; calling it without ``optuna`` installed raises ImportError
    with an install hint.

    Search semantics (Phase 3 hardening — the stage now matches its
    claims):

    * ``TPESampler(seed=seed)`` — with ``n_jobs=1`` the trial sequence is
      deterministic: identical seed + data + space reproduce identical
      trial order and best params.
    * ``HyperbandPruner`` — intermediate metrics are reported with
      ``trial.report(value, step)`` / ``trial.should_prune()`` and pruned
      trials raise ``TrialPruned``.  EVERY reported value is a
      development-data TRAINING-side evaluation: ``run_fast`` on a
      prefix of ``df`` (the development frame) at increasing
      ``report_fractions`` (floor ``min_prefix_bars``).  NO out-of-sample
      or certification metric is ever visible to the objective.
    * ``oos_guard_df`` — when given, the stage REFUSES to run if the
      optimization frame's content digest equals the guarded (OOS) frame:
      optimizing the certification slice is a protocol violation, caught
      before the first trial.
    * ``cache_dir`` — content-addressed per-step cache
      (dataset digest + strategy + params + run kwargs + step): a cache
      hit replays the identical value without re-simulation.
    * ``n_jobs > 1`` — optional parallel evaluation.  Trial ORDER is no
      longer deterministic (sampling depends on completion order); this
      is opt-in and documented rather than hidden.
    * If the installed Optuna has no ``HyperbandPruner`` the stage raises
      ``RuntimeError`` naming the version — it never silently substitutes
      another pruner.

    Screening signal only — certification stays on the TRUTH path (S5).
    """
    try:
        import optuna
    except ImportError as exc:  # optional extra only
        raise ImportError(
            "optuna_optimize requires the optional 'optimize' extra "
            "(pip install mql5bot[optimize]); it is never a core "
            "dependency of the pipeline") from exc
    if pruner != "hyperband":
        raise ValueError("pruner must be 'hyperband' (the documented "
                         "design); other pruners are not silently "
                         "substituted")
    if not hasattr(optuna.pruners, "HyperbandPruner"):
        raise RuntimeError(
            f"optuna {optuna.__version__} does not provide "
            "optuna.pruners.HyperbandPruner — the documented Hyperband "
            "design cannot be honoured on this version; upgrade optuna "
            "instead of silently substituting another pruner")
    if not 0.0 < min(report_fractions) <= max(report_fractions) <= 1.0:
        raise ValueError("report_fractions must be within (0, 1]")
    version = dataset_version_of(df, dataset_tag)
    if oos_guard_df is not None:
        guard_version = _dataset_digest(oos_guard_df)
        if guard_version == _dataset_digest(df):
            raise ValueError(
                "optuna_optimize: the optimization frame IS the guarded "
                "OOS certification slice (identical content digest) — "
                "never optimise on the certification data")
    else:
        guard_version = None
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    n = len(df)
    steps = []
    for frac in report_fractions:
        bars = max(round(n * frac), min_prefix_bars, 4)
        steps.append(min(bars, n))
    # Optuna compares STEP INDICES against min_resource * rf**rung, so
    # min/max_resource are in step units: rung 0 is judged from the
    # second reported step on, rung k at step rf**k.
    hyper = optuna.pruners.HyperbandPruner(
        min_resource=1, max_resource=len(steps))

    from .optimizer import _param_hash as _ph

    def _evaluate(bars: int, merged: dict) -> float:
        key = _cache_key("optuna-trial", {
            "version": version, "strategy": strategy, "params": merged,
            "bars": bars, "metric": metric, "run_kwargs": run_kwargs,
        })
        cached = _cache_load(cache_dir, key)
        if cached is not None and "value" in cached:
            return float(cached["value"])
        res = run_fast(df.iloc[:bars], strategy, merged, **run_kwargs)
        value = res.metrics.get(metric)
        value = float(value) if value is not None else float("-inf")
        _cache_save(cache_dir, key, {"value": value})
        return value

    def objective(trial):
        params = {}
        for name, spec in space.items():
            kind = spec["type"]
            if kind == "int":
                params[name] = trial.suggest_int(name, spec["low"],
                                                 spec["high"])
            elif kind == "float":
                params[name] = trial.suggest_float(name, spec["low"],
                                                   spec["high"])
            elif kind == "categorical":
                params[name] = trial.suggest_categorical(name,
                                                         spec["choices"])
            else:
                raise ValueError(f"unsupported space type {kind!r}")
        merged = {**default_params(strategy), **params}
        _ph(merged)  # canonical parameter identity (cache is content-keyed)
        value = float("-inf")
        for step, bars in enumerate(steps):
            value = _evaluate(bars, merged)
            trial.report(value, step=step)
            if trial.should_prune():
                raise optuna.TrialPruned(
                    f"pruned at step {step} (bars={bars}) on training-side "
                    "prefix metric only")
        return value

    sampler = optuna.samplers.TPESampler(seed=seed)
    # Hyperband assigns trials to brackets via crc32(study_name, trial
    # number) — an auto-generated (random) study name would make PRUNING
    # decisions unreproducible.  The study name is therefore derived from
    # the run identity.
    study = optuna.create_study(
        direction="maximize", sampler=sampler, pruner=hyper,
        study_name=f"mql5bot-{strategy}-{version[:12]}-{seed}-{metric}")
    study.optimize(objective, n_trials=n_trials, n_jobs=max(1, int(n_jobs)),
                   show_progress_bar=False)
    states = [t.state.name for t in study.trials]
    return {
        "stage": "optuna",
        "strategy": strategy,
        "dataset_version": version,
        "oos_guard_version": guard_version,
        "metric": metric,
        "seed": seed,
        "n_trials": n_trials,
        "n_jobs": max(1, int(n_jobs)),
        "pruner": "HyperbandPruner",
        "optuna_version": optuna.__version__,
        "report_bars": [int(b) for b in steps],
        "n_complete": states.count("COMPLETE"),
        "n_pruned": states.count("PRUNED"),
        "trials": [
            {"params": dict(t.params), "state": t.state.name,
             "value": (float(t.value) if t.value is not None else None)}
            for t in study.trials
        ],
        "best_params": dict(study.best_params),
        "best_value": float(study.best_value),
        "engine": "fast",
        "note": "deterministic under seed with n_jobs=1; intermediate "
                "metrics are development-frame TRAINING-side prefix "
                "evaluations only; screening signal — certification "
                "stays on the TRUTH path",
    }
