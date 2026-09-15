"""mql5bot.certify — real-tick certification protocol (plan Phase F).

The only path that may call a result VERIFIED: a ladder of data grades
on the SAME EA and SAME terminal, regime by regime:

    M1 OHLC  (tester model 1)  ->  Every tick (model 0)
        ->  Every tick based on real ticks (model 3)  ->  Real ticks (model 4)

plus a canonical Python TRUTH-engine M1-OHLC leg as an independent
cross-check of the same (strategy, params) manifest binding.

Protocol gates and reports (all explicit, nothing guessed):

* 100-trade minimum per regime leg and for the aggregate;
* a spread-floor report (modelled average spread vs the configured
  floor, in pips);
* slippage surcharge tiers of 0.5-3.0 pips applied analytically to the
  canonical leg (per-side, tick-valued via the canonical leg_cash
  convention) and reported per tier;
* the OHLC-vs-tick DEGRADATION of every tick-grade leg against its own
  M1-OHLC baseline, per regime, with the expected 30-50% band stated —
  a finding that is reported explicitly, never hidden;
* a final verdict that is VERIFIED only when every required leg ran and
  every gate passed, and NOT VERIFIED otherwise — without an MT5
  terminal host the tester legs cannot run and the verdict is
  NOT VERIFIED with the reason printed.  Backtests are research
  evidence, not a promise of live profit (see README).

The MT5 leg is executed through a runner callable (``mt5tester.run_*``
on a Windows terminal host); the core protocol is pure and fully
tested here without a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .mt5tester import MT5_MODEL_LABELS, ReportData, TesterConfig

# Regime sample windows (documented; EURUSD-anchored, any symbol works).
#   bear_2022   — 2022 H1: the Fed-hike bear trend
#   crash_2020  — the COVID crash and its whipsaw recovery
#   trend_2021  — 2021 H1 sustained trend
#   range_2023  — 2023 H1 choppy range
REGIMES: tuple[tuple[str, str, str], ...] = (
    ("bear_2022", "2022.01.01", "2022.06.30"),
    ("crash_2020", "2020.02.20", "2020.04.30"),
    ("trend_2021", "2021.01.01", "2021.06.30"),
    ("range_2023", "2023.01.01", "2023.06.30"),
)

# tester model ladder: 1 = 1 minute OHLC, 0 = every tick,
# 3 = every tick based on real ticks, 4 = real ticks
MODEL_LADDER: tuple[int, ...] = (1, 0, 3, 4)

# Execution-surface contract (FINAL REALITY-GATE §13): the MQL5 EA
# executes exactly the strategy ids of its five-member enum
# (mql5/Include/Mql5Bot/Config.mqh -> ENUM_MQL5BOT_STRATEGY, mapped by
# StrategyIdFromEnum).  The MQL5 tree contains NO DSL/JSON strategy
# interpreter, so any other id is NOT_EXECUTABLE — fail closed, never
# approximated/substituted onto a built-in (docs/CERTIFICATION.md
# §Certification scope surfaces).  Pinned by tests/test_docs_contract.py.
MQL5_EXECUTABLE_STRATEGIES: frozenset[str] = frozenset({
    "ema_crossover",
    "rsi_reversal",
    "donchian_breakout",
    "bollinger_reversal",
    "macd_momentum",
})

EXECUTABLE = "EXECUTABLE"
NOT_EXECUTABLE = "NOT_EXECUTABLE"


def mql5_execution_status(strategy_id: str) -> str:
    """Fail-closed executability of a strategy id on the MQL5 surface."""
    return (EXECUTABLE if strategy_id in MQL5_EXECUTABLE_STRATEGIES
            else NOT_EXECUTABLE)

# expected OHLC-vs-tick degradation band (percent), reported per leg
DEGRADATION_BAND_PCT: tuple[float, float] = (30.0, 50.0)

# canonical synonym map: report keys -> leg metrics keys
_KEY_SYNONYMS = {
    # canonical python metric -> mt5tester ReportData metric keys
    "net_profit": ("net_profit", "total_net_profit"),
    "trades": ("trades", "total_trades"),
    "profit_factor": ("profit_factor",),
    "avg_spread_pips": ("avg_spread_pips",),
}


@dataclass(frozen=True)
class CertifyConfig:
    """One certification: an EA (with inputs) x symbol x model ladder."""

    strategy: str
    ea: str = "Experts\\Mql5Bot\\Mql5Bot.ex5"
    params: dict = field(default_factory=dict)   # canonical python params
    ea_inputs: dict = field(default_factory=dict)  # EA .set input overrides
    symbol: str = "EURUSD"
    timeframe: str = "H1"
    deposit: float = 10_000.0
    currency: str = "USD"
    leverage: int = 100
    slippage_tiers_pips: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0)
    spread_floor_pips: float = 0.0
    min_trades: int = 100
    point: float = 1e-5
    contract_size: float = 100_000.0
    degradation_band_pct: tuple[float, float] = DEGRADATION_BAND_PCT
    manifest_id: str = ""  # binding: the S5-certified manifest, when given


def tester_plan(cfg: CertifyConfig) -> list[TesterConfig]:
    """One validated tester config per (regime, model-ladder grade)."""
    plan: list[TesterConfig] = []
    for name, date_from, date_to in REGIMES:
        for model in MODEL_LADDER:
            tc = TesterConfig(
                ea=cfg.ea,
                symbol=cfg.symbol,
                timeframe=cfg.timeframe,
                model=model,
                date_from=date_from,
                date_to=date_to,
                deposit=cfg.deposit,
                currency=cfg.currency,
                leverage=cfg.leverage,
                inputs=dict(cfg.ea_inputs),
                report_name=f"certify_{cfg.strategy}_{name}_{model}",
            )
            tc.validate()
            plan.append(tc)
    return plan


# ---------------------------------------------------------------------------
# Pure gates and reports
# ---------------------------------------------------------------------------


def slippage_surcharge_pnl(trades, pips: float, point: float,
                           contract_size: float) -> tuple[float, float]:
    """Worst-case round-trip slippage surcharge on a canonical trade
    frame: ``pips * point * contract * lots`` per side, both sides.

    Returns (surcharge_cash, mean_per_trade).  The canonical OHLC leg
    models explicit slippage already; this is the ANALYTICAL cushion
    tier applied on top for the report (0.5-3.0 pips).
    """
    if pips < 0.0:
        raise ValueError("pips must be >= 0")
    if trades is None or len(trades) == 0:
        return 0.0, 0.0
    lots = np.asarray(trades["lots"], dtype=float)
    per_side = float(pips) * point * contract_size
    total = float(2.0 * per_side * lots.sum())
    mean = total / len(lots) if len(lots) else 0.0
    return total, mean


def _metric(metrics: dict, key: str):
    """Resolve a metric through the synonym map (case-insensitive)."""
    key_l = key.lower()
    for canonical, synonyms in _KEY_SYNONYMS.items():
        names = synonyms + (canonical,)
        if key_l not in (n.lower() for n in names):
            continue
        for name in names:
            if name in metrics and metrics[name] is not None:
                return float(metrics[name])
        return None
    value = metrics.get(key)
    return float(value) if value is not None else None


def degradation_report(base_metrics: dict, leg_metrics: dict,
                       keys: tuple[str, ...] = ("net_profit",),
                       band_pct: tuple[float, float] = DEGRADATION_BAND_PCT,
                       ) -> dict:
    """OHLC-vs-tick degradation of ``leg_metrics`` vs ``base_metrics``.

    Degradation is the relative fall of the leg metric against the
    baseline, in percent (negative values mean the leg is worse):
    ``(leg - base) / |base| * 100``.  The expected 30-50% band from the
    protocol is reported as ``band`` and every key gets an explicit
    ``inside_band`` flag — a finding, reported, never hidden.  When the
    baseline is not a positive number the degradation is undefined and
    reported as ``None`` (a loss-making baseline makes ratios
    meaningless).
    """
    out: dict = {"band_pct": list(band_pct)}
    for key in keys:
        base = _metric(base_metrics, key)
        leg = _metric(leg_metrics, key)
        entry: dict = {"base": base, "leg": leg}
        if base is not None and leg is not None and base > 0.0:
            deg = (leg - base) / abs(base) * 100.0
            lo, hi = band_pct
            # the 30-50% band only describes degradation (deg < 0);
            # improvements are reported but are not "inside the band"
            entry.update({
                "degradation_pct": float(deg),
                "degraded": deg < 0.0,
                "inside_band": bool(-hi <= deg <= -lo) if deg < 0.0
                else False,
            })
        else:
            entry.update({"degradation_pct": None,
                          "degraded": None, "inside_band": None})
        out[key] = entry
    return out


def trade_gate(n_trades: int, minimum: int = 100) -> dict:
    """100-trade minimum gate (per leg and aggregate)."""
    return {"n_trades": int(n_trades), "minimum": int(minimum),
            "ok": bool(n_trades >= minimum)}


def spread_floor_report(avg_spread_pips: float | None,
                        floor_pips: float) -> dict:
    """Spread-floor report: the modelled average spread (pips) vs the
    configured floor.  ``None`` average (not modelled/reported) fails
    the floor check loudly — floors are never assumed."""
    if avg_spread_pips is None:
        return {"avg_spread_pips": None, "floor_pips": floor_pips,
                "ok": False,
                "reason": "average spread not reported — cannot verify "
                          "the floor"}
    return {"avg_spread_pips": float(avg_spread_pips),
            "floor_pips": float(floor_pips),
            "ok": bool(avg_spread_pips >= floor_pips)}


# ---------------------------------------------------------------------------
# Orchestration and verdict
# ---------------------------------------------------------------------------

VERIFIED = "VERIFIED"
NOT_VERIFIED = "NOT VERIFIED"


def verdict_for(legs: list[dict], *, min_trades: int = 100) -> dict:
    """Final verdict.  VERIFIED only when every REQUIRED leg ran ok and
    every gate passed; otherwise NOT VERIFIED with every reason listed.
    Nothing is ever guessed: unavailable legs make the verdict
    NOT VERIFIED.  Non-required legs (the python cross-check) are
    recorded but never gate the verdict."""
    reasons: list[str] = []
    required = [leg for leg in legs if leg["required"]]
    if not required:
        reasons.append("no required legs configured")
    for leg in required:
        tag = f"{leg['regime']}:{MT5_MODEL_LABELS.get(leg['model'], '?')}"
        if not leg["ran"]:
            reasons.append(f"{tag} did not run "
                           f"({leg['error'] or 'no runner'})")
            continue
        if not leg["ok"]:
            reasons.append(f"{tag} failed")
        gate = trade_gate(int(leg.get("trades", 0) or 0), min_trades)
        if not gate["ok"]:
            reasons.append(f"{tag} under the {min_trades}-trade minimum "
                           f"({int(gate['n_trades'])})")
        spread = leg.get("spread_floor")
        if spread is not None and not spread["ok"]:
            reasons.append(f"{tag} spread floor not met: "
                           f"{spread.get('reason') or spread}")
    status = VERIFIED if not reasons else NOT_VERIFIED
    return {"status": status, "reasons": reasons}


def run_certification(cfg: CertifyConfig, *, run_tester=None,
                      python_data=None,
                      runner_note: str = "",
                      reconciliation_ok: bool | None = None) -> dict:
    """Run the certification protocol.

    ``python_data`` — DataFrame for the canonical Python TRUTH M1-OHLC
    leg (pure, always run when provided).
    ``run_tester(tester_config) -> mt5tester.RunOutcome`` — the MT5
    terminal runner; when None (or raising) every tester leg is
    recorded as not run, and the verdict is NOT VERIFIED with the
    reason.  Tester legs are required; the Python leg is a cross-check.
    ``reconciliation_ok`` — fail-closed evidence of canonical step 8
    (Python↔MT5 reconciliation recorded and complete).  ``None`` =
    not recorded, ``False`` = recorded-incomplete; in either case a
    would-be ``VERIFIED`` verdict is WITHHELD — an empirical ladder
    pass without reconciliation is never a certification (mission:
    100 trades without reconciliation cannot become VERIFIED).
    """
    legs: list[dict] = []
    execution_surface = mql5_execution_status(cfg.strategy)
    report: dict = {
        "strategy": cfg.strategy,
        "ea": cfg.ea,
        "mql5_execution": execution_surface,
        "reconciliation_recorded": reconciliation_ok,
        "symbol": cfg.symbol,
        "timeframe": cfg.timeframe,
        "manifest_id": cfg.manifest_id,
        "spread_floor_pips": cfg.spread_floor_pips,
        "min_trades": cfg.min_trades,
        "degradation_band_pct": list(cfg.degradation_band_pct),
        "slippage_tiers_pips": list(cfg.slippage_tiers_pips),
        "legs": legs,
        "runner_note": runner_note,
    }

    # --- canonical Python TRUTH M1-OHLC leg (cross-check) -----------------
    if python_data is not None:
        from .backtest import run_backtest
        from .strategies import default_params

        params = default_params(cfg.strategy)
        params.update(cfg.params)
        res = run_backtest(python_data, cfg.strategy, params,
                           risk_percent=float(
                               cfg.ea_inputs.get("risk_percent", 1.0)))
        leg: dict = {
            "engine": "truth-python-m1-ohlc", "regime": "all",
            "model": 1, "ran": True, "ok": True, "required": False,
            "error": "", "metrics": dict(res.metrics),
            "trades": int(res.metrics.get("trades", 0)),
        }
        surcharges = []
        for pips in cfg.slippage_tiers_pips:
            total, mean = slippage_surcharge_pnl(res.trades, pips,
                                                 cfg.point,
                                                 cfg.contract_size)
            surcharges.append({"pips": float(pips),
                               "surcharge_cash": round(total, 2),
                               "mean_per_trade": round(mean, 4)})
        leg["slippage_surcharge"] = surcharges
        legs.append(leg)

    # --- MT5 tester legs (regime x model ladder) ---------------------------
    for tc in tester_plan(cfg):
        name = next(r for r in REGIMES
                    if r[1] == tc.date_from and r[2] == tc.date_to)[0]
        outcome = None
        error = ""
        ran = ok = False
        if execution_surface != EXECUTABLE:
            # fail closed BEFORE any runner is invoked: a strategy that
            # is not one of the five built-in engines has no MQL5
            # execution path and can never become MT5-validated.
            error = (f"{execution_surface}: {cfg.strategy!r} is not part "
                     "of the MQL5 execution surface (five built-in "
                     "engines only; no DSL interpreter exists)")
        elif run_tester is None:
            error = "no MT5 runner provided (certification runs on a " \
                    "Windows terminal host)"
        else:
            try:
                outcome = run_tester(tc)
                ran = True
                ok = bool(outcome.ok)
                if not ok:
                    error = outcome.error
            except Exception as exc:  # noqa: BLE001 — boundary: report any
                # terminal failure honestly; the verdict stays NOT
                # VERIFIED with the reason
                error = f"{type(exc).__name__}: {exc}"
        metrics: dict = {}
        if outcome is not None and outcome.report is not None:
            metrics = _report_metrics(outcome.report)
        legs.append({
            "engine": f"mt5-{MT5_MODEL_LABELS.get(tc.model, tc.model)}",
            "regime": name, "model": tc.model, "ran": ran, "ok": ok,
            "required": True, "error": error,
            "date_from": tc.date_from, "date_to": tc.date_to,
            "metrics": metrics,
            "trades": int(metrics.get("trades", 0) or 0),
            "spread_floor": spread_floor_report(
                _metric(metrics, "avg_spread_pips") if metrics else None,
                cfg.spread_floor_pips) if cfg.spread_floor_pips > 0.0
            else None,
        })

    # --- degradation table: tick grades vs their own M1-OHLC baseline ------
    degradation: list[dict] = []
    for name, _, _ in REGIMES:
        base = next((leg for leg in legs
                     if leg["regime"] == name and leg["model"] == 1), None)
        if base is None or not base["ran"]:
            continue
        for model in MODEL_LADDER[1:]:
            tick = next((leg for leg in legs
                         if leg["regime"] == name and leg["model"] == model),
                        None)
            if tick is None or not tick["ran"] or not tick["ok"] \
                    or not base["ok"]:
                continue
            degradation.append({
                "regime": name,
                "base": f"mt5-{MT5_MODEL_LABELS[1]}",
                "leg": f"mt5-{MT5_MODEL_LABELS[model]}",
                **degradation_report(base["metrics"], tick["metrics"],
                                     ("net_profit",),
                                     cfg.degradation_band_pct),
            })
    report["degradation"] = degradation
    verdict = verdict_for(legs, min_trades=cfg.min_trades)
    withheld: list[str] = []
    if verdict["status"] == VERIFIED and reconciliation_ok is not True:
        # Fail closed (canonical step 8): an unreconciled empirical run
        # is not a certification, however many trades it produced.
        withheld.append(
            "Python<->MT5 reconciliation not recorded"
            if reconciliation_ok is None
            else "Python<->MT5 reconciliation recorded INCOMPLETE")
        verdict = {"status": NOT_VERIFIED,
                   "reasons": verdict["reasons"] + withheld}
    report["verdict"] = verdict
    # Explicit status model (Blocker 7): VERIFIED only from a real MT5
    # ladder pass WITH reconciliation recorded; "did not run" is
    # EMPIRICAL_VALIDATION_PENDING with MT5 NOT VERIFIED — never a
    # pass; a ran-and-failed leg is FAILED; a withheld verdict stays
    # PENDING with the withholding reason.
    required = [leg for leg in legs if leg["required"]]
    ran = sum(1 for leg in required if leg["ran"])
    ok = sum(1 for leg in required if leg["ran"] and leg["ok"])
    from .status import certify_status_model

    report["status_model"] = certify_status_model(
        report["verdict"]["status"], ran, ok, withheld_reasons=withheld)
    return report


def _report_metrics(report_data: ReportData) -> dict:
    """Canonical python-side metric names from an MT5 report."""
    metrics = dict(report_data.metrics or {})
    out: dict = {}
    for key in ("net_profit", "trades", "max_drawdown_pct", "profit_factor",
                "avg_spread_pips"):
        val = _metric(metrics, key)
        if val is not None:
            out[key] = val
    return out


# ---------------------------------------------------------------------------
# Markdown rendering (report consumers read this, not the dict alone)
# ---------------------------------------------------------------------------


def render_report(report: dict) -> str:
    """Plain-markdown rendering of a certification report.  The verdict
    line is exactly VERIFIED or NOT VERIFIED, derived only from the leg
    outcomes above it."""
    v = report["verdict"]
    lines = [
        (f"# Certification — {report['strategy']} on {report['symbol']} "
         f"{report['timeframe']}"),
        "",
        f"- EA: `{report['ea']}`",
        (f"- manifest binding: `{report['manifest_id'] or '(none)'}`"),
        (f"- spread floor: {report['spread_floor_pips']} pips | "
         f"trade minimum: {report['min_trades']} | "
         f"slippage tiers: {report['slippage_tiers_pips']} pips"),
        f"- runner note: {report['runner_note'] or 'none'}",
        "",
        f"## VERDICT: {v['status']}",
        "",
    ]
    sm = report.get("status_model") or {}
    if sm:
        lines += [
            (f"- status model: {sm.get('status')} | MT5: "
             f"{sm.get('mt5_status')}"),
        ]
        if sm.get("reason"):
            lines.append(f"- status reason: {sm['reason']}")
        lines.append("")
    if v["reasons"]:
        lines.append("Reasons:")
        lines += [f"- {r}" for r in v["reasons"]]
        lines.append("")
    lines.append("## Legs")
    lines.append("| regime | grade | ran | ok | trades | net profit | "
                 "max dd % |")
    lines.append("| --- | --- | --- | --- | ---: | ---: | ---: |")
    for leg in report["legs"]:
        m = leg.get("metrics") or {}
        lines.append(
            f"| {leg['regime']} | {leg['engine']} | {leg['ran']} | "
            f"{leg['ok']} | {leg.get('trades', '-')} | "
            f"{_fmt(_metric(m, 'net_profit'))} | "
            f"{_fmt(_metric(m, 'max_drawdown_pct'))} |")
    lines.append("")
    if report["degradation"]:
        lines.append("## OHLC-vs-tick degradation "
                     f"(expected band {report['degradation_band_pct']}%)")
        lines.append("| regime | leg vs baseline | degradation % | "
                     "degraded | inside band |")
        lines.append("| --- | --- | ---: | --- | --- |")
        for d in report["degradation"]:
            np_ = d["net_profit"]
            lines.append(
                f"| {d['regime']} | {d['leg']} vs {d['base']} | "
                f"{_fmt(np_.get('degradation_pct'))} | "
                f"{np_.get('degraded')} | {np_.get('inside_band')} |")
        lines.append("")
    lines.append("Backtests are research evidence, not a promise of live "
                 "profit.")
    return "\n".join(lines)


def _fmt(value) -> str:
    return "-" if value is None else f"{value:.2f}"
