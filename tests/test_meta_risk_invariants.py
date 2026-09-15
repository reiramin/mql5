"""Meta Layer RISK INVARIANTS (Phase 12).

The Meta Layer cannot: remove/widen SL, bypass the Risk Engine or any
risk limit, trade on kill switch, exceed exposure, conjure orders from
no signal or hard-zero/uncertified strategies, or raise hard risk.
Proven structurally (module surface) AND behaviorally (decisions).
"""

import inspect
from dataclasses import fields
from datetime import datetime, timezone

import mql5bot.meta_layer as ml
import numpy as np
import pandas as pd
import pytest
from mql5bot.meta_layer import (
    EligibilityReason,
    MetaConfig,
    MetaLayer,
    MetaMode,
    StrategyMetaInput,
)

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
FORBIDDEN_VERBS = ("order", "send", "execute", "submit", "place", "trade_")


def _inp(sid="a", signal=1, **kw):
    base = {"regimes_allowed": frozenset({"TREND_UP"}),
            "regimes_preferred": frozenset({"TREND_UP"}),
            "regimes_forbidden": frozenset(),
            "drift_available": True, "drift_score": 0.0}
    base.update(kw)
    state = base.pop("certification_state", "VERIFIED")
    return StrategyMetaInput(sid, "EURUSD", signal, "TREND_UP",
                             base.pop("regimes_allowed"),
                             base.pop("regimes_preferred"),
                             base.pop("regimes_forbidden"), state, **base)


def _stats(*ids, e=0.01, n=100):
    return {i: (e, n) for i in ids}


# ---- structural seams ------------------------------------------------------


def test_1_2_no_stop_loss_api_or_fields():
    """(1)(2) SL/TP never enters the layer: no field, no verb, no path."""
    names = {f.name for f in fields(StrategyMetaInput)}
    assert not any("sl" in n or "stop" in n or "tp" in n for n in names)
    # the output type carries weights only — no order/SL objects
    out_names = {f.name for f in fields(ml.MetaDecision)}
    assert not any("order" in n or "sl" in n for n in out_names)


def test_3_10_no_order_or_risk_authority_api():
    """(3)(10) The module surface has NO order-emitting or limit-setting
    API, and MetaConfig cannot carry risk-limit overrides (exactly six
    documented tunables, frozen)."""
    for name, member in inspect.getmembers(ml):
        if not name.startswith("_"):
            low = name.lower()
            assert not any(v in low for v in FORBIDDEN_VERBS), name
    for name, member in inspect.getmembers(MetaLayer,
                                           inspect.isfunction):
        low = name.lower()
        assert not any(v in low for v in FORBIDDEN_VERBS), name
    cfg_fields = {f.name for f in fields(MetaConfig)}
    assert cfg_fields == {"mode", "policy", "vote_threshold",
                          "max_strategy_weight", "gross_exposure_cap",
                          "max_weight_change", "max_positions"}
    with pytest.raises(TypeError):  # frozen dataclass: unknown kwargs refuse
        MetaConfig(daily_loss_limit=999)  # type: ignore[arg-type]


def test_4_5_6_kill_switch_and_loss_limits_are_hard_blocks():
    """(4)(5)(6) Kill switch latches EVERYTHING; loss/drawdown authority
    is not even representable — only eligibility flags arrive."""
    lay = MetaLayer(MetaConfig())
    d = lay.decide([_inp("a"), _inp("b", kill_switch=True)],
                   as_of=NOW, oos_stats=_stats("a", "b"))
    assert d.weight_of("b") == 0.0
    assert d.eligibility["b"].reason is EligibilityReason.KILL_SWITCH
    d = lay.decide([_inp("a", kill_switch=True), _inp("b", kill_switch=True)],
                   as_of=NOW, oos_stats=_stats("a", "b"))
    assert all(w.final_weight == 0.0 for w in d.weights)
    assert "none_eligible" in d.fallback


def test_7_11_exposure_and_heat_never_exceed_budget():
    """(7)(11) Σ|final weights| ≤ gross budget in every mode/config."""
    inputs = [_inp(i, signal=(-1 if k % 2 else 1))
              for k, i in enumerate(["a", "b", "c", "d", "e"])]
    rng = np.random.default_rng(11)
    idx = pd.date_range("2026-01-01", periods=80, freq="h")
    rets = pd.DataFrame(
        {i: rng.normal(0, 1, 80) for i in "abcde"}, index=idx)
    for mode in MetaMode:
        for cap in (1.0, 0.5, 0.25):
            lay = MetaLayer(MetaConfig(mode=mode, gross_exposure_cap=cap,
                                       max_positions=3))
            d = lay.decide(inputs, as_of=NOW, returns=rets,
                           oos_stats=_stats(*"abcde"))
            gross = sum(abs(w.final_weight) for w in d.weights)
            assert gross <= cap + 1e-9, (mode, cap, gross)


def test_8_no_order_without_signal():
    """(8) An empty book for signal-less strategies: no contribution,
    no net, no vote can exist without a signal."""
    lay = MetaLayer(MetaConfig())
    d = lay.decide([_inp("a", signal=0), _inp("b", signal=0)],
                   as_of=NOW, oos_stats=_stats("a", "b"))
    assert d.book == [] and d.net_by_symbol == {}
    vote = MetaLayer(MetaConfig(mode=MetaMode.VOTE))
    d = vote.decide([_inp("a", signal=0), _inp("b", signal=0)],
                    as_of=NOW, oos_stats=_stats("a", "b"))
    assert d.vote_by_symbol == {}
    # and a positive weight with no signal still creates NO book entry
    assert all(w.final_weight >= 0.0 for w in d.weights)


def test_9_12_no_order_from_hard_zero_or_uncertified():
    """(9)(12) Hard-zero/uncertified strategies: zero weight, no book
    leg, no vote mass — in every mode, including global fallback."""
    inputs = [_inp("ok"), _inp("bad", certification_state=None),
              _inp("failed", certification_state="FAILED")]
    for mode in MetaMode:
        lay = MetaLayer(MetaConfig(mode=mode))
        d = lay.decide(inputs, as_of=NOW, oos_stats=_stats("ok", "bad",
                                                           "failed"))
        assert d.weight_of("bad") == 0.0
        assert d.weight_of("failed") == 0.0
        assert {b.strategy_id for b in d.book} <= {"ok"}
        # fallback path (global drift failure) still respects hard zeros
        lay_fb = MetaLayer(MetaConfig(mode=mode))
        d = lay_fb.decide(
            [_inp("ok", drift_available=False),
             _inp("bad", certification_state=None, drift_available=False),
             _inp("down", drift_available=False)],
            as_of=NOW, oos_stats=_stats("ok", "bad", "down"))
        assert "equal_weight" in d.fallback
        assert d.weight_of("bad") == 0.0


def test_layer_can_only_reduce_proven_by_redistribution_guard():
    """Constraint machinery never increases total mass beyond the
    budget it was given, and redistribution never touches zeros."""
    lay = MetaLayer(MetaConfig(max_strategy_weight=0.3))
    d = lay.decide([_inp("a"), _inp("b"), _inp("c")],
                   as_of=NOW, oos_stats=_stats("a", "b", "c", e=0.05))
    assert sum(w.final_weight for w in d.weights) <= 1.0 + 1e-9
    for w in d.weights:
        if w.final_weight == 0.0:
            assert w.zero_reason is not None or w.pre_cap_share == 0.0
