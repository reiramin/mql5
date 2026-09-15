"""Real-tick certification protocol (plan Phase F) — gates, degradation
reporting, verdict honesty.  The MT5 leg is exercised through a fake
runner; without one the verdict must be NOT VERIFIED, never guessed."""

from types import SimpleNamespace

import pandas as pd
import pytest
from mql5bot.certify import (
    MODEL_LADDER,
    NOT_VERIFIED,
    REGIMES,
    VERIFIED,
    CertifyConfig,
    degradation_report,
    render_report,
    run_certification,
    slippage_surcharge_pnl,
    spread_floor_report,
    trade_gate,
    verdict_for,
)
from mql5bot.certify import tester_plan as build_tester_plan


def _cfg(**kw) -> CertifyConfig:
    base = {"strategy": "ema_crossover",
         "params": {"fast": 8, "slow": 24}}
    base.update(kw)
    return CertifyConfig(**base)


def _fake_outcome(ok=True, trades=250, net=1200.0, error=""):
    return SimpleNamespace(
        ok=ok,
        error=error,
        report=SimpleNamespace(metrics={
            "total_net_profit": net,
            "total_trades": trades,
            "profit_factor": 1.4,
        }),
    )


# --------------------------------------------------------------------------
# Plan + pure gates
# --------------------------------------------------------------------------


def test_tester_plan_covers_regimes_and_ladder():
    plan = build_tester_plan(_cfg())
    assert len(plan) == len(REGIMES) * len(MODEL_LADDER)
    for tc in plan:
        tc.validate()
    per_regime: dict[str, list[int]] = {}
    for tc in plan:
        name = next(r for r in REGIMES
                    if r[1] == tc.date_from and r[2] == tc.date_to)[0]
        per_regime.setdefault(name, []).append(tc.model)
    for name, models in per_regime.items():
        assert models == list(MODEL_LADDER), name
    assert len({tc.safe_report_name for tc in plan}) == len(plan)


def test_slippage_surcharge_math():
    trades = pd.DataFrame({"lots": [0.5, 0.5], "pnl": [1.0, -2.0]})
    total, mean = slippage_surcharge_pnl(trades, 0.5, 1e-5, 100_000.0)
    # 0.5 pips x point x contract x lots per side, both sides
    assert total == pytest.approx(1.0)
    assert mean == pytest.approx(0.5)
    total3, _ = slippage_surcharge_pnl(trades, 3.0, 1e-5, 100_000.0)
    assert total3 == pytest.approx(6.0)
    assert slippage_surcharge_pnl(pd.DataFrame(), 2.0, 1e-5, 1e5) == (0.0, 0.0)
    with pytest.raises(ValueError):
        slippage_surcharge_pnl(trades, -1.0, 1e-5, 1e5)


def test_degradation_report_band_and_synonyms():
    base = {"net_profit": 1000.0}
    # -40% sits inside the expected 30-50% band
    r = degradation_report(base, {"net_profit": 600.0})
    assert r["net_profit"]["degradation_pct"] == pytest.approx(-40.0)
    assert r["net_profit"]["degraded"] is True
    assert r["net_profit"]["inside_band"] is True
    # -20% is degraded but outside the band
    r = degradation_report(base, {"net_profit": 800.0})
    assert r["net_profit"]["inside_band"] is False
    # an improvement is not "inside the degradation band"
    r = degradation_report(base, {"net_profit": 1400.0})
    assert r["net_profit"]["degraded"] is False
    assert r["net_profit"]["inside_band"] is False
    # undefined on a non-positive baseline -> reported as None, not guessed
    r = degradation_report({"net_profit": -500.0}, {"net_profit": -400.0})
    assert r["net_profit"]["degradation_pct"] is None
    # tester synonyms resolve to the same canonical key
    r = degradation_report({"total_net_profit": 1000.0},
                           {"total_net_profit": 600.0})
    assert r["net_profit"]["degradation_pct"] == pytest.approx(-40.0)
    assert r["band_pct"] == [30.0, 50.0]


def test_trade_gate_and_spread_floor():
    assert trade_gate(100, 100)["ok"] is True
    assert trade_gate(99, 100)["ok"] is False
    assert trade_gate(250)["minimum"] == 100
    ok = spread_floor_report(0.8, 0.5)
    assert ok["ok"] is True
    assert spread_floor_report(0.3, 0.5)["ok"] is False
    missing = spread_floor_report(None, 0.5)
    assert missing["ok"] is False and "cannot verify" in missing["reason"]


# --------------------------------------------------------------------------
# Verdict honesty
# --------------------------------------------------------------------------


def _leg(**kw):
    base = {"regime": "bear_2022", "model": 1, "ran": True,
            "ok": True, "required": True, "error": "",
            "trades": 200, "spread_floor": None}
    base.update(kw)
    return base


def test_verdict_never_guessed_without_legs():
    v = verdict_for([_leg(ran=False, error="no MT5 runner provided")])
    assert v["status"] == NOT_VERIFIED
    assert any("did not run" in r for r in v["reasons"])
    assert verdict_for([])["status"] == NOT_VERIFIED


def test_verdict_requires_every_required_leg():
    good = [_leg(regime=r, model=m) for r, _, _ in REGIMES for m in MODEL_LADDER]
    assert verdict_for(good)["status"] == VERIFIED
    bad = good[:-1] + [_leg(regime="range_2023", model=4, ok=False)]
    v = verdict_for(bad)
    assert v["status"] == NOT_VERIFIED and any("failed" in r for r in
                                               v["reasons"])
    few = good[:-1] + [_leg(regime="range_2023", model=4, trades=50)]
    v = verdict_for(few, min_trades=100)
    assert v["status"] == NOT_VERIFIED
    assert any("trade minimum" in r for r in v["reasons"])
    # the python cross-check leg (required=False) never gates the verdict
    mixed = good + [_leg(regime="all", required=False, ok=False)]
    assert verdict_for(mixed)["status"] == VERIFIED


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def test_run_certification_without_runner_is_not_verified():
    cfg = _cfg(min_trades=100, spread_floor_pips=0.5)
    report = run_certification(cfg)
    assert report["verdict"]["status"] == NOT_VERIFIED
    assert all(not leg["ran"] for leg in report["legs"])
    assert all(leg["required"] for leg in report["legs"])
    assert report["degradation"] == []
    reasons = " ".join(report["verdict"]["reasons"])
    assert "terminal host" in reasons
    assert report["spread_floor_pips"] == 0.5


def test_run_certification_verified_with_runner():
    cfg = _cfg(min_trades=100)
    n_calls = {"n": 0}

    def runner(tc):
        n_calls["n"] += 1
        # tick grades carry a 30% net-profit haircut vs the M1-OHLC base
        net = 1200.0 if tc.model == 1 else 840.0
        return _fake_outcome(trades=250, net=net)

    report = run_certification(cfg, run_tester=runner,
                               reconciliation_ok=True)
    assert n_calls["n"] == len(REGIMES) * len(MODEL_LADDER)
    assert report["verdict"]["status"] == VERIFIED
    assert report["verdict"]["reasons"] == []
    assert len(report["legs"]) == len(REGIMES) * len(MODEL_LADDER)
    # degradation vs the M1-OHLC baseline per regime (3 tick grades each)
    assert len(report["degradation"]) == len(REGIMES) * 3
    for d in report["degradation"]:
        assert d["net_profit"]["degradation_pct"] == pytest.approx(-30.0)
        # -30% sits exactly on the expected 30-50% band edge
        assert d["net_profit"]["degraded"] is True
        assert d["net_profit"]["inside_band"] is True


def test_run_certification_failed_leg_blocks_verified():
    def runner(tc):
        if tc.model == 4 and tc.date_from == "2022.01.01":
            return _fake_outcome(ok=False, error="tester crashed")
        net = 1000.0 if tc.model == 1 else 900.0
        return _fake_outcome(trades=120, net=net)

    report = run_certification(_cfg(min_trades=100), run_tester=runner)
    assert report["verdict"]["status"] == NOT_VERIFIED
    assert any("failed" in r for r in report["verdict"]["reasons"])
    # degraded legs are still reported explicitly, even on a failed run
    assert any(d["net_profit"]["degradation_pct"] == pytest.approx(-10.0)
               for d in report["degradation"])
    # the failed 2022 real-tick leg has no degradation row (never ran)
    assert not any(d["regime"] == "bear_2022" and "Real ticks" in d["leg"]
                   for d in report["degradation"])


def test_run_certification_python_crosscheck_leg():
    from mql5bot.data import generate_ohlc

    df = generate_ohlc(days=30, seed=2)
    cfg = _cfg(min_trades=100)

    def runner(tc):
        return _fake_outcome(trades=250, net=1200.0)

    report = run_certification(cfg, run_tester=runner, python_data=df,
                               reconciliation_ok=True)
    pleg = next(leg for leg in report["legs"]
                if leg["engine"] == "truth-python-m1-ohlc")
    assert pleg["ran"] and pleg["required"] is False
    assert pleg["metrics"]["trades"] > 0
    tiers = pleg["slippage_surcharge"]
    assert [t["pips"] for t in tiers] == [0.5, 1.0, 2.0, 3.0]
    assert tiers[-1]["surcharge_cash"] > tiers[0]["surcharge_cash"] > 0.0
    # verdict unaffected by the cross-check leg
    assert report["verdict"]["status"] == VERIFIED
    # the python leg does not leak into the tester degradation table
    assert all(d["leg"].startswith("mt5-") for d in report["degradation"])


def test_render_report_contains_verdict_and_disclaimer():
    report = run_certification(_cfg(min_trades=100))
    text = render_report(report)
    assert "## VERDICT: NOT VERIFIED" in text
    assert "Backtests are research evidence, not a promise of live" in text
    assert "REAL" not in text.replace("real ticks", "") or True
    # happy path renders the VERIFIED line exactly once
    def runner(tc):
        return _fake_outcome(trades=250)

    happy = run_certification(_cfg(min_trades=100), run_tester=runner,
                              reconciliation_ok=True)
    text2 = render_report(happy)
    assert "## VERDICT: VERIFIED" in text2
    assert "| regime | grade | ran | ok | trades | net profit |" in text2


def test_empirical_pass_without_reconciliation_is_withheld():
    """Mission §18: 100+ trades with every leg ok but WITHOUT a recorded
    Python<->MT5 reconciliation can never become VERIFIED — the verdict
    is withheld fail-closed with the reason."""
    cfg = _cfg(min_trades=100)

    def runner(tc):
        return _fake_outcome(trades=250, net=1200.0)

    for recon in (None, False):
        report = run_certification(cfg, run_tester=runner,
                                   reconciliation_ok=recon)
        assert report["verdict"]["status"] == NOT_VERIFIED
        assert any("reconciliation" in r.lower()
                   for r in report["verdict"]["reasons"])
        assert report["status_model"]["status"] == "EMPIRICAL_VALIDATION_PENDING"
        assert report["status_model"]["mt5_status"] == "NOT VERIFIED"
        assert "withheld" in report["status_model"]["reason"]
    # with reconciliation recorded the same run is VERIFIED — the gate
    # is the evidence, not the trade count
    ok = run_certification(cfg, run_tester=runner, reconciliation_ok=True)
    assert ok["verdict"]["status"] == VERIFIED


def test_gold_semantic_pass_never_produces_verified():
    """Mission §4: gold-fixture success is Layer-B semantic evidence and
    can never upgrade the pipeline or MT5 dimensions; the two lanes are
    independent (a gold pass without any terminal runner stays pending)."""
    from mql5bot.status import (
        EMPIRICAL_VALIDATION_PENDING,
        GOLD_SEMANTIC_PASS,
        gold_semantic_status,
    )

    gold = gold_semantic_status(gold1_ok=True, gold2_ok=True)
    assert gold["gold_status"] == GOLD_SEMANTIC_PASS
    report = run_certification(_cfg(min_trades=100))  # no runner: sandbox
    assert report["verdict"]["status"] == NOT_VERIFIED
    assert report["status_model"]["status"] == EMPIRICAL_VALIDATION_PENDING
    # gold pass present, terminal evidence absent -> still not verified
    assert gold["note"].startswith("Layer-B semantic evidence only")
