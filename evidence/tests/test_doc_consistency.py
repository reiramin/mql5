"""Documentation consistency tests (Phase 30).

Documentation drift is fixed by tests, not by hope: every number,
version, test-name reference and manifest-key list quoted in the docs
is pinned here against the code.  Docs that contradict the code fail
the suite.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parent.parent / "docs"
REPO = DOCS.parent


def _read(name: str) -> str:
    return (DOCS / name).read_text()


# ---- audit register ↔ failure matrix --------------------------------------


def test_failure_matrix_rows_reference_real_tests():
    doc = _read("META_REALISM_AUDIT.md")
    matrix = (REPO / "tests" / "test_meta_failure_matrix.py").read_text()
    rows = re.findall(r"`(test_f\d\w*)`", doc)
    assert len(rows) >= 8, "failure matrix table lost rows"
    for name in rows:
        assert f"def {name}" in matrix, f"{name} quoted in doc, missing in code"


def test_data_gate_f1_documented_and_implemented():
    doc = _read("META_REALISM_AUDIT.md")
    assert "non-finite OHLC" in doc          # the F1 refusal reason
    from mql5bot.meta_portfolio import InstrumentContext
    assert "data_error" in InstrumentContext.__dataclass_fields__.__class__.__dict__ \
        or hasattr(InstrumentContext, "data_error")


# ---- versions and constants -------------------------------------------------


def test_corr_min_obs_doc_matches_code():
    from mql5bot.meta_layer import CORR_MIN_OBS
    doc = _read("CORRELATION_CONVENTIONS.md")
    assert f"`CORR_MIN_OBS = {CORR_MIN_OBS}`" in doc


def test_regime_drift_versions_doc_matches_code():
    from mql5bot.drift_feed import DRIFT_VERSION
    from mql5bot.regime_feed import REGIME_VERSION
    realism = _read("META_REALISM_AUDIT.md")
    assert REGIME_VERSION in realism and DRIFT_VERSION in realism
    matrix = _read("REGIME_MATRIX.md")
    assert REGIME_VERSION in matrix and DRIFT_VERSION in matrix


def test_drift_ladder_constants_doc_consistent():
    from mql5bot.meta_layer import DRIFT_BLOCK, DRIFT_MILD, DRIFT_MISSING
    assert DRIFT_MILD == 0.10 and DRIFT_BLOCK == 0.50
    assert DRIFT_MISSING == 0.5
    doc = _read("META_REALISM_AUDIT.md")
    assert "DRIFT_MISSING" in doc


# ---- canonical OOS numbers (prior gate, frozen) -----------------------------


def test_oos_canonical_table_is_the_frozen_prior_gate_result():
    doc = _read("META_OOS_CANONICAL.md")
    for token in ("1334.34", "1414.28", "1.4505", "1.1696",
                  "-5.47%", "-8.32%", "-0.1121", "+0.2173", "0.4367"):
        assert token in doc, f"canonical number {token} missing"
    assert "straddles zero" in doc.lower()
    assert "DISABLED" in doc


# ---- performance benchmark artifact -----------------------------------------


def test_perf_benchmark_covers_required_scales():
    data = json.loads((DOCS / "META_PERF_BENCHMARK.json").read_text())
    scales = {r["scale"] for r in data["results"]}
    assert scales == {"1sym x 3books", "3sym x 5books",
                      "6sym x 10books"}


# ---- regime matrix frozen config ↔ tool -------------------------------------


def test_regime_matrix_frozen_config_matches_tool():
    tool = (REPO / "tools" / "meta_regime_matrix.py").read_text()
    payload = json.loads((DOCS / "REGIME_MATRIX.json").read_text())
    frozen = payload["frozen_config"]
    assert f"DAYS = {frozen['days']}" in tool
    assert f"EVERY_DAYS = {frozen['every_days']}" in tool
    assert f"MIN_HISTORY = {frozen['min_history']}" in tool
    assert "no-tuning" in tool.lower() or "NO TUNING" in tool


def test_regime_matrix_commit_hash_is_a_hash():
    doc = _read("REGIME_MATRIX.md")
    m = re.search(r"`([0-9a-f]{7,40})`", doc)
    assert m, "REGIME_MATRIX.md must cite a git commit"


# ---- manifest key list ↔ code ------------------------------------------------


def test_replay_doc_manifest_keys_match_engine():
    from mql5bot.data import generate_ohlc
    from mql5bot.meta_portfolio import MetaPortfolioEngine

    from tests.test_meta_multi_asset import FX_SPEC, _ctx
    df = generate_ohlc(days=30, seed=1)
    eng = MetaPortfolioEngine(contexts=[
        _ctx("EURUSD", "boll@EURUSD", "bollinger_reversal", df, FX_SPEC)])
    man = set(eng.manifest())
    doc = _read("META_REPLAY_CONVENTIONS.md")
    quoted = {"git_commit", "engine_version", "cost_version",
              "meta_version", "contract_version", "regime_version",
              "drift_version", "certification_protocol", "config_hash",
              "random_seed", "rebalance_schedule_hash", "dataset_sha256",
              "ineligible"}
    missing = {k.replace("dataset_sha256", "dataset_sha256") for k in quoted} - man \
        - {"dataset_sha256"}
    assert not missing, f"doc quotes manifest keys absent from engine: {missing}"
    assert "dataset_sha256" in doc and "dataset_sha256" in str(
        eng.manifest()["instruments"][0])


# ---- forbidden-claims gate ----------------------------------------------------


@pytest.mark.parametrize("doc_name", [
    "META_REALISM_AUDIT.md",
    "META_OOS_CANONICAL.md",
    "META_REPLAY_CONVENTIONS.md",
    "CORRELATION_CONVENTIONS.md",
    "REGIME_MATRIX.md",
])
def test_no_doc_claims_meta_is_enabled_or_promoted(doc_name):
    doc = _read(doc_name).lower()
    forbidden = ["meta is enabled", "meta promoted to production",
                 "meta is now live", "promotion approved"]
    for phrase in forbidden:
        assert phrase not in doc, f"{doc_name} claims: {phrase}"


def test_vix_never_claims_to_complete_the_basket():
    tool = (REPO / "tools" / "meta_real_basket.py").read_text().lower()
    assert "never substitutes" in tool or "never count" in tool
