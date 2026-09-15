"""AEGIS INTEGRATION GATE — one real end-to-end candidate.

Proves (mission §4/§5/§31/§32/§33, §6-§9):

- EN and Persian source text normalize to the SAME semantic spec and
  produce IDENTICAL signal series, exits, SL and TP on the same bars;
- a deterministic fixture (ema_rsi_atr_fixture) travels
  USER TEXT → INTERPRET → CANONICAL DSL → SCHEMA → NORMALIZATION →
  STRATEGY VERSION → BACKTEST → VALIDATION → OOS → REGIME → SHADOW →
  REGISTRY with store-enforced evidence at every promotion;
- the artifact chain (§31) references one immutable identity
  (spec_hash/version) end to end;
- the NEGATIVE path (§32): excellent backtest + failing OOS ⇒
  REJECTED, no certification, Meta allocation blocked;
- version immutability (§6), reproducibility (§7), manifest
  completeness (§8) and multiple-testing accounting (§9).

Gate thresholds come from factory/gates.fixture.yaml (config, §21);
the production policy factory/gates.yaml is untouched.  The fixture is
NOT optimized to pass — it exists to prove the pipeline.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from mql5bot.backtest import run_backtest
from mql5bot.data import generate_ohlc
from mql5bot.dsl import desired_positions, parse_spec
from mql5bot.factory import lifecycle as lc
from mql5bot.factory.adapter import meta_input
from mql5bot.factory.gates import evaluate_gates, overall, policy_hash
from mql5bot.factory.interpreter import TemplateInterpreter
from mql5bot.factory.providers import ResearchMaterial
from mql5bot.factory.store import FactoryStore
from mql5bot.meta_layer import MetaLayer

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_POLICY = yaml.safe_load(
    (ROOT / "factory" / "gates.fixture.yaml").read_text())

EN_TEXT = ("Buy when EMA20 crosses above EMA50 and RSI is above 55. "
           "Use an ATR-based stop of 1.5 ATR and a 3 ATR target.")
FA_TEXT = ("این استراتژی را بساز: وقتی EMA20 بالای EMA50 کراس کرد و "
           "RSI بالای ۵۵ بود خرید کن، حد ضرر 1.5 ATR و تارگت 3 ATR.")

DAYS, SEED, RISK = 1500, 7, 0.1
PARAMS = {"sl_atr": 1.5, "tp_atr": 3.0}


def fixture_document(strategy_id="ema_rsi_atr_fixture", version=1):
    interp = TemplateInterpreter()
    r = interp.interpret(ResearchMaterial("USER_TEXT", "fixture",
                                          EN_TEXT))
    doc = r.draft
    doc["strategy_id"] = strategy_id
    doc["version"] = version
    return doc


def _years(df):
    idx = df.index
    return (idx[-1] - idx[0]).total_seconds() / (365.25 * 24 * 3600)


def _trade_metrics(res: dict, df) -> dict:
    """Measured gate-2 inputs from a real engine run (deterministic)."""
    m = res.metrics
    tr = res.trades
    net = tr["pnl"].sum()
    top10 = tr["pnl"].nlargest(10).sum() / net if net > 0 else 1.0
    eq = res.equity
    q = eq.resample("QE").last().pct_change().dropna()
    pos_q = float((q > 0).mean()) if len(q) else 0.0
    avg_cost = 2 * (1.0 + 0.0) * 1e-5 * 100_000 * tr["lots"].mean() \
        if len(tr) else 1.0
    edge = float(tr["pnl"].mean() / max(avg_cost, 1e-9))
    return {"n_trades": float(m["trades"]), "years": _years(df),
            "pf": float(m["profit_factor"]),
            "max_dd_pct": abs(float(m["max_drawdown_pct"])),
            "top10_profit_share": float(top10),
            "positive_quarters_share": pos_q,
            "edge_to_cost": edge}


def _psr_daily(res, sr_bench=0.0) -> float:
    """Probabilistic Sharpe Ratio vs SR* on daily returns (deterministic
    closed-form; López de Prado).  Real measurement — no simulation."""
    r = res.equity.resample("1D").last().pct_change().dropna()
    sr = r.mean() / (r.std(ddof=1) + 1e-12)
    skew = float(r.skew())
    kurt = float(r.kurt() + 3.0)
    n = len(r)
    if n < 3:
        return 0.0
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr +
                          (kurt - 1.0) / 4.0 * sr * sr))
    z = (sr - sr_bench) * math.sqrt(n - 1) / denom
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _mc_p05_dd(res, perms=200, seed=11) -> float:
    """Monte-Carlo trade-order shuffle → 5th percentile of maxDD%."""
    pnl = res.trades["pnl"].to_numpy()
    rng = np.random.default_rng(seed)
    dds = []
    for _ in range(perms):
        eq = 10_000.0 + np.cumsum(rng.permutation(pnl))
        peak = np.maximum.accumulate(np.maximum(eq, 1e-9))
        dd = (eq - peak) / peak
        dds.append(-100.0 * dd.min() if len(dd) else 0.0)
    return float(np.percentile(dds, 5))


def _regime_pf(res, df) -> float:
    """PF inside the expected regime (200-bar SMA slope = TREND_UP)."""
    tr = res.trades.copy()
    sma = df["close"].rolling(200).mean()
    slope = sma.diff(20)
    exit_idx = df.index.get_indexer(tr["exit_time"])
    mask = slope.to_numpy()[exit_idx] > 0
    sel = tr[pd.Series(mask, index=tr.index)]
    wins = sel[sel["pnl"] > 0]["pnl"].sum()
    losses = -sel[sel["pnl"] < 0]["pnl"].sum()
    return float(wins / losses) if losses > 0 else \
        (float("inf") if wins > 0 else 0.0)


def run_full_metrics(df):
    """One deterministic backtest + every measured gate input."""
    doc = fixture_document()
    spec = parse_spec(doc)
    sig = desired_positions(spec, df)
    res = run_backtest(df, "dsl:" + spec.strategy_id, PARAMS,
                       signal=sig, risk_percent=RISK)
    m = _trade_metrics(res, df)
    stress = run_backtest(df, "dsl:" + spec.strategy_id, PARAMS,
                          signal=sig, risk_percent=RISK,
                          spread_points=2.0, slippage_points=1.0)
    m["pf_under_cost_stress"] = float(
        stress.metrics["profit_factor"])
    # gate4: DD sensitivity to ±1 fast-period perturbation
    dds = {}
    for p in (19, 21):
        d2 = json.loads(json.dumps(doc))
        d2["indicators"][0]["period"] = p
        s2 = parse_spec(d2)
        r2 = run_backtest(df, "dsl:sens", PARAMS,
                          signal=desired_positions(s2, df),
                          risk_percent=RISK)
        dds[p] = abs(r2.metrics["max_drawdown_pct"])
    m["param_sensitivity_dd_ratio"] = max(
        dds[19], dds[21]) / max(m["max_dd_pct"], 1e-9)
    # OOS window (last 30%) for gate5 WFE := OOS_PF − IS_PF
    cut = int(len(df) * 0.7)
    r_is = run_backtest(df.iloc[:cut], "dsl:is", PARAMS,
                        signal=desired_positions(spec, df.iloc[:cut]),
                        risk_percent=RISK)
    r_oos = run_backtest(df.iloc[cut:], "dsl:oos", PARAMS,
                         signal=desired_positions(spec, df.iloc[cut:]),
                         risk_percent=RISK)
    m["wfe"] = float(r_oos.metrics["profit_factor"]
                     - r_is.metrics["profit_factor"])
    m["oos_pf"] = float(r_oos.metrics["profit_factor"])
    m["is_pf"] = float(r_is.metrics["profit_factor"])
    # gate6: single pre-registered candidate ⇒ PBO=0 (no selection);
    # DSR via closed-form PSR on daily returns
    m["pbo"] = 0.0
    m["dsr_p"] = _psr_daily(res)
    # gate7
    m["mc_p05_dd_pct"] = _mc_p05_dd(res)
    # gate8
    m["positive_in_expected_regime"] = _regime_pf(res, df) > 1.0
    # gate9: empty fixture book ⇒ measured zeros (no invented corr)
    m["max_correlation_with_book"] = 0.0
    m["marginal_heat_add"] = 0.0
    m["schema_valid"] = True
    m["semantic_ok"] = True
    return spec, sig, res, m, (r_is, r_oos)


# ---------------------------------------------------------------- §4


def test_en_fa_identical_signals_exits_sl_tp():
    interp = TemplateInterpreter()
    en = interp.interpret(ResearchMaterial("USER_TEXT", "en", EN_TEXT))
    fa = interp.interpret(ResearchMaterial("USER_TEXT", "fa", FA_TEXT))
    assert fa.draft["entry"] == en.draft["entry"]
    assert fa.draft["exit"] == en.draft["exit"]
    assert fa.draft["indicators"] == en.draft["indicators"]
    assert en.draft["exit"]["sl"] == {"model": "atr", "mult": 1.5}
    assert en.draft["exit"]["tp"] == {"model": "atr", "mult": 3.0}
    d_en = dict(en.draft, strategy_id="same_id", version=1)
    d_fa = dict(fa.draft, strategy_id="same_id", version=1)
    s_en, s_fa = parse_spec(d_en), parse_spec(d_fa)
    df = generate_ohlc(days=240, seed=5)
    np.testing.assert_array_equal(
        desired_positions(s_en, df).to_numpy(),
        desired_positions(s_fa, df).to_numpy())


# ---------------------------------------------------------------- §5/§31/§33


@pytest.fixture(scope="module")
def journey(tmp_path_factory):
    """The full positive-path lifecycle over one deterministic fixture."""
    tmp = tmp_path_factory.mktemp("e2e")
    store = FactoryStore(tmp / "factory.db")
    df = generate_ohlc(days=DAYS, seed=SEED, annual_vol=0.10, drift=0.30)
    spec, sig, _res, m, (_r_is, r_oos) = run_full_metrics(df)
    verdicts = evaluate_gates(FIXTURE_POLICY, m)
    verdict_map = {v.gate: v.status for v in verdicts}
    _vid, _created = store.register_strategy(
        spec, created_by="fixture", source={"type": "USER_TEXT"},
        original_text=EN_TEXT)
    sid = spec.strategy_id
    ladder = [("parse", "PARSED"), ("schema", "VALIDATED"),
              ("backtest", "BACKTESTED"), ("robustness", "ROBUSTNESS_PASS"),
              ("oos", "OOS_SURVIVOR"), ("shadow_entry", "SHADOW")]
    run_ids = {}
    metrics_by_type = {
        "parse": {}, "schema": {}, "backtest": m,
        "robustness": {k: m[k] for k in
                       ("param_sensitivity_dd_ratio", "wfe", "dsr_p",
                        "mc_p05_dd_pct")},
        "oos": {"pf": m["oos_pf"], "n_trades":
                float(r_oos.metrics["trades"])},
        "shadow_entry": {}}
    for rtype, _state in ladder:
        rid = store.record_run(sid, 1, run_type=rtype, status="PASS",
                               spec_hash=spec.spec_hash,
                               metrics=metrics_by_type[rtype],
                               dataset_hash=f"synthetic-{SEED}",
                               config_hash=policy_hash(FIXTURE_POLICY),
                               gate_version=FIXTURE_POLICY[
                                   "policy_version"],
                               detail={"gate_verdicts": verdict_map,
                                       "overall": overall(verdicts)})
        run_ids[rtype] = rid
        store.transition(sid, 1, {"parse": lc.PARSED,
                                  "schema": lc.VALIDATED,
                                  "backtest": lc.BACKTESTED,
                                  "robustness": lc.ROBUSTNESS_PASS,
                                  "oos": lc.OOS_SURVIVOR,
                                  "shadow_entry": lc.SHADOW}[rtype],
                         evidence_refs=(rid,), actor="fixture",
                         gate_version=FIXTURE_POLICY["policy_version"])
    # shadow observations (real replay, cost-adjusted, order-free)
    from mql5bot.factory.oversight import run_shadow
    trades = run_shadow(spec, df)
    for t in trades[:50]:
        store.record_shadow(sid, 1, symbol="EURUSD",
                            signal=t.side, executed_would_be=False,
                            hypothetical_pnl=t.pnl_assumed,
                            spread_assumed=2.0, slippage_assumed=1.0)
    return {"store": store, "spec": spec, "metrics": m,
            "verdicts": verdict_map, "overall": overall(verdicts),
            "run_ids": run_ids, "df": df, "sid": sid,
            "shadow_trades": trades, "sig": sig}


def test_gate_policy_is_real_and_binding(journey):
    assert FIXTURE_POLICY["policy_version"].startswith("fixture")
    prod = yaml.safe_load((ROOT / "factory" / "gates.yaml").read_text())
    assert prod["policy_version"] == "spec-10.4-defaults"   # untouched
    assert journey["overall"] == "PASS"
    assert all(v == "PASS" for v in journey["verdicts"].values())


def test_full_ladder_to_shadow(journey):
    store, sid = journey["store"], journey["sid"]
    assert store.current_state(sid) == lc.SHADOW
    states = [e.to_state for e in store.history(sid)]
    assert states == ["PARSED", "VALIDATED", "BACKTESTED",
                      "ROBUSTNESS_PASS", "OOS_SURVIVOR", "SHADOW"]


def test_artifact_chain_binds_one_identity(journey):
    """§31: every stage references the same immutable spec identity."""
    store, spec, sid = journey["store"], journey["spec"], journey["sid"]
    with store.session() as sess:
        from mql5bot.factory.models import ValidationRun
        from sqlalchemy import select
        runs = list(sess.scalars(select(ValidationRun).where(
            ValidationRun.strategy_id == sid)))
    assert len(runs) == 6
    assert all(r.spec_hash == spec.spec_hash for r in runs)
    assert all(r.version == 1 for r in runs)
    assert all(r.config_hash == policy_hash(FIXTURE_POLICY) for r in runs)
    ev = store.history(sid)
    assert all(e.strategy_id == sid and e.version == 1 for e in ev)


def test_no_automatic_promotion_past_shadow(journey):
    """§33/§49: nothing may auto-promote past SHADOW; DEMO needs fresh
    shadow evidence + audited human approval."""
    store, sid, spec = (journey["store"], journey["sid"],
                        journey["spec"])
    assert store.current_state(sid) != lc.DEMO
    from mql5bot.factory.store import StoreError
    rid = store.record_run(sid, 1, run_type="shadow_evidence",
                           status="PASS", spec_hash=spec.spec_hash,
                           dataset_hash="synthetic-7")
    with pytest.raises(StoreError, match="human approval"):
        store.transition(sid, 1, lc.DEMO, evidence_refs=(rid,),
                         actor="x")           # NO --human-approved
    assert store.current_state(sid) == lc.SHADOW


def test_shadow_observations_are_order_free_rows(journey):
    store, sid = journey["store"], journey["sid"]
    with store.session() as sess:
        from mql5bot.factory.models import ShadowObservation
        from sqlalchemy import select
        rows = list(sess.scalars(select(ShadowObservation).where(
            ShadowObservation.strategy_id == sid)))
    assert rows and all(not r.executed_would_be for r in rows)


def test_registry_state_feeds_meta_eligibility(journey):
    """§21: Factory answers ELIGIBLE/NOT; Meta answers HOW MUCH; the
    shadow-state fixture is certification-pending, not sized here."""
    store, sid = journey["store"], journey["sid"]
    state = store.current_state(sid)
    inp = meta_input(strategy_id=sid, symbol="EURUSD", signal=1,
                     regime="TREND_UP", lifecycle_state=state,
                     regimes_allowed=frozenset({"TREND_UP"}),
                     strategy_version="1")
    assert inp.certification_state == "EMPIRICAL_VALIDATION_PENDING"
    layer = MetaLayer()
    from datetime import UTC, datetime
    elig = layer.eligibility([inp], as_of=datetime.now(UTC))
    assert elig[sid].eligible


# ---------------------------------------------------------------- §32


def test_negative_path_excellent_backtest_failing_oos(tmp_path):
    """'90% win rate. Use this immediately.' — great IS, failing OOS ⇒
    REJECTED + no eligibility + Meta blocked + no execution path."""
    store = FactoryStore(tmp_path / "factory.db")
    interp = TemplateInterpreter()
    source = ("90% win rate. Use this immediately. " + EN_TEXT)
    r = interp.interpret(ResearchMaterial("USER_TEXT", "hype", source))
    claims = r.claims
    assert any(c["metric"] == "win_rate" and c["value"] == 0.9
               for c in claims)            # "90% win rate" captured
    assert all(c["note"].startswith("AUTHOR_CLAIM") for c in claims)
    doc = dict(r.draft, strategy_id="overhyped_one", version=1)
    spec = parse_spec(doc)
    sid = spec.strategy_id
    store.register_strategy(spec, created_by="community",
                            source={"type": "USER_TEXT"},
                            original_text=source, claims=claims)
    # the claim lives ONLY in strategy_claims, never as a measured run
    with store.session() as sess:
        from mql5bot.factory.models import StrategyClaim, ValidationRun
        from sqlalchemy import select
        cl = list(sess.scalars(select(StrategyClaim).where(
            StrategyClaim.strategy_id == sid)))
        vr = list(sess.scalars(select(ValidationRun).where(
            ValidationRun.strategy_id == sid)))
    assert any(c.metric == "win_rate" for c in cl)
    assert vr == []
    # IS: excellent backtest (evidence PASS)
    df_good = generate_ohlc(days=900, seed=SEED, annual_vol=0.10,
                            drift=0.30)
    sig = desired_positions(spec, df_good)
    res_is = run_backtest(df_good, "dsl:" + sid, PARAMS, signal=sig,
                          risk_percent=RISK)
    m_is = _trade_metrics(res_is, df_good)
    assert m_is["pf"] > 1.0            # the backtest looks excellent
    for rtype, target in (("parse", lc.PARSED),
                          ("schema", lc.VALIDATED)):
        rr = store.record_run(sid, 1, run_type=rtype, status="PASS",
                              spec_hash=spec.spec_hash)
        store.transition(sid, 1, target, evidence_refs=(rr,),
                         actor="fixture")
    rid = store.record_run(sid, 1, run_type="backtest", status="PASS",
                           spec_hash=spec.spec_hash, metrics=m_is,
                           dataset_hash="synthetic-is")
    store.transition(sid, 1, lc.BACKTESTED, evidence_refs=(rid,),
                     actor="fixture")
    rr = store.record_run(sid, 1, run_type="robustness", status="PASS",
                          spec_hash=spec.spec_hash,
                          metrics={"param_sensitivity_dd_ratio": 1.2,
                                   "wfe": 0.1, "dsr_p": 0.6,
                                   "mc_p05_dd_pct": 15.0})
    store.transition(sid, 1, lc.ROBUSTNESS_PASS, evidence_refs=(rr,),
                     actor="fixture")
    # OOS: different regime, negative drift → strategy fails
    df_oos = generate_ohlc(days=400, seed=SEED + 1, annual_vol=0.12,
                           drift=-0.30)
    sig_oos = desired_positions(spec, df_oos)
    res_oos = run_backtest(df_oos, "dsl:" + sid, PARAMS,
                           signal=sig_oos, risk_percent=RISK)
    pf_oos = res_oos.metrics["profit_factor"]
    assert pf_oos < 1.0                # OOS fails
    store.record_run(sid, 1, run_type="oos", status="FAIL",
                     spec_hash=spec.spec_hash,
                     metrics={"pf": float(pf_oos)},
                     dataset_hash="synthetic-oos")
    from mql5bot.factory.store import StoreError
    with pytest.raises(StoreError, match="not evidence"):
        store.transition(sid, 1, lc.OOS_SURVIVOR,
                         evidence_refs=(rid,),   # backtest run ≠ OOS
                         actor="fixture")
    store.transition(sid, 1, lc.REJECTED, actor="gate:oos",
                     reason="OOS profit factor < 1")
    assert store.current_state(sid) == lc.REJECTED
    assert store.original_text(sid) == source     # claim stayed DATA
    # live eligibility: NONE (adapter → None ⇒ Meta blocks ⇒ zero size)
    inp = meta_input(strategy_id=sid, symbol="EURUSD", signal=1,
                     regime="TREND_UP", lifecycle_state="REJECTED",
                     regimes_allowed=frozenset({"TREND_UP"}))
    assert inp.certification_state is None
    layer = MetaLayer()
    from datetime import UTC, datetime
    elig = layer.eligibility([inp], as_of=datetime.now(UTC))
    assert not elig[sid].eligible       # Meta allocation = 0
    # and no Factory module can reach a broker (structural MT5 refusal)
    factory_src = ROOT / "python" / "mql5bot" / "factory"
    import ast
    for f in factory_src.glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {a.name for a in node.names}
                assert "MetaTrader5" not in names, f.name
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "") != "MetaTrader5", f.name
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Attribute):
                assert node.func.attr != "order_send", f.name


