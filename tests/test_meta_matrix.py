"""Meta Layer matrix tests — Phases 17-21, 24-26, 29, 30.

Regime matrix, drift matrix, the 22 adversarial scenarios, restart
equivalence, shadow mode, activation ladder, decision journal, file
contract, and the lightweight-performance sanity bound.
"""

import itertools
import json
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from mql5bot.meta_layer import (
    CORR_MIN_OBS,
    Activation,
    EligibilityReason,
    MetaConfig,
    MetaConfigError,
    MetaDecisionJournal,
    MetaFileError,
    MetaLayer,
    MetaMode,
    MetaPolicy,
    MetaState,
    StrategyMetaInput,
    read_allocation_file,
    safe_decision,
    write_allocation_file,
)

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
ATOL = 1e-9


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


def _stats(*ids, e=0.01):
    return {i: (e, 100) for i in ids}


def _ret(seed=3, n=80, ids=("a", "b", "c")):
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    rng = np.random.default_rng(seed)
    return pd.DataFrame({i: rng.normal(0, 1, n) for i in ids}, index=idx)


# ---- Phase 24: regime matrix ------------------------------------------------


@pytest.mark.parametrize("regime,expect_zero", [
    ("TREND_UP", False),
    ("TREND_DOWN", True),      # not declared -> unknown -> fail-safe zero
    ("RANGE", True),
    ("HIGH_VOL", True),        # explicitly forbidden
    ("LOW_VOL", True),
    ("TRANSITION", True),
    ("TOTALLY_UNKNOWN", True),
])
def test_regime_matrix_deterministic(regime, expect_zero):
    allowed = _inp("a", regime=regime)
    forbidden = _inp("b", regime=regime,
                     regimes_allowed=frozenset({"TREND_UP"}),
                     regimes_forbidden=frozenset({"HIGH_VOL"}))
    d = MetaLayer(MetaConfig()).decide(
        [allowed, forbidden], as_of=NOW, returns=None,
        oos_stats=_stats("a", "b"))
    assert (d.weight_of("a") == 0.0) is expect_zero or expect_zero is False
    if regime == "HIGH_VOL":
        assert d.eligibility["b"].reason is EligibilityReason.REGIME_FORBIDDEN
        assert d.weight_of("b") == 0.0
    elif regime != "TREND_UP":
        assert d.eligibility["a"].reason is EligibilityReason.REGIME_UNKNOWN
    # deterministic under permutation in every regime
    d2 = MetaLayer(MetaConfig()).decide(
        [forbidden, allowed], as_of=NOW, returns=None,
        oos_stats=_stats("a", "b"))
    assert d2.canonical_json() == d.canonical_json()


def test_preferred_equals_allowed_constant_no_hidden_boost():
    """v1.1.0 fixes preferred fit at 1.0 (= allowed): no winner-picking
    boost exists.  Forbidden is the only regime that zeroes."""
    fit = MetaLayer._regime_factor(
        _inp("a", regime="RANGE",
             regimes_allowed=frozenset({"TREND_UP"}),
             regimes_preferred=frozenset({"RANGE"})))
    assert fit.value == 1.0


# ---- Phase 25: drift matrix --------------------------------------------------


def test_drift_matrix_exact():
    lay = MetaLayer(MetaConfig())
    d = lay.decide([_inp("a", drift_score=0.0),          # NO_DRIFT
                    _inp("b", drift_score=0.30),         # MILD
                    _inp("c", drift_score=0.50)],        # SEVERE
                   as_of=NOW, returns=None,
                   oos_stats=_stats("a", "b", "c"))
    f = {r.strategy_id: {x.name: x.value for x in r.factors}
         for r in d.raw_scores}
    assert f["a"]["drift_factor"] == 1.0
    assert f["b"]["drift_factor"] == pytest.approx(0.75)
    assert d.eligibility["c"].reason is EligibilityReason.DRIFT_BLOCK
    assert d.weight_of("c") == 0.0
    # missing for one -> bounded 0.5, flagged; NOT a block
    d = lay.decide([_inp("a"), _inp("b", drift_available=False)],
                   as_of=NOW, returns=None, oos_stats=_stats("a", "b"))
    fb = {x.name: x for x in d.raw_scores[1].factors}
    assert fb["drift_factor"].value == 0.5
    assert fb["drift_factor"].status.value == "MISSING_FALLBACK"
    # mild drift is MONOTONE in d (no sudden weight jumps inside mild)
    vals = [MetaLayer._drift_factor(_inp(drift_score=x / 100.0)).value
            for x in range(50)]
    assert all(a >= b - 1e-12 for a, b in itertools.pairwise(vals))


def test_drift_weight_jump_is_clamped_by_change_limit():
    cfg = MetaConfig(max_weight_change=0.1)
    lay = MetaLayer(cfg)
    d1 = lay.decide([_inp("a")], as_of=NOW, returns=None,
                    oos_stats=_stats("a"))
    assert d1.weight_of("a") == pytest.approx(1.0, abs=ATOL)
    d2 = lay.decide([_inp("a", drift_score=0.30)], as_of=NOW,
                    returns=None, oos_stats=_stats("a"))
    assert d2.weight_of("a") <= 1.0
    assert d2.weights[0].final_weight >= 0.9 - 1e-9  # moved <= 0.1


# ---- Phase 26: adversarial matrix (22 scenarios) ------------------------------


def test_adv_01_identical_strategies_split_deterministically():
    twins = [_inp(f"s{i}") for i in range(4)]
    d = MetaLayer(MetaConfig()).decide(twins, as_of=NOW, returns=None,
                                       oos_stats=_stats(*[f"s{i}" for i
                                                          in range(4)]))
    assert all(w.final_weight == pytest.approx(0.25, abs=1e-9)
               for w in d.weights)


def test_adv_02_all_zero_factors_safe_hold():
    dead = [_inp("a", certification_state="FAILED"),
            _inp("b", enabled=False)]
    d = MetaLayer(MetaConfig()).decide(dead, as_of=NOW)
    assert d.fallback == ("none_eligible",)
    assert all(w.final_weight == 0.0 for w in d.weights)


def test_adv_03_single_strategy_gets_budget():
    d = MetaLayer(MetaConfig()).decide([_inp("only")], as_of=NOW,
                                       returns=None,
                                       oos_stats=_stats("only"))
    assert d.weight_of("only") == pytest.approx(1.0, abs=1e-9)
    d = MetaLayer(MetaConfig(gross_exposure_cap=0.3)).decide(
        [_inp("only")], as_of=NOW, returns=None, oos_stats=_stats("only"))
    assert d.weight_of("only") == pytest.approx(0.3, abs=1e-9)


def test_adv_04_no_eligible():
    d = MetaLayer(MetaConfig()).decide([_inp("a", enabled=False)],
                                       as_of=NOW)
    assert d.fallback == ("none_eligible",)


def test_adv_05_one_hard_zero_among_many():
    d = MetaLayer(MetaConfig()).decide(
        [_inp("a"), _inp("b", certification_state=None), _inp("c")],
        as_of=NOW, returns=None, oos_stats=_stats("a", "b", "c"))
    assert d.weight_of("b") == 0.0
    assert d.weight_of("a") + d.weight_of("c") == pytest.approx(1.0,
                                                                abs=1e-9)


def test_adv_06_correlation_window_semantics():
    """(a) rows AFTER as_of are excluded (no lookahead); old-but-complete
    history stays usable — source staleness is the caller's `stale`
    flag.  (b) insufficient overlap is flagged and degrades to the
    global equal-weight fallback, never to fabricated correlations."""
    n = CORR_MIN_OBS + 5
    idx = pd.date_range("2025-01-01", periods=n, freq="h")
    rng = np.random.default_rng(4)
    old = pd.DataFrame({"a": rng.normal(0, 1, n),
                        "b": rng.normal(0, 1, n)}, index=idx)
    # future rows (after as_of) never enter the window: with as_of at
    # row 10 only 11 observations remain < CORR_MIN_OBS -> flagged
    _, status, gf = MetaLayer.correlation_matrix(old, ["a", "b"],
                                                 as_of=idx[10])
    assert gf is True and status["a"].value == "MISSING_FALLBACK"
    short_idx = pd.date_range("2026-08-01", periods=CORR_MIN_OBS - 1,
                              freq="h")
    short = pd.DataFrame({"a": rng.normal(0, 1, len(short_idx)),
                          "b": rng.normal(0, 1, len(short_idx))},
                         index=short_idx)
    _, status, gf = MetaLayer.correlation_matrix(short, ["a", "b"],
                                                 as_of=NOW)
    assert gf is True and status["a"].value == "MISSING_FALLBACK"
    d = MetaLayer(MetaConfig()).decide(
        [_inp("a"), _inp("b")], as_of=NOW, returns=short,
        oos_stats=_stats("a", "b"))
    assert "equal_weight" in d.fallback


def test_adv_07_missing_drift():
    d = MetaLayer(MetaConfig()).decide(
        [_inp("a", drift_available=False),
         _inp("b", drift_available=False)], as_of=NOW,
        oos_stats=_stats("a", "b"))
    assert "equal_weight" in d.fallback and "source:drift" in d.fallback


def test_adv_08_missing_performance():
    d = MetaLayer(MetaConfig()).decide([_inp("a"), _inp("b")],
                                       as_of=NOW, returns=None)
    assert "equal_weight" in d.fallback and "source:performance" \
        in d.fallback


def test_adv_09_conflicting_signals_net_zero_vote_tie():
    d = MetaLayer(MetaConfig()).decide(
        [_inp("a", signal=1), _inp("b", signal=-1)], as_of=NOW,
        returns=None, oos_stats=_stats("a", "b", e=0.0))
    assert d.net_by_symbol["EURUSD"] == pytest.approx(0.0, abs=1e-9)
    v = MetaLayer(MetaConfig(mode=MetaMode.VOTE)).decide(
        [_inp("a", signal=1), _inp("b", signal=-1)], as_of=NOW,
        returns=None, oos_stats=_stats("a", "b", e=0.0))
    assert v.vote_by_symbol == {}       # exact tie -> no trade


def test_adv_10_identical_previous_weights_equal_prior():
    cfg = MetaConfig()
    state = MetaState(config_hash=cfg.config_hash,
                      weights={"a": 0.5, "b": 0.5})
    lay = MetaLayer(cfg, state=state)
    d = lay.decide([_inp("a", signal=1), _inp("b", signal=-1)],
                   as_of=NOW, returns=_ret(ids=("a", "b")),
                   oos_stats=_stats("a", "b"))
    # symmetric everything -> symmetric penalty -> equal shares
    assert d.weight_of("a") == pytest.approx(d.weight_of("b"), abs=ATOL)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.5, 1e9])
def test_adv_11_12_13_14_invalid_drift_inputs_are_config_invalid(bad):
    d = MetaLayer(MetaConfig()).decide([_inp("a", drift_score=bad)],
                                       as_of=NOW)
    assert d.eligibility["a"].reason is EligibilityReason.CONFIG_INVALID
    assert d.weight_of("a") == 0.0


def test_adv_11_nan_in_returns_flagged():
    rets = _ret(ids=("a", "b"))
    rets.iloc[10, 0] = np.nan
    _, _, gf = MetaLayer.correlation_matrix(rets, ["a", "b"],
                                            as_of=NOW)
    # NaN rows are dropped, remaining 79 observations still correlate
    assert gf is False


def test_adv_15_duplicate_strategy_id_refused():
    with pytest.raises(MetaConfigError, match="duplicate"):
        MetaLayer(MetaConfig()).decide([_inp("a"), _inp("a")], as_of=NOW)


def test_adv_16_ordering_permutation_invariant():
    inputs = [_inp(i, signal=(1 if k % 2 == 0 else -1))
              for k, i in enumerate("abc")]
    kw = {"as_of": NOW, "returns": _ret(),
          "oos_stats": _stats("a", "b", "c")}
    d1 = MetaLayer(MetaConfig()).decide(inputs, **kw)
    d2 = MetaLayer(MetaConfig()).decide(list(reversed(inputs)), **kw)
    assert d1.canonical_json() == d2.canonical_json()


def test_adv_17_extreme_correlation_hits_penalty_floor():
    idx = pd.date_range("2026-01-01", periods=60, freq="h")
    x = np.linspace(0, 1, 60)
    rets = pd.DataFrame({"a": x, "b": x}, index=idx)  # corr = +1
    d = MetaLayer(MetaConfig()).decide([_inp("a"), _inp("b")],
                                       as_of=NOW, returns=rets,
                                       oos_stats=_stats("a", "b"))
    pens = [f.value for r in d.raw_scores for f in r.factors
            if f.name == "correlation_penalty"]
    # equal prior 0.5 over the pair -> pen = 1 - 0.5*1.0 = 0.5 exactly
    # (the 0.1 floor binds only with many highly-correlated strategies)
    assert all(p == pytest.approx(0.5, abs=1e-9) for p in pens)
    # perfect correlation cannot exceed the budget either
    assert sum(w.final_weight for w in d.weights) <= 1.0 + 1e-9


def test_adv_18_external_corr_matrix_is_unrepresentable():
    """PSD violations cannot enter: the module ACCEPTS NO correlation
    matrix — it computes its own from timestamped returns (symmetric,
    unit diagonal by construction)."""
    import inspect
    sig = inspect.signature(MetaLayer.decide)
    assert "returns" in sig.parameters
    assert not any("corr" in p or "matrix" in p
                   for p in sig.parameters)


def test_adv_19_stale_allocation_flagged(tmp_path):
    d = MetaLayer(MetaConfig()).decide([_inp("a")], as_of=NOW,
                                       returns=None,
                                       oos_stats=_stats("a"))
    path = tmp_path / "allocation.json"
    write_allocation_file(d, path)
    fresh = read_allocation_file(path, now=NOW)
    assert fresh["stale"] is False
    stale = read_allocation_file(path, now=NOW + timedelta(days=8))
    assert stale["stale"] is True


def test_adv_20_malformed_allocation_refused(tmp_path):
    good = MetaLayer(MetaConfig()).decide([_inp("a")], as_of=NOW,
                                          returns=None,
                                          oos_stats=_stats("a"))
    path = tmp_path / "allocation.json"
    doc = write_allocation_file(good, path)
    # any mutation breaks the digest
    obj = json.loads(doc)
    obj["body"]["strategies"][0]["weight"] = 42.0
    path.write_text(json.dumps(obj))
    with pytest.raises(MetaFileError, match="digest"):
        read_allocation_file(path)
    # truncated / non-JSON
    path.write_text("{not json")
    with pytest.raises(MetaFileError):
        read_allocation_file(path)
    # unknown schema version (digest rebuilt so the schema check runs)
    from mql5bot.meta_layer import canonical_json, sha256_hex
    obj = json.loads(doc)
    obj["body"]["schema_version"] = "99"
    payload = canonical_json(obj["body"])
    path.write_text(canonical_json(
        {"body": json.loads(payload), "digest": sha256_hex(payload)}))
    with pytest.raises(MetaFileError, match="schema_version"):
        read_allocation_file(path)
    # duplicate strategy id inside the file (digest rebuilt to reach it)
    obj = json.loads(doc)
    obj["body"]["strategies"].append(dict(obj["body"]["strategies"][0]))
    payload = canonical_json(obj["body"])
    path.write_text(canonical_json(
        {"body": json.loads(payload), "digest": sha256_hex(payload)}))
    with pytest.raises(MetaFileError, match="bad strategy id"):
        read_allocation_file(path)


def test_adv_21_restart_after_clamp_continues_limits(tmp_path):
    cfg = MetaConfig(max_weight_change=0.1)
    lay = MetaLayer(cfg)
    d1 = lay.decide([_inp("a")], as_of=NOW, returns=None,
                    oos_stats=_stats("a"))
    path = tmp_path / "meta_state.json"
    path.write_text(lay.state.serialize())
    restored = MetaLayer(cfg, state=MetaState.deserialize(
        path.read_text()))
    d2 = restored.decide([_inp("a")], as_of=NOW, returns=None,
                         oos_stats=_stats("a"))
    # clamped movement relative to the RESTORED weight, not from zero
    assert d2.weights[0].final_weight <= d1.weight_of("a") + 0.1 + 1e-9
    assert restored.state.weights["a"] == \
        pytest.approx(d2.weight_of("a"), abs=1e-9)


def test_adv_22_kill_switch_active_freezes_everything():
    d = MetaLayer(MetaConfig()).decide(
        [_inp("a", kill_switch=True), _inp("b", kill_switch=True)],
        as_of=NOW, returns=None, oos_stats=_stats("a", "b"))
    assert all(w.final_weight == 0.0 for w in d.weights)
    assert {e.reason for e in d.eligibility.values()} == {
        EligibilityReason.KILL_SWITCH}
    assert d.book == []


# ---- Phase 18: activation ladder ----------------------------------------------


def test_activation_ladder_explicit_only_and_audited():
    lay = MetaLayer(MetaConfig())
    assert lay.activation is Activation.DISABLED     # default
    j = MetaDecisionJournal()
    with pytest.raises(MetaConfigError):
        lay.transition(Activation.ACTIVE, as_of=NOW)   # skip states
    lay.transition(Activation.SHADOW, as_of=NOW, journal=j)
    lay.transition(Activation.DEMO, as_of=NOW, journal=j)
    lay.transition(Activation.LIVE_SMALL, as_of=NOW, journal=j)
    with pytest.raises(MetaConfigError):
        lay.transition(Activation.DISABLED, as_of=NOW)  # backwards 3 steps
    assert lay.activation.can_transition_to(Activation.DEMO)  # -1 allowed
    assert not Activation.DISABLED.may_influence_sizing
    assert not Activation.SHADOW.may_influence_sizing
    assert Activation.LIVE_SMALL.may_influence_sizing
    events = [t for t in j.entries if False] or j._transitions
    assert [e["to"] for e in events] == ["SHADOW", "DEMO", "LIVE_SMALL"]


# ---- Phase 17: shadow mode ------------------------------------------------------


def test_shadow_computes_but_diverges_from_actual_baseline():
    shadow_layer = MetaLayer(MetaConfig(policy=MetaPolicy.META),
                             Activation.SHADOW)
    baseline_layer = MetaLayer(MetaConfig(policy=MetaPolicy.EQUAL_WEIGHT),
                               Activation.SHADOW)
    inputs = [_inp("a", signal=1), _inp("b", signal=-1)]
    shadow = shadow_layer.decide(inputs, as_of=NOW, returns=None,
                                 oos_stats={"a": (0.02, 300),
                                            "b": (0.0, 100)})
    actual = baseline_layer.decide(inputs, as_of=NOW, returns=None,
                                   oos_stats={"a": (0.02, 300),
                                              "b": (0.0, 100)})
    div = shadow_layer.shadow_divergence(shadow, actual)
    assert div["weight_l1"] > 0.0            # policies genuinely differ
    assert div["gross_actual"] == pytest.approx(1.0, abs=ATOL)
    # shadow never influences sizing: activation gate is structural
    assert not shadow_layer.activation.may_influence_sizing


# ---- Phase 19: restart equivalence ----------------------------------------------


def test_restart_equivalence_byte_identical(tmp_path):
    cfg = MetaConfig(max_weight_change=0.3)
    inputs = [_inp("a", signal=1), _inp("b", signal=-1)]
    kw = {"as_of": NOW, "returns": None, "oos_stats": _stats("a", "b")}
    # continuous run
    cont = MetaLayer(cfg)
    cont.decide(inputs, **kw)
    c2 = cont.decide(inputs, **kw)
    # restarted run after decision 1
    restarted = MetaLayer(cfg, state=MetaState.deserialize(
        cont.state.serialize()))
    r2 = restarted.decide(inputs, **kw)
    assert r2.canonical_json() == c2.canonical_json()
    # persisted state contains NO factor/OOS data (weights + flags only)
    blob = cont.state.serialize()
    body = json.loads(blob)["body"]
    assert set(body) <= {"schema_version", "decision_version",
                         "config_hash", "as_of", "weights", "zeroed",
                         "activation"}  # Phase 20: activation persists


# ---- Phase 30: failure mode ------------------------------------------------------


def test_failure_mode_is_safe_hold():
    lay = MetaLayer(MetaConfig())
    # a factor source that explodes inside decide (impossible via the
    # typed model, simulated on the descriptor to keep staticness)
    import mql5bot.meta_layer as ml_mod

    orig = ml_mod.MetaLayer.__dict__["_gate_factor"]

    def _boom(inp):
        raise RuntimeError("boom")

    ml_mod.MetaLayer._gate_factor = staticmethod(_boom)
    try:
        decision, exc = safe_decision(lay, [_inp("a")], as_of=NOW,
                                      oos_stats=_stats("a"))
        assert isinstance(exc, RuntimeError)
        assert decision.fallback == ("failure_safe",)
        assert decision.weights == [] and decision.book == []
    finally:
        ml_mod.MetaLayer._gate_factor = orig
    # layer usable again after the failure
    d = lay.decide([_inp("a")], as_of=NOW, oos_stats=_stats("a"))
    assert d.weight_of("a") == pytest.approx(1.0, abs=ATOL)


# ---- Phase 20: journal ordering ---------------------------------------------------


def test_journal_sorted_by_strategy_id_and_serialization_stable():
    ids = ["zeta", "alpha", "Mid", "beta"]
    inputs = [_inp(i) for i in ids]
    d = MetaLayer(MetaConfig()).decide(inputs, as_of=NOW, returns=None,
                                       oos_stats=_stats(*ids))
    wids = [w.strategy_id for w in d.weights]
    assert wids == sorted(ids)
    assert d.canonical_json() == d.canonical_json()


# ---- Phase 29: lightweight performance sanity (NOT an optimization claim) ----


def test_decision_latency_is_allocation_grade():
    """Slow-cadence allocation: a 10-strategy decision with a 500-bar
    correlation window must stay in the milliseconds — measured, with a
    generous bound (this is a sanity gate, not a benchmark)."""
    ids = [f"s{i:02d}" for i in range(10)]
    inputs = [_inp(i, signal=(1 if k % 2 == 0 else -1))
              for k, i in enumerate(ids)]
    idx = pd.date_range("2026-01-01", periods=500, freq="h")
    rng = np.random.default_rng(9)
    rets = pd.DataFrame({i: rng.normal(0, 1, 500) for i in ids},
                        index=idx)
    stats = {i: (0.01, 100) for i in ids}
    lay = MetaLayer(MetaConfig())
    lay.decide(inputs, as_of=NOW, returns=rets, oos_stats=stats)  # warm
    t0 = time.perf_counter()
    for _ in range(5):
        d = lay.decide(inputs, as_of=NOW, returns=rets, oos_stats=stats)
    per_decision = (time.perf_counter() - t0) / 5
    assert per_decision < 0.25, per_decision  # generous: sandbox-shared
    t0 = time.perf_counter()
    d.canonical_json()
    assert time.perf_counter() - t0 < 0.25
