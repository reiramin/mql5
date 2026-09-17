"""Executable-bundle contract tests (mission §10).

The bundle binds identity + market + spec + indicator contracts under one
tamper-evident hash, and the loader FAILS CLOSED on every malformed /
unsupported / mismatched input.  The MQL5 generic runtime loader must
enforce the SAME refusals — these tests are the executable spec of that
contract.
"""

from __future__ import annotations

import copy

import pytest
from mql5bot.dsl import (
    BUNDLE_FORMAT_VERSION,
    RUNTIME_CONTRACT_VERSION,
    BundleError,
    build_bundle,
    desired_positions,
    load_bundle,
    parse_spec,
)
from mql5bot.dsl.bundle import _HASH_FIELD, _binding_hash

# a minimal, fully-executable spec (v1, explicit market, SL/TP, no ambiguity)
_DOC = {
    "schema_version": "1.0",
    "strategy_id": "bundle_demo",
    "version": 1,
    "market": {"symbol": "EURUSD", "timeframe": "H1"},
    "indicators": [
        {"id": "ema_f", "kind": "EMA", "period": 20, "applied": "close"},
        {"id": "ema_s", "kind": "EMA", "period": 50, "applied": "close"},
    ],
    "entry": {"mode": "state",
              "long": {"cross": "ABOVE", "a": {"ind": "ema_f"},
                       "b": {"ind": "ema_s"}},
              "short": {"cross": "BELOW", "a": {"ind": "ema_f"},
                        "b": {"ind": "ema_s"}}},
    "exit": {"sl": {"model": "atr", "mult": 2.0},
             "tp": {"model": "atr", "mult": 3.0}},
}


def _spec():
    return parse_spec(copy.deepcopy(_DOC))


def _rehash(env: dict) -> dict:
    """Recompute the binding hash so a tampered envelope stays internally
    consistent — used to isolate the DEEPER binding checks from the hash
    check."""
    env = copy.deepcopy(env)
    env[_HASH_FIELD] = _binding_hash(env)
    return env


# --------------------------------------------------------------- happy path


def test_roundtrip_preserves_identity_and_executes():
    spec = _spec()
    env = build_bundle(spec)
    assert env["bundle_format_version"] == BUNDLE_FORMAT_VERSION
    assert env["runtime_contract_version"] == RUNTIME_CONTRACT_VERSION
    loaded = load_bundle(env)
    assert loaded.strategy_id == "bundle_demo"
    assert loaded.strategy_version == 1
    assert loaded.spec_hash == spec.spec_hash
    assert loaded.market == {"symbol": "EURUSD", "timeframe": "H1"}
    assert loaded.spec.executable
    # the reconstructed spec actually runs and produces the SAME signal
    # series as the original spec (the bundle is a faithful carrier)
    from mql5bot.data import generate_ohlc
    df = generate_ohlc(days=180, seed=3)
    import numpy as np
    np.testing.assert_array_equal(
        desired_positions(loaded.spec, df).to_numpy(),
        desired_positions(spec, df).to_numpy())


def test_bundle_hash_is_deterministic():
    a = build_bundle(_spec())[_HASH_FIELD]
    b = build_bundle(_spec())[_HASH_FIELD]
    assert a == b and len(a) == 64


def test_indicator_contracts_are_bound():
    env = build_bundle(_spec())
    kinds = {c["kind"] for c in env["indicator_contracts"]}
    assert kinds == {"EMA"}
    assert all("version" in c and "mql5_status" in c
               for c in env["indicator_contracts"])


# --------------------------------------------------------------- fail closed


def test_tampered_spec_is_rejected_by_hash():
    env = build_bundle(_spec())
    env["spec"]["indicators"][0]["period"] = 21   # tamper, no re-hash
    with pytest.raises(BundleError, match="bundle_hash mismatch"):
        load_bundle(env)


def test_unsupported_bundle_format_version_rejected():
    env = _rehash({**build_bundle(_spec()),
                   "bundle_format_version": "9.9"})
    with pytest.raises(BundleError, match="bundle_format_version"):
        load_bundle(env)


def test_unsupported_runtime_version_rejected():
    env = _rehash({**build_bundle(_spec()),
                   "runtime_contract_version": "0.0"})
    with pytest.raises(BundleError, match="runtime_contract_version"):
        load_bundle(env)


def test_missing_identity_rejected():
    env = build_bundle(_spec())
    env2 = _rehash({k: v for k, v in env.items() if k != "identity"})
    with pytest.raises(BundleError, match="identity"):
        load_bundle(env2)


def test_missing_market_rejected():
    env = build_bundle(_spec())
    env["market"] = {"symbol": "", "timeframe": ""}
    with pytest.raises(BundleError, match="market"):
        load_bundle(_rehash(env))


def test_identity_that_does_not_bind_the_spec_is_rejected():
    """A wrong spec_hash that is nevertheless hash-consistent must still
    be refused — identity MUST bind the content."""
    env = build_bundle(_spec())
    env["identity"]["spec_hash"] = "0" * 64
    with pytest.raises(BundleError, match="spec_hash"):
        load_bundle(_rehash(env))


def test_indicator_contract_drift_is_rejected():
    env = build_bundle(_spec())
    env["indicator_contracts"][0]["version"] = 999
    with pytest.raises(BundleError, match="contract drift"):
        load_bundle(_rehash(env))


def test_unknown_indicator_in_bundle_is_rejected():
    env = build_bundle(_spec())
    env["spec"]["indicators"][0]["kind"] = "NOT_A_REAL_INDICATOR"
    with pytest.raises(BundleError):
        load_bundle(_rehash(env))


def test_normalized_document_is_reparseable_for_n_and_cooldown():
    """Idempotency (gate §29.1): a normalized document that uses `rising`
    (integer n) and `cooldown_bars` must re-validate — the canonical doc
    floatifies numeric leaves, so the schema must accept integral floats
    for these fields (it already does for period/time_bars). This is what
    lets a bundle carry `spec.document` and the loader re-parse it."""
    doc = copy.deepcopy(_DOC)
    doc["entry"] = {"mode": "instant",
                    "long": {"rising": {"ind": "ema_f"}, "n": 3}}
    doc["filters"] = {"cooldown_bars": 5}
    spec = parse_spec(doc)
    assert spec.document["entry"]["long"]["n"] == 3
    # re-parsing the normalized document must succeed and be stable
    spec2 = parse_spec(spec.document)
    assert spec2.spec_hash == spec.spec_hash
    # and it survives a full bundle round-trip
    loaded = load_bundle(build_bundle(spec))
    assert loaded.spec.spec_hash == spec.spec_hash


def test_oversized_bundle_is_rejected_on_in_memory_path():
    """An already-parsed dict never went through load_document's byte
    check, so load_bundle must enforce the total-size limit itself — a
    bundle is untrusted data and must fail closed on oversize before any
    structural work (mission P1 security: oversized JSON fails closed)."""
    from mql5bot.dsl.schema import MAX_DOC_BYTES
    env = build_bundle(_spec())
    env["_pad"] = "x" * (MAX_DOC_BYTES + 1024)   # push envelope over the cap
    with pytest.raises(BundleError, match="size limit"):
        load_bundle(env)


def test_draft_cannot_be_bundled():
    draft = parse_spec(dict(copy.deepcopy(_DOC), version=0))
    assert not draft.executable
    with pytest.raises(BundleError, match="non-executable"):
        build_bundle(draft)


def test_ambiguous_spec_cannot_be_bundled():
    doc = copy.deepcopy(_DOC)
    # inject an unresolved ambiguous threshold
    doc["indicators"].append({"id": "rsi", "kind": "RSI", "period": 14})
    doc["entry"]["long"] = {"and": [
        doc["entry"]["long"],
        {"cmp": "GT", "left": {"ind": "rsi"},
         "right": {"ambiguous": "rsi_threshold"}}]}
    spec = parse_spec(doc)
    assert not spec.executable
    with pytest.raises(BundleError, match="non-executable"):
        build_bundle(spec)
