"""ML interfaces (plan Phase E) — stubs raise; risk invariants pinned.

The owner brief: interfaces only, no ML implementations, no training,
no neural networks anywhere.  These tests pin (a) every stub method
raises NotImplementedError, (b) the advisory schema physically cannot
express an SL removal / risk override / new trade / raised limit, and
(c) the invariant checker catches each of the four violations when
adversarial inputs are pushed through the seam.
"""

import re
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pandas as pd
import pytest
from mql5bot.ml_interfaces import (
    FeatureStore,
    MetaLabeler,
    MLAdvice,
    ProbabilityCalibrator,
    RiskContext,
    TripleBarrierLabeler,
    apply_ml_advice,
    check_ml_invariants,
)

_IDX = pd.date_range("2024-01-01", periods=60, freq="h")


def _orders():
    return pd.DataFrame({
        "entry_time": [str(t) for t in _IDX[::20]],
        "side": ["long", "short", "long"],
        "lots": [0.5, 0.3, 0.2],
        "sl": [1.0790, 1.0910, 1.0840],
        "tp": [1.0850, 1.0790, 1.0900],
    })


def _ctx(max_lots: float = 10.0) -> RiskContext:
    return RiskContext(max_lots=max_lots)


# --------------------------------------------------------------------------
# Stubs raise
# --------------------------------------------------------------------------


@pytest.mark.parametrize("call", [
    lambda: TripleBarrierLabeler().label(
        pd.DataFrame(), profit_atr=2.0, stop_atr=2.0, max_bars=10),
    lambda: MetaLabeler().fit(pd.DataFrame(), pd.Series(dtype=float)),
    lambda: MetaLabeler().predict(pd.DataFrame()),
    lambda: ProbabilityCalibrator().calibrate(
        pd.Series(dtype=float), pd.Series(dtype=float)),
    lambda: ProbabilityCalibrator().predict_proba(pd.Series(dtype=float)),
    lambda: FeatureStore().put("d1", "f1", pd.DataFrame()),
    lambda: FeatureStore().get("d1", "f1"),
])
def test_ml_stubs_raise_not_implemented(call):
    with pytest.raises(NotImplementedError, match="interface-only stub"):
        call()


def test_no_ml_stack_anywhere_in_package():
    """Banned imports cannot exist in the shipped python package."""
    root = Path(__file__).resolve().parents[1] / "python" / "mql5bot"
    banned = ("tensorflow", "keras", "torch", "sklearn", "scikit-learn",
              "transformers", "lightgbm", "xgboost")
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lib in banned:
            assert not re.search(rf"^\s*(import|from)\s+{lib}", text,
                                 re.MULTILINE), \
                f"{path.name} imports banned ML lib {lib}"


# --------------------------------------------------------------------------
# Schema-level invariants
# --------------------------------------------------------------------------


def test_ml_advice_schema_cannot_carry_risk_controls():
    names = {f.name for f in fields(MLAdvice)}
    assert names <= {"confidence", "suggested_side", "max_lots_cap", "note"}
    # unknown/risk fields are rejected at construction
    with pytest.raises(TypeError):
        MLAdvice(remove_stop=True)
    with pytest.raises(TypeError):
        MLAdvice(risk_value=10.0)
    with pytest.raises(TypeError):
        MLAdvice(max_daily_loss_pct=99.0)


def test_ml_advice_validation():
    with pytest.raises(ValueError):
        MLAdvice(confidence=1.5)
    with pytest.raises(ValueError):
        MLAdvice(confidence=-0.1)
    with pytest.raises(ValueError):
        MLAdvice(suggested_side=2)
    with pytest.raises(ValueError):
        MLAdvice(max_lots_cap=0.0)
    with pytest.raises(ValueError):
        MLAdvice(max_lots_cap=-3.0)
    assert MLAdvice().max_lots_cap is None  # no cap = engine sizes


def test_risk_context_is_frozen():
    ctx = _ctx()
    with pytest.raises(FrozenInstanceError):
        ctx.max_lots = 1000.0
    with pytest.raises(FrozenInstanceError):
        ctx.risk_value = 0.0
    with pytest.raises(ValueError):
        RiskContext(max_lots=0.0)
    with pytest.raises(ValueError):
        RiskContext(max_lots=1.0, initial_capital=-5.0)


# --------------------------------------------------------------------------
# Seam behaviour + the four invariants
# --------------------------------------------------------------------------


def test_apply_advice_veto_flat_drops_everything():
    ctx = _ctx()
    out = apply_ml_advice(_orders(), MLAdvice(suggested_side=0), ctx)
    assert out.empty


def test_apply_advice_conflicting_side_drops_direction():
    ctx = _ctx()
    out = apply_ml_advice(_orders(), MLAdvice(suggested_side=-1), ctx)
    assert list(out["side"]) == ["short"]


def test_apply_advice_cap_shrinks_never_grows():
    ctx = _ctx()
    orders = _orders()
    out = apply_ml_advice(orders, MLAdvice(max_lots_cap=0.25), ctx)
    assert list(out["lots"]) == [0.25, 0.25, 0.2]
    # a cap above every order (but under the hard limit) is a pass-through
    out2 = apply_ml_advice(orders, MLAdvice(max_lots_cap=0.6), ctx)
    pd.testing.assert_frame_equal(out2.reset_index(drop=True),
                                  orders.reset_index(drop=True))
    # stops survive every path
    assert list(out["sl"]) == list(orders["sl"])
    assert list(out2["tp"]) == list(orders["tp"])


def test_apply_advice_refuses_cap_above_hard_limit():
    orders = _orders()
    with pytest.raises(ValueError, match="hard max_lots"):
        apply_ml_advice(orders, MLAdvice(max_lots_cap=11.0), _ctx(max_lots=10.0))


def test_apply_advice_neutral_advice_is_identity():
    ctx = _ctx()
    out = apply_ml_advice(_orders(), MLAdvice(), ctx)
    pd.testing.assert_frame_equal(out.reset_index(drop=True),
                                  _orders().reset_index(drop=True))


def test_checker_catches_each_invariant_violation():
    ctx = _ctx()
    orders = _orders()
    advice = MLAdvice()
    # 1+3: an uncontrolled extra trade (also no SL on it)
    extra = pd.concat([orders, pd.DataFrame([{
        "entry_time": "2024-01-05 00:00:00", "side": "long",
        "lots": 2.0, "sl": None, "tp": None,
    }])], ignore_index=True)
    v = check_ml_invariants(orders, extra, advice, ctx)
    assert any("uncontrolled trade" in x for x in v)
    assert any("without stops" in x for x in v)
    # 2: an enlarged trade
    enlarged = orders.copy()
    enlarged.loc[0, "lots"] = 0.9  # was 0.5
    v = check_ml_invariants(orders, enlarged, advice, ctx)
    assert any("enlarged" in x for x in v)
    # 4: a cap above the hard limit
    v = check_ml_invariants(orders, orders, MLAdvice(max_lots_cap=99.0),
                            ctx)
    assert any("hard max_lots" in x for x in v)
    # clean pass yields no violations
    assert check_ml_invariants(orders, orders, advice, ctx) == []


def test_invariant_registry_documented():
    from mql5bot.ml_interfaces import ML_INVARIANTS

    assert len(ML_INVARIANTS) == 4
    joined = " ".join(ML_INVARIANTS).lower()
    for word in ("stop loss", "risk engine", "uncontrolled", "hard risk"):
        assert word in joined
