"""mql5bot.meta_portfolio — the canonical Meta portfolio engine
(meta-realism gate: multi-asset, shared account, explicit specs).

Strategy signals on ONE shared account across MANY symbols → Meta
decision at time t (inputs available at t only) → per-book weights →
the canonical :class:`engine.PortfolioEngine` mechanics (netting or
hedging, shared cash/equity/drawdown/heat, real fills, costs, Risk-
Engine sizing, exposure caps, shared margin basis) → PnL, attribution,
constraints → next rebalance.

Instrument identity: every context is one (symbol, strategy) book with
an EXPLICIT broker :class:`SymbolSpec` + :class:`CostConfig` + currency
conversion.  There is no generic fallback on the production path: specs
are inputs.  The legacy single-frame constructor (``MetaPortfolioEngine(df,
specs, ...)``) remains ONLY as a labelled synthetic-diagnostic path.

Causality contract: rebalance timestamps form a fixed grid; a decision
at ``t`` consumes bars strictly before ``t`` (per-book trade statistics,
correlation, the causal regime feed and the causal drift feed); runtime
state (prior allocation) carries across rebalances; research knowledge
never does; every journal entry carries ``as_of`` + regime/drift
provenance.
"""

from __future__ import annotations

import hashlib
import json
import types
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .backtest import run_backtest
from .drift_feed import DriftSnapshot, drift_snapshots
from .engine import CostConfig, Instrument, PortfolioEngine, RunConfig
from .meta_layer import MetaConfig, MetaLayer, MetaPolicy, StrategyMetaInput
from .meta_oos import StrategySpec
from .regime_feed import RegimeSnapshot, regime_snapshot

TRADING_DAYS = 252

ALL_REGIMES = ("TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL", "LOW_VOL",
               "TRANSITION", "UNKNOWN")


# ---- instrument context (Phase 2/5: explicit identity per book) ------------


@dataclass(frozen=True)
class InstrumentContext:
    """One (symbol, strategy) trading book with EXPLICIT broker context.

    ``strategy_id`` is the unique book id (attribution + allocation key).
    ``conversion`` is the profit-currency → deposit-currency rate; it is
    REQUIRED when the currencies differ — a missing conversion makes the
    context INELIGIBLE (safe failure), never a silent 1.0.
    """

    symbol: str
    strategy_id: str
    engine_strategy: str
    df: pd.DataFrame
    spec: object                     # SymbolSpec (explicit; no fallback)
    costs: CostConfig
    params: dict = field(default_factory=dict)
    corr_group: str = ""
    conversion: float | None = None
    margin_calc: object = None       # Callable[[lots], margin] (shared basis)

    @property
    def currencies_equal(self) -> bool:
        return self.spec.currency_profit == self.spec.currency_deposit

    @property
    def data_error(self) -> str:
        """Non-empty when the frame itself is unsafe for the mechanics
        (injected-failure gate: a corrupt dataset must be REFUSED at
        the context boundary — journaled INELIGIBLE — never reach the
        fills, where a NaN bar would crash the tick math)."""
        df = self.df
        missing = [c for c in ("open", "high", "low", "close")
                   if c not in df.columns]
        if missing:
            return (f"{self.strategy_id}: frame missing OHLC columns "
                    f"{missing} — refusing (never reach the fills)")
        vals = df.loc[:, ["open", "high", "low", "close"]].to_numpy(
            dtype=float)
        if not np.isfinite(vals).all():
            return (f"{self.strategy_id}: frame has non-finite OHLC "
                    "values — refusing (journaled INELIGIBLE, never "
                    "a silent NaN into the fills)")
        idx = df.index
        if not (idx.is_monotonic_increasing and not idx.has_duplicates):
            return (f"{self.strategy_id}: frame index must be "
                    "monotonically increasing and unique — refusing")
        return ""

    @property
    def conversion_error(self) -> str:
        """Non-empty when the context must be refused (conversion)."""
        if self.currencies_equal:
            return ""
        if self.conversion is None or not np.isfinite(self.conversion) \
                or self.conversion <= 0.0:
            return (f"{self.strategy_id}: profit currency "
                    f"{self.spec.currency_profit} != deposit "
                    f"{self.spec.currency_deposit} and no explicit "
                    f"conversion supplied — refusing (never fake 1.0)")
        return ""

    @property
    def profit_to_deposit(self) -> float:
        if self.currencies_equal:
            return 1.0
        return float(self.conversion)

    def stats_kwargs(self) -> dict:
        """Legacy ``run_backtest`` kwargs expressing THIS context's
        spec/cost surface for the as-of statistics runs (the portfolio
        run itself injects the full SymbolSpec object)."""
        return {
            "point": float(self.spec.point),
            "contract_size": float(self.spec.contract_size),
            "spread_points": float(self.costs.spread_points),
            "slippage_points": float(self.costs.slippage_points),
            "commission_per_lot": float(self.costs.commission_per_lot),
            "commission_min": float(self.costs.commission_min),
            "swap_long_per_lot_day":
                float(self.costs.swap_long_per_lot_day),
            "swap_short_per_lot_day":
                float(self.costs.swap_short_per_lot_day),
            "max_gap_fraction": float(self.costs.max_gap_fraction)
            if np.isfinite(self.costs.max_gap_fraction) else 1e9,
        }


def contexts_from_specs(df: pd.DataFrame, specs: list[StrategySpec], *,
                        instrument: dict | None = None,
                        label: str = "SYNTH") -> list[InstrumentContext]:
    """SYNTHETIC-DIAGNOSTIC path: one shared frame, one generic spec.
    Kept for diagnostics only — never for production validation."""
    instrument = dict(instrument or {})
    point = float(instrument.get("point", 1e-5))
    contract = float(instrument.get("contract_size", 100_000.0))
    spec = __import__("mql5bot.symbolspec", fromlist=["SymbolSpec"]) \
        .SymbolSpec(name=label, point=point, tick_size=point,
                    tick_value_loss=point * contract,
                    contract_size=contract,
                    currency_profit="USD", currency_deposit="USD")
    costs = CostConfig(symbol=label, **{
        k: v for k, v in instrument.items()
        if k in CostConfig.__dataclass_fields__})
    out = []
    for s in sorted(specs, key=lambda s: s.name):
        out.append(InstrumentContext(
            symbol=label, strategy_id=s.name,
            engine_strategy=s.engine_strategy or s.name, df=df, spec=spec,
            costs=costs, params=dict(s.params)))
    return out


# ---- as-of statistics (strictly exclusive: index < t) ----------------------


def _context_stats(ctx: InstrumentContext, as_of: pd.Timestamp
                   ) -> tuple[tuple[float, int], pd.Series]:
    window = ctx.df.loc[ctx.df.index < as_of]
    res = run_backtest(window, ctx.engine_strategy, ctx.params,
                       **ctx.stats_kwargs())
    pnl = res.trades["pnl_pct"] if len(res.trades) else \
        pd.Series(dtype=float)
    stats = (float(pnl.mean()) if len(pnl) else 0.0, len(pnl))
    return stats, res.equity.pct_change().fillna(0.0)


def as_of_stats_exclusive(df: pd.DataFrame, specs: list[StrategySpec],
                          as_of: pd.Timestamp,
                          instrument: dict | None = None
                          ) -> tuple[dict, pd.DataFrame]:
    """Legacy single-frame as-of statistics (diagnostic path)."""
    ctxs = contexts_from_specs(df, specs, instrument=instrument)
    stats, rets = as_of_stats_contexts(ctxs, as_of)
    return stats, pd.DataFrame(rets)


def as_of_stats_contexts(contexts: list[InstrumentContext],
                         as_of: pd.Timestamp
                         ) -> tuple[dict, dict[str, pd.Series]]:
    stats: dict[str, tuple[float, int]] = {}
    rets: dict[str, pd.Series] = {}
    for ctx in sorted(contexts, key=lambda c: c.strategy_id):
        s, r = _context_stats(ctx, as_of)
        stats[ctx.strategy_id] = s
        rets[ctx.strategy_id] = r
    return stats, rets


# ---- rebalance grid ---------------------------------------------------------


def rebalance_grid(index: pd.DatetimeIndex, *, first_bar: int,
                   every_days: int = 1) -> list[pd.Timestamp]:
    out: list[pd.Timestamp] = []
    days = sorted({ts.date() for ts in index[first_bar:]})
    for d in days[::max(1, every_days)]:
        for ts in index[first_bar:]:
            if ts.date() == d:
                out.append(ts)
                break
    return out


# ---- immutable decision snapshot (Phase 2 of the production gate) ----------


@dataclass(frozen=True)
class MetaSnapshot:
    """Everything a decision at ``as_of`` may consume — and nothing else.

    Frozen; stats mapping and returns/specs containers are defensively
    copied at construction; regime and drift snapshots are frozen
    dataclasses computed from pre-``as_of`` information only.
    """

    as_of: pd.Timestamp
    stats: dict
    returns: pd.DataFrame
    contexts: tuple
    regimes: dict            # symbol -> RegimeSnapshot
    drift: dict              # strategy_id -> DriftSnapshot

    def __post_init__(self):
        object.__setattr__(self, "as_of", pd.Timestamp(self.as_of))
        object.__setattr__(self, "stats",
                           types.MappingProxyType(dict(self.stats)))
        object.__setattr__(self, "returns", self.returns.copy(deep=True))
        object.__setattr__(self, "contexts", tuple(self.contexts))
        object.__setattr__(self, "regimes", types.MappingProxyType(
            dict(self.regimes)))
        object.__setattr__(self, "drift", types.MappingProxyType(
            dict(self.drift)))


# ---- results -----------------------------------------------------------------


@dataclass
class PolicyRun:
    policy: str
    equity: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    events: list = field(default_factory=list)
    weights: list[dict] = field(default_factory=list)   # decision journal
    metrics: dict = field(default_factory=dict)
    attribution: pd.DataFrame = field(
        default_factory=pd.DataFrame)                   # per-book PnL
    attribution_symbol: pd.DataFrame = field(
        default_factory=pd.DataFrame)                   # per-symbol PnL
    attribution_strategy: pd.DataFrame = field(
        default_factory=pd.DataFrame)                   # per-strategy PnL


@dataclass
class MetaPortfolioResult:
    meta: PolicyRun
    equal_weight: PolicyRun
    rebalance_dates: list = field(default_factory=list)
    comparison: dict = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)
    ineligible: list = field(default_factory=list)


# ---- the engine --------------------------------------------------------------


class MetaPortfolioEngine:
    """Multi-asset META vs EQUAL_WEIGHT portfolios with identical
    mechanics: one shared account, per-symbol explicit specs, causal
    regime/drift/correlation feeds, per-book attribution."""

    def __init__(self, df: pd.DataFrame | None = None,
                 specs: list[StrategySpec] | None = None, *,
                 contexts: list[InstrumentContext] | None = None,
                 config: MetaConfig | None = None,
                 instrument: dict | None = None,
                 mode: str = "netting",
                 initial_capital: float = 10_000.0,
                 risk_percent: float = 1.0,
                 every_days: int = 1,
                 min_history_bars: int = 250,
                 label: str = "SYNTH",
                 initial_weights: dict[str, float] | None = None,
                 certified: set[str] | None = None,
                 seed: int = 0):
        if contexts is None:
            if df is None or specs is None:
                raise ValueError("provide contexts (canonical) or "
                                 "df+specs (synthetic diagnostic)")
            contexts = contexts_from_specs(df, specs,
                                           instrument=instrument,
                                           label=label)
        self.config = config or MetaConfig()
        self.mode = mode
        self.initial_capital = initial_capital
        self.risk_percent = risk_percent
        self.every_days = every_days
        self.min_history = min_history_bars
        self.initial_weights = dict(initial_weights or {})
        self.certified = certified
        self.seed = int(seed)
        # eligibility: conversion safety first (never fake 1.0)
        self.ineligible: list[dict] = []
        eligible: list[InstrumentContext] = []
        seen: set[tuple[str, str]] = set()
        for ctx in contexts:
            err = ctx.data_error or ctx.conversion_error
            if err:
                self.ineligible.append({"strategy_id": ctx.strategy_id,
                                        "symbol": ctx.symbol,
                                        "reason": err})
                continue
            key = (ctx.symbol, ctx.strategy_id)
            if key in seen:
                self.ineligible.append({"strategy_id": ctx.strategy_id,
                                        "symbol": ctx.symbol,
                                        "reason": "duplicate (symbol, "
                                                  "strategy) line"})
                continue
            seen.add(key)
            eligible.append(ctx)
        self.contexts = sorted(eligible, key=lambda c: c.strategy_id)
        if not self.contexts:
            raise ValueError("no eligible instrument contexts")
        first_index = self.contexts[0].df.index
        for ctx in self.contexts:
            if not ctx.df.index.equals(first_index):
                raise ValueError(
                    f"{ctx.strategy_id}: index not aligned with the other "
                    "contexts (one shared DatetimeIndex is required)")
        line_ids = [(c.symbol, c.engine_strategy) for c in self.contexts]
        dupes = {sym for sym in line_ids if line_ids.count(sym) > 1}
        if dupes:
            raise ValueError(
                "duplicate (symbol, engine_strategy) execution lines: "
                f"{sorted(dupes)} — one book per registry strategy per "
                "symbol (the execution seam's line identity); give the "
                "books distinct engine strategies")
        self.df = self.contexts[0].df          # shared clock reference
        self.rebalances = rebalance_grid(first_index,
                                         first_bar=min_history_bars,
                                         every_days=every_days)

    # -- decisions ---------------------------------------------------------

    def snapshot(self, t: pd.Timestamp) -> MetaSnapshot:
        """The immutable input snapshot for a decision at ``t``:
        pre-``t`` statistics, causal regime labels per symbol, causal
        drift per book."""
        stats, rets = as_of_stats_contexts(self.contexts, t)
        regimes = {c.symbol: regime_snapshot(c.df["close"], t)
                   for c in self.contexts}
        closed = {c.strategy_id: _closed_trades(c, t)
                  for c in self.contexts}
        drift = drift_snapshots(
            closed, t,
            regimes={c.strategy_id: regimes[c.symbol].label
                     for c in self.contexts})
        return MetaSnapshot(as_of=t, stats=stats,
                            returns=pd.DataFrame(rets),
                            contexts=tuple(self.contexts),
                            regimes=regimes, drift=drift)

    def decide_weights(self, t: pd.Timestamp, policy: MetaPolicy,
                       layer: MetaLayer) -> tuple[dict[str, float], dict]:
        """Causal weights at ``t`` from the immutable snapshot."""
        snap = self.snapshot(t)
        inputs = _context_inputs(list(snap.contexts), self.certified,
                                 snap.regimes, snap.drift)
        corr = snap.returns if policy is MetaPolicy.META \
            and not snap.returns.empty else None
        d = layer.decide(inputs, as_of=snap.as_of.to_pydatetime(),
                         returns=corr,
                         oos_stats=dict(snap.stats))
        w = {x.strategy_id: x.final_weight for x in d.weights}
        journal = {"as_of": str(t), "policy": policy.value,
                   "n_trades_prior": {k: v[1]
                                      for k, v in snap.stats.items()},
                   "regimes": {sym: rs.journal()
                               for sym, rs in sorted(snap.regimes.items())},
                   "drift": {sid: ds.journal() for sid, ds
                             in sorted(snap.drift.items())},
                   **{f"w::{k}": v for k, v in sorted(w.items())}}
        return w, journal

    def _schedules(self, weights_seq: list[tuple[pd.Timestamp, dict]]
                   ) -> dict[str, tuple]:
        sched: dict[str, list] = {c.strategy_id: [] for c in self.contexts}
        for t, w in weights_seq:
            for c in self.contexts:
                sched[c.strategy_id].append(
                    (t, float(w.get(c.strategy_id, 0.0))))
        return {k: tuple(v) for k, v in sched.items()}

    # -- the run -----------------------------------------------------------

    def run_policy(self, policy: MetaPolicy,
                   layer: MetaLayer) -> PolicyRun:
        weights_seq: list[tuple[pd.Timestamp, dict]] = []
        journals: list[dict] = []
        for t in self.rebalances:
            w, journal = self.decide_weights(t, policy, layer)
            weights_seq.append((t, w))
            journals.append(journal)
        sched = self._schedules(weights_seq)
        instruments = [
            Instrument(symbol=c.symbol, strategy=c.engine_strategy, df=c.df,
                       costs=c.costs, spec=c.spec,
                       profit_to_deposit=c.profit_to_deposit,
                       corr_group=c.corr_group, params=dict(c.params),
                       margin_calc=c.margin_calc,
                       allocation_schedule=sched[c.strategy_id])
            for c in self.contexts]
        cfg = RunConfig(initial_capital=self.initial_capital,
                        mode=self.mode,
                        risk_value=self.risk_percent,
                        warmup_bars=self.min_history)
        res = PortfolioEngine(cfg).run(instruments)
        run = PolicyRun(policy=policy.value, equity=res.equity,
                        trades=res.trades, events=res.events,
                        weights=journals)
        run.metrics = self._metrics(run)
        run.attribution = self._attribution(run, ["symbol", "strategy"])
        run.attribution_symbol = self._attribution(run, "symbol")
        run.attribution_strategy = self._attribution(run, "strategy")
        return run

    # -- metrics / attribution ----------------------------------------------

    def _metrics(self, run: PolicyRun) -> dict:
        """Full canonical report via :func:`metrics.compute_metrics`
        (net, CAGR, Sharpe, Sortino, Calmar, maxDD, DD duration, PF,
        expectancy, recovery, CVaR, exposure, turnover, concentration),
        plus realized cross-book correlation."""
        from .metrics import compute_metrics
        idx = run.equity.index
        if len(idx) > 2:
            step = float(np.median(np.diff(idx.values)
                                   .astype("timedelta64[s]")
                                   .astype(float)))
            ppy = 365 * 24 * 3600 / step if step > 0 else 24 * TRADING_DAYS
        else:
            ppy = 24 * TRADING_DAYS
        m = compute_metrics(run.equity, run.trades, periods_per_year=ppy)
        m["n_trades"] = len(run.trades)
        m["realized_corr_mean"] = _realized_corr(run.trades)
        return m

    @staticmethod
    def _attribution(run: PolicyRun, key) -> pd.DataFrame:
        keys = [key] if isinstance(key, str) else list(key)
        if not len(run.trades):
            return pd.DataFrame(columns=[*keys, "pnl", "trades"])
        g = run.trades.groupby(keys)["pnl"].agg(["sum", "count"])
        g.columns = ["pnl", "trades"]
        return g.reset_index().sort_values(keys)

    # -- layers --------------------------------------------------------------

    def meta_layer(self) -> MetaLayer:
        """The META layer for this engine (public so tests/replay can
        drive single decisions through the identical path)."""
        return MetaLayer(self.config,
                         state=None if not self.initial_weights
                         else self._seeded_state())

    def run(self) -> MetaPortfolioResult:
        meta_layer = self.meta_layer()
        ew_layer = MetaLayer(_ew_config(self.config))
        meta = self.run_policy(MetaPolicy.META, meta_layer)
        ew = self.run_policy(MetaPolicy.EQUAL_WEIGHT, ew_layer)
        out = MetaPortfolioResult(meta=meta, equal_weight=ew,
                                  rebalance_dates=self.rebalances,
                                  ineligible=list(self.ineligible))
        out.comparison = compare_policies(meta, ew)
        out.manifest = self.manifest()
        return out

    def _seeded_state(self):
        from .meta_layer import MetaState
        return MetaState(config_hash=self.config.config_hash,
                         weights=dict(self.initial_weights))

    # -- research manifest (Phase 26) ----------------------------------------

    def manifest(self) -> dict:
        """Complete semantic identity of a replay: git commit, dataset
        and instrument digests, all feed/engine/cost versions, meta
        config hash, seed, rebalance-schedule hash, certification
        protocol."""
        from .data_layer import content_digest
        from .drift_feed import DRIFT_VERSION
        from .meta_layer import CONTRACT_VERSION, META_LAYER_VERSION
        from .regime_feed import REGIME_VERSION
        from .versions import (
            CERTIFICATION_PROTOCOL_VERSION,
            COST_MODEL_VERSION,
            ENGINE_VERSION,
            git_commit,
        )
        sched_hash = hashlib.sha256(json.dumps(
            [str(t) for t in self.rebalances]).encode()).hexdigest()
        return {
            "git_commit": git_commit(),
            "engine_version": ENGINE_VERSION,
            "cost_version": COST_MODEL_VERSION,
            "meta_version": META_LAYER_VERSION,
            "contract_version": CONTRACT_VERSION,
            "regime_version": REGIME_VERSION,
            "drift_version": DRIFT_VERSION,
            "certification_protocol": CERTIFICATION_PROTOCOL_VERSION,
            "config_hash": self.config.config_hash,
            "random_seed": self.seed,
            "rebalance_schedule_hash": sched_hash,
            "mode": self.mode,
            "initial_capital": self.initial_capital,
            "risk_percent": self.risk_percent,
            "every_days": self.every_days,
            "min_history_bars": self.min_history,
            "instruments": [
                {"strategy_id": c.strategy_id, "symbol": c.symbol,
                 "dataset_sha256": content_digest(
                     c.df.loc[:, ["open", "high", "low", "close"]]),
                 "spec": {"point": c.spec.point,
                          "tick_size": c.spec.tick_size,
                          "tick_value_loss": c.spec.tick_value_loss,
                          "contract_size": c.spec.contract_size,
                          "volume_min": c.spec.volume_min,
                          "volume_max": c.spec.volume_max,
                          "volume_step": c.spec.volume_step,
                          "stops_level_points": c.spec.stops_level_points,
                          "currency_profit": c.spec.currency_profit,
                          "currency_deposit": c.spec.currency_deposit},
                 "conversion": c.profit_to_deposit}
                for c in self.contexts],
            "ineligible": list(self.ineligible),
        }


def _closed_trades(ctx: InstrumentContext, as_of: pd.Timestamp
                   ) -> pd.DataFrame:
    """The book's closed-trade ledger strictly before ``as_of`` (causal
    drift input).  Runs the context over its own pre-``as_of`` window."""
    window = ctx.df.loc[ctx.df.index < as_of]
    res = run_backtest(window, ctx.engine_strategy, ctx.params,
                       **ctx.stats_kwargs())
    if len(res.trades):
        keep = ["exit_time", "pnl_pct", "bars_held"]
        return res.trades[keep].reset_index(drop=True)
    return res.trades


def _context_inputs(contexts: list[InstrumentContext],
                    certified: set[str] | None,
                    regimes: dict[str, RegimeSnapshot],
                    drift: dict[str, DriftSnapshot]
                    ) -> list[StrategyMetaInput]:
    """Per-book Meta inputs: causal regime label per symbol, causal
    drift per book, certification under test (``certified``); allowed =
    every label, preferred = current label, forbidden = ∅ (the regime
    engine drives the input — never a hand-picked constant)."""
    out = []
    for c in sorted(contexts, key=lambda c: c.strategy_id):
        label = regimes[c.symbol].label
        ds = drift.get(c.strategy_id)
        state = "VERIFIED" if certified is None or \
            c.strategy_id in certified else "UNCERTIFIED"
        out.append(StrategyMetaInput(
            c.strategy_id, c.symbol, 0, label,
            frozenset(ALL_REGIMES), frozenset({label}),
            frozenset(), state,
            drift_available=ds.available if ds else False,
            drift_score=ds.overall_score if ds and ds.available else None,
            strategy_version=c.engine_strategy))
    return out


def _ew_config(config: MetaConfig) -> MetaConfig:
    return MetaConfig(policy=MetaPolicy.EQUAL_WEIGHT,
                      mode=config.mode,
                      vote_threshold=config.vote_threshold,
                      max_strategy_weight=config.max_strategy_weight,
                      gross_exposure_cap=config.gross_exposure_cap,
                      max_weight_change=config.max_weight_change,
                      max_positions=config.max_positions)


def _realized_corr(trades: pd.DataFrame) -> float:
    """Mean pairwise realized correlation across BOOKS
    (symbol, strategy) — same-strategy cross-asset, cross-strategy
    same-asset and cross-strategy cross-asset pairs all contribute."""
    if not len(trades):
        return float("nan")
    t = trades.assign(book=trades["symbol"] + "@" + trades["strategy"])
    if t["book"].nunique() < 2:
        return float("nan")
    piv = t.assign(day=pd.to_datetime(t["exit_time"]).dt.date) \
        .pivot_table(index="day", columns="book", values="pnl",
                     aggfunc="sum").fillna(0.0)
    corr = piv.corr().to_numpy()
    mask = ~np.eye(len(corr), dtype=bool)
    return float(np.nanmean(corr[mask])) if mask.any() else float("nan")


# ---- statistical comparison -------------------------------------------------


def compare_policies(meta: PolicyRun, ew: PolicyRun) -> dict:
    from .meta_replay import block_bootstrap_sharpe_diff, probabilistic_sharpe
    mr, er = meta.equity, ew.equity   # both helpers pct_change() internally
    out: dict = {"net_meta": float(meta.metrics.get("net_profit", 0.0)),
                 "net_ew": float(ew.metrics.get("net_profit", 0.0)),
                 "sharpe_meta": float(meta.metrics.get("sharpe", 0.0)),
                 "sharpe_ew": float(ew.metrics.get("sharpe", 0.0)),
                 "maxdd_meta": float(meta.metrics.get("max_drawdown_pct",
                                                      0.0) or 0.0),
                 "maxdd_ew": float(ew.metrics.get("max_drawdown_pct",
                                                  0.0) or 0.0),
                 "trades_meta": int(meta.metrics.get("n_trades", 0)),
                 "trades_ew": int(ew.metrics.get("n_trades", 0))}
    if len(mr) > 30 and len(er) > 30:
        try:
            out["bootstrap"] = block_bootstrap_sharpe_diff(mr, er)
            out["psr_meta_gt_ew"] = probabilistic_sharpe(mr, er)
        except Exception:  # noqa: BLE001 — never fake significance
            out["bootstrap"] = None
    return out


def main(days: int = 365, seed: int = 5) -> int:
    from .data import generate_ohlc
    df = generate_ohlc(days=days, seed=seed)
    specs = [StrategySpec("bollinger_reversal", {}),
             StrategySpec("ema_crossover", {"fast": 10, "slow": 50}),
             StrategySpec("macd_momentum", {})]
    eng = MetaPortfolioEngine(df, specs, min_history_bars=480,
                              every_days=2, label="SYNTH")
    res = eng.run()
    for run, name in ((res.meta, "META"), (res.equal_weight, "EQUAL_WEIGHT")):
        print(f"{name}: net={run.metrics['net_profit']:.2f} "
              f"sharpe={run.metrics['sharpe']:.3f} "
              f"trades={run.metrics['n_trades']}")
    print("comparison:", {k: v for k, v in res.comparison.items()
                          if k in ("net_meta", "net_ew", "psr_meta_gt_ew")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
