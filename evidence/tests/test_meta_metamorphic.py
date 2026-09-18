"""Meta Layer METAMORPHIC tests (Phase 13, properties A–K).

These verify mathematical relationships, not fixed outputs.  Every
tolerance states its reason: 1e-9 absolute on weights reflects the
10-decimal serialization contract; exact equality on canonical JSON
reflects the byte-identical journal requirement.
"""

import random
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from mql5bot.meta_layer import (
    Activation,
    MetaConfig,
    MetaDecisionJournal,
    MetaLayer,
    MetaMode,
    MetaPolicy,
    StrategyMetaInput,
)

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
ATOL = 1e-9  # 10-dp serialization contract


def _inp(sid, signal=1, symbol="EURUSD", **kw):
    base = {"regimes_allowed": frozenset({"TREND_UP"}),
            "regimes_preferred": frozenset({"TREND_UP"}),
            "regimes_forbidden": frozenset(),
            "drift_available": True, "drift_score": 0.0}
    base.update(kw)
    state = base.pop("certification_state", "VERIFIED")
    return StrategyMetaInput(sid, symbol, signal, "TREND_UP",
                             base.pop("regimes_allowed"),
                             base.pop("regimes_preferred"),
                             base.pop("regimes_forbidden"), state, **base)


IDS = ["alpha", "bravo", "charlie", "delta", "echo"]


def _inputs(**kw):
    return [_inp(i, signal=(1 if k % 2 == 0 else -1), **kw)
            for k, i in enumerate(IDS)]


def _returns(seed=5, n=120, corr_boost=None):
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    rng = np.random.default_rng(seed)
    base = {i: rng.normal(0, 1, n) for i in IDS}
    if corr_boost:
        # make 'alpha' and 'bravo' increasingly correlated
        lam = corr_boost
        base["bravo"] = (1 - lam) * base["bravo"] + lam * base["alpha"]
    return pd.DataFrame(base, index=idx)


STATS = {i: (0.01, 100 + 40 * k) for k, i in enumerate(IDS)}


_UNSET = object()


def _decide(inputs=None, config=None, oos_stats=None, returns=_UNSET,
            **kw):
    lay = MetaLayer(config or MetaConfig())
    return lay.decide(inputs if inputs is not None else _inputs(),
                      as_of=NOW,
                      returns=_returns() if returns is _UNSET else returns,
                      oos_stats=dict(STATS) if oos_stats is None
                      else oos_stats, **kw)


# ---- A. permutation invariance --------------------------------------------


@pytest.mark.parametrize("mode", list(MetaMode))
def test_a_permutation_invariance_all_modes(mode):
    ref = _decide(config=MetaConfig(mode=mode)).canonical_json()
    for seed in (1, 7, 42):
        shuffled = list(_inputs())
        random.Random(seed).shuffle(shuffled)
        got = _decide(inputs=shuffled,
                      config=MetaConfig(mode=mode)).canonical_json()
        assert got == ref, f"order changed the decision (seed {seed})"


def test_a_permutation_invariance_fallback_and_policies():
    fb = [_inp(i, drift_available=False) for i in IDS]
    ref = _decide(inputs=fb).canonical_json()
    assert "equal_weight" in _decide(inputs=fb).fallback
    sh = list(fb)
    random.Random(3).shuffle(sh)
    assert _decide(inputs=sh).canonical_json() == ref
    for policy in MetaPolicy:
        ref = _decide(config=MetaConfig(policy=policy)).canonical_json()
        sh = list(_inputs())
        random.Random(9).shuffle(sh)
        assert _decide(inputs=sh,
                       config=MetaConfig(policy=policy)).canonical_json() \
            == ref


# ---- B. hard zero remains zero ---------------------------------------------


def test_b_hard_zero_survives_caps_fallback_and_vote():
    inputs = [_inp("ok"), _inp("bad", certification_state="FAILED")]
    for mode in MetaMode:
        d = _decide(inputs=inputs, config=MetaConfig(mode=mode))
        assert d.weight_of("bad") == 0.0
    # global fallback (drift down for everyone) still keeps bad at zero
    fb = [_inp("ok", drift_available=False),
          _inp("bad", certification_state="FAILED", drift_available=False)]
    d = _decide(inputs=fb)
    assert "equal_weight" in d.fallback and d.weight_of("bad") == 0.0
    # vote mode: a hard-zero strategy contributes NO vote mass
    v = MetaLayer(MetaConfig(mode=MetaMode.VOTE, vote_threshold=0.9))
    d = v.decide([_inp("x", signal=1, certification_state="FAILED"),
                  _inp("y", signal=-1)],
                 as_of=NOW, oos_stats={"x": (0.01, 100), "y": (0.01, 100)})
    # x is hard-zero: only y votes -> fires (x's signal never counted)
    assert d.vote_by_symbol == {"EURUSD": -1}


# ---- C. reducing risk budget cannot increase exposure ----------------------


def test_c_reducing_budget_never_increases_any_weight():
    ref = _decide(config=MetaConfig())
    tight = _decide(config=MetaConfig(gross_exposure_cap=0.4))
    for w_ref in ref.weights:
        w_tight = tight.weight_of(w_ref.strategy_id)
        assert w_tight <= w_ref.final_weight + ATOL


# ---- D. reducing portfolio cap cannot increase exposure --------------------


def test_d_reducing_cap_bounds_gross_and_per_strategy():
    base = _decide(config=MetaConfig())
    for cap in (0.6, 0.4, 0.2):
        tight = _decide(config=MetaConfig(max_strategy_weight=cap))
        gross_t = sum(abs(w.final_weight) for w in tight.weights)
        gross_b = sum(abs(w.final_weight) for w in base.weights)
        assert gross_t <= gross_b + ATOL      # total never increases
        for w in tight.weights:               # cap is a hard bound
            assert w.final_weight <= cap + ATOL


# ---- E. increasing correlation penalty cannot increase weight --------------


def test_e_higher_correlation_never_raises_penalized_weights():
    lo = _decide(returns=_returns(corr_boost=0.0))
    hi = _decide(returns=_returns(corr_boost=0.95))
    for sid in ("alpha", "bravo"):            # the penalized pair
        assert hi.weight_of(sid) <= lo.weight_of(sid) + ATOL
    # the uncorrelated third party may only gain or hold
    assert hi.weight_of("charlie") >= lo.weight_of("charlie") - ATOL


# ---- F. removing a strategy only acts through documented normalization -----


def test_f_removal_acts_only_through_documented_channels():
    # (a) zero-correlation case: removal acts ONLY through
    # normalization -> survivor ratio and ALL factors preserved exactly
    full = _decide(returns=None)
    reduced = _decide(returns=None,
                      inputs=[_inp(i) for i in IDS if i != "charlie"])
    wa = full.weight_of("alpha") / full.weight_of("bravo")
    wb = reduced.weight_of("alpha") / reduced.weight_of("bravo")
    assert wa == pytest.approx(wb, rel=1e-9)
    ea, er = full.eligibility["alpha"], reduced.eligibility["alpha"]
    assert (ea.eligible, ea.reason) == (er.eligible, er.reason)
    fa = next(r for r in full.raw_scores if r.strategy_id == "alpha")
    fr = next(r for r in reduced.raw_scores if r.strategy_id == "alpha")
    assert fa.to_dict() == fr.to_dict()
    # (b) with real correlations, removal legitimately updates the
    # correlation interaction of survivors (documented: the pairwise
    # set changed) — every OTHER factor stays identical, deterministically
    full = _decide()
    reduced = _decide(inputs=[_inp(i) for i in IDS if i != "charlie"])
    fa = next(r for r in full.raw_scores if r.strategy_id == "alpha")
    fr = next(r for r in reduced.raw_scores if r.strategy_id == "alpha")
    other_full = [f.to_dict() for f in fa.factors
                  if f.name != "correlation_penalty"]
    other_red = [f.to_dict() for f in fr.factors
                 if f.name != "correlation_penalty"]
    assert other_full == other_red


# ---- G. equal-weight fallback is permutation invariant ----------------------


def test_g_equal_weight_fallback_permutation_invariant():
    fb = [_inp(i, drift_available=False,
               signal=(1 if k % 2 else -1))
          for k, i in enumerate(IDS)]
    ref = _decide(inputs=fb)
    assert ref.fallback[0] == "equal_weight"
    for w in ref.weights:
        if ref.eligibility[w.strategy_id].eligible:
            assert w.final_weight == pytest.approx(0.2, abs=ATOL)
    sh = list(fb)
    random.Random(11).shuffle(sh)
    assert _decide(inputs=sh).canonical_json() == ref.canonical_json()


# ---- H. byte-identical journals --------------------------------------------


def test_h_identical_inputs_byte_identical_journals(tmp_path):
    j1, j2 = MetaDecisionJournal(), MetaDecisionJournal()
    for j in (j1, j2):
        lay = MetaLayer(MetaConfig(), Activation.SHADOW)
        j.append(lay.decide(_inputs(), as_of=NOW, returns=_returns(),
                            oos_stats=dict(STATS)))
    assert j1.canonical_json() == j2.canonical_json()
    p1, p2 = tmp_path / "j1.json", tmp_path / "j2.json"
    j1.save(p1)
    j2.save(p2)
    assert p1.read_bytes() == p2.read_bytes()


# ---- I. tied strategies resolve deterministically ---------------------------


def test_i_ties_resolve_lexically_under_any_order():
    tie = [_inp("zz", signal=1), _inp("aa", signal=1)]
    stats = {"zz": (0.0, 50), "aa": (0.0, 50)}
    winners = set()
    for order in ([tie[0], tie[1]], [tie[1], tie[0]]):
        d = _decide(inputs=order,
                    config=MetaConfig(mode=MetaMode.BEST_OF_REGIME),
                    oos_stats=stats)
        winners.add(next(w.strategy_id for w in d.weights
                         if w.final_weight > 0))
    assert winners == {"aa"}
    # equal scores in weighted_netting -> equal shares, stable ids order
    d = _decide(inputs=tie, oos_stats=stats)
    assert d.weight_of("aa") == pytest.approx(d.weight_of("zz"), abs=ATOL)


# ---- J. missing optional data follows the documented fallback ---------------


def test_j_missing_data_is_bounded_fallback_never_free_pass():
    no_echo = {k: v for k, v in STATS.items() if k != "echo"}
    inputs = _inputs()
    d = _decide(inputs=inputs, oos_stats=no_echo)
    f_echo = next(f for r in d.raw_scores if r.strategy_id == "echo"
                  for f in r.factors if f.name == "performance_factor")
    assert f_echo.value == 0.5
    assert f_echo.status.value == "MISSING_FALLBACK"
    # a measured positive strategy outranks the missing-data one: the
    # fallback is NOT a neutral free pass
    f_alpha = next(f for r in d.raw_scores if r.strategy_id == "alpha"
                   for f in r.factors if f.name == "performance_factor")
    assert f_alpha.value > 0.5
    assert d.weight_of("alpha") > d.weight_of("echo")
    # missing drift for ONE strategy -> 0.5 factor, flagged
    inp = [_inp("a"), _inp("b", drift_available=False)]
    d = _decide(inputs=inp, returns=None,
                oos_stats={"a": (0.0, 100), "b": (0.0, 100)})
    fd = next(f for r in d.raw_scores if r.strategy_id == "b"
              for f in r.factors if f.name == "drift_factor")
    assert fd.value == 0.5 and fd.status.value == "MISSING_FALLBACK"


# ---- K. all-zero / fallback never resurrects hard zeros ---------------------


def test_k_all_zero_and_fallback_never_resurrect():
    # everyone hard-blocked (kill switch) -> SAFE HOLD, NOT equal weight
    dead = [_inp(i, kill_switch=True) for i in IDS]
    d = _decide(inputs=dead)
    assert all(w.final_weight == 0.0 for w in d.weights)
    assert d.fallback == ("none_eligible",)
    assert d.book == []
    # global failure with a hard-zero present: eligible get equal
    # weight, the hard zero stays exactly zero
    mixed = [_inp("ok1", drift_available=False),
             _inp("ok2", drift_available=False),
             _inp("zero", certification_state="FAILED",
                  drift_available=False)]
    d = _decide(inputs=mixed)
    assert "equal_weight" in d.fallback
    assert d.weight_of("zero") == 0.0
    assert d.weight_of("ok1") == pytest.approx(0.5, abs=ATOL)
    assert d.weight_of("ok2") == pytest.approx(0.5, abs=ATOL)
    # and the hard zero never appears in the attribution book
    assert {b.strategy_id for b in d.book} == {"ok1", "ok2"}
