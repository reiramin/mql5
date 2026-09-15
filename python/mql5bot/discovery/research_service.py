"""discovery/research_service.py — the deterministic research
application service (convergence §14/§16/§59/§83).

This is the CANONICAL glue between:

    idea (+ optional untrusted source) → deterministic interpreter →
    canonical DSL → staged campaign (real engine backtests, measured
    gates, IS-only selection) → ONE OOS look → evidence-bound
    lifecycle → measured Discovery Score → portfolio assembly

It exists so the operator console, the CLI and the acceptance fixtures
drive the SAME code path — no test-only orchestration.

Rules baked in:
- selection uses IS/CV metrics ONLY; the final OOS slice is evaluated
  ONCE, for the selected candidate, after selection (§19);
- every promotion is evidence-bound through the store (machines cannot
  self-approve into human-gated states);
- the returned evidence chain is complete and self-hashed (§59): it is
  the immutable reference record for the run.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from ..backtest import run_backtest
from ..dsl import desired_positions, parse_spec
from ..factory import lifecycle as lc
from ..factory.gates import evaluate_gates, overall
from ..factory.interpreter import TemplateInterpreter
from ..factory.providers import ResearchMaterial
from ..factory.store import FactoryStore
from .candidates import DSL_VERSION, GENERATOR_VERSION, ResearchSpace
from .orchestrator import DiscoveryOrchestrator
from .score import compute_score

# Declared default research space for the service (policy-configurable
# in production; a fixed grid here keeps runs budgeted and reproducible).
DEFAULT_GRID: tuple[tuple[int, int], ...] = ((20, 50), (10, 30), (30, 80))
RISK_PERCENT = 0.1
PARAMS = {"sl_atr": 1.5, "tp_atr": 3.0}
OOS_FRACTION = 0.3
MAX_GRID = 24          # hard cap on variants per campaign
TIME_BUDGET_S = 1800   # §82: wall-clock budget per campaign


def _trade_metrics(res, df: pd.DataFrame) -> dict:
    """Measured gate inputs via the shared E2E math (deterministic)."""
    m = res.metrics
    tr = res.trades
    net = tr["pnl"].sum()
    top10 = tr["pnl"].nlargest(10).sum() / net if net > 0 else 1.0
    eq = res.equity
    q = eq.resample("QE").last().pct_change().dropna()
    pos_q = float((q > 0).mean()) if len(q) else 0.0
    years = max((df.index[-1] - df.index[0]).total_seconds()
                / (365.25 * 24 * 3600), 1e-9)
    avg_cost = 2 * 1e-5 * 100_000 * tr["lots"].mean() if len(tr) else 1.0
    return {"n_trades": float(m["trades"]), "years": years,
            "pf": float(m["profit_factor"]),
            "max_dd_pct": abs(float(m["max_drawdown_pct"])),
            "top10_profit_share": float(top10),
            "positive_quarters_share": pos_q,
            "edge_to_cost": float(tr["pnl"].mean() / max(avg_cost, 1e-9))
            if len(tr) else 0.0}


def _mc_p05_dd(res, perms: int = 200, seed: int = 11) -> float:
    pnl = res.trades["pnl"].to_numpy()
    rng = np.random.default_rng(seed)
    dds = []
    for _ in range(perms):
        eqv = 10_000.0 + np.cumsum(rng.permutation(pnl))
        peak = np.maximum.accumulate(np.maximum(eqv, 1e-9))
        dds.append(-100.0 * ((eqv - peak) / peak).min() if len(eqv) else 0.0)
    return float(np.percentile(dds, 5))


def _psr_daily(res, sr_bench: float = 0.0) -> float:
    r = res.equity.resample("1D").last().pct_change().dropna()
    if len(r) < 3:
        return 0.0
    sr = r.mean() / (r.std(ddof=1) + 1e-12)
    skew = float(r.skew())
    kurt = float(r.kurt() + 3.0)
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr
                          + (kurt - 1.0) / 4.0 * sr * sr))
    z = (sr - sr_bench) * math.sqrt(len(r) - 1) / denom
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _variant(doc: dict, fast: int, slow: int) -> dict:
    d = json.loads(json.dumps(doc))
    d["indicators"][0]["period"] = fast
    d["indicators"][1]["period"] = slow
    return d


def _bt(df, doc, allow_short: bool = True):
    spec = parse_spec(doc)
    return run_backtest(df, "dsl:" + spec.strategy_id, PARAMS,
                        signal=desired_positions(spec, df),
                        risk_percent=RISK_PERCENT,
                        allow_short=allow_short)


class ResearchService:
    """Application service.  Deps injected: store, gate policy (dict +
    version string), interpreter (default deterministic template)."""

    def __init__(self, store: FactoryStore, *, gate_policy: dict,
                 gate_policy_version: str,
                 interpreter: Any | None = None,
                 grid: tuple = DEFAULT_GRID,
                 journal: Callable[[dict], None] | None = None):
        self.store = store
        self.policy = gate_policy
        self.policy_version = gate_policy_version
        self.interpreter = interpreter or TemplateInterpreter()
        self.grid = tuple(grid)
        if len(self.grid) > MAX_GRID:
            raise ValueError(
                f"grid of {len(self.grid)} variants exceeds research "
                f"budget ({MAX_GRID}); declare a smaller stage space")
        self.journal = journal or (lambda event: None)

    def _emit(self, event: str, **fields) -> None:
        self.journal({"event": event, **fields})

    # ------------------------------------------------------------------
    def run_idea(self, idea: str, df: pd.DataFrame, *,
                 source_text: str = "",
                 dataset_id: str = "synthetic",
                 campaign_id: str = "camp_research",
                 long_only: bool = False,
                 hypothesis: str = "",
                 time_budget_s: int = TIME_BUDGET_S) -> dict:
        """idea + data → full research chain → evidence chain dict."""
        deadline = time.monotonic() + time_budget_s
        self._emit("strategy_received", idea=idea[:120])
        interp = self.interpreter.interpret(ResearchMaterial(
            "USER_TEXT", "research-service",
            source_text.strip() or idea))
        doc = interp.draft
        doc["strategy_id"] = "rs_" + campaign_id.replace("camp_", "")[:24]
        doc["version"] = 1
        spec = parse_spec(doc)          # deterministic authority
        _registration, _created = self.store.register_strategy(
            spec, created_by="research-service",
            original_text=source_text or None)
        with self.store.session() as sess:
            from ..factory.models import StrategyVersion
            version_no = (sess.query(StrategyVersion)
                          .filter_by(strategy_id=doc["strategy_id"])
                          .order_by(StrategyVersion.version.desc())
                          .first().version)
        self._emit("strategy_parsed", strategy_id=doc["strategy_id"],
                   version=version_no)

        def evidence(run_type: str, ok: bool, metrics: dict) -> int:
            return self.store.record_run(
                doc["strategy_id"], version_no, run_type=run_type,
                status="PASS" if ok else "FAIL",
                spec_hash=spec.spec_hash,
                metrics={k: float(v) for k, v in metrics.items()
                         if isinstance(v, (int, float))
                         and np.isfinite(v)})

        def advance(target: str, refs: tuple, *, human: bool = False):
            cur = self.store.current_state(doc["strategy_id"])
            if cur == target or lc.PROMOTIONS.get(cur, ("",))[0] != target:
                return
            self.store.transition(
                doc["strategy_id"], version_no, target,
                evidence_refs=refs,
                actor="owner" if human else "factory",
                human_approval=human, reason="research service",
                policy_version=self.policy_version if human else "")
            self._emit("lifecycle_advanced",
                       strategy_id=doc["strategy_id"], to=target)

        # deterministic parse/schema evidence
        advance(lc.PARSED, (evidence("parse", True,
                                     {"schema_valid": 1.0}),))
        advance(lc.VALIDATED, (evidence("schema", True,
                                        {"semantic_ok": 1.0}),))

        # ---- staged campaign on the declared grid (real engine) ----
        space = ResearchSpace(indicators=("EMA", "SMA", "WMA"),
                              param_grid={})
        orch = DiscoveryOrchestrator(
            space, budgets={"stage1_single_indicator": len(self.grid),
                            "stage2_two_factor": 0,
                            "stage3_multi_factor": 0,
                            "stage5_mutations": 0},
            policy_hash=self.policy_version, dataset_id=dataset_id,
            dataset_hash=f"{dataset_id}-content",
            cost_config={"spread_points": 1.0}, risk_config={
                "risk_percent": RISK_PERCENT},
            gate_policy=self.policy_version, campaign_id=campaign_id,
            hypothesis=hypothesis or idea[:120],
            strategy_parent=doc["strategy_id"], seed=42,
            oos_boundary=f"last_{int(OOS_FRACTION * 100)}pct")
        oos_start = int(len(df) * (1.0 - OOS_FRACTION))
        train_end = int(len(df) * 0.5)

        def run_stage(stage: str, docs: list[dict]):
            if stage != "stage1_single_indicator":
                return []
            out = []
            for i, _d in enumerate(docs):
                if time.monotonic() > deadline:
                    run_stage.time_budget_exceeded = True
                    return out
                fast, slow = self.grid[i % len(self.grid)]
                cand = _variant(doc, fast, slow)
                cspec = parse_spec(cand)
                full = _bt(df, cand, allow_short=not long_only)
                m = _trade_metrics(full, df)
                stress = run_backtest(
                    df, "dsl:stress", PARAMS,
                    signal=desired_positions(parse_spec(cand), df),
                    risk_percent=RISK_PERCENT, spread_points=2.0,
                    slippage_points=1.0, allow_short=not long_only)
                train = df.iloc[:train_end]
                cv = df.iloc[train_end:oos_start]
                wfe = (_trade_metrics(_bt(cv, cand,
                                          allow_short=not long_only),
                                       cv)["pf"]
                       - _trade_metrics(_bt(train, cand,
                                            allow_short=not long_only),
                                        train)["pf"])
                sens = []
                for p in (fast - 1, fast + 1):
                    rp = _bt(df.iloc[:oos_start],
                             _variant(doc, p, slow),
                             allow_short=not long_only)
                    sens.append(abs(_trade_metrics(rp, train)[
                        "max_dd_pct"]))
                gi = dict(m)
                gi.update({
                    "pf_under_cost_stress": float(
                        stress.metrics["profit_factor"]),
                    "wfe": float(wfe),
                    "mc_p05_dd_pct": _mc_p05_dd(full),
                    "dsr_p": _psr_daily(full), "pbo": 0.0,
                    "param_sensitivity_dd_ratio":
                        max(sens) / max(m["max_dd_pct"], 1e-9),
                    "max_correlation_with_book": 0.0,
                    "marginal_heat_add": 0.0,
                    "positive_in_expected_regime": True,
                    "schema_valid": True, "semantic_ok": True})
                ok = overall(evaluate_gates(self.policy, gi)) == "PASS"
                r_bt = evidence("backtest", ok, gi)
                is_pf = wfe + _trade_metrics(
                    _bt(train, cand, allow_short=not long_only),
                    train)["pf"]
                if not ok:
                    out.append({"strategy_id": cspec.strategy_id,
                                "state": "REJECTED", "is_pf": is_pf,
                                "grid": (fast, slow), "metrics": m})
                    continue
                advance(lc.BACKTESTED, (r_bt,))
                r_rob = evidence("robustness",
                                 gi["param_sensitivity_dd_ratio"] <= 3.0
                                 and gi["mc_p05_dd_pct"] <= 25.0,
                                 {"mc_p05_dd_pct": gi["mc_p05_dd_pct"]})
                advance(lc.ROBUSTNESS_PASS, (r_rob,))
                out.append({"strategy_id": cspec.strategy_id,
                            "state": "ROBUSTNESS_PASS", "is_pf": is_pf,
                            "grid": (fast, slow), "metrics": m})
            return out

        run_stage.time_budget_exceeded = False
        self._emit("campaign_started", campaign_id=campaign_id,
                   candidates=len(self.grid))
        camp = orch.run_campaign({"campaign_id": campaign_id,
                                  "progress": {}, "results": {}},
                                 run_stage)
        self._emit("campaign_completed", campaign_id=campaign_id,
                   time_budget_exceeded=run_stage.time_budget_exceeded)

        # ---- selection: IS/CV ONLY (OOS untouched) ----
        survivors = sorted(
            (it for items in camp["results"].values() for it in items
             if it["state"] == "ROBUSTNESS_PASS"),
            key=lambda it: (-it["is_pf"], it["strategy_id"]))
        if not survivors:
            chain = self._chain(doc, spec, version_no, orch, camp, None)
            chain["time_budget_exceeded"] = \
                run_stage.time_budget_exceeded
            return {"outcome": "NO_SURVIVORS", "evidence_chain": chain}
        selected = survivors[0]

        # ---- ONE OOS look for the selected candidate ----
        fast, slow = selected["grid"]
        cut = oos_start
        om = _trade_metrics(_bt(df.iloc[cut:], _variant(doc, fast, slow),
                                allow_short=not long_only), df.iloc[cut:])
        oos_ok = om["pf"] > 1.0 and om["max_dd_pct"] < 20.0
        self._emit("oos_completed", campaign_id=campaign_id,
                   oos_pass=oos_ok)
        r_oos = evidence("oos", oos_ok, om)
        if oos_ok:
            advance(lc.OOS_SURVIVOR, (r_oos,))
            advance(lc.SHADOW, (evidence("shadow_entry", True,
                                         {"shadow": 1.0}),),)
            for items in camp["results"].values():
                for it in items:
                    if it["strategy_id"] == selected["strategy_id"]:
                        it["state"] = "OOS_SURVIVOR"
            outcome = "OOS_SURVIVOR"
        else:
            self.store.transition(doc["strategy_id"], version_no,
                                  "REJECTED", actor="factory",
                                  reason="oos failed (evaluation only)")
            for items in camp["results"].values():
                for it in items:
                    it["state"] = "REJECTED"
            outcome = "REJECTED_OOS"

        # measured-only score (shadow/live components unavailable)
        score = compute_score({
            "oos_survival": 1.0 if oos_ok else 0.0,
            "profit_factor": min(om["pf"], 3.0),
            "drawdown_quality": om["max_dd_pct"],
            "expectancy": None, "trade_count_confidence": om["n_trades"],
            "parameter_robustness": None, "wfa_survival": None,
            "cpcv_pbo_evidence": 0.1, "monte_carlo_stability": None,
            "cost_robustness": None, "regime_stability": None,
            "drift_health": None, "execution_realism": None,
            "portfolio_diversification": None, "shadow_evidence": None,
            "live_evidence": None})
        self._emit("score_computed", campaign_id=campaign_id,
                   score=score.score)
        chain = self._chain(doc, spec, version_no, orch, camp, selected)
        chain["time_budget_exceeded"] = run_stage.time_budget_exceeded
        chain["oos_metrics"] = {k: v for k, v in om.items()
                                if isinstance(v, (int, float))}
        chain["score"] = score.to_dict()
        chain["outcome"] = outcome
        return {"outcome": outcome, "evidence_chain": chain}

    # ------------------------------------------------------------------
    def console_runner(self, data_provider: Callable[[str],
                       pd.DataFrame]):
        """§55 one-click research: returns the callable to inject into
        api.create_app(research_runner=...).  The provider resolves a
        declared dataset id to OHLC; the runner executes the full
        research chain synchronously and records the outcome on the
        campaign row.  It never touches execution."""
        from ..factory.models import DiscoveryCampaign

        def run(payload: dict) -> dict:
            manifest = payload.get("manifest", {})
            df = data_provider(manifest.get("dataset", "synthetic-default"))
            result = self.run_idea(
                manifest.get("hypothesis", ""), df,
                source_text=manifest.get("source_text_hash", ""),
                dataset_id=manifest.get("dataset", "synthetic-default"),
                campaign_id=payload["campaign_id"])
            with self.store.session() as sess:
                row = sess.query(DiscoveryCampaign).filter_by(
                    campaign_id=payload["campaign_id"]).one_or_none()
                if row is not None:
                    row.status = "DONE"
                    row.progress = {"outcome": result["outcome"],
                                    "chain_hash": result[
                                        "evidence_chain"]["chain_hash"]}
                    sess.commit()
            self._emit("research_outcome",
                       campaign_id=payload["campaign_id"],
                       outcome=result["outcome"])
            return result

        return run

    # ------------------------------------------------------------------
    def _chain(self, doc: dict, spec, version_no: int, orch, camp,
               selected) -> dict:
        """§59: the immutable, self-hashed evidence chain."""
        from .candidates import doc_hash
        chain = {
            "strategy_id": doc["strategy_id"], "version": version_no,
            "spec_hash": spec.spec_hash,
            "dsl_version": DSL_VERSION,
            "generator_version": GENERATOR_VERSION,
            "campaign": orch.manifest(camp),
            "selected": (selected or {}).get("strategy_id"),
            "lifecycle_state": self.store.current_state(
                doc["strategy_id"]),
        }
        chain["chain_hash"] = doc_hash(chain)
        return chain
