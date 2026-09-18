"""Meta Layer EMPIRICAL-GATE tests (mission Phases 2-10, 17, 19-22).

Pins the reduce-only property, the MQL5 seam structure, the ML-9
authority separation, normalization robustness, correlation failure
safety, prior-allocation sensitivity, version binding and restart
safety.  Real-data replay scenarios live in test_meta_replay_real.py.
"""

import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from mql5bot.meta_layer import (
    Activation,
    EligibilityReason,
    MetaConfig,
    MetaFileError,
    MetaLayer,
    MetaState,
    StrategyMetaInput,
    read_allocation_file,
    safe_decision,
    write_allocation_file,
)

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
REPO = __import__("pathlib").Path(__file__).resolve().parents[1]


def _inp(sid="a", signal=1, regime="TREND_UP", **kw):
    base = {"regimes_allowed": frozenset({"TREND_UP"}),
            "regimes_preferred": frozenset({"TREND_UP"}),
            "regimes_forbidden": frozenset(),
            "drift_available": True, "drift_score": 0.0}
    base.update(kw)
    state = base.pop("certification_state", "VERIFIED")
    return StrategyMetaInput(sid, "EURUSD", signal, regime,
                             base.pop("regimes_allowed"),
                             base.pop("regimes_preferred"),
                             base.pop("regimes_forbidden"), state, **base)


def _stats(*ids, e=0.01, n=100):
    return {i: (e, n) for i in ids}


# ---------------------------------------------------------------------------
# Phase 1 / ML-9: the four controls stay distinct
# ---------------------------------------------------------------------------


def test_no_risk_authority_concepts_in_surface():
    """The Meta Layer surface cannot express a daily-loss, drawdown or
    kill-switch AUTHORITY: no such config field, no such input, no
    such computation.  (Eligibility FLAGS named kill_switch arrive as
    external booleans — the layer never computes or owns them.)"""
    import dataclasses
    cfg_fields = {f.name for f in dataclasses.fields(MetaConfig)}
    for banned in ("daily_loss", "drawdown", "kill", "risk_percent",
                   "margin", "heat_limit"):
        assert not any(banned in f for f in cfg_fields), banned
    input_fields = {f.name for f in dataclasses.fields(StrategyMetaInput)}
    assert not any("daily" in f or "drawdown" in f or "risk_pct" in f
                   for f in input_fields)
    src = (REPO / "python/mql5bot/meta_layer.py").read_text()
    # no daily-loss or drawdown arithmetic exists in the module
    for expr in ("daily_loss", "drawdown_pct", "max_daily",
                 "kill_threshold"):
        assert expr not in src, expr


def test_weight_change_limit_is_not_a_loss_limit():
    """The change limit bounds Δweight between decisions; it has no
    relationship to account loss and never gates on P/L."""
    cfg = MetaConfig(max_weight_change=0.2)
    lay = MetaLayer(cfg)
    d1 = lay.decide([_inp("a")], as_of=NOW, returns=None,
                    oos_stats=_stats("a"))
    # a strategy bleeding money still moves at most the change limit —
    # the limit is NOT a loss response, it is an allocation smoothness
    d2 = lay.decide([_inp("a")], as_of=NOW, returns=None,
                    oos_stats=_stats("a", e=-0.09))
    for w in d2.weights:
        assert w.final_weight <= d1.weight_of(w.strategy_id) + 0.2 + 1e-12


# ---------------------------------------------------------------------------
# Phase 3: REDUCE-ONLY — the exact EA seam arithmetic, mirrored
# ---------------------------------------------------------------------------


def _scale_lots(risk_lots: float, weight: float, step: float = 0.01,
                vol_min: float = 0.01) -> float:
    """Deterministic mirror of Mql5Bot.mq5's seam:
    scaled = risk_lots * weight  ->  floor to step  ->
    no trade (< vol_min or > risk-approved).  Mirrors are asserted
    equal to the MQL5 source by tests/test_mql5_sources pins."""
    if weight <= 0.0:
        return 0.0
    scaled = risk_lots * weight
    floored = math.floor(scaled / step + 1e-9) * step
    if floored < vol_min or floored > risk_lots:
        return 0.0
    return floored


@pytest.mark.parametrize("weight", [1.0, 0.8, 0.5, 0.1, 0.0])
@pytest.mark.parametrize("risk_lots", [10.0, 2.5, 0.5, 0.05, 0.0])
def test_reduce_only_lot_grid(weight, risk_lots):
    final = _scale_lots(risk_lots, weight)
    assert final <= risk_lots + 1e-12          # THE reduce-only property
    if weight == 0.0 or risk_lots == 0.0:
        assert final == 0.0                    # zero weight => no trade
    if 0.0 < weight < 1.0:
        assert final <= risk_lots * weight + 1e-12  # respects the intent


def test_meta_weights_never_scale_up(monkeypatch):
    """Every weight the layer can emit is in [0, 1] for any hostile
    factor input — so lot scaling can never exceed the risk-approved
    size."""
    hostile = [
        _inp("a", drift_score=0.49),
        _inp("b", certification_state="SOFTWARE_PASS"),
        _inp("c", certification_state="EMPIRICAL_VALIDATION_PENDING"),
    ]
    rets = pd.DataFrame(
        {"a": np.linspace(0, 1, 60), "b": np.linspace(1, 0, 60),
         "c": np.sin(np.linspace(0, 6, 60))},
        index=pd.date_range("2026-01-01", periods=60, freq="h"))
    stats = {"a": (0.02, 200), "b": (-0.02, 200), "c": (100.0, 50)}
    d = MetaLayer(MetaConfig()).decide(hostile, as_of=NOW, returns=rets,
                                       oos_stats=stats)
    for w in d.weights:
        assert 0.0 <= w.final_weight <= 1.0
        assert math.isfinite(w.final_weight)


# ---------------------------------------------------------------------------
# Phase 4: MQL5 seam structure (source-level pins)
# ---------------------------------------------------------------------------


def test_seam_structure_in_source():
    ea = (REPO / "mql5/Experts/Mql5Bot/Mql5Bot.mq5").read_text()
    alloc = (REPO / "mql5/Include/Mql5Bot/Allocation.mqh").read_text()
    # 1. risk engine computes lots FIRST, meta scales AFTER
    lots_pos = ea.index("g_risk.GetLots(")
    scale_pos = ea.index("g_alloc.ScaleLots(")
    assert lots_pos < scale_pos
    # 2. final lots re-normalized DOWN to the broker grid
    assert "MathFloor(lots / g_spec.volumeStep" in ea
    # 3. below-minimum meta size means NO TRADE (never force volume_min)
    assert "metaLots < g_spec.volumeMin" in ea
    # 4. guard against exceeding the risk-approved size
    assert "metaLots > riskApproved" in ea
    # 5. no order API may originate in Allocation
    for banned in ("OrderSend", "CTrade", "OrderCalcMargin",
                   "PositionOpen"):
        assert banned not in alloc, banned
    # 6. the kill switch stays upstream (risk eligibility flag path)
    ml_src = (REPO / "python/mql5bot/meta_layer.py").read_text()
    assert "KILL_SWITCH" in ml_src


def test_zero_weight_means_no_new_trade_behaviorally():
    d = MetaLayer(MetaConfig()).decide(
        [_inp("a", signal=1)], as_of=NOW, returns=None,
        oos_stats=_stats("a"))
    assert d.weight_of("a") > 0.0 and d.book
    # weight zero (kill switch) => no book contribution at all
    d0 = MetaLayer(MetaConfig()).decide(
        [_inp("a", signal=1, kill_switch=True)], as_of=NOW)
    assert d0.weight_of("a") == 0.0 and d0.book == []


# ---------------------------------------------------------------------------
# Phase 5: normalization robustness (hostile sweep)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_perf", [float("nan"), float("inf"),
                                      -float("inf"), -1e308, 1e308])
def test_no_nan_inf_or_out_of_range_weights_from_hostile_stats(bad_perf):
    with __import__("warnings").catch_warnings():
        __import__("warnings").simplefilter("ignore")
        d = MetaLayer(MetaConfig()).decide(
            [_inp("a"), _inp("b")], as_of=NOW, returns=None,
            oos_stats={"a": (bad_perf, 100), "b": (0.0, 100)})
    for w in d.weights:
        assert math.isfinite(w.final_weight)
        assert 0.0 <= w.final_weight <= 1.0
    # canonical serialization REFUSES non-finite values anywhere
    from mql5bot.meta_layer import MetaError, canonical_json
    with pytest.raises(MetaError):
        canonical_json({"x": float("nan")})


def test_no_order_dependence_and_deterministic_floats():
    inputs = [_inp("a"), _inp("b"), _inp("c")]
    rets = pd.DataFrame(
        {i: np.random.default_rng(k + 1).normal(0, 1, 60)
         for k, i in enumerate("abc")},
        index=pd.date_range("2026-01-01", periods=60, freq="h"))
    kw = {"as_of": NOW, "returns": rets,
          "oos_stats": _stats("a", "b", "c")}
    j1 = MetaLayer(MetaConfig()).decide(inputs, **kw).canonical_json()
    j2 = MetaLayer(MetaConfig()).decide(
        list(reversed(inputs)), **kw).canonical_json()
    j3 = MetaLayer(MetaConfig()).decide(inputs, **kw).canonical_json()
    assert j1 == j2 == j3


# ---------------------------------------------------------------------------
# Phase 6/7: correlation — prior sensitivity, negative corr, partial loss
# ---------------------------------------------------------------------------


def test_different_previous_allocations_change_penalties_monotonically():
    """A concentrated prior on B must penalize B's correlated partner A
    more than an equal prior does."""
    idx = pd.date_range("2026-01-01", periods=80, freq="h")
    x = np.linspace(0, 1, 80)
    rets = pd.DataFrame({"a": x, "b": x}, index=idx)  # corr(a,b)=+1
    equal_state = MetaState(config_hash=MetaConfig().config_hash,
                            weights={"a": 0.5, "b": 0.5})
    conc_state = MetaState(config_hash=MetaConfig().config_hash,
                           weights={"a": 0.0, "b": 1.0})
    outs = []
    for state in (equal_state, conc_state):
        lay = MetaLayer(MetaConfig(), state=state)
        d = lay.decide([_inp("a"), _inp("b")], as_of=NOW, returns=rets,
                       oos_stats=_stats("a", "b"))
        pen = {r.strategy_id: next(f.value for f in r.factors
                                   if f.name == "correlation_penalty")
               for r in d.raw_scores}
        outs.append(pen)
    # equal prior 0.5 on the perfectly correlated partner: pen_a = 1-0.5*1 = 0.5;
    # concentrated prior 1.0 on b: pen_a = 0.0 -> floored at 0.1
    assert outs[1]["a"] < outs[0]["a"]
    assert outs[1]["a"] == pytest.approx(0.1, abs=1e-9)
    assert outs[0]["a"] == pytest.approx(0.5, abs=1e-9)


def test_negative_correlation_is_never_penalized():
    idx = pd.date_range("2026-01-01", periods=80, freq="h")
    x = np.linspace(0, 1, 80)
    rets = pd.DataFrame({"a": x, "b": -x}, index=idx)  # corr = -1
    lay = MetaLayer(MetaConfig())
    d = lay.decide([_inp("a"), _inp("b")], as_of=NOW, returns=rets,
                   oos_stats=_stats("a", "b"))
    pens = [f.value for r in d.raw_scores for f in r.factors
            if f.name == "correlation_penalty"]
    assert all(p == pytest.approx(1.0, abs=1e-9) for p in pens)


@pytest.mark.filterwarnings(
    "ignore:invalid value encountered in divide:RuntimeWarning")
def test_one_missing_pair_is_flag_not_global_failure():
    """3 candidates where ONE has no usable overlap: that strategy is
    flagged, the other two correlate normally, NO global fallback."""
    idx = pd.date_range("2026-01-01", periods=80, freq="h")
    rng = np.random.default_rng(3)
    rets = pd.DataFrame({
        "a": rng.normal(0, 1, 80),
        "b": rng.normal(0, 1, 80),
        # c: present but flat (zero variance) -> corr undefined for
        # (a,c) and (b,c); (a,b) remains valid
        "c": np.zeros(80)}, index=idx)
    mat, status, gf = MetaLayer.correlation_matrix(rets, ["a", "b", "c"],
                                                   as_of=NOW)
    assert gf is False
    assert status["a"] is status["b"]
    from mql5bot.meta_layer import FactorStatus
    assert status["a"] is FactorStatus.OK
    assert status["c"] is FactorStatus.MISSING_FALLBACK
    assert mat.loc["a", "b"] != 0.0
    assert mat.loc["a", "c"] == 0.0            # no evidence -> no penalty
    # the decision uses the valid pair and only flags c
    d = MetaLayer(MetaConfig()).decide(
        [_inp("a"), _inp("b"), _inp("c")], as_of=NOW, returns=rets,
        oos_stats=_stats("a", "b", "c"))
    assert d.fallback == ()                    # NOT equal_weight


# ---------------------------------------------------------------------------
# Phase 8: performance factor source isolation
# ---------------------------------------------------------------------------


def test_performance_factor_is_oos_ledger_only():
    """The input type carries (mean, n) OOS trade stats ONLY — there is
    no field that could carry IS/training/certification metrics."""
    import dataclasses
    fields = {f.name for f in dataclasses.fields(StrategyMetaInput)}
    assert not any("is_" in f or "train" in f or "in_sample" in f
                   or "cert_metric" in f for f in fields)
    # and the winsorized shrinkage still beats luck (Phase 8 stress)
    lucky = MetaLayer._performance_factor(_inp("l"), {"l": (0.5, 5)})
    normal = MetaLayer._performance_factor(_inp("n"), {"n": (0.01, 300)})
    assert normal.value > lucky.value


# ---------------------------------------------------------------------------
# Phase 9/10: regime + drift fail-safes (gate restatement)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime,expect", [
    ("TREND_UP", "positive"), ("TREND_DOWN", "zero"),
    ("RANGE", "zero"), ("HIGH_VOL", "zero"), ("LOW_VOL", "zero"),
    ("TRANSITION", "zero"), ("UNKNOWN_X", "zero"),
])
def test_regime_failsafe_matrix(regime, expect):
    d = MetaLayer(MetaConfig()).decide(
        [_inp("a", regime=regime)], as_of=NOW, returns=None,
        oos_stats=_stats("a"))
    if expect == "positive":
        assert d.weight_of("a") > 0.0
    else:
        assert d.weight_of("a") == 0.0
        assert d.eligibility["a"].reason in (
            EligibilityReason.REGIME_UNKNOWN,
            EligibilityReason.REGIME_FORBIDDEN)


def test_drift_missing_is_bounded_never_free():
    d = MetaLayer(MetaConfig()).decide(
        [_inp("a"), _inp("m", drift_available=False)],
        as_of=NOW, returns=None, oos_stats=_stats("a", "m", e=0.0))
    fd = next(f for r in d.raw_scores if r.strategy_id == "m"
              for f in r.factors if f.name == "drift_factor")
    assert fd.value == 0.5 and fd.status.value == "MISSING_FALLBACK"
    # 0.5 is BELOW the healthy 1.0: missing telemetry is a penalty, not
    # a pass — m cannot outrun an identical fully-monitored peer
    assert d.weight_of("m") < d.weight_of("a")


# ---------------------------------------------------------------------------
# Phase 20/21: restart + version binding
# ---------------------------------------------------------------------------


def test_activation_state_survives_restart():
    lay = MetaLayer(MetaConfig(), Activation.SHADOW)
    lay.decide([_inp("a")], as_of=NOW, returns=None, oos_stats=_stats("a"))
    restored = MetaLayer(MetaConfig(), state=MetaState.deserialize(
        lay.state.serialize()))
    assert restored.activation is Activation.SHADOW


def test_strategy_versions_flow_into_decision_and_file(tmp_path):
    d = MetaLayer(MetaConfig()).decide(
        [_inp("v1", signal=1, strategy_version="2.5.0"),
         _inp("v2", signal=-1, strategy_version="0.9.1")],
        as_of=NOW, returns=None, oos_stats=_stats("v1", "v2"))
    assert d.strategy_versions == {"v1": "2.5.0", "v2": "0.9.1"}
    path = tmp_path / "allocation.json"
    write_allocation_file(d, path)
    body = read_allocation_file(path, now=NOW)
    assert body["strategy_versions"] == {"v1": "2.5.0", "v2": "0.9.1"}
    # a decision for a CHANGED strategy version is distinguishable
    d2 = MetaLayer(MetaConfig()).decide(
        [_inp("v1", signal=1, strategy_version="2.6.0")],
        as_of=NOW, returns=None, oos_stats=_stats("v1"))
    assert d2.strategy_versions != d.strategy_versions


def test_stale_or_corrupt_state_fails_safe():
    lay = MetaLayer(MetaConfig(), Activation.SHADOW)
    lay.decide([_inp("a")], as_of=NOW, returns=None, oos_stats=_stats("a"))
    good = lay.state.serialize()
    # corrupt digest -> refused, never applied
    obj = json.loads(good)
    obj["body"]["weights"]["a"] = 0.99
    with pytest.raises(MetaFileError):
        MetaState.deserialize(json.dumps(obj))
    # truncated -> refused
    with pytest.raises(MetaFileError):
        MetaState.deserialize("{oops")
    # and safe_decision still holds on any internal failure
    decision, exc = safe_decision(lay, None, as_of=NOW)  # type: ignore
    assert exc is not None and decision.fallback == ("failure_safe",)
