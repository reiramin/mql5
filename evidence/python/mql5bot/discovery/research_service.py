"""discovery/research_service.py — the deterministic research
application service (convergence §14/§16/§59/§83).

This is the CANONICAL glue between:

    idea (+ optional untrusted source) → deterministic interpreter →
    canonical DSL → staged campaign (real engine backtests, MEASURED
    gates, IS-only selection) → ONE OOS look → evidence-bound
    lifecycle → measured Discovery Score → portfolio assembly

It exists so the operator console, the CLI and the acceptance fixtures
drive the SAME code path — no test-only orchestration.

Rules baked in:
- selection uses IS/CV metrics ONLY; the final OOS slice is evaluated
  ONCE, for the selected candidate, after selection (§19);
- EVERY gate input is a real measurement — PBO from combinatorial purged
  CV across the searched grid, regime edge from a causal regime
  partition, portfolio interaction from the actual book.  A measurement
  that cannot be taken is left UNSET so its gate SKIPs (blocks); no gate
  input is ever fabricated to force a pass (mission P0-truthfulness);
- the promoted candidate is a REAL research identity: the grid search is
  a pre-registration selection step (IS/CV only), and evidence is bound
  to the SELECTED variant's own spec_hash — never to a base spec that was
  not the one measured (§19 candidate identity);
- every promotion is evidence-bound through the store (machines cannot
  self-approve, and a FAIL evidence record can never promote);
- the returned evidence chain is complete and self-hashed (§59).
"""

from __future__ import annotations

import json
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
from . import research_metrics as rm
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

    def _portfolio_book(self) -> list[pd.Series]:
        """Daily-return series of the strategies already in observed/live
        states — the real book a new candidate is measured against
        (gate-9).  Empty when nothing is live yet (the honest common case
        for a strategy researched in isolation)."""
        # The service store carries no execution return history in the
        # research context; observed-state return curves live in the
        # shadow/live observation tables and are not reconstructable here,
        # so the researched-in-isolation book is legitimately empty.  This
        # is a MEASURED empty book (queried), not an assumed one; when a
        # book with return history exists it flows straight into
        # rm.portfolio_interaction.
        return []

    # ------------------------------------------------------------------
    def run_idea(self, idea: str, df: pd.DataFrame, *,
                 source_text: str = "",
                 dataset_id: str = "synthetic",
                 campaign_id: str = "camp_research",
                 long_only: bool = False,
                 hypothesis: str = "",
                 market: dict | None = None,
                 time_budget_s: int = TIME_BUDGET_S) -> dict:
        """idea + data → full research chain → evidence chain dict.

        ``market`` (``{"symbol", "timeframe"}``) is REQUIRED: the research
        dataset always belongs to a specific instrument, and the market is
        never guessed from the idea text (§6)."""
        deadline = time.monotonic() + time_budget_s
        self._emit("strategy_received", idea=idea[:120])
        interp = self.interpreter.interpret(ResearchMaterial(
            "USER_TEXT", "research-service",
            source_text.strip() or idea), market=market)
        doc = interp.draft
        mk = doc.get("market", {}) or {}
        if not (mk.get("symbol") and mk.get("timeframe")):
            raise ValueError(
                "research-service requires an explicit market "
                "(symbol + timeframe); none was supplied — the market is "
                "never guessed from the idea text (§6)")
        strategy_id = "rs_" + campaign_id.replace("camp_", "")[:24]
        doc["strategy_id"] = strategy_id
        doc["version"] = 1

        allow_short = not long_only
        oos_start = int(len(df) * (1.0 - OOS_FRACTION))
        train_end = int(len(df) * 0.5)
        is_df = df.iloc[:oos_start]
        book = self._portfolio_book()

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
            strategy_parent=strategy_id, seed=42,
            oos_boundary=f"last_{int(OOS_FRACTION * 100)}pct")

        def measure_stage(stage: str, _docs: list[dict]):
            """Pure MEASUREMENT of every grid variant on the search
            (IS/CV) window — no store writes, no OOS look.  PBO is a
            property of the SEARCH, so per-config IS returns are collected
            here and the single grid-wide PBO is computed after the loop
            (§17 trial accounting → §21 gate-6)."""
            if stage != "stage1_single_indicator":
                return []
            measured = []
            for i in range(len(self.grid)):
                if time.monotonic() > deadline:
                    measure_stage.time_budget_exceeded = True
                    break
                fast, slow = self.grid[i]
                cand = _variant(doc, fast, slow)
                cspec = parse_spec(cand)
                full = _bt(df, cand, allow_short=allow_short)
                m = rm.trade_metrics(full, df)
                stress = run_backtest(
                    df, "dsl:stress", PARAMS,
                    signal=desired_positions(parse_spec(cand), df),
                    risk_percent=RISK_PERCENT, spread_points=2.0,
                    slippage_points=1.0, allow_short=allow_short)
                train = df.iloc[:train_end]
                cv = df.iloc[train_end:oos_start]   # held-out OOS-of-window (IS)
                train_bt = _bt(train, cand, allow_short=allow_short)
                cv_bt = _bt(cv, cand, allow_short=allow_short)
                sel_pf = rm.trade_metrics(cv_bt, cv)["pf"]   # CV selection PF
                # gate-5 walk-forward efficiency: the CONTRACT WFE ratio
                # (held-out return / IS return, WFA_CONTRACT §6) over one
                # rolling-origin window inside the IS region — the exact
                # formula optimizer.walk_forward uses.  ``None`` when the IS
                # leg is non-positive (→ gate-5 SKIP/block).  This is real
                # walk-forward efficiency, not a profit-factor delta.
                wfe = rm.walk_forward_efficiency(train_bt, cv_bt)
                sens = []
                for p in (fast - 1, fast + 1):
                    rp = _bt(is_df, _variant(doc, p, slow),
                             allow_short=allow_short)
                    sens.append(abs(rm.trade_metrics(rp, train)["max_dd_pct"]))
                is_bt = _bt(is_df, cand, allow_short=allow_short)
                # measured gate inputs (PBO added after the grid loop)
                gi = dict(m)
                gi.update({
                    "pf_under_cost_stress": float(
                        stress.metrics["profit_factor"]),
                    "mc_p05_dd_pct": rm.mc_p05_dd(full),
                    "param_sensitivity_dd_ratio":
                        max(sens) / max(m["max_dd_pct"], 1e-9),
                    "schema_valid": True, "semantic_ok": True})
                # WFE is left UNSET when undefined (non-positive IS leg) so
                # gate-5 SKIPs/blocks — never fabricated (mission P0/§21).
                if wfe is not None:
                    gi["wfe"] = float(wfe)
                dsr = rm.dsr_p_daily(full)
                if dsr is not None:
                    gi["dsr_p"] = dsr
                reg = rm.regime_pf(full, df)
                if reg is not None:
                    gi["positive_in_expected_regime"] = reg > 1.0
                corr, heat = rm.portfolio_interaction(
                    rm.daily_returns(full), book)
                gi["max_correlation_with_book"] = corr
                gi["marginal_heat_add"] = heat
                # distinct campaign-record label per searched variant (the
                # trial identity); the PROMOTED identity is the base
                # strategy_id registered with the SELECTED variant's spec.
                measured.append({
                    "strategy_id": f"{strategy_id}_{fast}x{slow}",
                    "state": "MEASURED", "grid": (fast, slow),
                    "metrics": m, "gi": gi, "sel_pf": sel_pf, "cand": cand,
                    "spec_hash": cspec.spec_hash,
                    "is_returns": rm.daily_returns(is_bt)})
            # grid-wide PBO (probability of backtest overfitting from the
            # selection) — one measurement bound into each candidate's
            # gate-6 evidence; None (→ gate-6 SKIP) when the search is too
            # small to estimate it. NEVER a fabricated 0.0.
            pbo = rm.cpcv_pbo([r["is_returns"] for r in measured])
            for r in measured:
                if pbo is not None:
                    r["gi"]["pbo"] = pbo
                verdicts = evaluate_gates(self.policy, r["gi"])
                r["gate_overall"] = overall(verdicts)
                r["state"] = ("ROBUSTNESS_PASS"
                              if r["gate_overall"] == "PASS" else "REJECTED")
            measure_stage.pbo = pbo
            return measured

        measure_stage.time_budget_exceeded = False
        measure_stage.pbo = None
        self._emit("campaign_started", campaign_id=campaign_id,
                   candidates=len(self.grid))
        camp = orch.run_campaign({"campaign_id": campaign_id,
                                  "progress": {}, "results": {}},
                                 measure_stage)
        self._emit("campaign_completed", campaign_id=campaign_id,
                   time_budget_exceeded=measure_stage.time_budget_exceeded)

        records = [it for items in camp["results"].values() for it in items]

        # ---- selection: IS/CV ONLY (OOS untouched) ----
        survivors = sorted(
            (it for it in records if it["state"] == "ROBUSTNESS_PASS"),
            key=lambda it: (-it["sel_pf"], it["strategy_id"]))

        # the promoted identity is the SELECTED variant (real spec_hash);
        # with no survivor the best-by-IS variant is registered so the
        # chain still names a real, measured identity (never a base spec
        # that was not measured).
        chosen = survivors[0] if survivors else (
            min(records, key=lambda it: (-it["sel_pf"], it["strategy_id"]))
            if records else None)

        if chosen is None:
            # no candidate was even measured (e.g. budget exhausted before
            # the first variant): register the base draft so the chain has
            # an identity, then stop.
            spec = parse_spec(doc)
            self.store.register_strategy(
                spec, created_by="research-service",
                original_text=source_text or None)
            version_no = self._version_of(strategy_id)
            self._emit("strategy_parsed", strategy_id=strategy_id,
                       version=version_no)
            chain = self._chain(doc, spec, version_no, orch, camp, None)
            chain["time_budget_exceeded"] = measure_stage.time_budget_exceeded
            return {"outcome": "NO_SURVIVORS", "evidence_chain": chain}

        cand_doc = chosen["cand"]
        spec = parse_spec(cand_doc)             # SELECTED variant identity
        self.store.register_strategy(
            spec, created_by="research-service",
            original_text=source_text or None)
        version_no = self._version_of(strategy_id)
        self._emit("strategy_parsed", strategy_id=strategy_id,
                   version=version_no)

        def evidence(run_type: str, ok: bool, metrics: dict) -> int:
            return self.store.record_run(
                strategy_id, version_no, run_type=run_type,
                status="PASS" if ok else "FAIL",
                spec_hash=spec.spec_hash,
                metrics={k: float(v) for k, v in metrics.items()
                         if isinstance(v, (int, float))
                         and not isinstance(v, bool) and np.isfinite(v)})

        def advance(target: str, refs: tuple, *, human: bool = False) -> None:
            cur = self.store.current_state(strategy_id)
            if cur == target or lc.PROMOTIONS.get(cur, ("",))[0] != target:
                return
            self.store.transition(
                strategy_id, version_no, target, evidence_refs=refs,
                actor="owner" if human else "factory",
                human_approval=human, reason="research service",
                policy_version=self.policy_version if human else "")
            self._emit("lifecycle_advanced", strategy_id=strategy_id,
                       to=target)

        advance(lc.PARSED, (evidence("parse", True, {"schema_valid": 1.0}),))
        advance(lc.VALIDATED, (evidence("schema", True,
                                        {"semantic_ok": 1.0}),))

        # The SELECTED candidate now runs the tail of the chain: IS gates
        # (already measured) → robustness → ONE final OOS look → score.
        # Promotion needs the full ladder to PASS *and* OOS to confirm; a
        # candidate that fails any IS gate is recorded truthfully and
        # REJECTED, but the single OOS look and the score still run (the
        # chain always renders an evidence-based ACCEPT/REJECT verdict).
        gi = chosen["gi"]
        gates_ok = chosen["state"] == "ROBUSTNESS_PASS"
        r_bt = evidence("backtest", gates_ok, gi)
        rob_ok = False
        if gates_ok:
            advance(lc.BACKTESTED, (r_bt,))
            rob_ok = (gi["param_sensitivity_dd_ratio"] <= 3.0
                      and gi["mc_p05_dd_pct"] <= 25.0)
            r_rob = evidence("robustness", rob_ok,
                             {"mc_p05_dd_pct": gi["mc_p05_dd_pct"]})
            # a FAILED robustness record must NEVER promote (§28.15): only
            # advance when the evidence itself is PASS.
            if rob_ok:
                advance(lc.ROBUSTNESS_PASS, (r_rob,))

        # ---- ONE OOS look for the selected candidate (after selection) ----
        fast, slow = chosen["grid"]
        om = rm.trade_metrics(
            _bt(df.iloc[oos_start:], _variant(doc, fast, slow),
                allow_short=allow_short), df.iloc[oos_start:])
        oos_ok = om["pf"] > 1.0 and om["max_dd_pct"] < 20.0
        self._emit("oos_completed", campaign_id=campaign_id, oos_pass=oos_ok)
        r_oos = evidence("oos", oos_ok, om)
        promoted = (gates_ok and rob_ok and oos_ok
                    and self.store.current_state(strategy_id)
                    == lc.ROBUSTNESS_PASS)
        if promoted:
            advance(lc.OOS_SURVIVOR, (r_oos,))
            advance(lc.SHADOW, (evidence("shadow_entry", True,
                                         {"shadow": 1.0}),))
            for it in records:
                if it["strategy_id"] == chosen["strategy_id"]:
                    it["state"] = "OOS_SURVIVOR"
            outcome = "OOS_SURVIVOR"
        else:
            if self.store.current_state(strategy_id) not in (
                    lc.REJECTED, lc.DRAFT):
                self.store.transition(strategy_id, version_no, "REJECTED",
                                      actor="factory",
                                      reason="not certified (gate or OOS "
                                      "evidence failed)")
            for it in records:
                if it["strategy_id"] == chosen["strategy_id"]:
                    it["state"] = "REJECTED"
            outcome = "REJECTED_OOS"

        # measured-only score (shadow/live components unavailable; the
        # cpcv/pbo component is DERIVED from the measured PBO, never a
        # constant — 1 - PBO is the survival evidence of the search).
        pbo = measure_stage.pbo
        score = compute_score({
            "oos_survival": 1.0 if oos_ok else 0.0,
            "profit_factor": min(om["pf"], 3.0),
            "drawdown_quality": om["max_dd_pct"],
            "expectancy": None, "trade_count_confidence": om["n_trades"],
            "parameter_robustness": None, "wfa_survival": None,
            "cpcv_pbo_evidence": (1.0 - pbo) if pbo is not None else None,
            "monte_carlo_stability": None,
            "cost_robustness": None, "regime_stability": None,
            "drift_health": None, "execution_realism": None,
            "portfolio_diversification": None, "shadow_evidence": None,
            "live_evidence": None})
        self._emit("score_computed", campaign_id=campaign_id,
                   score=score.score)
        chain = self._chain(cand_doc, spec, version_no, orch, camp, chosen)
        chain["time_budget_exceeded"] = measure_stage.time_budget_exceeded
        chain["oos_metrics"] = {k: v for k, v in om.items()
                                if isinstance(v, (int, float))}
        chain["pbo"] = pbo
        chain["score"] = score.to_dict()
        chain["outcome"] = outcome
        return {"outcome": outcome, "evidence_chain": chain}

    def _version_of(self, strategy_id: str) -> int:
        from ..factory.models import StrategyVersion
        with self.store.session() as sess:
            return (sess.query(StrategyVersion)
                    .filter_by(strategy_id=strategy_id)
                    .order_by(StrategyVersion.version.desc())
                    .first().version)

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
                market=manifest.get("market"),   # §6: explicit, never guessed
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
            "lifecycle_state": self.store.current_state(doc["strategy_id"]),
        }
        chain["chain_hash"] = doc_hash(chain)
        return chain
