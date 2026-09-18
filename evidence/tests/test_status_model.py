"""Certification status model (Phase 3 hardening, Blocker 7).

SOFTWARE_PASS / EMPIRICAL_VALIDATION_PENDING / VERIFIED / FAILED are
distinct; MT5 NOT VERIFIED is a separate dimension; "tool executed
successfully" never becomes "strategy verified".
"""

from types import SimpleNamespace

import pytest
from mql5bot.certify import CertifyConfig, render_report, run_certification
from mql5bot.status import (
    EMPIRICAL_VALIDATION_PENDING,
    FAILED,
    MT5_NOT_VERIFIED,
    MT5_VERIFIED,
    NOT_ELIGIBLE,
    SOFTWARE_PASS,
    VERIFIED,
    certify_status_model,
    pipeline_certification_status,
)

# ---------------------------------------------------------------------------
# Pipeline transitions
# ---------------------------------------------------------------------------


def test_zero_survivors_is_not_eligible_never_certified():
    sec = pipeline_certification_status(
        s2_survivors=0, cv_status="skipped", oos_ran=False,
        oos_status="blocked")
    assert sec["status"] == NOT_ELIGIBLE
    assert sec["reason"] == "NO_VALID_SURVIVOR"
    assert sec["status"] != VERIFIED


def test_full_python_funnel_is_empirical_pending_mt5_not_verified():
    sec = pipeline_certification_status(
        s2_survivors=2, cv_status="ok", oos_ran=True, oos_status="ok")
    assert sec["status"] == EMPIRICAL_VALIDATION_PENDING
    assert sec["mt5_status"] == MT5_NOT_VERIFIED


def test_cv_failure_is_failed_not_pending():
    sec = pipeline_certification_status(
        s2_survivors=2, cv_status="error", oos_ran=False,
        oos_status="not_requested")
    assert sec["status"] == FAILED
    assert "purged_cv" in sec["reason"]


def test_oos_failure_is_failed():
    sec = pipeline_certification_status(
        s2_survivors=1, cv_status="ok", oos_ran=True, oos_status="blocked")
    assert sec["status"] == FAILED


def test_software_pass_is_always_recorded_and_never_a_claim():
    for kwargs in (
        {"s2_survivors": 0, "cv_status": "skipped", "oos_ran": False,
         "oos_status": "blocked"},
        {"s2_survivors": 2, "cv_status": "ok", "oos_ran": True,
         "oos_status": "ok"},
    ):
        sec = pipeline_certification_status(**kwargs)
        assert sec["software_status"] == SOFTWARE_PASS


def test_sandbox_cannot_reach_verified():
    """The sandbox has no MT5 terminal: with mt5_status NOT VERIFIED the
    pipeline status is capped at EMPIRICAL_VALIDATION_PENDING for every
    combination of the other flags."""
    for kwargs in (
        {"s2_survivors": 2, "cv_status": "ok", "oos_ran": False,
         "oos_status": "not_requested"},
        {"s2_survivors": 2, "cv_status": "ok", "oos_ran": True,
         "oos_status": "ok"},
        {"s2_survivors": 5, "cv_status": "ok", "oos_ran": True,
         "oos_status": "ok"},
    ):
        sec = pipeline_certification_status(**kwargs)
        assert sec["status"] in (EMPIRICAL_VALIDATION_PENDING, FAILED,
                                 NOT_ELIGIBLE)
        assert sec["status"] != VERIFIED


# ---------------------------------------------------------------------------
# Certification ladder mapping
# ---------------------------------------------------------------------------


def test_certify_mapping():
    assert certify_status_model(VERIFIED, 6, 6) == {
        "status": VERIFIED, "mt5_status": MT5_VERIFIED, "reason": ""}
    # a leg ran and failed -> FAILED (with MT5 still not verified)
    assert certify_status_model("NOT VERIFIED", 6, 4)["status"] == FAILED
    # nothing required ran -> EMPIRICAL_VALIDATION_PENDING, honest reason
    pending = certify_status_model("NOT VERIFIED", 0, 0)
    assert pending["status"] == EMPIRICAL_VALIDATION_PENDING
    assert pending["mt5_status"] == MT5_NOT_VERIFIED
    assert "did not run" in pending["reason"]


class _Outcome:
    def __init__(self, ok: bool, report=None, error: str = ""):
        self.ok = ok
        self.report = report
        self.error = error
        self.run_id = "rid"


def test_run_certification_without_terminal_is_pending_not_verified(
        tmp_path):
    """No MT5 runner: every required leg is 'did not run' -> the report
    is EMPIRICAL_VALIDATION_PENDING with MT5 NOT VERIFIED.  A successful
    Python cross-check leg never upgrades the verdict."""
    cfg = CertifyConfig(strategy="ema_crossover", ea="Experts\\Mql5Bot\\Mql5Bot.ex5",
                        symbol="EURUSD", timeframe="M1", manifest_id="")
    report = run_certification(cfg, run_tester=None)
    assert report["verdict"]["status"] == "NOT VERIFIED"
    sm = report["status_model"]
    assert sm["status"] == EMPIRICAL_VALIDATION_PENDING
    assert sm["mt5_status"] == MT5_NOT_VERIFIED
    text = render_report(report)
    assert "EMPIRICAL_VALIDATION_PENDING" in text
    assert "NOT VERIFIED" in text
    assert "## VERDICT: VERIFIED" not in text


def test_run_certification_failed_leg_is_failed(tmp_path):
    """A required MT5 leg that RAN and failed -> FAILED (not pending,
    not verified)."""
    cfg = CertifyConfig(strategy="ema_crossover", ea="Experts\\Mql5Bot\\Mql5Bot.ex5",
                        symbol="EURUSD", timeframe="M1", manifest_id="")
    report = run_certification(
        cfg, run_tester=lambda tc: _Outcome(False, None, "boom"))
    sm = report["status_model"]
    assert sm["status"] == FAILED
    assert sm["mt5_status"] == MT5_NOT_VERIFIED


# ---------------------------------------------------------------------------
# Degradation is REPORTED, never a gate (Phase 12 policy)
# ---------------------------------------------------------------------------


def _mt5_leg(net: float):
    """A passing MT5 leg netting ``net`` (SimpleNamespace report, same
    shape test_certify uses)."""
    return SimpleNamespace(ok=True, error="",
                           report=SimpleNamespace(metrics={
                               "total_net_profit": net,
                               "total_trades": 250,
                               "profit_factor": 1.2,
                           }))


def _ladder_runner(net_base: float, net_tick: float):
    """M1-OHLC baseline legs net ``net_base``; tick grades net
    ``net_tick`` — the degradation under test."""
    return lambda tc: _mt5_leg(net_base if tc.model == 1 else net_tick)


def test_degradation_outside_band_is_a_finding_not_a_gate(tmp_path):
    """An 80% real-tick degradation (far outside the historical 30-50%
    band) is REPORTED as measured but must NOT fail the verdict when
    every gate (ran/ok/trade-minimum) passes — the band is informative
    only."""
    cfg = CertifyConfig(strategy="ema_crossover", ea="Experts\\Mql5Bot\\Mql5Bot.ex5",
                        symbol="EURUSD", timeframe="M1", manifest_id="",
                        min_trades=100)
    report = run_certification(
        cfg, run_tester=_ladder_runner(1000.0, 200.0),
        reconciliation_ok=True)
    deg = report["degradation"]
    assert deg, "degradation must be reported"
    worst = min(d["net_profit"]["degradation_pct"] for d in deg)
    assert worst <= -50.0  # observed, far below the historical band
    assert all(d["net_profit"]["inside_band"] is False for d in deg)
    # informative flag only: the verdict still reflects the hard gates
    assert report["verdict"]["status"] == VERIFIED
    sm = report["status_model"]
    assert sm["status"] == VERIFIED
    # and the finding is visible in the rendered report
    text = render_report(report)
    assert "80.0" in text or "degradation" in text.lower()


def test_degradation_mild_also_reported(tmp_path):
    """5% degradation (better than the band) is likewise reported
    truthfully and never gates."""
    cfg = CertifyConfig(strategy="ema_crossover", ea="Experts\\Mql5Bot\\Mql5Bot.ex5",
                        symbol="EURUSD", timeframe="M1", manifest_id="",
                        min_trades=100)
    report = run_certification(
        cfg, run_tester=_ladder_runner(1000.0, 950.0),
        reconciliation_ok=True)
    assert report["verdict"]["status"] == VERIFIED
    deg = report["degradation"][0]["net_profit"]
    assert deg["degradation_pct"] == pytest.approx(-5.0)
    assert deg["inside_band"] is False


# ---------------------------------------------------------------------------
# Certification model lock (FINAL CERTIFICATION MODEL LOCK mission §3/§4):
# the gold-semantic lane and the empirical lane are INDEPENDENT dimensions.
# ---------------------------------------------------------------------------


def test_gold_semantic_lane_is_an_independent_dimension():
    from mql5bot.status import (
        GOLD_SEMANTIC_PASS,
        GOLD_SEMANTIC_PENDING,
        MT5_NOT_VERIFIED,
        gold_semantic_status,
    )

    # gold pass is derived ONLY from the frozen-fixture checks
    both = gold_semantic_status(gold1_ok=True, gold2_ok=True)
    assert both["gold_status"] == GOLD_SEMANTIC_PASS
    assert gold_semantic_status(gold1_ok=False, gold2_ok=True)[
        "gold_status"] == GOLD_SEMANTIC_PENDING
    assert gold_semantic_status(gold1_ok=True, gold2_ok=False)[
        "gold_status"] == GOLD_SEMANTIC_PENDING
    # ...and it never claims anything about the MT5 dimension
    assert "never implies" in both["note"]
    assert MT5_NOT_VERIFIED == "NOT VERIFIED"


def test_empirical_pass_never_produces_gold_semantic_pass():
    """Mission §4 mirror rule: 100 empirical trades can never prove gold
    semantic parity — the lanes never substitute for each other."""
    from mql5bot.status import (
        GOLD_SEMANTIC_PASS,
        GOLD_SEMANTIC_PENDING,
        gold_semantic_status,
    )

    # an empirical run carries no gold checks at all: without the
    # byte-level reconciliation evidence the gold lane stays PENDING
    empirical_only = gold_semantic_status(gold1_ok=False, gold2_ok=False)
    assert empirical_only["gold_status"] == GOLD_SEMANTIC_PENDING
    assert empirical_only["gold_status"] != GOLD_SEMANTIC_PASS


def test_withheld_status_reason_names_the_missing_evidence():
    from mql5bot.status import certify_status_model

    # every leg ran ok but the verdict was withheld for missing evidence
    sm = certify_status_model("NOT VERIFIED", 16, 16,
                              withheld_reasons=("reconciliation missing",))
    assert sm["status"] == "EMPIRICAL_VALIDATION_PENDING"
    assert sm["mt5_status"] == "NOT VERIFIED"
    assert "withheld" in sm["reason"]
    assert "reconciliation missing" in sm["reason"]
