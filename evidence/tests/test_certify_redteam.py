"""Certification red-team + fail-closed regressions (FINAL REALITY-GATE).

Mission §13 (unsupported generated strategy must fail closed as
NOT_EXECUTABLE), §14 (stale/fake/empty/malformed artifacts must never
become an ok leg) and §15 (no artifact/state ever upgrades to VERIFIED
without real terminal evidence).

Every attack below must FAIL CLOSED: the outcome is a recorded refusal
with a reason, never a pass.
"""

from __future__ import annotations

import pytest
from mql5bot import certify, mt5tester
from mql5bot.mt5tester import (
    MT5_MODEL_LABELS,
    REAL_TICK_COVERAGES,
    ReportData,
    parse_report_html,
    report_gate,
)

# ---------------------------------------------------------------------------
# §14 — report-level attacks (empty / truncated / non-report / malformed)
# ---------------------------------------------------------------------------


def test_redteam_no_report_is_not_a_leg():
    ok, reason = report_gate(None)
    assert not ok
    assert "did not parse" in reason


def test_redteam_empty_report_fails_closed():
    parsed = parse_report_html("")
    ok, reason = report_gate(parsed)
    assert not ok
    assert "no tables" in reason


def test_redteam_non_report_html_fails_closed():
    # a page that is not a tester report at all
    parsed = parse_report_html("<html><body><p>hello world</p></body></html>")
    ok, reason = report_gate(parsed)
    assert not ok
    assert "no tables" in reason


def test_redteam_truncated_table_without_rows_fails_closed():
    parsed = parse_report_html("<table></table>")
    ok, _reason = report_gate(parsed)
    assert not ok


def test_redteam_minimal_real_report_passes_the_gate():
    html = """
    <table>
      <tr><td>Symbol</td><td>EURUSD (Euro vs US Dollar)</td></tr>
      <tr><td>Model</td><td>Every tick based on real ticks</td></tr>
      <tr><td>Total Net Profit</td><td>123.45</td></tr>
      <tr><td>Total Trades</td><td>42</td></tr>
    </table>
    """
    parsed = parse_report_html(html)
    ok, reason = report_gate(parsed)
    assert ok, reason
    # the report's ACTUAL modelling mode is captured as evidence
    assert parsed.settings.get("model") == "Every tick based on real ticks"
    assert parsed.settings.get("symbol", "").startswith("EURUSD")


def test_redteam_wrong_config_values_are_rejected():
    with pytest.raises(ValueError):
        mt5tester.TesterConfig(model=99).validate()           # wrong model
    with pytest.raises(ValueError):
        mt5tester.TesterConfig(timeframe="X9").validate()     # wrong timeframe
    with pytest.raises(ValueError):
        mt5tester.TesterConfig(symbol="   ").validate()       # wrong symbol
    with pytest.raises(ValueError):
        mt5tester.TesterConfig(date_from="2020-01-01").validate()  # wrong date form


# ---------------------------------------------------------------------------
# §13 — unsupported generated strategy must fail closed (NOT_EXECUTABLE)
# ---------------------------------------------------------------------------


def test_builtin_five_are_the_only_executable_ids():
    assert certify.MQL5_EXECUTABLE_STRATEGIES == frozenset({
        "ema_crossover",
        "rsi_reversal",
        "donchian_breakout",
        "bollinger_reversal",
        "macd_momentum",
    })
    for sid in certify.MQL5_EXECUTABLE_STRATEGIES:
        assert certify.mql5_execution_status(sid) == certify.EXECUTABLE


@pytest.mark.parametrize("sid", [
    "ichimoku_cloud_drift",      # research-universe kind, not an EA engine
    "t3_breakout",
    "gold2_multifactor",         # Gold #2 strategy: research/DSL surface
    "ema_crossover ",            # near-miss / spoofing ids
    "",
])
def test_unsupported_generated_strategy_is_not_executable(sid):
    assert certify.mql5_execution_status(sid) == certify.NOT_EXECUTABLE


def test_not_executable_strategy_never_reaches_a_tester_leg():
    """A strategy outside the five built-in engines can never produce an
    MT5 leg — the runner must not even be invoked (no approximation onto
    a built-in, no silent substitution)."""
    invoked = []

    def runner(tc):  # pragma: no cover — must never run
        invoked.append(tc)
        raise AssertionError("runner invoked for a NOT_EXECUTABLE strategy")

    cfg = certify.CertifyConfig(strategy="ichimoku_cloud_drift")
    report = certify.run_certification(cfg, run_tester=runner)

    assert report["mql5_execution"] == certify.NOT_EXECUTABLE
    required = [leg for leg in report["legs"] if leg["required"]]
    assert required, "the tester ladder must still be listed"
    assert all(not leg["ran"] and not leg["ok"] for leg in required)
    assert all("NOT_EXECUTABLE" in leg["error"] for leg in required)
    assert report["verdict"]["status"] == certify.NOT_VERIFIED
    assert report["status_model"]["status"] != certify.VERIFIED
    assert not invoked


def test_executable_strategy_without_runner_stays_pending_not_verified():
    """§15 — a built-in strategy with no terminal is honest PENDING,
    never VERIFIED: Python-only evidence cannot produce MT5 validation."""
    cfg = certify.CertifyConfig(strategy="ema_crossover")
    report = certify.run_certification(cfg)
    assert report["mql5_execution"] == certify.EXECUTABLE
    assert report["verdict"]["status"] == certify.NOT_VERIFIED
    assert report["status_model"]["mt5_status"] == "NOT VERIFIED"
    assert report["status_model"]["status"] == "EMPIRICAL_VALIDATION_PENDING"


# ---------------------------------------------------------------------------
# §4 — real-tick coverage vocabulary is a closed set
# ---------------------------------------------------------------------------


def test_real_tick_coverage_vocabulary_is_closed():
    assert REAL_TICK_COVERAGES == (
        "REAL_TICK_COVERAGE_FULL",
        "REAL_TICK_COVERAGE_PARTIAL",
        "REAL_TICK_COVERAGE_UNKNOWN",
    )


def test_model_ladder_distinguishes_every_tick_from_real_ticks():
    # §20 — the two tick grades are different modelling paths, and both
    # sit ABOVE the M1-OHLC baseline in the strict ladder.
    assert MT5_MODEL_LABELS[0] == "Every tick"
    assert MT5_MODEL_LABELS[3] == "Every tick based on real ticks"
    assert certify.MODEL_LADDER == (1, 0, 3, 4)


def test_report_data_shape_is_hashable_evidence_container():
    # the parsed report keeps every raw row — an edited report cannot
    # silently lose fields between archive and reconciliation
    data = ReportData(tables=1, settings={}, fields={"A": "1"}, metrics={})
    assert data.to_dict()["fields"] == {"A": "1"}


def test_minimal_unsupported_universe_kind_fails_closed_end_to_end():
    """Mission §20 — the minimal boundary case: a generated strategy
    built on an indicator that EXISTS in the 71-kind research universe
    but has no representation in the five-engine MQL5 execution
    surface. Expected: promotion stops, execution status is
    NOT_EXECUTABLE, no MT5 order path exists, and certification can
    never become VERIFIED. No interpreter is introduced."""
    from mql5bot.factory import lifecycle as lc
    from mql5bot.indicator_universe import ALL_KINDS

    kind = "T3"                       # in the 71-kind universe…
    assert kind in ALL_KINDS
    sid = f"{kind.lower()}_drift"     # …but not an EA engine id
    assert sid not in certify.MQL5_EXECUTABLE_STRATEGIES
    assert certify.mql5_execution_status(sid) == certify.NOT_EXECUTABLE

    # promotion toward any execution state stops without evidence —
    # an unsupported spec has no shadow_entry evidence to offer
    with pytest.raises(lc.IllegalTransition):
        lc.check_transition(lc.OOS_SURVIVOR, lc.SHADOW,
                            evidence_refs=(), actor="gate:test")

    # certification refuses the tester legs before any runner call and
    # can never reach VERIFIED
    def poisoned_runner(tc):  # pragma: no cover — must never run
        raise AssertionError("runner invoked for NOT_EXECUTABLE strategy")

    report = certify.run_certification(
        certify.CertifyConfig(strategy=sid), run_tester=poisoned_runner,
        reconciliation_ok=True)
    assert report["mql5_execution"] == certify.NOT_EXECUTABLE
    assert report["verdict"]["status"] == certify.NOT_VERIFIED
    assert report["status_model"]["status"] != certify.VERIFIED
