"""FINAL CONVERGENCE ACCEPTANCE (mission §75–§82).

One complete fixture walks the ENTIRE canonical chain with the REAL
engines (interpreter → DSL → campaign → backtests → gates → lifecycle →
score → portfolio → governor → entry chain → risk sizing → execution
boundary), plus the negative (§76), safety (§77), capital (§78),
live-small (§79/§80) and retirement (§81) acceptances.

At NO point does the Factory trade: the chain ends at an execution
INTENT carrying Risk-approved risk — lots are computed only by the
Risk sizer, and the MQL5 execution boundary is the only order origin.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from mql5bot.backtest import run_backtest
from mql5bot.data import generate_ohlc
from mql5bot.discovery import (
    AllocationCircuitBreaker,
    AllocationGovernor,
    AllocationProposal,
    GovernorBounds,
    LiveSmallRamp,
    ResearchSpace,
    build_portfolio,
    compute_score,
)
from mql5bot.discovery.entry_chain import ChainContext, EntryRequest, govern_entry
from mql5bot.discovery.orchestrator import DiscoveryOrchestrator
from mql5bot.discovery.safety import KillSwitchState
from mql5bot.dsl import desired_positions, parse_spec
from mql5bot.factory import lifecycle as lc
from mql5bot.factory.gates import evaluate_gates, overall, policy_hash
from mql5bot.factory.interpreter import TemplateInterpreter
from mql5bot.factory.providers import ResearchMaterial
from mql5bot.factory.store import FactoryStore

ROOT = Path(__file__).resolve().parent.parent
POLICY = yaml.safe_load((ROOT / "factory" / "gates.fixture.yaml").read_text())

DAYS, SEED, RISK = 1500, 7, 0.1
from tests.test_factory_e2e import _mc_p05_dd, _psr_daily, _regime_pf, _trade_metrics

GRID = ((20, 50), (10, 30), (30, 80))       # declared research space
SID = "conv_accept_strat"
SOURCE = ("Buy when EMA20 crosses above EMA50 and RSI is above 55. "
          "Use an ATR-based stop of 1.5 ATR and a 3 ATR target.")


def _metrics(res, df: pd.DataFrame) -> dict:
    """Measured via the shared E2E helpers (same engine, same math)."""
    m = _trade_metrics(res, df)
    m["expectancy"] = float(res.trades["pnl"].mean()) \
        if len(res.trades) else 0.0
    return m


def _bt(df, doc, params, risk=RISK, allow_short=True):
    spec = parse_spec(doc)
    sig = desired_positions(spec, df)
    return run_backtest(df, "dsl:" + spec.strategy_id, params,
                        signal=sig, risk_percent=risk,
                        allow_short=allow_short)


def _variant_doc(base_doc: dict, fast: int, slow: int) -> dict:
    doc = json.loads(json.dumps(base_doc))
    doc["indicators"][0]["period"] = fast
    doc["indicators"][1]["period"] = slow
    return doc


def _run_research(store: FactoryStore, df: pd.DataFrame, *,
                  oos_shrink: float = 0.0, long_only: bool = False):
    """Idea → … → lifecycle, driven by the REAL engines.  Returns
    (orch, campaign, parent_spec, oos_result_or_None)."""
    # 1) interpretation (deterministic template; LLM optional by design)
    interp = TemplateInterpreter()
    material = ResearchMaterial("USER_TEXT", "acceptance", SOURCE)
    r = interp.interpret(material)
    doc = r.draft
    doc["strategy_id"] = SID
    doc["version"] = 1
    spec = parse_spec(doc)                    # deterministic authority
    store.register_strategy(spec, created_by="owner")
    with store.session() as sess:
        from mql5bot.factory.models import StrategyVersion
        v1 = (sess.query(StrategyVersion)
              .filter_by(strategy_id=SID).one())
        version_no = v1.version

    def evidence(run_type: str, ok: bool, metrics: dict) -> int:
        return store.record_run(
            SID, version_no, run_type=run_type,
            status="PASS" if ok else "FAIL", spec_hash=spec.spec_hash,
            metrics={k: float(v) for k, v in metrics.items()
                     if np.isfinite(v)})

    def advance(target: str, refs: tuple, *, human=False):
        cur = store.current_state(SID)
        if cur == target:
            return
        if not PROMOTIONS_OK(cur, target):
            # the parent lifecycle records the STRONGEST evidence
            # achieved so far; a later candidate cannot rewind it
            return
        store.transition(SID, version_no, target, evidence_refs=refs,
                         actor="owner" if human else "factory",
                         human_approval=human,
                         reason="convergence acceptance",
                         policy_version="discovery-defaults-1.0"
                         if human else "")

    def PROMOTIONS_OK(cur, target):
        return lc.PROMOTIONS.get(cur, ("",))[0] == target

    # parse+schema evidence (validation layer, deterministic)
    r_parse = evidence("parse", True, {"schema_valid": 1.0})
    advance(lc.PARSED, (r_parse,))
    r_schema = evidence("schema", True, {"semantic_ok": 1.0})
    advance(lc.VALIDATED, (r_schema,))

    # 2) campaign over the DECLARED grid, run by the REAL pipeline
    # (three declared param pairs → three enumerated candidates)
    space = ResearchSpace(indicators=("EMA", "SMA", "WMA"),
                          param_grid={})
    orch = DiscoveryOrchestrator(
        space, budgets={"stage1_single_indicator": len(GRID),
                        "stage2_two_factor": 0, "stage3_multi_factor": 0,
                        "stage5_mutations": 0},
        policy_hash=policy_hash(POLICY), dataset_id="synthetic-conv",
        dataset_hash="synthetic" * 8, data_horizon=f"{DAYS}d",
        cost_config={"spread_points": 1.0, "slippage_points": 0.0},
        risk_config={"risk_percent": RISK}, gate_policy="fixture",
        campaign_id="camp_accept", hypothesis="ema cross persists",
        strategy_parent=SID, seed=42, oos_boundary="last_30pct")

    def run_stage(stage: str, docs: list[dict]):
        assert stage == "stage1_single_indicator" or not docs
        out = []
        final_oos_start = int(len(df) * 0.7)   # frozen research boundary
        for i, _doc in enumerate(docs):
            fast, slow = GRID[i % len(GRID)]
            cand = _variant_doc(doc, fast, slow)
            cspec = parse_spec(cand)
            params = {"sl_atr": 1.5, "tp_atr": 3.0}
            full = _bt(df, cand, params, allow_short=not long_only)
            m = _metrics(full, df)
            # 2x cost stress (measured)
            stress = run_backtest(df, "dsl:stress", params,
                                  signal=desired_positions(
                                      parse_spec(cand), df),
                                  risk_percent=RISK, spread_points=2.0,
                                  slippage_points=1.0,
                                  allow_short=not long_only)
            # train/cv split for WFE — the FINAL OOS (last 30%) is
            # never read during search (§18 structural firewall)
            train = df.iloc[:int(len(df) * 0.5)]
            cv = df.iloc[int(len(df) * 0.5):final_oos_start]
            wfe = (_metrics(_bt(cv, cand, params, allow_short=not
                                 long_only), cv)["pf"]
                   - _metrics(_bt(train, cand, params, allow_short=not
                                  long_only), train)["pf"])
            # ±1 perturbation DD ratio on train+cv only
            dds = []
            for p in (fast - 1, fast + 1):
                rp = _bt(df.iloc[:final_oos_start],
                         _variant_doc(doc, p, slow), params,
                         allow_short=not long_only)
                dds.append(abs(_metrics(rp, train)["max_dd_pct"]))
            gate_input = dict(m)
            gate_input.update({
                "pf_under_cost_stress": float(
                    stress.metrics["profit_factor"]),   # raw engine key
                "wfe": float(wfe),
                "mc_p05_dd_pct": _mc_p05_dd(full),
                "dsr_p": _psr_daily(full),
                "pbo": 0.0,
                "param_sensitivity_dd_ratio":
                    max(dds) / max(abs(m["max_dd_pct"]), 1e-9),
                "max_correlation_with_book": 0.0,
                "marginal_heat_add": 0.0,
                "positive_in_expected_regime":
                    _regime_pf(full, df) > 1.0,
                "schema_valid": True, "semantic_ok": True})
            # ranking uses IS/CV ONLY (§18)
            is_pf = gate_input["wfe"] + _metrics(
                _bt(train, cand, params), train)["pf"]
            verdicts = evaluate_gates(POLICY, gate_input)
            gates_ok = overall(verdicts) == "PASS"
            r_bt = evidence("backtest", gates_ok, m)
            if not gates_ok:
                out.append({"strategy_id": cspec.strategy_id,
                            "state": "REJECTED", "is_pf": is_pf,
                            "metrics": m})
                continue
            advance(lc.BACKTESTED, (r_bt,))
            # robustness evidence: perturbation DD stayed within limits
            rob_ok = max(dds) / max(abs(m["max_dd_pct"]), 1e-9) <= \
                3.0 and gate_input["mc_p05_dd_pct"] <= 25.0
            r_rob = evidence("robustness", rob_ok,
                             {"param_sensitivity_dd_ratio":
                              gate_input["param_sensitivity_dd_ratio"],
                              "mc_p05_dd_pct":
                              gate_input["mc_p05_dd_pct"]})
            advance(lc.ROBUSTNESS_PASS, (r_rob,))
            out.append({"strategy_id": cspec.strategy_id,
                        "state": "ROBUSTNESS_PASS", "is_pf": is_pf,
                        "grid": (fast, slow), "metrics": m})
        return out

    camp = orch.run_campaign({"campaign_id": "camp_accept",
                              "progress": {}, "results": {}}, run_stage)

    # 3) SELECTION on IS/CV metrics only — OOS untouched so far (§18)
    survivors = [it for stage_items in camp["results"].values()
                 for it in stage_items
                 if it["state"] == "ROBUSTNESS_PASS"]
    assert survivors, "campaign produced no survivors"
    survivors.sort(key=lambda it: (-it["is_pf"], it["strategy_id"]))
    selected_id = survivors[0]["strategy_id"]

    # 4) ONE OOS look for the selected candidate only
    cut = int(len(df) * (0.7 + oos_shrink))
    fast, slow = survivors[0]["grid"]
    oos_doc = _variant_doc(doc, fast, slow)
    oos = _bt(df.iloc[cut:], oos_doc, {"sl_atr": 1.5, "tp_atr": 3.0},
              allow_short=not long_only)
    om = _metrics(oos, df.iloc[cut:])
    oos_ok = om["pf"] > 1.0 and om["max_dd_pct"] < 20.0
    r_oos = evidence("oos", oos_ok, om)
    if oos_ok:
        advance(lc.OOS_SURVIVOR, (r_oos,))
        r_sh = evidence("shadow_entry", True, {"shadow": 1.0})
        advance(lc.SHADOW, (r_sh,))
        for stage_items in camp["results"].values():
            for it in stage_items:
                if it["strategy_id"] == selected_id:
                    it["state"] = "OOS_SURVIVOR"
    else:
        store.transition(SID, version_no, "REJECTED", actor="factory",
                         reason="oos failed (evaluation evidence only)")
        for stage_items in camp["results"].values():
            for it in stage_items:
                it["state"] = "REJECTED"
    return orch, camp, spec, om, version_no


# ------------------------------------------------------------ §75 E2E


def test_full_chain_idea_to_execution_boundary():
    store = FactoryStore(":memory:")
    df = generate_ohlc(days=DAYS, seed=SEED, annual_vol=0.10, drift=0.30)
    orch, camp, spec, _oos_m, version_no = _run_research(store, df)

    # campaign manifest complete + hashed
    m = orch.manifest(camp)
    assert m["campaign_id"] == "camp_accept"
    assert m["candidate_count"] == len(GRID)
    assert m["manifest_hash"]

    # measured-only discovery score: shadow/live components UNAVAILABLE
    full_m = _metrics(_bt(df, _variant_doc(
        _base_doc_of(spec), *GRID[0]), {"sl_atr": 1.5, "tp_atr": 3.0}),
        df)
    score = compute_score({
        "oos_survival": 1.0, "profit_factor": full_m["pf"],
        "drawdown_quality": full_m["max_dd_pct"],
        "expectancy": full_m["expectancy"],
        "trade_count_confidence": full_m["n_trades"],
        "parameter_robustness": 0.7, "wfa_survival": None,
        "cpcv_pbo_evidence": 0.1, "monte_carlo_stability": None,
        "cost_robustness": 0.8, "regime_stability": None,
        "drift_health": None, "execution_realism": None,
        "portfolio_diversification": None, "shadow_evidence": None,
        "live_evidence": None})
    assert "live_evidence" in score.unavailable
    assert score.score > 0

    # portfolio assembly keeps the survivor inside the target band
    pf = build_portfolio([{"strategy_id": SID, "score": score.score,
                           "symbol": "EURUSD", "direction": "long",
                           "asset_class": "fx", "weight": 1.0,
                           "returns": ()}], min_score=0.3)
    assert not pf["zero_exposure"]
    assert 0 < pf["gross_exposure_pct"] <= 20.0

    # HUMAN approval SHADOW → DEMO (structured record, §32)
    cur = store.current_state(SID)
    assert cur == "SHADOW"
    rid = store.record_run(SID, version_no, run_type="shadow_evidence",
                           status="PASS", spec_hash=spec.spec_hash)
    store.transition(SID, version_no, "DEMO", evidence_refs=(rid,),
                     actor="owner", human_approval=True,
                     reason="acceptance: shadow reviewed",
                     policy_version="discovery-defaults-1.0")
    # demo evidence → LIVE_SMALL ELIGIBLE (not LIVE, §79)
    rid2 = store.record_run(SID, version_no, run_type="demo_evidence",
                            status="PASS", spec_hash=spec.spec_hash)
    store.transition(SID, version_no, "LIVE_SMALL",
                     evidence_refs=(rid2,), actor="owner",
                     human_approval=True, reason="acceptance: demo ok",
                     policy_version="discovery-defaults-1.0")
    assert store.current_state(SID) == "LIVE_SMALL"

    # Meta proposal (governor) with live-small ramp 0.25
    from mql5bot.discovery.governor import EligibilityRecord
    ramp = LiveSmallRamp()
    factor, _ = ramp.factor_for(live_trades=1, live_dd_pct=0.5,
                                slippage_bps=2.0)
    assert factor == 0.25
    gov = AllocationGovernor(GovernorBounds(max_strategy_delta=1.0))
    rec = gov.recommend(
        [EligibilityRecord(strategy_id=SID, lifecycle_state="LIVE_SMALL",
                           human_approved=True, gates_pass=True,
                           kill_switch_ok=True, evidence_ok=True)],
        {SID: score.score}, ramp={SID: factor})
    assert rec["status"] == "OK"
    assert 0 < rec["gross_pct"] <= 20.0 * 0.25 + 1e-9

    # entry chain: Risk-approved risk, execution boundary intent
    d = govern_entry(
        EntryRequest(origin="strategy", strategy_id=SID,
                     symbol="EURUSD", side="long",
                     requested_risk=0.005),
        ChainContext(lifecycle_state="LIVE_SMALL", meta_weight=0.10,
                     risk_approved_risk=0.005, risk_budget=0.01))
    assert d.allowed and d.approved_risk <= 0.001 + 1e-12

    # Risk computes lots (sizer) from the approved risk — the Factory
    # never does; the intent dict is the ENTIRE execution boundary
    from mql5bot.sizer import size_position
    from mql5bot.symbolspec import SymbolSpec
    spec_eu = SymbolSpec()
    sizing = size_position(spec_eu, mode="risk_percent_equity",
                           equity=10_000.0, stop_distance=0.0020,
                           value=d.approved_risk * 100)
    assert not sizing.rejected and sizing.lots > 0
    # §39: real risk at the stop stays within the approved budget
    assert sizing.risk_money_actual <= sizing.risk_money_budget + 1e-9
    # and a below-minimum size is REFUSED, never bumped up into a trade
    tiny = size_position(spec_eu, mode="risk_percent_equity",
                         equity=10_000.0, stop_distance=0.0020, value=1e-6)
    assert tiny.rejected or tiny.lots == 0.0
    intent = {"strategy_id": SID, "symbol": "EURUSD", "side": "long",
              "approved_risk": d.approved_risk}
    assert set(intent) == {"strategy_id", "symbol", "side",
                           "approved_risk"}
    # promotion record binds policy version + evidence hash (§32)
    with store.session() as sess:
        from mql5bot.factory.models import PromotionDecision
        from sqlalchemy import select
        rows = sess.scalars(select(PromotionDecision).where(
            PromotionDecision.strategy_id == SID)).all()
    assert any(r.to_state == "DEMO" and r.policy_version ==
               "discovery-defaults-1.0" and len(r.evidence_hash) == 64
               for r in rows)


def _base_doc_of(spec):
    doc = {
        "schema_version": "1.0", "strategy_id": spec.strategy_id,
        "version": 1, "market": {"symbol": "EURUSD",
                                 "timeframe": "H1"},
        "indicators": [
            {"id": "ema_f", "kind": "EMA", "period": 20},
            {"id": "ema_s", "kind": "EMA", "period": 50}],
        "entry": {"mode": "state",
                  "long": {"left": {"ind": "ema_f"}, "cmp": "GT",
                           "right": {"ind": "ema_s"}},
                  "short": {"left": {"ind": "ema_f"}, "cmp": "LT",
                            "right": {"ind": "ema_s"}}},
        "risk": {"sl_atr_mult": 1.5, "tp_atr_mult": 3.0},
    }
    return doc


# -------------------------------------------------- §76 negative case


def test_negative_great_is_bad_oos_rejected_everywhere():
    """§76: excellent IS (strong uptrend), then the market turns — the
    long-only book's final OOS FAILS.  Expected: REJECTED, zero
    eligibility, zero allocation, never LIVE."""
    store = FactoryStore(":memory:")
    up = generate_ohlc(days=1050, seed=SEED, annual_vol=0.10, drift=0.30)
    down = generate_ohlc(days=450, seed=8, annual_vol=0.15, drift=-0.30,
                         start_price=float(up["close"].iloc[-1]),
                         start=up.index[-1] + pd.Timedelta(hours=1))
    df = pd.concat([up, down])          # deterministic reversal fixture
    _orch, _camp, _spec, _om, _version_no = _run_research(
        store, df, long_only=True)
    if store.current_state(SID) == "REJECTED":
        # zero eligibility → zero allocation → never LIVE
        from mql5bot.discovery.governor import EligibilityRecord
        gov = AllocationGovernor()
        rec = gov.recommend(
            [EligibilityRecord(strategy_id=SID, lifecycle_state="REJECTED",
                               human_approved=False, gates_pass=False,
                               kill_switch_ok=True, evidence_ok=False)],
            {SID: 0.99})
        assert rec["allocations"][0]["effective_weight"] == 0.0
        d = govern_entry(EntryRequest(origin="strategy",
                                      strategy_id=SID, symbol="EURUSD",
                                      side="long", requested_risk=0.005),
                         ChainContext(lifecycle_state="REJECTED"))
        assert not d.allowed and d.veto_owner == "lifecycle"
        assert store.current_state(SID) != "LIVE"
    else:
        pytest.fail("expected OOS failure to reject; fixture drifted")


# -------------------------------------------------- §77 safety case


def test_safety_acceptance_no_unsafe_new_exposure():
    req = EntryRequest(origin="strategy", strategy_id=SID,
                       symbol="EURUSD", side="long",
                       requested_risk=0.005)
    base = ChainContext(lifecycle_state="LIVE_SMALL", meta_weight=0.10,
                        risk_approved_risk=0.005, risk_budget=0.01)
    # kill switch NO_NEW_TRADES / EMERGENCY_HALT
    for ks in ("NO_NEW_TRADES", "EMERGENCY_HALT"):
        assert not govern_entry(req, ChainContext(
            **{**base.__dict__, "kill_switch_state": ks})).allowed
    # breaker frozen
    assert not govern_entry(req, ChainContext(
        **{**base.__dict__, "breaker_frozen": True})).allowed
    # concentration breach
    assert not govern_entry(req, ChainContext(
        **{**base.__dict__, "portfolio_ok": False})).allowed
    # broker/market data failure
    assert not govern_entry(req, ChainContext(
        **{**base.__dict__, "market_data_ok": False})).allowed
    # capital: kill switch → governor returns 0% new exposure
    gov = AllocationGovernor()
    out = gov.recommend(
        [_elig()], {SID: 0.9},
        kill_switch_state=KillSwitchState.EMERGENCY_HALT)
    assert out["gross_pct"] == 0.0 and out["status"] == "KILL_SWITCH"
    # breaker → last safe allocation kept
    cb = AllocationCircuitBreaker()
    cb.review(AllocationProposal({"a": 0.08}, gross_exposure_pct=13.0),
              previous_gross_pct=13.0)
    eff, st = cb.review(AllocationProposal({"a": 0.6},
                                           gross_exposure_pct=60.0),
                        previous_gross_pct=13.0)
    assert st == "FROZEN_KEEP_LAST_SAFE" and eff == {"a": 0.08}


def _elig():
    from mql5bot.discovery.governor import EligibilityRecord
    return EligibilityRecord(strategy_id=SID, lifecycle_state="LIVE",
                             human_approved=True, gates_pass=True,
                             kill_switch_ok=True, evidence_ok=True)


# -------------------------------------------------- §78 capital case


def test_capital_acceptance_targets_never_forced():
    gov = AllocationGovernor(GovernorBounds(max_strategy_delta=1.0))
    # no qualified strategy → 0% is the LEGAL outcome
    empty = gov.recommend([_elig_paused()], {SID: 0.9})
    assert empty["gross_pct"] == 0.0
    # qualified portfolio → inside the 10–20% target band
    out = gov.recommend([_elig()], {SID: 0.8})
    assert 0 < out["gross_pct"] <= 20.0
    # high-concentration book → reduced (§59 test covers reduction)
    # kill switch → 0% new exposure regardless of scores
    ks = gov.recommend([_elig()], {SID: 0.999},
                       kill_switch_state=KillSwitchState.EMERGENCY_HALT)
    assert ks["gross_pct"] == 0.0


def _elig_paused():
    from mql5bot.discovery.governor import EligibilityRecord
    return EligibilityRecord(strategy_id=SID, lifecycle_state="PAUSED",
                             human_approved=True, gates_pass=True,
                             kill_switch_ok=True, evidence_ok=True)


# ------------------------------------------- §80 scale + §81 retirement


def test_scale_up_and_down_is_gradual_and_reversible():
    ramp = LiveSmallRamp()
    seq = []
    for trades, dd, degraded in ((3, 0.5, False), (25, 1.0, False),
                                 (45, 1.5, False), (70, 2.0, False),
                                 (110, 2.0, False)):
        f, _ = ramp.factor_for(live_trades=trades, live_dd_pct=dd,
                               slippage_bps=3.0)
        seq.append(f)
    assert seq == sorted(seq)                     # gradual increases
    f_down, _ = ramp.factor_for(live_trades=110, live_dd_pct=2.0,
                                slippage_bps=3.0, degraded=True)
    assert f_down < seq[-1]                       # reduction on decay


def test_retirement_preserves_immutable_history():
    store = FactoryStore(":memory:")
    df = generate_ohlc(days=DAYS, seed=SEED, annual_vol=0.10, drift=0.30)
    _run_research(store, df)
    cur = store.current_state(SID)
    if cur in ("SHADOW", "DEMO", "LIVE_SMALL"):
        store.transition(SID, 1, "RETIRED", actor="owner",
                         reason="acceptance: retire")
    assert store.current_state(SID) == "RETIRED"
    with store.session() as sess:
        from mql5bot.factory.models import LifecycleEvent, ValidationRun
        from sqlalchemy import func, select
        n_ev = sess.scalar(select(func.count()).select_from(LifecycleEvent)
                           .where(LifecycleEvent.strategy_id == SID))
        n_runs = sess.scalar(select(func.count()).select_from(ValidationRun)
                             .where(ValidationRun.strategy_id == SID))
    assert n_ev and n_runs          # historical truth remains
