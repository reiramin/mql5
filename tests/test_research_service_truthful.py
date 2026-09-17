"""Regression tests for the research-service truthfulness fixes
(mission FINAL-WAVE P0 — "no fabricated PASS").

These pin the behaviour that used to be violated by hard-coded gate
inputs in ``discovery/research_service.py``:

  * ``"pbo": 0.0`` — a searched grid now measures a REAL PBO via
    combinatorial purged CV; an overfitting search is rejected, never
    passed by an injected 0.0.
  * ``"positive_in_expected_regime": True`` — measured from a causal
    regime partition, not asserted.
  * ``"max_correlation_with_book"/"marginal_heat_add": 0.0`` — measured
    against the actual book (empty ⇒ honest 0.0, non-empty ⇒ real).
  * score ``cpcv_pbo_evidence: 0.1`` — derived from the measured PBO.
  * every evidence run is bound to the SELECTED variant's own spec_hash,
    never a base spec that was not the one measured.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from mql5bot.data import generate_ohlc
from mql5bot.discovery import research_metrics as rm
from mql5bot.discovery.research_service import ResearchService
from mql5bot.factory.models import StrategyVersion, ValidationRun
from mql5bot.factory.store import FactoryStore, StoreError
from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
POLICY = yaml.safe_load((ROOT / "factory" / "gates.fixture.yaml").read_text())
IDEA = ("Buy when EMA20 crosses above EMA50 and RSI is above 55. "
        "Use an ATR-based stop of 1.5 ATR and a 3 ATR target.")
MK = {"symbol": "EURUSD", "timeframe": "H1"}


def _run(store, df, **kw):
    svc = ResearchService(store, gate_policy=POLICY,
                          gate_policy_version="fixture")
    return svc.run_idea(IDEA, df, market=MK, **kw)


# ---------------------------------------------------------------- no fake PBO


def test_overfitting_search_measures_real_pbo_and_is_rejected():
    """A grid search over a marginal-edge fixture genuinely overfits:
    the MEASURED PBO is high (≫ 0), gate-6 blocks, and the strategy is
    NEVER promoted to SHADOW.  The old ``pbo=0.0`` would have forced a
    pass."""
    store = FactoryStore(":memory:")
    df = generate_ohlc(days=1500, seed=7, annual_vol=0.10, drift=0.30)
    res = _run(store, df, campaign_id="camp_of")
    ch = res["evidence_chain"]
    assert ch["pbo"] is not None
    assert ch["pbo"] > 0.5                      # real overfitting, not 0.0
    assert res["outcome"] != "OOS_SURVIVOR"
    assert store.current_state(ch["strategy_id"]) != "SHADOW"
    # the measured PBO is recorded as evidence (a real number, not 0.0)
    from mql5bot.factory.models import ValidationMetric
    with store.session() as s:
        vals = [m.value for m in s.scalars(
            select(ValidationMetric).where(ValidationMetric.name == "pbo"))]
    assert vals and all(v > 0.0 for v in vals)


def test_backtest_fail_evidence_never_promotes():
    """The overfitting run records a FAIL backtest evidence; a FAIL
    record can never carry the strategy past VALIDATED (store boundary
    §28.15)."""
    store = FactoryStore(":memory:")
    df = generate_ohlc(days=1500, seed=7, annual_vol=0.10, drift=0.30)
    ch = _run(store, df, campaign_id="camp_fail")["evidence_chain"]
    with store.session() as s:
        bt = list(s.scalars(select(ValidationRun).where(
            ValidationRun.strategy_id == ch["strategy_id"],
            ValidationRun.run_type == "backtest")))
    assert bt and bt[0].status == "FAIL"
    assert store.current_state(ch["strategy_id"]) in (
        "VALIDATED", "REJECTED")


def test_every_evidence_run_binds_selected_variant_identity():
    """No evidence is recorded against a base spec that was not the one
    measured: every run's spec_hash equals the registered version's
    (the SELECTED variant), and the chain reports that identity."""
    store = FactoryStore(":memory:")
    df = generate_ohlc(days=1500, seed=7, annual_vol=0.10, drift=0.30)
    ch = _run(store, df, campaign_id="camp_id")["evidence_chain"]
    with store.session() as s:
        ver = s.scalar(select(StrategyVersion).where(
            StrategyVersion.strategy_id == ch["strategy_id"]))
        runs = list(s.scalars(select(ValidationRun).where(
            ValidationRun.strategy_id == ch["strategy_id"])))
    assert ver is not None
    assert ch["spec_hash"] == ver.spec_hash
    assert runs and all(r.spec_hash == ver.spec_hash for r in runs)


def test_source_has_no_fabricated_gate_inputs():
    """Belt-and-suspenders: the exact fabricated literals the mission
    forbids must not reappear in the service source."""
    src = (ROOT / "python" / "mql5bot" / "discovery"
           / "research_service.py").read_text()
    for forbidden in ('"pbo": 0.0',
                      '"positive_in_expected_regime": True',
                      '"max_correlation_with_book": 0.0',
                      '"marginal_heat_add": 0.0',
                      '"cpcv_pbo_evidence": 0.1'):
        assert forbidden not in src, forbidden


# ------------------------------------------------------- measured-module units


def test_cpcv_pbo_unavailable_for_single_or_short_series():
    idx = pd.date_range("2024-01-01", periods=40, freq="D")
    one = [pd.Series(np.linspace(0, 1, 40), index=idx)]
    assert rm.cpcv_pbo(one) is None                 # <2 configs → unavailable
    short = [pd.Series(np.arange(4), index=idx[:4]),
             pd.Series(np.arange(4), index=idx[:4])]
    assert rm.cpcv_pbo(short) is None               # <8 periods → unavailable


def test_cpcv_pbo_measures_a_probability():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=120, freq="D")
    cols = [pd.Series(rng.normal(0, 1, 120), index=idx) for _ in range(4)]
    pbo = rm.cpcv_pbo(cols)
    assert pbo is not None and 0.0 <= pbo <= 1.0


def test_portfolio_interaction_empty_book_is_measured_zero():
    idx = pd.date_range("2024-01-01", periods=50, freq="D")
    cand = pd.Series(np.random.default_rng(1).normal(0, 1, 50), index=idx)
    assert rm.portfolio_interaction(cand, []) == (0.0, 0.0)


def test_portfolio_interaction_correlated_book_is_measured_nonzero():
    idx = pd.date_range("2024-01-01", periods=50, freq="D")
    a = pd.Series(np.random.default_rng(2).normal(0, 1, 50), index=idx)
    book = [a * 1.0]                                # perfectly correlated
    corr, heat = rm.portfolio_interaction(a, book)
    assert corr > 0.99 and heat > 0.0


def test_walk_forward_efficiency_is_the_contract_ratio_not_a_pf_delta():
    """gate-5 WFE must be the CONTRACT ratio (held-out return / IS return,
    WFA_CONTRACT §6), NOT the old ``cv_pf - train_pf`` profit-factor delta
    (mission P0 — never a misleading certification metric name)."""
    class _Res:
        def __init__(self, ret):
            self.metrics = {"total_return_pct": ret}
    # 12% held-out on 6% in-sample → WFE 2.0 (retained 2x the IS edge)
    assert rm.walk_forward_efficiency(_Res(6.0), _Res(12.0)) == pytest.approx(2.0)
    # negative held-out → negative WFE (blocked by min_wfe=0 gate)
    assert rm.walk_forward_efficiency(_Res(6.0), _Res(-3.0)) == pytest.approx(-0.5)


def test_walk_forward_efficiency_unset_when_is_leg_non_positive():
    """A non-positive in-sample leg makes efficiency undefined: return
    None so the caller leaves gate-5 unset → gate SKIPs (blocks), never a
    fabricated pass."""
    class _Res:
        def __init__(self, ret):
            self.metrics = {"total_return_pct": ret}
    assert rm.walk_forward_efficiency(_Res(0.0), _Res(5.0)) is None
    assert rm.walk_forward_efficiency(_Res(-2.0), _Res(5.0)) is None
    assert rm.walk_forward_efficiency(_Res(None), _Res(5.0)) is None


def test_service_source_has_no_pf_delta_wfe():
    """Belt-and-suspenders: the old misleading ``cv_pf - train_pf`` WFE
    must not reappear; the gate-5 input comes from the canonical
    walk_forward_efficiency measurement."""
    src = (ROOT / "python" / "mql5bot" / "discovery"
           / "research_service.py").read_text()
    assert "cv_pf - train_pf" not in src
    assert "rm.walk_forward_efficiency(" in src


def test_dsr_p_unavailable_for_too_few_observations():
    class _Res:
        equity = pd.Series([1.0, 1.01],
                           index=pd.date_range("2024-01-01", periods=2,
                                               freq="h"))
    assert rm.dsr_p_daily(_Res()) is None


def test_failed_robustness_evidence_cannot_promote_store_boundary():
    """The store is the boundary: a FAIL robustness run can never promote
    BACKTESTED → ROBUSTNESS_PASS (mission P0-evidence-binding)."""
    from mql5bot.dsl.parse import parse_spec
    from mql5bot.factory import lifecycle as lc

    from tests.test_dsl_core import _base_doc
    store = FactoryStore(":memory:")
    doc = _base_doc()
    doc["strategy_id"] = "boundary_strat"
    spec = parse_spec(doc)
    store.register_strategy(spec, created_by="t")
    for rtype, target in (("parse", lc.PARSED), ("schema", lc.VALIDATED)):
        rid = store.record_run("boundary_strat", 1, run_type=rtype,
                               status="PASS", spec_hash=spec.spec_hash)
        store.transition("boundary_strat", 1, target,
                         evidence_refs=(rid,), actor="factory")
    rid = store.record_run("boundary_strat", 1, run_type="backtest",
                           status="PASS", spec_hash=spec.spec_hash)
    store.transition("boundary_strat", 1, lc.BACKTESTED,
                     evidence_refs=(rid,), actor="factory")
    bad = store.record_run("boundary_strat", 1, run_type="robustness",
                           status="FAIL", spec_hash=spec.spec_hash)
    with pytest.raises(StoreError):
        store.transition("boundary_strat", 1, lc.ROBUSTNESS_PASS,
                         evidence_refs=(bad,), actor="factory")
    assert store.current_state("boundary_strat") == lc.BACKTESTED
