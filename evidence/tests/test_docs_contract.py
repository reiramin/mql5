"""Documentation-contract pins (Phase 3 gate).

The MT5 round-trip is a TEN-step owner sequence with exactly five
certification states, and the degradation band is informational only.
These are contract documents: tests fail if the contract silently
changes.
"""

import subprocess
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"

# Canonical owner protocol (mission §5, 2026-09-07): ONE numbered
# sequence — docs/MT5_ROUNDTRIP.md is the single source of truth and
# every other checklist must map onto these numbers or label itself a
# SHORTCUT. Raw-report archiving and parsing are mandatory sub-steps of
# each tester leg (steps 5–7), not standalone steps.
TEN_STEPS = [
    "strict compile",
    "compiler-log verification",
    "SymbolSpec export",
    "fixture / data preparation",
    "baseline leg (M1-OHLC)",
    "Every Tick leg",
    "Every-Tick-real-ticks leg",
    "Python↔MT5 comparison",
    "immutable archive / manifest",
    "certification-state assignment",
]

FIVE_STATES = [
    "SOFTWARE_PASS",
    "EMPIRICAL_VALIDATION_PENDING",
    "VERIFIED",
    "FAILED",
    "NOT_ELIGIBLE",
]


def test_mt5_roundtrip_documents_exactly_ten_steps():
    text = (DOCS / "MT5_ROUNDTRIP.md").read_text(encoding="utf-8")
    for i, step in enumerate(TEN_STEPS, start=1):
        assert f"| {i} | **{step}** |" in text, f"step {i} ({step}) missing"
    # the SEQUENCE table itself has exactly ten rows (later tables, e.g.
    # the owner shadow procedure, may legitimately number further)
    sequence = text[text.index("## The canonical owner sequence"):
                    text.index("## Certification states")]
    assert "| 11 |" not in sequence
    # canonicality is stated: single source of truth + SHORTCUT rule
    assert "CANONICAL PROTOCOL" in text
    assert "SHORTCUT" in text
    # the kill-switch seam and restart proofs live in step 8 as
    # sub-checks 8a/8b, not as independently-numbered steps
    assert "sub-check 8a Kill-Switch seam proof" in text
    assert "sub-check 8b restart proof" in text


def test_mt5_roundtrip_documents_exactly_five_states():
    text = (DOCS / "MT5_ROUNDTRIP.md").read_text(encoding="utf-8")
    for state in FIVE_STATES:
        assert f"`{state}`" in text, f"state {state} missing"


def test_degradation_band_is_informational_only_everywhere():
    cert = (DOCS / "CERTIFICATION.md").read_text(encoding="utf-8")
    mt5 = (DOCS / "MT5_ROUNDTRIP.md").read_text(encoding="utf-8")
    for name, text in (("CERTIFICATION", cert), ("MT5_ROUNDTRIP", mt5)):
        assert "INFORMATIVE ONLY" in text or "informational only" in text \
            or "INFORMATIONAL ONLY" in text, \
            f"{name}: the never-a-gate rule must be stated"
        assert "never gates the" in text or "NEVER a pass/fail" in text, \
            f"{name}: the never-gates wording must be present"
    # the reference band may be stated, but never as a verdict criterion
    assert "30-50" in cert or "30–50" in cert


def test_wfa_cpcv_review_matrix_present():
    text = (DOCS / "WFA_CPCV_REVIEW.md").read_text(encoding="utf-8")
    assert "STATE CARRY" in text and "KNOWLEDGE CARRY" in text
    # the 11-row comparison matrix (header + 10 data rows min)
    rows = [ln for ln in text.splitlines()
            if ln.startswith("|") and "---" not in ln]
    assert len(rows) >= 12  # header + >=11 matrix rows


def test_benchmark_fast_never_claims_fully_vectorized():
    text = (DOCS / "BENCHMARK_FAST.md").read_text(encoding="utf-8")
    assert "fully vectorized" not in text.lower()
    assert "fully-vectorized" not in text.lower()
    assert "NO MEASURABLE SPEEDUP" in text  # claim-discipline wording kept
    engine = Path(__file__).resolve().parents[1] / "python" / "mql5bot" \
        / "fast_engine.py"
    assert "fully vectorized" not in engine.read_text(encoding="utf-8") \
        .lower()


def test_scope_boundary_docs_match_source_truth():
    """Mission FINAL-REALITY-GATE §2 (2026-09-08).

    The README previously claimed generated/DSL strategies 'reach MT5
    through the same EA pipeline'. The MQL5 source contradicts that:
    the EA selects strategies from a five-member enum input and the
    MQL5 tree contains NO DSL/JSON strategy interpreter. This pin
    locks the truthful wording and the source surface it describes, so
    a silent regression in either direction fails the gate.
    """
    repo = Path(__file__).resolve().parents[1]
    readme = (repo / "README.md").read_text(encoding="utf-8")
    # the false claim must stay gone
    assert "reach MT5 through the same EA pipeline" not in readme
    assert "reaches MT5 through the same EA pipeline" not in readme
    # the truthful surface statement must stay present
    assert "ONLY MQL5 execution surface" in readme
    assert "no DSL interpreter" in readme
    # the binding scope model must stay present and named
    cert = (DOCS / "CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Certification scope surfaces" in cert
    assert "Execution-certified surface" in cert
    assert "Research-certified surface" in cert
    assert "Owner-pending surface" in cert


def test_mql5_execution_surface_is_exactly_five_builtin_engines():
    """Source-contract pin: the EA's executable strategy surface is
    exactly the five built-in engines of ENUM_MQL5BOT_STRATEGY and the
    strategy selection is an enum input (no spec/DSL ingestion). Any
    new engine or an interpreter seam changes this contract and must
    update the scope docs deliberately."""
    repo = Path(__file__).resolve().parents[1]
    cfg = (repo / "mql5/Include/Mql5Bot/Config.mqh").read_text(
        encoding="utf-8")
    members = [line.split("=")[0].strip()
               for line in cfg.splitlines()
               if line.strip().startswith("STRAT_")]
    assert members == [
        "STRAT_EMA_CROSSOVER",
        "STRAT_RSI_REVERSAL",
        "STRAT_DONCHIAN_BREAKOUT",
        "STRAT_BOLLINGER_REVERSAL",
        "STRAT_MACD_MOMENTUM",
    ]
    ea = (repo / "mql5/Experts/Mql5Bot/Mql5Bot.mq5").read_text(
        encoding="utf-8")
    assert "input ENUM_MQL5BOT_STRATEGY InpStrategy" in ea


def test_owner_mt5_gate_package_exists_and_is_pending_owner():
    """OWNER MT5 EXECUTION GATE: the owner package directory must exist
    with its scaffold, its owner-side values must stay PENDING_OWNER
    (no fabricated evidence), and the frozen inputs must bind the exact
    current commit."""
    import json

    pkg = Path(__file__).resolve().parents[1] / "artifacts" / "owner_mt5_gate"
    for name in ("README.md", "frozen_inputs.json",
                 "certification_manifest.json", "real_tick_coverage.json",
                 "checklist.md", "report_template.md"):
        assert (pkg / name).is_file(), f"owner package missing {name}"

    repo = Path(__file__).resolve().parents[1]
    frozen = json.loads((pkg / "frozen_inputs.json").read_text())
    anchor = frozen["source"]["commit"]
    # the freeze anchor must be reachable from HEAD ...
    rc = subprocess.run(["git", "merge-base", "--is-ancestor", anchor,
                         "HEAD"], cwd=repo, check=False).returncode
    assert rc == 0, "frozen source commit is not part of this history"
    # ... and the gold artifacts must be UNCHANGED since the anchor
    # (the freeze invariant: later commits never touch the golds)
    diff = subprocess.run(["git", "diff", "--name-only", anchor, "HEAD",
                           "--", "artifacts/gold", "artifacts/gold_2"],
                          cwd=repo, capture_output=True, text=True,
                          check=False).stdout
    assert diff.strip() == "", f"gold artifacts changed since freeze: {diff}"
    assert "FROZEN" in frozen["gold_1"]["status"]
    assert frozen["gold_2"]["provenance_label"] == \
        "GOLD_2_RECONSTRUCTED_NEW_PROVENANCE"

    manifest = json.loads(
        (pkg / "certification_manifest.json").read_text())
    assert manifest["chain"]["VERDICT"]["status"] == "REALITY_GATE_BLOCKED"
    assert manifest["chain"]["EX5"]["compile_timestamp"] == "PENDING_OWNER"
    coverage = json.loads((pkg / "real_tick_coverage.json").read_text())
    assert coverage["coverage"] == "REAL_TICK_COVERAGE_UNKNOWN"


def test_owner_readme_matches_verifier_layout_exactly():
    """The owner manual and the verifier must describe the SAME
    directory contract. Every LAYOUT path appears in the README, the
    README documents exactly the verifier's file count, and no stale
    filenames from earlier drafts survive (an owner who follows the
    manual must produce a package the verifier accepts)."""
    import re

    from mql5bot import owner_gate as og

    repo = Path(__file__).resolve().parents[1]
    readme = (repo / "artifacts" / "owner_mt5_gate" /
              "README.md").read_text(encoding="utf-8")

    for rel in og.LAYOUT.values():
        assert f"`{rel}`" in readme, \
            f"owner README does not document mandatory path {rel}"

    # no stale filenames from the superseded 16-slot draft
    for stale in ("logs/compile-", "data/broker_exports/",
                  "gold1_m1ohlc.htm", "reconciliation_owner.json",
                  "<leg>.parsed.json", "certification_manifest.json |"):
        assert stale not in readme, f"stale artifact name survived: {stale}"

    # the documented path count equals the implemented one
    assert "29 individual files" in readme
    backticked = set(re.findall(r"`([A-Za-z0-9_/]+\.(?:log|json|ex5|htm))`",
                                readme))
    layout_paths = set(og.LAYOUT.values())
    assert layout_paths <= backticked
    # every backticked .htm/.ex5/.log evidence path is a real LAYOUT path
    evidence_paths = {p for p in backticked
                      if p.endswith((".htm", ".ex5", ".log"))}
    assert evidence_paths <= layout_paths
    assert len(layout_paths) == 29
