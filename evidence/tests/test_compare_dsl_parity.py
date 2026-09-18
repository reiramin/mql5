"""Unit tests for tools/compare_dsl_parity.py — the exact comparator
that renders the MQL5-side parity verdict (mission §12/§13).

Covers: a synthetic PASS (byte-faithful runner outputs -> exit 0), a
synthetic MISMATCH (one flipped position -> exit 1 naming fixture, bar
index, expected and actual), missing outputs, provenance-pin breaks,
the tampered-bundle refusal contract, and — against the real committed
golden set — that all 14 fixtures are required and the tampered fixture
is refused by the Python loader too.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from compare_dsl_parity import compare_dir, main

GOLD = REPO / "artifacts" / "dsl_parity"


# ---------------------------------------------------------------- helpers


def _synthetic_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    """A minimal golden set (2 fixtures + tampered negative) and the
    matching PERFECT runner-output dir."""
    fixtures = tmp_path / "fixtures"
    out = tmp_path / "out"
    out.mkdir()
    manifest: dict = {"fixtures": {}}
    for name, positions in (("alpha", [0, 1, 1, 0]),
                            ("beta", [0, 0, -1, -1])):
        d = fixtures / name
        d.mkdir(parents=True)
        events = []
        prev = 0
        for i, p in enumerate(positions):
            if p != prev:
                events.append({"bar": i, "from": prev, "to": p})
                prev = p
        trace = {"n_bars": len(positions), "positions": positions,
                 "events": events, "position_hash": f"hash-{name}",
                 "exit_geometry": {"breakeven_atr": 0.0, "sl_atr": 2.0,
                                   "trail_atr": 0.0},
                 "spec_hash": f"spec-{name}", "strategy_id": name,
                 "strategy_version": 1}
        (d / "expected_trace.json").write_text(json.dumps(trace))
        manifest["fixtures"][name] = {
            "bundle_hash": f"bundle-{name}",
            "files": {"ohlc.csv": f"ohlc-{name}"}}
        mql5 = dict(trace)
        mql5["bundle_hash"] = f"bundle-{name}"
        mql5["ohlc_sha256"] = f"ohlc-{name}"
        (out / f"{name}.json").write_text(json.dumps(mql5))
    (fixtures / "manifest.json").write_text(json.dumps(manifest))
    tb = fixtures / "tampered_bundle"
    tb.mkdir()
    (tb / "bundle.json").write_text("{}")
    (out / "tampered_bundle.json").write_text(json.dumps(
        {"error": "bundle_hash mismatch (tampered or mis-encoded): x",
         "fixture": "tampered_bundle", "refused": True}))
    return fixtures, out


# ------------------------------------------------------------ synthetic


def test_synthetic_pass_exits_zero(tmp_path):
    fixtures, out = _synthetic_fixtures(tmp_path)
    ok, lines = compare_dir(out, fixtures)
    assert ok, lines
    assert any(line == "EXACT alpha" for line in lines)
    assert "2/2 fixtures EXACT" in lines[-1]
    assert main([str(out), "--fixtures", str(fixtures)]) == 0


def test_synthetic_position_mismatch_names_first_divergence(tmp_path):
    fixtures, out = _synthetic_fixtures(tmp_path)
    doc = json.loads((out / "beta.json").read_text())
    doc["positions"][2] = 1                       # flipped bar
    (out / "beta.json").write_text(json.dumps(doc))
    ok, lines = compare_dir(out, fixtures)
    assert not ok
    joined = "\n".join(lines)
    assert "beta: first divergence at bar 2: expected -1, actual 1" \
        in joined
    assert "PARITY NOT PROVEN" in lines[-1]
    assert main([str(out), "--fixtures", str(fixtures)]) == 1


def test_synthetic_missing_output_fails(tmp_path):
    fixtures, out = _synthetic_fixtures(tmp_path)
    (out / "alpha.json").unlink()
    ok, lines = compare_dir(out, fixtures)
    assert not ok
    assert any("missing runner output" in line for line in lines)


def test_synthetic_broken_provenance_pin_fails(tmp_path):
    """A trace whose positions match but whose ohlc_sha256 does not
    bind the committed fixture bytes is NOT parity."""
    fixtures, out = _synthetic_fixtures(tmp_path)
    doc = json.loads((out / "alpha.json").read_text())
    doc["ohlc_sha256"] = "some-other-frame"
    (out / "alpha.json").write_text(json.dumps(doc))
    ok, lines = compare_dir(out, fixtures)
    assert not ok
    assert any("ohlc_sha256" in line for line in lines)


def test_synthetic_refused_manifest_fixture_fails(tmp_path):
    fixtures, out = _synthetic_fixtures(tmp_path)
    (out / "alpha.json").write_text(json.dumps(
        {"error": "eval refused: x", "fixture": "alpha",
         "refused": True}))
    ok, lines = compare_dir(out, fixtures)
    assert not ok
    assert any("REFUSED by the runner" in line for line in lines)


def test_synthetic_tampered_trace_instead_of_refusal_fails(tmp_path):
    """If the runner produces a TRACE for the tampered bundle, hash
    verification is broken and the whole comparison fails."""
    fixtures, out = _synthetic_fixtures(tmp_path)
    (out / "tampered_bundle.json").write_text(json.dumps(
        {"positions": [0, 0], "n_bars": 2}))
    ok, lines = compare_dir(out, fixtures)
    assert not ok
    assert any("bundle_hash verification is broken" in line
               for line in lines)


def test_synthetic_missing_tampered_output_fails(tmp_path):
    fixtures, out = _synthetic_fixtures(tmp_path)
    (out / "tampered_bundle.json").unlink()
    ok, lines = compare_dir(out, fixtures)
    assert not ok
    assert any("tamper check did not run" in line for line in lines)


# ------------------------------------------------- against the real set


def test_real_golden_set_requires_all_14(tmp_path):
    """Empty output dir vs the committed set: every one of the 14
    manifest fixtures is reported missing and the verdict is FAIL."""
    manifest = json.loads((GOLD / "manifest.json").read_text())
    assert len(manifest["fixtures"]) == 14
    empty = tmp_path / "empty"
    empty.mkdir()
    ok, lines = compare_dir(empty, GOLD)
    assert not ok
    missing = [line for line in lines if "missing runner output" in line]
    assert len(missing) == 14
    assert "0/14 fixtures EXACT" in lines[-1]


def test_python_loader_refuses_tampered_fixture():
    """The committed tampered_bundle fixture is refused by the PYTHON
    loader as well — both engines fail closed on the same bytes."""
    from mql5bot.dsl import BundleError, load_bundle
    tampered = json.loads(
        (GOLD / "tampered_bundle" / "bundle.json").read_text())
    with pytest.raises(BundleError):
        load_bundle(tampered)
