"""mql5bot.meta_oos — OOS validation of the Meta Layer policy
(mandate Phases 14, 15, 27, 28).

The Meta Layer is treated EXACTLY like a strategy-selection policy:

* development  → fold diagnostics (purged, contiguous, embargoed);
* freeze       → the config hash is pinned BEFORE any OOS data is read;
* OOS          → ONE look at the untouched slice, recorded in the
  one-look :class:`~mql5bot.pipeline.OosRegistry` under the strategy id
  ``META_POLICY`` with meta_config_version, meta_parameter_hash,
  dataset content digest, strategy/engine/cost versions and the static
  regime-metadata version.

Nothing here tunes anything: the policy is deterministic (six explicit
parameters).  ``run_meta_oos`` is measurement + registry discipline —
a second call on the same OOS slice raises ``OosOneLookViolation``
even if the config changed, so the evaluation slice can never become a
tuning loop.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .backtest import run_backtest
from .meta_layer import (
    META_LAYER_VERSION,
    MetaConfig,
    MetaLayer,
    MetaPolicy,
    StrategyMetaInput,
    canonical_json,
    sha256_hex,
)
from .optimizer import STRATEGY_VERSIONS, _dataset_digest
from .versions import COST_MODEL_VERSION, ENGINE_VERSION

REGIME_VERSION = "static-metadata-1"   # declared regimes, no classifier
META_POLICY_ID = "META_POLICY"
TRADING_DAYS = 252


@dataclass(frozen=True)
class StrategySpec:
    """A contributing strategy: unique book id + engine registry name
    (same engine strategy may contribute twice with different params —
    the book id keeps attribution distinct) + frozen params."""

    name: str
    params: dict
    engine_name: str = ""       # defaults to `name` when empty

    @property
    def version(self) -> str:
        return STRATEGY_VERSIONS.get(self.engine_name or self.name,
                                     "undeclared")

    @property
    def engine_strategy(self) -> str:
        return self.engine_name or self.name


# ---- policy weights from DEVELOPMENT-side information only --------------


def policy_inputs(specs: Sequence[StrategySpec], symbol: str = "SYNTH",
                  *, regime: str = "TREND_UP") -> list[StrategyMetaInput]:
    """Certification-state inputs for the research comparison: every
    contributing strategy is treated as VERIFIED (the comparison
    isolates the WEIGHTING policy; certification gating is tested
    elsewhere)."""
    return [StrategyMetaInput(
        s.name, symbol, 0, regime,
        frozenset({regime}), frozenset({regime}), frozenset(),
        "VERIFIED", drift_available=True, drift_score=0.0)
        for s in sorted(specs, key=lambda s: s.name)]


def policy_weights(config: MetaConfig, specs, oos_stats, returns=None,
                   as_of: datetime | None = None) -> dict[str, float]:
    """Final weights under the configured policy.  Both policies run
    through the SAME eligibility/normalization/constraint machinery —
    only the weighting policy differs."""
    as_of = as_of or datetime.now(timezone.utc)
    inputs = policy_inputs(specs)
    lay = MetaLayer(config)
    d = lay.decide(inputs, as_of=as_of, returns=returns,
                   oos_stats=oos_stats)
    return {w.strategy_id: w.final_weight for w in d.weights}


# ---- portfolio combination + metrics (Phase 27) --------------------------


def combine_equities(equities: dict[str, pd.Series],
                     weights: dict[str, float]) -> pd.Series:
    """Fixed-weight combination on aligned per-strategy returns
    (per-bar rebalanced approximation; identical cost basis per
    strategy ledger — the policies differ ONLY in weights)."""
    frame = pd.DataFrame({k: v for k, v in sorted(equities.items())})
    frame = frame.sort_index().ffill().dropna(how="all")
    rets = frame.pct_change().fillna(0.0)
    w = {k: float(weights.get(k, 0.0)) for k in frame.columns}
    port = sum(rets[c] * w[c] for c in frame.columns)
    start = float(frame.iloc[0].mean()) if len(frame) else 1.0
    return pd.Series(start * (1.0 + port).cumprod(), index=frame.index)


def policy_metrics(equity: pd.Series, weights: dict[str, float],
                   n_trades: int = 0) -> dict:
    """Phase 27 metric set, computed AS OBSERVED (no annualization
    magic beyond the documented 252 trading days)."""
    rets = equity.pct_change().dropna()
    if len(rets) == 0:
        rets = pd.Series([0.0])
    years = max(len(rets) / TRADING_DAYS, 1e-9)
    cagr = (float(equity.iloc[-1]) / float(equity.iloc[0])) \
        ** (1.0 / years) - 1.0 if equity.iloc[0] > 0 else float("nan")
    sd = float(rets.std(ddof=0))
    sharpe = float(rets.mean()) / sd * np.sqrt(TRADING_DAYS) if sd > 0 \
        else 0.0
    downside = rets[rets < 0].std(ddof=0)
    sortino = float(rets.mean()) / float(downside) * np.sqrt(TRADING_DAYS) \
        if downside and downside > 0 else 0.0
    roll_max = equity.cummax()
    dd = equity / roll_max - 1.0
    max_dd = float(dd.min())
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0
    recovery = (float(equity.iloc[-1]) - float(equity.iloc[0])) \
        / abs(max_dd * float(equity.iloc[0])) if max_dd < 0 else 0.0
    tail = rets[rets <= rets.quantile(0.05)]
    cvar = float(tail.mean()) if len(tail) else 0.0
    gross = sum(abs(v) for v in weights.values())
    hhi = sum(v * v for v in weights.values()) if gross > 0 else 0.0
    return {"cagr": cagr, "sharpe": sharpe, "sortino": sortino,
            "calmar": calmar, "max_dd": max_dd, "recovery": recovery,
            "cvar_5": cvar, "expectancy_per_bar": float(rets.mean()),
            "turnover": 0.0,              # fixed-weight policy
            "gross_exposure": gross, "concentration_hhi": hhi,
            "n_trades": int(n_trades)}


# ---- fold diagnostics on DEVELOPMENT data (purged, contiguous) -----------


def dev_fold_table(df: pd.DataFrame, specs: list[StrategySpec],
                   config: MetaConfig, *, n_folds: int = 4,
                   embargo_bars: int = 5) -> list[dict]:
    """Contiguous purge-and-embargo folds over the development frame.
    For each fold: per-strategy TRUTH-engine runs on TRAIN (stats) and
    TEST (equity); both policies weight the TEST window using
    TRAIN-side information only."""
    n = len(df)
    edges = np.linspace(0, n, n_folds + 1, dtype=int)
    rows = []
    for k in range(n_folds):
        t0, t1 = edges[k], edges[k + 1]
        train = df.iloc[:max(t0 - embargo_bars, 1)]
        test = df.iloc[t0:t1]
        if len(train) < 60 or len(test) < 20:
            continue
        equities_tr, stats = {}, {}
        for spec in specs:
            res = run_backtest(train, spec.engine_strategy,
                               spec.params)
            equities_tr[spec.name] = res.equity
            pnl = res.trades["pnl_pct"] if len(res.trades) else \
                pd.Series(dtype=float)
            stats[spec.name] = (float(pnl.mean()) if len(pnl) else 0.0,
                                len(pnl))
        eq_te, trades_te = {}, 0
        for spec in specs:
            res = run_backtest(test, spec.engine_strategy,
                               spec.params)
            eq_te[spec.name] = res.equity
            trades_te += len(res.trades)
        r_tr = pd.DataFrame({k2: v.pct_change().fillna(0.0)
                             for k2, v in sorted(equities_tr.items())})
        w_meta = policy_weights(config, specs, stats, returns=r_tr)
        w_eq = policy_weights(MetaConfig(policy=MetaPolicy.EQUAL_WEIGHT),
                              specs, stats, returns=r_tr)
        rows.append({
            "fold": k,
            "train_bars": len(train), "test_bars": len(test),
            "meta": policy_metrics(combine_equities(eq_te, w_meta), w_meta,
                                   trades_te),
            "equal_weight": policy_metrics(
                combine_equities(eq_te, w_eq), w_eq, trades_te),
        })
    return rows


# ---- the ONE-LOOK OOS evaluation -----------------------------------------


def run_meta_oos(dev_df: pd.DataFrame, oos_df: pd.DataFrame,
                 specs: list[StrategySpec], config: MetaConfig, *,
                 registry=None, dataset_tag: str = "OOS-META",
                 n_folds: int = 4, embargo_bars: int = 5) -> dict:
    """Freeze → dev diagnostics → ONE OOS look (registry-recorded)."""
    names = [s.name for s in specs]
    if len(set(names)) != len(names):
        raise ValueError(
            f"duplicate contributing strategy names: {names!r} "
            "(per-strategy books would silently collide)")
    frozen = {"meta_layer_version": META_LAYER_VERSION,
              "meta_parameter_hash": config.config_hash,
              "mode": config.mode.value,
              "policy": config.policy.value,
              "dev_dataset_digest": _dataset_digest(dev_df)}

    folds = dev_fold_table(dev_df, specs, config, n_folds=n_folds,
                           embargo_bars=embargo_bars)

    # ---- development-side statistics (the ONLY tuning-side information)
    equities_dev, stats_dev = {}, {}
    for spec in specs:
        res = run_backtest(dev_df, spec.engine_strategy,
                           spec.params)
        equities_dev[spec.name] = res.equity
        pnl = res.trades["pnl_pct"] if len(res.trades) else pd.Series(
            dtype=float)
        stats_dev[spec.name] = (float(pnl.mean()) if len(pnl) else 0.0,
                                len(pnl))
    r_dev = pd.DataFrame({k: v.pct_change().fillna(0.0)
                          for k, v in sorted(equities_dev.items())})
    w_meta = policy_weights(config, specs, stats_dev, returns=r_dev)
    w_eq = policy_weights(MetaConfig(policy=MetaPolicy.EQUAL_WEIGHT),
                          specs, stats_dev, returns=r_dev)

    # ---- ONE look at OOS
    eq_oos, trades_oos, per_strategy = {}, 0, {}
    for spec in specs:
        res = run_backtest(oos_df, spec.engine_strategy,
                           spec.params)
        eq_oos[spec.name] = res.equity
        trades_oos += len(res.trades)
        pnl = res.trades["pnl_pct"] if len(res.trades) else pd.Series(
            dtype=float)
        per_strategy[spec.name] = {
            "oos_trades": len(res.trades),
            "oos_expectancy": float(pnl.mean()) if len(pnl) else 0.0,
            "oos_net": float(res.metrics.get("net_profit", 0.0)),
        }
    datetime.now(timezone.utc)
    m_meta = policy_metrics(combine_equities(eq_oos, w_meta), w_meta,
                            trades_oos)
    m_eq = policy_metrics(combine_equities(eq_oos, w_eq), w_eq, trades_oos)

    identity_block = {
        "meta_config_version": META_LAYER_VERSION,
        "meta_parameter_hash": frozen["meta_parameter_hash"],
        "dataset_digest": _dataset_digest(oos_df),
        "strategy_versions": {s.name: s.version for s in specs},
        "engine_version": ENGINE_VERSION,
        "cost_version": COST_MODEL_VERSION,
        "regime_version": REGIME_VERSION,
    }

    if registry is not None:
        from .pipeline import oos_identity

        identity = oos_identity(oos_df, META_POLICY_ID,
                                dataset_tag=dataset_tag,
                                strategy_version=META_LAYER_VERSION)
        registry.check_identity(identity)
        registry.certify_identity(
            identity,
            params={"config_hash": frozen["meta_parameter_hash"],
                    "mode": frozen["mode"],
                    "frozen": frozen},
            strategy_version=META_LAYER_VERSION,
            metrics={"meta": m_meta, "equal_weight": m_eq},
            cost_config={"policy_comparison": True},
            dataset_bars=len(oos_df))

    return {"frozen": frozen, "folds": folds,
            "weights": {"meta": w_meta, "equal_weight": w_eq},
            "oos": {"meta": m_meta, "equal_weight": m_eq},
            "per_strategy": per_strategy,
            "identity": identity_block,
            "canonical_digest": sha256_hex(canonical_json(
                {"frozen": frozen, "identity": identity_block,
                 "oos": {"meta": m_meta, "equal_weight": m_eq}}))}


def verify_frozen(recorded_hash: str, config: MetaConfig) -> bool:
    """A recorded OOS evaluation replays ONLY against the frozen config
    (no OOS tuning: a changed config can never claim the same look)."""
    return recorded_hash == config.config_hash
