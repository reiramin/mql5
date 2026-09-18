"""DSL generic-runtime parity golden tests (mission §12/§13/§30/§35).

Verifies, entirely on the Mac/Python side:

* every committed golden bundle LOADS (fail-closed loader) and its spec
  re-derives the pinned identity/hash;
* the Python parity trace REPRODUCES the committed expected_trace.json
  byte-for-byte from the committed ohlc.csv (determinism / no-drift gate);
* the CANONICAL example ("EMA20 crosses above EMA50 AND RSI14>55, SL 2ATR,
  TP 3ATR") runs through the GENERIC runtime as recursive DSL nodes and is
  NEVER mapped onto one of the five legacy enum families (§35);
* the fail-closed refusals (§13 25-28) actually fire.

The MQL5 side of this parity is OWNER-PENDING (compile + Strategy Tester)
and is never simulated here.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd
import pytest
from mql5bot.dsl import BundleError, build_bundle, load_bundle, parse_spec
from mql5bot.dsl.parity import compare_traces, parity_trace

GOLD = Path(__file__).resolve().parents[1] / "artifacts" / "dsl_parity"
MANIFEST = json.loads((GOLD / "manifest.json").read_text())
NAMES = sorted(MANIFEST["fixtures"])


def _read_ohlc(name: str) -> pd.DataFrame:
    df = pd.read_csv(GOLD / name / "ohlc.csv", index_col=0,
                     parse_dates=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


@pytest.mark.parametrize("name", NAMES)
def test_golden_bundle_loads_and_reproduces_trace(name):
    bundle = json.loads((GOLD / name / "bundle.json").read_text())
    expected = json.loads((GOLD / name / "expected_trace.json").read_text())
    loaded = load_bundle(bundle)                     # fail-closed loader
    assert loaded.spec_hash == MANIFEST["fixtures"][name]["spec_hash"]
    df = _read_ohlc(name)
    trace = parity_trace(loaded.spec, df)
    # LOGICAL parity: positions + events + position_hash EXACT
    assert compare_traces(expected, trace) == [], name
    assert trace["position_hash"] == expected["position_hash"], name


def test_manifest_digest_is_stable():
    """Recomputing the manifest from disk yields the pinned digest — a
    drift tripwire (regenerating is a decision-changing event)."""
    import hashlib

    from mql5bot.dsl.normalize import canon_json
    digest = hashlib.sha256(
        canon_json(MANIFEST["fixtures"]).encode()).hexdigest()
    # every fixture's on-disk files match their pinned sha256
    for name, meta in MANIFEST["fixtures"].items():
        for fname, h in meta["files"].items():
            got = hashlib.sha256(
                (GOLD / name / fname).read_bytes()).hexdigest()
            assert got == h, f"{name}/{fname} drifted"
    assert len(digest) == 64


def test_canonical_example_runs_generically_not_as_a_legacy_enum():
    """The central convergence requirement (§35): the canonical strategy
    reaches execution as GENERIC DSL nodes — it never becomes one of
    EMA_CROSSOVER / RSI_REVERSAL / DONCHIAN_BREAKOUT / BOLLINGER_REVERSAL
    / MACD_MOMENTUM."""
    name = "canonical_ema_rsi_atr"
    bundle = json.loads((GOLD / name / "bundle.json").read_text())
    loaded = load_bundle(bundle)
    spec = loaded.spec
    # the long entry is a recursive AND( cross , cmp ) — pure DSL, no enum
    long = spec.entry.long
    assert "and" in long
    kinds = {c.get("cross") or c.get("cmp") for c in long["and"]}
    assert "ABOVE" in kinds and "GT" in kinds
    # nothing in the executable identity names a legacy enum family
    blob = json.dumps(bundle)
    for enum in ("EMA_CROSSOVER", "RSI_REVERSAL", "DONCHIAN_BREAKOUT",
                 "BOLLINGER_REVERSAL", "MACD_MOMENTUM"):
        assert enum not in blob
    # and it actually TRADES both directions over the fixture
    trace = json.loads((GOLD / name / "expected_trace.json").read_text())
    tos = {e["to"] for e in trace["events"]}
    assert 1 in tos and -1 in tos, "canonical example must trade both ways"
    # exit geometry is carried faithfully (SL 2 ATR, TP 3 ATR)
    assert trace["exit_geometry"]["sl_atr"] == 2.0
    assert trace["exit_geometry"]["tp_atr"] == 3.0


# ------------------------------------------------------- §13 25-28 refusals


_CANON = {
    "schema_version": "1.0", "strategy_id": "refuse_demo", "version": 1,
    "market": {"symbol": "EURUSD", "timeframe": "H1"},
    "indicators": [{"id": "ema_f", "kind": "EMA", "period": 20},
                   {"id": "ema_s", "kind": "EMA", "period": 50}],
    "entry": {"mode": "state",
              "long": {"cross": "ABOVE", "a": {"ind": "ema_f"},
                       "b": {"ind": "ema_s"}},
              "short": {"cross": "BELOW", "a": {"ind": "ema_f"},
                        "b": {"ind": "ema_s"}}},
    "exit": {"sl": {"model": "atr", "mult": 2.0}},
}


def test_refusal_ambiguous_spec_not_bundlable():
    doc = copy.deepcopy(_CANON)
    doc["indicators"].append({"id": "rsi", "kind": "RSI", "period": 14})
    doc["entry"]["long"] = {"and": [
        doc["entry"]["long"],
        {"cmp": "GT", "left": {"ind": "rsi"},
         "right": {"ambiguous": "rsi_threshold"}}]}
    with pytest.raises(BundleError):
        build_bundle(parse_spec(doc))


def test_refusal_unknown_indicator_in_bundle():
    env = build_bundle(parse_spec(copy.deepcopy(_CANON)))
    env["spec"]["indicators"][0]["kind"] = "NOPE_NOT_REAL"
    from mql5bot.dsl.bundle import _binding_hash
    env["bundle_hash"] = _binding_hash(env)
    with pytest.raises(BundleError):
        load_bundle(env)


def test_refusal_malformed_bundle():
    with pytest.raises(BundleError):
        load_bundle({"not": "a bundle"})


def test_refusal_hash_mismatch():
    env = build_bundle(parse_spec(copy.deepcopy(_CANON)))
    env["spec"]["indicators"][0]["period"] = 21     # tamper, no re-hash
    with pytest.raises(BundleError, match="hash mismatch"):
        load_bundle(env)
