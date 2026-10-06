"""S8-CEILING-1 (owner decision 2026-10-06): MT5_VALIDATED_BAR_MODELS.

The gold fixtures are bar-only, so a VALID REAL_TICK_COVERAGE_NONE record
capped the verdict at NOT_VERIFIED_REAL_TICK_COVERAGE_UNKNOWN forever.
MT5_VALIDATED_BAR_MODELS is assigned ONLY when every other MT5_VALIDATED
condition holds AND the coverage is a VALID NONE record. A scoped run maps
it to the non-positive _PARTIAL_SCOPE form. MT5_VALIDATED stays FULL-only.

Verifier self-tests on synthetic owner packages (test_owner_gate): a green
test here is NOT MT5 evidence.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from mql5bot import certify
from mql5bot import owner_gate as og
from test_owner_gate import FROZEN, _build_manifest, _w, build_package, gate

REPO = Path(__file__).resolve().parents[1]
PS1 = (REPO / "tools" / "owner_gate.ps1").read_text(encoding="utf-8")
PHRASE = "no real-tick claim; m1_ohlc + every_tick only"


def bar_only(root: Path, golds=og.GOLDS, *, cov_mutate=None,
             stage5_golds=None) -> Path:
    """Turn a complete synthetic package into the bar-only shape the gate
    builds: each gold's real_ticks leg NOT_APPLICABLE (no reports, a
    not_applicable triad, the gate's stage-5 record naming it) and a
    REAL_TICK_COVERAGE_NONE coverage record. Re-binds the manifest."""
    for g in golds:
        (root / g / "real_ticks.htm").unlink()
        (root / "parsed" / f"{g}_real_ticks.json").unlink()
        path = root / "reconciliation" / f"{g}.json"
        recon = json.loads(path.read_text(encoding="utf-8"))
        b = recon["bindings"]
        del b["raw_report_hashes"]["real_ticks"]
        del b["parsed_report_hashes"]["real_ticks"]
        b["tester_models"]["real_ticks"] = {
            "not_applicable": True, "outcome": og.STAGE5_NOT_APPLICABLE}
        _w(path, recon)
    named = golds if stage5_golds is None else stage5_golds
    _w(root / og.GATE_STAGE5_REL, {
        "stage": 5, "name": "tester_legs", "status": "PASS_FROM_LOG",
        "reason": "; ".join(
            f"{g}_real_ticks: {og.STAGE5_NOT_APPLICABLE}: bar-only fixture "
            f"artifacts/{g}/fixture.csv -- leg NOT launched, NOT a pass"
            for g in named)})
    cov = {"coverage": og.REAL_TICK_COVERAGE_NONE, "leg_launched": False,
           "outcome": og.STAGE5_NOT_APPLICABLE,
           "golds": {g: {"fixture": f"artifacts/{g}/fixture.csv",
                         "leg": "not launched"} for g in golds},
           "note": "NONE (bar-only fixture)"}
    if cov_mutate:
        cov_mutate(cov)
    _w(root / "real_tick_coverage.json", cov)
    _w(root / "archive_manifest.json", _build_manifest(root))
    return root


def scoped(root, golds=("gold2",)):
    return og.run_gate(root, FROZEN, list(golds))


# ---------------------------------------------------------------------------
# the new branch
# ---------------------------------------------------------------------------

def test_bar_only_complete_package_is_mt5_validated_bar_models(tmp_path):
    rep = gate(bar_only(build_package(tmp_path)))
    assert rep["verdict"] == og.MT5_VALIDATED_BAR_MODELS
    assert rep["real_tick_coverage"]["state"] == og.VALID
    assert rep["real_tick_coverage"]["coverage"] == og.REAL_TICK_COVERAGE_NONE
    assert PHRASE in rep["reasons"][0]
    assert og.BAR_MODELS_REASON == PHRASE
    assert rep["verdict"] in og.POSITIVE_VERDICTS


def test_bar_models_is_never_mt5_validated(tmp_path):
    rep = gate(bar_only(build_package(tmp_path)))
    assert rep["verdict"] != og.MT5_VALIDATED


def test_scoped_bar_only_run_is_partial_scope_and_not_positive(tmp_path):
    rep = scoped(bar_only(build_package(tmp_path)))
    assert rep["verdict"] == og.MT5_VALIDATED_BAR_MODELS_PARTIAL_SCOPE
    assert rep["verdict"] not in og.POSITIVE_VERDICTS
    assert PHRASE in rep["reasons"][0]
    assert any(r.startswith("PARTIAL: excluded ['gold1']")
               for r in rep["reasons"])


# ---------------------------------------------------------------------------
# every other ladder branch, unchanged
# ---------------------------------------------------------------------------

def test_full_coverage_is_still_mt5_validated(tmp_path):
    rep = gate(build_package(tmp_path))
    assert rep["verdict"] == og.MT5_VALIDATED
    assert PHRASE not in " ".join(rep["reasons"])


def test_scoped_full_coverage_is_still_mt5_validated_partial_scope(tmp_path):
    rep = scoped(build_package(tmp_path))
    assert rep["verdict"] == og.MT5_VALIDATED_PARTIAL_SCOPE
    assert rep["verdict"] not in og.POSITIVE_VERDICTS


@pytest.mark.parametrize("coverage", ["PARTIAL", "UNKNOWN"])
def test_partial_and_unknown_coverage_stay_capped(tmp_path, coverage):
    rep = gate(build_package(tmp_path, coverage=coverage))
    assert rep["verdict"] == og.NOT_VERIFIED_REAL_TICK_COVERAGE_UNKNOWN


def test_an_invalid_none_record_is_never_bar_models(tmp_path):
    # NONE claiming the leg ran: the record is INVALID -> missing evidence
    root = bar_only(build_package(tmp_path),
                    cov_mutate=lambda c: c.update(leg_launched=True))
    rep = gate(root)
    assert rep["real_tick_coverage"]["state"] == og.INVALID
    assert rep["verdict"] == og.NOT_VERIFIED_MISSING_MT5_EVIDENCE


def test_a_mismatched_none_record_is_never_bar_models(tmp_path):
    # the coverage names gold1 but the stage-5 record marks only gold2
    root = bar_only(build_package(tmp_path), stage5_golds=("gold2",))
    rep = gate(root)
    assert rep["verdict"] not in (og.MT5_VALIDATED_BAR_MODELS,
                                  og.MT5_VALIDATED)
    assert rep["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH


def test_bar_only_with_a_divergence_is_artifact_mismatch(tmp_path):
    root = bar_only(build_package(tmp_path,
                                  diverge_gold2=("sl", 1.05, 1.06)))
    rep = gate(root)
    assert rep["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH


@pytest.mark.parametrize("skip", [("safety",), ("hedging",),
                                  ("environment",), ("symbolspec",)])
def test_bar_only_with_missing_evidence_gets_the_unchanged_verdict(
        tmp_path_factory, skip):
    # the same defect yields the same verdict as with FULL coverage: no
    # other rule changed, and it is never a bar-models pass
    full = gate(build_package(tmp_path_factory.mktemp("f"), skip=skip))
    bar = gate(bar_only(build_package(tmp_path_factory.mktemp("b"),
                                      skip=skip)))
    assert bar["verdict"] == full["verdict"]
    assert bar["verdict"] not in og.POSITIVE_VERDICTS


def test_bar_only_without_reconciliation_never_passes(tmp_path_factory):
    def drop(root):
        for g in og.GOLDS:
            (root / "reconciliation" / f"{g}.json").unlink()
        _w(root / "archive_manifest.json", _build_manifest(root))
        return root
    full = gate(drop(build_package(tmp_path_factory.mktemp("f"))))
    bar = gate(drop(bar_only(build_package(tmp_path_factory.mktemp("b")))))
    assert bar["verdict"] == full["verdict"]
    assert bar["verdict"] not in og.POSITIVE_VERDICTS


# ---------------------------------------------------------------------------
# the verifier tool's exit code, certify scope label, ps1 wiring
# ---------------------------------------------------------------------------

def _tool(root, *extra):
    return subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_owner_mt5_gate.py"),
         str(root), "--repo", str(REPO), *extra],
        capture_output=True, text=True, check=False)


def test_tool_exit_follows_positive_verdicts():
    assert og.MT5_VALIDATED_BAR_MODELS in og.POSITIVE_VERDICTS
    assert og.MT5_VALIDATED_BAR_MODELS_PARTIAL_SCOPE not in \
        og.POSITIVE_VERDICTS
    assert og.MT5_VALIDATED_PARTIAL_SCOPE not in og.POSITIVE_VERDICTS


def test_certificate_states_the_bar_models_scope():
    report = certify.run_certification(
        certify.CertifyConfig(strategy="gold2_multifactor"),
        run_tester=None, runner_note="no terminal (test)")
    report["certificate_scope"] = "bar models"
    text = certify.render_report(report)
    assert "Certificate scope: bar models — " + PHRASE in text


def test_certify_strategy_takes_the_scope():
    src = (REPO / "tools" / "certify_strategy.py").read_text("utf-8")
    assert '"--certificate-scope", default="full"' in src
    assert 'choices=("full", "bar models")' in src
    assert 'report["certificate_scope"] = args.certificate_scope' in src


def test_ps1_accepts_bar_models_and_labels_stages_9_10():
    assert ('$s8Verdict -eq "MT5_VALIDATED" -or $s8Verdict -eq '
            '"MT5_VALIDATED_BAR_MODELS"') in PS1
    assert ('$Script:Partial -and ($s8Verdict -eq '
            '"MT5_VALIDATED_PARTIAL_SCOPE" -or $s8Verdict -eq '
            '"MT5_VALIDATED_BAR_MODELS_PARTIAL_SCOPE")') in PS1
    assert ('$Script:CertScope = if ($s8Verdict -like '
            '"MT5_VALIDATED_BAR_MODELS*") { "bar models" } else { "full" }'
            ) in PS1
    assert '"--certificate-scope", $Script:CertScope' in PS1
    assert "scope: \" + $Script:CertScope" in PS1
    # a scoped run is still refused at stages 9-10, whatever the verdict
    assert "[refused_scoped_run] archive manifest not built" in PS1
