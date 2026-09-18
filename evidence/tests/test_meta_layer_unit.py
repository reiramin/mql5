"""Meta Layer unit pins — Phases 2–11 (contract v1.1.1 semantics)."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from mql5bot.meta_layer import (
    CORR_MIN_OBS,
    DRIFT_BLOCK,
    EligibilityReason,
    MetaConfig,
    MetaConfigError,
    MetaLayer,
    MetaMode,
    MetaState,
    StrategyMetaInput,
)

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def _inp(sid="a", symbol="EURUSD", signal=1, regime="TREND_UP",
         state="VERIFIED", **kw):
    # tests default to a HEALTHY drift source; missing-drift behavior is
    # tested explicitly (global fallback per the missing-data table)
    base = {
        "regimes_allowed": frozenset({"TREND_UP"}),
        "regimes_preferred": frozenset({"TREND_UP"}),
        "regimes_forbidden": frozenset(),
        "drift_available": True, "drift_score": 0.0,
    }
    base.update(kw)
    state = base.pop("certification_state", state)
    allowed = base.pop("regimes_allowed")
    preferred = base.pop("regimes_preferred")
    forbidden = base.pop("regimes_forbidden")
    return StrategyMetaInput(sid, symbol, signal, regime, allowed,
                             preferred, forbidden, state, **base)


def _inputs():
    return [
        _inp("alpha", signal=1),
        _inp("beta", signal=-1, state="EMPIRICAL_VALIDATION_PENDING"),
        _inp("gamma", symbol="GBPUSD", signal=1, state="FAILED"),
    ]


def _retsWith(seed=3, n=60):
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    rng = np.random.default_rng(seed)
    return pd.DataFrame({s: rng.normal(0, 1, n)
                         for s in ("alpha", "beta", "gamma")}, index=idx)


STATS = {"alpha": (0.01, 120), "beta": (0.002, 300), "gamma": (0.0, 40)}


# ---- Phase 2: config / typed model ---------------------------------------


def test_config_validates_and_hashes():
    with pytest.raises(MetaConfigError):
        MetaConfig(mode="nope")  # type: ignore[arg-type]
    with pytest.raises(MetaConfigError):
        MetaConfig(vote_threshold=0.3)
    with pytest.raises(MetaConfigError):
        MetaConfig(gross_exposure_cap=1.5)
    h1 = MetaConfig().config_hash
    h2 = MetaConfig(max_strategy_weight=0.5).config_hash
    assert h1 != h2 and len(h1) == 16


def test_exactly_six_tunables():
    fields = [f for f in MetaConfig.__dataclass_fields__
              if f not in ("policy",)]
    assert set(fields) == {"mode", "vote_threshold", "max_strategy_weight",
                           "gross_exposure_cap", "max_weight_change",
                           "max_positions"}


# ---- Phase 3: eligibility engine ------------------------------------------


@pytest.mark.parametrize("kwargs,reason", [
    ({"kill_switch": True}, "KILL_SWITCH"),
    ({"enabled": False}, "DISABLED"),
    ({"certification_state": None}, "UNCERTIFIED"),
    ({"certification_state": "MYSTERY"}, "UNCERTIFIED"),
    ({"certification_state": "FAILED"}, "CERT_FAILED"),
    ({"certification_state": "NOT_ELIGIBLE"}, "CERT_FAILED"),
    ({"regime": "RANGE"}, "REGIME_UNKNOWN"),
    ({"regime": "HIGH_VOL", "regimes_forbidden":
        frozenset({"HIGH_VOL"})}, "REGIME_FORBIDDEN"),
    ({"drift_score": 0.5, "drift_available": True}, "DRIFT_BLOCK"),
    ({"stale": True}, "STALE_DATA"),
    ({"signal": 2}, "CONFIG_INVALID"),
    ({"drift_score": float("nan")}, "CONFIG_INVALID"),
    ({"drift_score": 1.5}, "CONFIG_INVALID"),
])
def test_eligibility_reasons_are_deterministic(kwargs, reason):
    lay = MetaLayer(MetaConfig())
    e = lay.eligibility([_inp(**kwargs)], as_of=NOW)["a"]
    assert e.reason.value == reason
    assert e.eligible is (reason == "ELIGIBLE")


def test_cooldown_blocks_until_expiry():
    from datetime import timedelta
    lay = MetaLayer(MetaConfig())
    until = NOW + timedelta(hours=1)
    assert lay.eligibility([_inp(cooldown_until=until)],
                           as_of=NOW)["a"].reason.value == "COOLDOWN"
    assert lay.eligibility([_inp(cooldown_until=NOW - timedelta(seconds=1))],
                           as_of=NOW)["a"].eligible


def test_hard_zero_never_receives_weight_in_any_mode():
    for mode in MetaMode:
        lay = MetaLayer(MetaConfig(mode=mode))
        d = lay.decide(_inputs(), as_of=NOW, returns=_retsWith(),
                       oos_stats=STATS)
        w = {x.strategy_id: x.final_weight for x in d.weights}
        assert w["gamma"] == 0.0  # FAILED certification: hard zero
        assert d.eligibility["gamma"].reason is EligibilityReason.CERT_FAILED


# ---- Phase 4/5: factor math ------------------------------------------------


def test_gate_weight_map():
    f = MetaLayer._gate_factor(_inp(state="VERIFIED"))
    assert f.value == 1.0
    assert MetaLayer._gate_factor(
        _inp(state="EMPIRICAL_VALIDATION_PENDING")).value == 0.5
    assert MetaLayer._gate_factor(_inp(state="SOFTWARE_PASS")).value == 0.5
    assert MetaLayer._gate_factor(_inp(state="FAILED")).value == 0.0


def test_performance_factor_shrinks_small_samples():
    # five lucky trades (huge mean) vs hundreds of modest trades
    lucky = MetaLayer._performance_factor(
        _inp("lucky"), {"lucky": (0.10, 5)})
    solid = MetaLayer._performance_factor(
        _inp("solid"), {"solid": (0.01, 300)})
    assert solid.value > lucky.value          # shrinkage beats luck
    assert lucky.value < 1.0                  # and never dominates
    none = MetaLayer._performance_factor(_inp("none"), None)
    assert none.value == 0.5 and none.status.value == "MISSING_FALLBACK"
    # winsorized record stays below the cap even with huge mean
    huge = MetaLayer._performance_factor(
        _inp("huge"), {"huge": (100.0, 10_000)})
    assert huge.value == pytest.approx(0.5998, rel=1e-6)  # clip + prior
    # product formula: raw == product of the five factors exactly
    lay = MetaLayer(MetaConfig())
    d = lay.decide(_inputs()[:1], as_of=NOW,
                   oos_stats={"alpha": (0.02, 100)})
    assert d.raw_scores, "healthy single strategy must score"
    r = d.raw_scores[0]
    prod = 1.0
    for f in r.factors:
        prod *= f.value
    assert r.raw_score == pytest.approx(prod, rel=1e-12)


def test_drift_factor_map_exact():
    assert MetaLayer._drift_factor(
        _inp(drift_score=0.05, drift_available=True)).value == 1.0
    mid = MetaLayer._drift_factor(
        _inp(drift_score=0.30, drift_available=True)).value
    assert mid == pytest.approx(1.0 - (0.30 - 0.10) / 0.40 * 0.5)
    assert MetaLayer._drift_factor(
        _inp(drift_available=False)).value == 0.5  # missing source
    assert MetaLayer._drift_factor(
        _inp(drift_score=DRIFT_BLOCK, drift_available=True)).value == 0.0


# ---- Phase 6: correlation ---------------------------------------------------


def test_correlation_min_observations_and_global_failure():
    n = CORR_MIN_OBS - 1
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    short = pd.DataFrame({"x": np.linspace(0, 1, n),
                          "y": np.linspace(1, 0, n)}, index=idx)
    _, status, gf = MetaLayer.correlation_matrix(
        short, ["x", "y"], as_of=NOW)
    assert gf is True                      # source insufficient for ALL
    assert status["x"].value == "MISSING_FALLBACK"
    _, status, gf = MetaLayer.correlation_matrix(
        _retsWith(), ["alpha", "beta"], as_of=NOW)
    assert gf is False and status["alpha"].value == "OK"


def test_correlation_no_lookahead():
    idx = pd.date_range("2026-01-01", periods=100, freq="h")
    rng = np.random.default_rng(7)
    rets = pd.DataFrame({"a": rng.normal(0, 1, 100),
                         "b": rng.normal(0, 1, 100)}, index=idx)
    cut = idx[50]
    mat, _, _ = MetaLayer.correlation_matrix(rets, ["a", "b"], as_of=cut)
    full, _, _ = MetaLayer.correlation_matrix(
        rets, ["a", "b"], as_of=idx[-1])
    assert mat.loc["a", "b"] == pytest.approx(
        np.corrcoef(rets["a"][:51], rets["b"][:51])[0, 1], abs=1e-12)
    assert mat.loc["a", "b"] != pytest.approx(full.loc["a", "b"], abs=1e-3)


# ---- Phase 8: normalization / caps -----------------------------------------


def test_normalization_sums_to_budget_and_preserves_ratios():
    lay = MetaLayer(MetaConfig())
    d = lay.decide(_inputs(), as_of=NOW, returns=_retsWith(),
                   oos_stats=STATS)
    w = {x.strategy_id: x.final_weight for x in d.weights}
    assert sum(w.values()) == pytest.approx(1.0, rel=1e-9)
    r = {x.strategy_id: x.raw_score for x in d.raw_scores}
    assert w["alpha"] / w["beta"] == pytest.approx(r["alpha"] / r["beta"],
                                                   rel=1e-9)


def test_cap_redistributes_only_into_uncapped_eligible():
    lay = MetaLayer(MetaConfig(max_strategy_weight=0.4))
    d = lay.decide(_inputs(), as_of=NOW, returns=_retsWith(),
                   oos_stats=STATS)
    w = {x.strategy_id: x.final_weight for x in d.weights}
    assert all(v <= 0.4 + 1e-12 for v in w.values())
    assert sum(v for k, v in w.items() if k != "gamma") <= 1.0 + 1e-9
    # if any weight hit the cap, redistribution kept others positive
    if any(x.clamp_reasons for x in d.weights):
        assert w["alpha"] > 0 and w["beta"] > 0


def test_gross_cap_scales_everything_down():
    lay = MetaLayer(MetaConfig(gross_exposure_cap=0.5))
    d = lay.decide(_inputs(), as_of=NOW, returns=_retsWith(),
                   oos_stats=STATS)
    assert sum(x.final_weight for x in d.weights) == pytest.approx(
        0.5, rel=1e-9)


def test_max_positions_keeps_top_k_deterministically():
    lay = MetaLayer(MetaConfig(max_positions=1))
    d = lay.decide(_inputs(), as_of=NOW, returns=_retsWith(),
                   oos_stats=STATS)
    live = [x.strategy_id for x in d.weights if x.final_weight > 0]
    assert len(live) == 1
    best = min(d.raw_scores,
               key=lambda x: (-x.raw_score, x.strategy_id))
    assert live == [best.strategy_id]
    zeroed = [x for x in d.weights if x.final_weight == 0.0
              and x.strategy_id != "gamma"]
    assert all(x.zero_reason is EligibilityReason.MAX_POSITIONS
               for x in zeroed)


def test_no_epsilon_resurrection_of_zero():
    lay = MetaLayer(MetaConfig(max_strategy_weight=0.01))
    d = lay.decide([_inp("hard", state="FAILED"), _inp("ok")],
                   as_of=NOW, oos_stats={"ok": (0.05, 200)})
    assert d.weight_of("hard") == 0.0
    assert "hard" not in {b.strategy_id for b in d.book}


# ---- Phase 9: modes ---------------------------------------------------------


def test_weighted_netting_book_attribution_exact():
    lay = MetaLayer(MetaConfig())  # default mode
    d = lay.decide(_inputs(), as_of=NOW, returns=_retsWith(),
                   oos_stats=STATS)
    wmap = {x.strategy_id: x.final_weight for x in d.weights}
    eurusd = [b for b in d.book if b.symbol == "EURUSD"]
    assert {b.strategy_id: b.contribution for b in eurusd} == {
        "alpha": wmap["alpha"] * 1, "beta": wmap["beta"] * -1}
    assert d.net_by_symbol["EURUSD"] == pytest.approx(
        sum(b.contribution for b in eurusd), abs=1e-12)


def test_vote_threshold_ties_and_abstention():
    cfg = MetaConfig(mode=MetaMode.VOTE, vote_threshold=0.6)
    lay = MetaLayer(cfg)
    # both agree -> fires
    d = lay.decide([_inp("a", signal=1), _inp("b", signal=1)],
                   as_of=NOW, oos_stats={"a": (0.01, 100), "b": (0.01, 100)})
    assert d.vote_by_symbol.get("EURUSD") == 1
    # exact tie -> no trade
    d = lay.decide([_inp("a", signal=1), _inp("b", signal=-1)],
                   as_of=NOW, oos_stats={"a": (0.01, 100), "b": (0.01, 100)})
    assert d.vote_by_symbol == {}
    # below threshold: 2/3 agreeing mass with threshold 0.9 -> no trade
    strict = MetaLayer(MetaConfig(mode=MetaMode.VOTE, vote_threshold=0.9))
    d = strict.decide([_inp("a", signal=1), _inp("b", signal=-1),
                       _inp("c", signal=1)],
                      as_of=NOW, oos_stats={"a": (0.0, 100), "b": (0.0, 100),
                                            "c": (0.0, 100)})
    assert d.vote_by_symbol == {}
    # abstention (signal 0) is EXCLUDED from both masses, not counted
    # against: one agreeing vote fires alone
    d = lay.decide([_inp("a", signal=0), _inp("b", signal=1)],
                   as_of=NOW, oos_stats={"a": (0.0, 100), "b": (0.0, 100)})
    assert d.vote_by_symbol.get("EURUSD") == 1


def test_best_of_regime_winner_and_lexical_tie():
    lay = MetaLayer(MetaConfig(mode=MetaMode.BEST_OF_REGIME))
    d = lay.decide(_inputs(), as_of=NOW, returns=_retsWith(),
                   oos_stats=STATS)
    winners = [x for x in d.weights if x.final_weight > 0]
    assert len(winners) == 1
    best = min(d.raw_scores,
               key=lambda r: (-r.raw_score, r.strategy_id))
    assert winners[0].strategy_id == best.strategy_id
    # exact tie (identical factors) -> lexical ascending wins
    tie = [_inp("zz", signal=1), _inp("aa", signal=1)]
    d = lay.decide(tie, as_of=NOW,
                   oos_stats={"zz": (0.0, 50), "aa": (0.0, 50)},
                   returns=None)
    w = {x.strategy_id: x.final_weight for x in d.weights}
    assert [k for k, v in w.items() if v > 0] == ["aa"]
    # global source failure + best_of_regime: ranking is impossible, so
    # the equal-weight fallback stands (mode ranking suspended, documented)
    nolive = MetaLayer(MetaConfig(mode=MetaMode.BEST_OF_REGIME))
    d = nolive.decide([_inp("a", drift_available=False),
                       _inp("b", drift_available=False)],
                      as_of=NOW)
    assert d.fallback[0] == "equal_weight"
    assert sorted(x.final_weight for x in d.weights) == [0.5, 0.5]


# ---- Phase 11: constraints only reduce --------------------------------------


def test_symbol_and_currency_exposure_never_exceed_budget():
    lay = MetaLayer(MetaConfig())
    d = lay.decide(_inputs(), as_of=NOW, returns=_retsWith(),
                   oos_stats=STATS)
    per_symbol = {}
    for b in d.book:
        per_symbol[b.symbol] = per_symbol.get(b.symbol, 0.0) + abs(
            b.contribution)
    budget = MetaConfig().gross_exposure_cap
    assert all(v <= budget + 1e-9 for v in per_symbol.values())
    assert sum(x.final_weight for x in d.weights) <= budget + 1e-9


def test_daily_change_limit_clamps_movement():
    cfg = MetaConfig(max_weight_change=0.1)
    prev = MetaState(config_hash=cfg.config_hash,
                     weights={"a": 0.0, "b": 0.0})
    lay = MetaLayer(cfg, state=prev)
    d = lay.decide([_inp("a"), _inp("b")], as_of=NOW,
                   oos_stats={"a": (0.01, 100), "b": (0.01, 100)})
    for x in d.weights:
        assert x.final_weight <= 0.1 + 1e-12
        assert "WEIGHT_CHANGE_LIMIT" in x.clamp_reasons
    # ineligibility is NEVER slowed by the limit
    d2 = lay.decide([_inp("a", enabled=False), _inp("b")], as_of=NOW,
                    oos_stats={"b": (0.01, 100)})
    assert d2.weight_of("a") == 0.0
